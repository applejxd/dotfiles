"""scripts/verify.py (変更パス → 試験の選択) の試験。git も子プロセスも呼ばない。"""

from __future__ import annotations

import importlib.util
import posixpath
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify.py"

_spec = importlib.util.spec_from_file_location("verify", SCRIPT)
assert _spec is not None
assert _spec.loader is not None
verify = importlib.util.module_from_spec(_spec)
sys.modules["verify"] = verify
_spec.loader.exec_module(verify)

TEST_FILES = verify.discover_test_files()


def _plan(*paths: str):
    """規則だけを見る (試験が読むファイルからの選択 refs は空にする)。"""
    return verify.plan(list(paths), TEST_FILES, exists=lambda _p: True, refs={})


def _plan_real(*paths: str):
    return verify.plan(list(paths), TEST_FILES, exists=lambda _p: True)


def test_full_run_is_parallel_with_worksteal():
    cmd = verify.pytest_command(["test/"])
    assert "pytest-xdist" in cmd
    assert cmd[-4:] == ["-n", str(verify.jobs()), "--dist", "worksteal"]


def test_jobs_default_is_half_the_cores_and_can_be_overridden(monkeypatch):
    monkeypatch.delenv("VERIFY_JOBS", raising=False)
    monkeypatch.setattr(verify.os, "cpu_count", lambda: 16)
    assert verify.jobs() == 8
    monkeypatch.setattr(verify.os, "cpu_count", lambda: 2)
    assert verify.jobs() == 1  # 半分。低コアでもコア数を超えない
    monkeypatch.setattr(verify.os, "cpu_count", lambda: 1)
    assert verify.jobs() == 1
    monkeypatch.setenv("VERIFY_JOBS", "3")
    assert verify.jobs() == 3
    for bad in ("0", "-1", "x", ""):
        monkeypatch.setenv("VERIFY_JOBS", bad)
        assert verify.jobs() >= 1, bad


def test_small_selections_stay_serial_and_large_ones_go_parallel():
    few = verify.pytest_command(["test/test_a.py", "test/test_b.py"])
    assert "pytest-xdist" not in few and "-n" not in few
    many = verify.pytest_command(["test/test_a.py", "test/test_b.py", "test/test_c.py"])
    assert "pytest-xdist" in many and many[-4:] == ["-n", str(verify.jobs()), "--dist", "worksteal"]


def _pytest_targets(result) -> set[str]:
    targets: set[str] = set()
    for cmd in result.commands:
        if "pytest" in cmd:
            targets.update(a for a in cmd if a.startswith("test/") and a.endswith(".py"))
    return targets


def _flat(result) -> list[str]:
    return [" ".join(c) for c in result.commands]


def _pytest_target(cmd: list[str]) -> str:
    """pytest コマンドの最初の対象 ("--no-project pytest <対象>")。"""
    return cmd[cmd.index("--no-project") + 2]


def test_no_change():
    result = _plan()
    assert result.no_change
    assert result.commands == []


@pytest.mark.parametrize(
    "path",
    [
        "home/dot_config/agents/common.toml.tmpl",
        "scripts/agents/generate.py",
        "scripts/agents/hooks.py",
        "pyproject.toml",
        ".pre-commit-config.yaml",
        "mise.toml",
        "uv.lock",
        "conftest.py",
        "test/agents/agents_common.py",
    ],
)
def test_full_regions_fall_back_to_all(path):
    result = _plan(path)
    assert result.full
    # 全件は段に分かれ、T2 (最後) は全件の pytest。T1 に選んだ試験は T2 で --ignore される
    assert _pytest_target(result.commands[-1]) == "test/"
    assert result.gates


def test_unknown_path_is_full():
    assert _plan("something/unknown.txt").full


def test_one_unknown_path_makes_everything_full():
    assert _plan("docs/spec/x.md", "something/unknown.txt").full


def test_docs_only_runs_no_pytest():
    result = _plan("docs/spec/development.md")
    assert not result.full
    assert _pytest_targets(result) == set()
    assert not any("pytest" in c for c in result.commands)
    flat = _flat(result)
    assert any("lint_docs.py" in c for c in flat)
    assert any("pre-commit run --files docs/spec/development.md" in c for c in flat)


def test_hook_change_selects_hook_tests():
    result = _plan("home/dot_claude/hooks/check_bash.py")
    assert not result.full
    targets = _pytest_targets(result)
    assert "test/agents/test_command_policy.py" in targets
    assert "test/agents/test_shellparse.py" in targets
    assert "test/agents/test_pi_harness.py" not in targets


def test_pi_judge_change():
    targets = _pytest_targets(_plan("home/dot_config/pi/harness/judge/index.ts"))
    assert "test/agents/test_pi_judge_ts.py" in targets
    assert "test/agents/test_pi_boundary.py" in targets


def test_template_change_adds_template_lint():
    result = _plan("home/.chezmoitemplates/foo.tmpl")
    assert not result.full
    assert any("lint_templates.py" in c for c in _flat(result))
    assert "test/test_windows_assets.py" in _pytest_targets(result)


def test_windows_assets_use_no_yaml_command_and_note():
    result = _plan("home/dot_config/powershell/profile.ps1")
    assert result.windows
    for cmd in result.commands:
        if "test/test_windows_assets.py" in cmd:
            assert "pyyaml" not in cmd


def test_test_file_change_runs_itself():
    result = _plan("test/test_websearch.py")
    assert not result.full
    assert _pytest_targets(result) == {"test/test_websearch.py"}


def test_skill_md_selects_frontmatter_test():
    result = _plan("home/dot_claude/skills/commit/SKILL.md")
    assert not result.full
    assert "test/agents/test_skill_frontmatter.py" in _pytest_targets(result)


@pytest.mark.parametrize("path", ["docs/gone.md", "test/test_gone.py", "test/test_verify.py"])
def test_deleted_path_falls_back_to_all(path):
    result = verify.plan([path], TEST_FILES, exists=lambda _p: False, refs={})
    assert result.full
    assert _pytest_target(result.commands[-1]) == "test/"


def test_one_deleted_path_makes_everything_full():
    result = verify.plan(
        ["docs/a.md", "docs/gone.md"], TEST_FILES, exists=lambda p: p != "docs/gone.md", refs={}
    )
    assert result.full


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("./docs/a.md", "docs/a.md"),
        ("docs\\spec\\a.md", "docs/spec/a.md"),
        ("/docs/a.md", "docs/a.md"),
        (verify.ROOT.as_posix() + "/docs/a.md", "docs/a.md"),
        ("docs//x/../a.md", "docs/a.md"),
        (".", ""),
    ],
)
def test_normalize_path(raw, expected):
    assert verify.normalize_path(raw) == expected


def test_plan_normalizes_paths_before_matching():
    assert _plan(".\\pyproject.toml").full
    assert _plan("./docs/spec/development.md").hits == {"docs/spec/development.md": ["docs"]}
    assert _plan(".").no_change


def test_references_pick_up_path_chains():
    refs = verify.test_references(["test/agents/test_modifier_wrappers.py"])
    assert (
        "home/dot_config/opencode/modify_opencode.json.py.tmpl"
        in refs["test/agents/test_modifier_wrappers.py"]
    )


def test_file_a_test_reads_selects_that_test():
    result = _plan_real("home/dot_config/opencode/modify_opencode.json.py.tmpl")
    assert "test/agents/test_modifier_wrappers.py" in _pytest_targets(result)


@pytest.mark.parametrize(
    ("path", "test"),
    [
        ("home/.chezmoitemplates/agent-instructions.md", "test/agents/test_pi_harness.py"),
        (
            "home/dot_config/opencode/guide-plugin/commit-message.js",
            "test/agents/test_pi_commit_confirm.py",
        ),
        ("home/dot_config/pi/harness/commit-message.js", "test/agents/test_pi_commit_confirm.py"),
        (
            "home/.chezmoiscripts/100_linux/run_onchange_after_126_agent_cli.sh.tmpl",
            "test/agents/test_herdr_integration.py",
        ),
        (
            "home/.chezmoiscripts/400_unix/run_after_441_websearch_keys.sh.tmpl",
            "test/test_websearch.py",
        ),
        (
            "home/.chezmoiscripts/300_windows/run_after_349_websearch_keys.ps1.tmpl",
            "test/test_websearch.py",
        ),
        ("home/dot_claude/skills/commit/SKILL.md", "test/agents/test_check_bash_config.py"),
        ("home/dot_claude/skills/sdd-docs/SKILL.md", "test/agents/test_opencode_external_read.py"),
        ("docs/spec/guard/agent-command-policy.md", "test/agents/test_check_bash_config.py"),
        (
            "home/dot_config/opencode/modify_opencode.json.py.tmpl",
            "test/agents/test_modifier_wrappers.py",
        ),
    ],
)
def test_rules_select_tests_that_read_the_file(path, test):
    assert test in _pytest_targets(_plan(path))


def test_hook_change_does_not_run_away_guard():
    assert "test/agents/test_away_guard.py" not in _pytest_targets(
        _plan("home/dot_claude/hooks/check_bash.py")
    )


def test_shell_script_runs_shellcheck():
    result = _plan("home/dot_config/shell/fzf/tools.sh")
    assert any("shellcheck" in c for c in _flat(result))


def test_full_commands_shape():
    cmds = verify.full_commands(shell_files=["a.sh"])
    # T0: 安い検査を先に (pre-commit の 2 段、shellcheck、登録ずれの試験)
    assert cmds[0] == ["uv", "run", "pre-commit", "run", "--all-files"]
    # pre-push の hook (lint-templates-local など) も全件の流れで走る
    assert cmds[1] == [
        "uv",
        "run",
        "pre-commit",
        "run",
        "--all-files",
        "--hook-stage",
        "pre-push",
    ]
    assert ["mise", "exec", "shellcheck", "--", "shellcheck", "a.sh"] in cmds
    assert any(verify.REGISTRATION_TEST in c for c in cmds[:4])
    # lint_docs は pre-commit の hook (lint-docs-local) が --all-files で同じ検査をするので、直接は呼ばない
    assert verify.LINT_DOCS not in cmds
    # 最後が全件の pytest (T2)
    assert "test/" in cmds[-1]


def test_full_run_is_staged_cheap_first_and_t2_is_the_complement():
    stages = verify.full_stages(["test/test_a.py"], ["a.sh"])
    assert len(stages) == 3  # T0 / T1 / T2
    t2 = stages[-1][0]
    assert "--ignore=test/test_a.py" in t2 and f"--ignore={verify.REGISTRATION_TEST}" in t2
    # T0 の pre-push の hook が実行する試験も、T2 から外して二重実行を避ける
    assert all(f"--ignore={f}" in t2 for f in verify.HOOK_PYTEST_FILES)
    commands, gates = verify.flatten_stages(stages)
    assert gates == [len(stages[0]) - 1, len(stages[0]) + len(stages[1]) - 1]
    assert commands[-1] == t2 and len(commands) == sum(map(len, stages))
    # T1 が空なら段は 2 つ (T0 / T2)
    assert len(verify.full_stages([], [])) == 2


def test_selective_plan_runs_cheap_checks_before_tests():
    result = _plan("home/dot_config/shell/fzf/tools.sh", "test/test_verify.py")
    assert not result.full
    flat = _flat(result)
    first_pytest = next(i for i, c in enumerate(flat) if "pytest" in c)
    assert all("pytest" not in c for c in flat[:first_pytest]) and first_pytest > 0
    assert result.gates == [first_pytest - 1]


def test_execute_stops_at_a_failed_gate_unless_keep_going(capsys):
    ok = [sys.executable, "-c", "pass"]
    bad = [sys.executable, "-c", "raise SystemExit(1)"]
    marker = [sys.executable, "-c", "print('REACHED')"]
    failed = verify.execute([ok, bad, marker], gates=[1])
    assert failed == [bad]
    out = capsys.readouterr().out
    assert "REACHED" not in out and "残り 1 件を実行しません" in out
    failed = verify.execute([ok, bad, marker], gates=[1], keep_going=True)
    assert failed == [bad] and "REACHED" in capsys.readouterr().out
    # 失敗が無ければ、段を越えて続く
    assert verify.execute([ok, marker], gates=[0]) == []
    assert "REACHED" in capsys.readouterr().out


def test_tracked_shell_files_reads_git_output():
    run = lambda _cmd: "b.sh\0a.sh\0gone.sh\0"  # noqa: E731
    assert verify.tracked_shell_files(run, exists=lambda p: p != "gone.sh") == ["a.sh", "b.sh"]


def test_t2_is_skipped_when_the_complement_is_empty():
    # 補集合が空のまま pytest を走らせると「試験なし」で失敗する
    all_files = ["test/test_a.py", *verify.T0_PYTEST_FILES]
    stages = verify.full_stages(["test/test_a.py"], [], all_files)
    assert len(stages) == 2 and _pytest_target(stages[-1][0]) == "test/test_a.py"
    stages = verify.full_stages(["test/test_a.py"], [], [*all_files, "test/test_b.py"])
    assert len(stages) == 3 and "--ignore=test/test_a.py" in stages[-1][0]


def test_hook_pytest_files_are_what_the_pre_commit_hook_runs():
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    for f in verify.HOOK_PYTEST_FILES:
        assert f"pytest {f}" in config, f
        assert f in TEST_FILES


def test_all_runs_the_tests_for_the_changed_paths_first(monkeypatch, capsys):
    # verify:all でも、変更に当たる試験を T1 として先に回し、T2 では除く
    monkeypatch.setattr(verify, "collect_changed", lambda _run: ["test/agents/test_pi_confirm.py"])
    monkeypatch.setattr(verify, "tracked_shell_files", lambda _run: [])
    assert verify.main(["--all", "--dry-run"]) == 0
    lines = capsys.readouterr().out.splitlines()
    t1 = next(
        i for i, line in enumerate(lines) if line.endswith("test/agents/test_pi_confirm.py -q")
    )
    t2 = next(
        i for i, line in enumerate(lines) if "--ignore=test/agents/test_pi_confirm.py" in line
    )
    gates = [i for i, line in enumerate(lines) if line.startswith("# ---")]
    assert t1 < t2 and len(gates) == 2 and gates[0] < t1 < gates[1] < t2


def test_plan_records_the_selected_tests():
    result = _plan("home/dot_config/pi/harness/actions.ts")
    assert "test/agents/test_pi_actions_harness.py" in result.selected


class _FakeStamp:
    def __init__(self, now):
        self.now = now
        self.written: list[object] = []

    def snapshot(self, _root):
        return self.now

    def write_stamp(self, _root, entries=None):
        self.written.append(entries)


def test_stamp_records_the_state_at_the_start_and_skips_when_the_tree_changed(monkeypatch, capsys):
    start = {"a.txt": ["100644", "1"]}
    same = _FakeStamp(dict(start))
    monkeypatch.setattr(verify, "_stamp_module", lambda: same)
    verify._write_stamp(start)
    assert same.written == [start]  # 開始時の状態を記録する (終わりの状態ではない)

    changed = _FakeStamp({"a.txt": ["100644", "2"]})
    monkeypatch.setattr(verify, "_stamp_module", lambda: changed)
    verify._write_stamp(start)
    assert changed.written == [] and "実行中に作業ツリーが変わった" in capsys.readouterr().err

    verify._write_stamp(None)
    assert changed.written == [] and "開始時の状態が無い" in capsys.readouterr().err


def _hook_stages() -> tuple[dict, dict[str, list[str]]]:
    """.pre-commit-config.yaml を読み、(設定全体, hook id → 実効の stage) を返す。"""
    yaml = pytest.importorskip("yaml")
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    default = config["default_stages"]
    stages = {
        hook["id"]: hook.get("stages", default)
        for repo in config["repos"]
        for hook in repo["hooks"]
    }
    return config, stages


def test_pre_commit_config_splits_stages():
    """速い hook は commit、重いものと印の警告 (push 用) は push。"""
    config, stages = _hook_stages()
    assert set(config["default_install_hook_types"]) == {"pre-commit", "pre-push"}
    assert config["default_stages"] == ["pre-commit"]
    heavy = {"lint-templates-local", "raspi-regression-local", "verify-stamp-push"}
    for hook_id in heavy:
        assert stages[hook_id] == ["pre-push"], hook_id
    for hook_id in stages.keys() - heavy:
        assert "pre-push" not in stages[hook_id], hook_id
    assert stages["verify-stamp"] == ["pre-commit"]


def test_every_test_file_is_selectable():
    """どの試験も、選択実行で永遠に走らないことがない。"""
    patterns = [p for rule in verify.RULES for p in rule.tests]
    never = [f for f in TEST_FILES if not verify.resolve_tests(patterns, [f])]
    assert never == []


def test_every_rule_test_pattern_matches_a_real_file():
    for rule in verify.RULES:
        for pattern in rule.tests:
            assert verify.resolve_tests([pattern], TEST_FILES), f"{rule.name}: {pattern}"


def test_collect_changed_merges_diff_and_untracked():
    calls: list[list[str]] = []

    def fake_run(cmd: list[str]) -> str:
        calls.append(cmd)
        return "a.py\0b.py\0" if cmd[1] == "diff" else "b.py\0c d\ne.py\0"

    assert verify.collect_changed(fake_run) == ["a.py", "b.py", "c d\ne.py"]
    assert ["git", "diff", "--name-only", "--no-renames", "-z", "HEAD"] in calls
    assert ["git", "ls-files", "-z", "--others", "--exclude-standard"] in calls
    assert all("--" not in c for c in calls)


_LITERAL = re.compile(r"\"([^\"\n\\]+)\"|'([^'\n\\]+)'")
_ROOT_CHAIN = re.compile(r'\bROOT\s*/\s*((?:"[^"\n]+"\s*/\s*)*"[^"\n]+")')
_PART = re.compile(r'"([^"\n]+)"')
# (試験, パス) → 理由。偽陽性だけをここに足す
READ_ALLOWLIST: dict[tuple[str, str], str] = {}


def _files_read_by(source: str) -> set[str]:
    """verify.py の AST 走査とは独立に、正規表現で拾う (走査器の取りこぼしを検出するため)。"""
    found = {m.group(1) or m.group(2) for m in _LITERAL.finditer(source)}
    found = {t for t in found if "/" in t}
    found |= {"/".join(_PART.findall(m.group(1))) for m in _ROOT_CHAIN.finditer(source)}
    paths = {posixpath.normpath(p) for p in found if p and not p.startswith("/") and "\n" not in p}
    return {p for p in paths if not p.startswith("..") and (ROOT / p).is_file()}


def test_every_file_a_test_reads_selects_that_test_or_everything():
    """試験が直接読むファイルの変更で、その試験が走らない取りこぼしを機械で検出する。"""
    missed = []
    for test in TEST_FILES:
        if test == "test/test_verify.py":  # 自身の入力は表の例で、読むファイルではない
            continue
        source = (ROOT / test).read_text(encoding="utf-8")
        for path in sorted(_files_read_by(source)):
            if (test, path) in READ_ALLOWLIST:
                continue
            result = _plan_real(path)
            if not result.full and not any(test in cmd for cmd in result.commands):
                missed.append(f"{test} <- {path}")
    assert missed == []


def test_no_shell_true_in_source():
    assert "shell=True" not in SCRIPT.read_text(encoding="utf-8")

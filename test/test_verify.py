"""scripts/verify.py (変更パス → 試験の選択) の試験。git も子プロセスも呼ばない。"""

from __future__ import annotations

import importlib.util
import posixpath
import re
import shutil
import subprocess
import sys
import time
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
    result = _plan("home/dot_agents/skills/commit/SKILL.md")
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
        ("home/dot_agents/skills/commit/SKILL.md", "test/agents/test_check_bash_config.py"),
        ("home/dot_agents/skills/sdd-docs/SKILL.md", "test/agents/test_opencode_external_read.py"),
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
    heavy = {
        "lint-templates-local",
        "raspi-regression-local",
        "verify-stamp-push",
        "gitleaks-prepush",
    }
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


# --- 全件検査の排他ロック (リポジトリ全体で 1 本だけ) ---

_HOLDER = """
import importlib.util, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("verify", sys.argv[1])
v = importlib.util.module_from_spec(spec)
sys.modules["verify"] = v
spec.loader.exec_module(v)
try:
    h = v.acquire_all_lock(Path(sys.argv[2]), float(sys.argv[3]))
except v.LockTimeout as exc:
    print(exc, file=sys.stderr)
    raise SystemExit(3)
print("ACQUIRED", flush=True)
time.sleep(float(sys.argv[4]))
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "--allow-empty", "-m", "i")
    return r


def _holder(tmp_path: Path, root: Path, timeout: float, hold: float) -> subprocess.Popen:
    script = tmp_path / "holder.py"
    script.write_text(_HOLDER, encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, str(script), str(SCRIPT), str(root), str(timeout), str(hold)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
    )


def _wait_acquired(p: subprocess.Popen) -> None:
    assert p.stdout is not None
    assert p.stdout.readline().strip() == "ACQUIRED"


def test_lock_second_process_waits_until_first_exits(tmp_path, repo):
    a = _holder(tmp_path, repo, 5, 1.5)
    _wait_acquired(a)
    t0 = time.monotonic()
    b = _holder(tmp_path, repo, 10, 0)
    _wait_acquired(b)
    assert time.monotonic() - t0 >= 0.8  # a が持っている間は待った
    assert a.wait(5) == 0 and b.wait(5) == 0


def test_lock_released_when_holder_is_killed(tmp_path, repo):
    a = _holder(tmp_path, repo, 5, 60)
    _wait_acquired(a)
    a.kill()
    a.wait(5)
    t0 = time.monotonic()
    b = _holder(tmp_path, repo, 0, 0)
    _wait_acquired(b)  # stale にならず、待たずに取れる
    assert time.monotonic() - t0 < 5
    assert b.wait(5) == 0


def test_lock_timeout_exits_3_and_names_holder(tmp_path, repo):
    a = _holder(tmp_path, repo, 5, 20)
    _wait_acquired(a)
    try:
        t0 = time.monotonic()
        b = _holder(tmp_path, repo, 1, 0)
        _, err = b.communicate(timeout=15)
        assert b.returncode == 3
        assert 0.8 <= time.monotonic() - t0 < 10
        assert str(a.pid) in err
        c = _holder(tmp_path, repo, 0, 0)  # 0 は待たずに即失敗
        _, err0 = c.communicate(timeout=15)
        assert c.returncode == 3 and str(a.pid) in err0
    finally:
        a.kill()
        a.wait(5)


def test_lock_is_shared_by_worktrees_but_not_by_other_repos(tmp_path, repo):
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", str(wt), "-b", "side")
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q")
    a = _holder(tmp_path, repo, 5, 20)
    _wait_acquired(a)
    try:
        b = _holder(tmp_path, wt, 0, 0)
        b.communicate(timeout=15)
        assert b.returncode == 3  # 同じリポジトリの別 worktree は同じロック
        c = _holder(tmp_path, other, 0, 0)
        _wait_acquired(c)  # 別リポジトリは独立
        assert c.wait(5) == 0
    finally:
        a.kill()
        a.wait(5)


def test_lock_without_git_warns_and_continues(tmp_path, capsys, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setenv(
        "GIT_CEILING_DIRECTORIES", str(tmp_path)
    )  # tmp_path が別のリポジトリ内でも git と見なさない
    assert verify.acquire_all_lock(plain, 0) is None
    assert "警告" in capsys.readouterr().err


def test_main_all_acquires_lock_but_other_modes_do_not(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(verify, "acquire_all_lock", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(verify, "execute", lambda *a, **k: [])
    monkeypatch.setattr(verify, "_stamp_snapshot", lambda: None)
    monkeypatch.setattr(verify, "_write_stamp", lambda started=None: None)
    monkeypatch.setattr(verify.os, "nice", lambda n: 0, raising=False)
    for argv in (["--all", "--dry-run"], ["--dry-run"], ["--list"], ["--changed", "--dry-run"]):
        assert verify.main(argv) == 0
    assert calls == []
    assert verify.main(["--all"]) == 0
    assert calls == [1]


def test_main_all_returns_3_on_lock_timeout(monkeypatch):
    def boom(*a, **k):
        raise verify.LockTimeout("busy")

    ran: list[int] = []
    monkeypatch.setattr(verify, "acquire_all_lock", boom)
    monkeypatch.setattr(verify.os, "nice", lambda n: 0, raising=False)
    monkeypatch.setattr(verify, "execute", lambda *a, **k: ran.append(1) or [])
    assert verify.main(["--all"]) == 3
    assert ran == []


def test_import_does_not_take_lock(tmp_path, repo):
    code = (
        "import importlib.util, sys, time\n"
        "s = importlib.util.spec_from_file_location('verify', sys.argv[1])\n"
        "m = importlib.util.module_from_spec(s); sys.modules['verify'] = m; s.loader.exec_module(m)\n"
        "print('IMPORTED', flush=True); time.sleep(5)\n"
    )
    p = subprocess.Popen(
        [sys.executable, "-c", code, str(SCRIPT)],
        cwd=repo,
        stdout=subprocess.PIPE,
        encoding="utf-8",
    )
    try:
        assert p.stdout is not None
        assert p.stdout.readline().strip() == "IMPORTED"
        h = _holder(tmp_path, repo, 0, 0)
        _wait_acquired(h)  # import しただけの者はロックを持たない
        assert h.wait(5) == 0
    finally:
        p.kill()
        p.wait(5)


# --- 変更の基準 (統合先との merge-base) と前提不足 ---


def _g(repo: Path, *args: str) -> str:
    env_args = ["-c", "user.name=Example Dev", "-c", "user.email=you@example.com"]
    out = subprocess.run(
        ["git", *env_args, *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return out.stdout


def _repo(tmp_path: Path, branch: str = "develop") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _g(repo, "init", "-q", "-b", branch)
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    _g(repo, "add", ".")
    _g(repo, "commit", "-q", "-m", "init")
    return repo


def _run_main(monkeypatch, repo: Path, *argv: str) -> int:
    monkeypatch.setattr(verify, "ROOT", repo)
    return verify.main(["--dry-run", *argv])


def test_committed_changes_are_selected_when_the_worktree_is_clean(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    _g(repo, "switch", "-q", "-c", "feature/x")
    (repo / "docs").mkdir()
    (repo / "docs" / "a.md").write_text("a\n", encoding="utf-8")
    _g(repo, "add", ".")
    _g(repo, "commit", "-q", "-m", "docs")
    assert _g(repo, "status", "--short") == ""
    assert _run_main(monkeypatch, repo) == 0
    out = capsys.readouterr().out
    assert "pre-commit run --files docs/a.md" in out
    assert "変更なし" not in out


def test_the_base_line_is_always_printed(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    _run_main(monkeypatch, repo)
    base = _g(repo, "rev-parse", "develop").strip()[:8]
    assert f"基準: develop との merge-base {base}、対象 0 件" in capsys.readouterr().out


def test_no_change_when_head_is_the_base(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    assert _run_main(monkeypatch, repo) == 0
    assert "変更なし (基準と同一)" in capsys.readouterr().out


def test_zero_targets_with_commits_warns(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    _g(repo, "switch", "-q", "-c", "feature/x")
    _g(repo, "commit", "-q", "--allow-empty", "-m", "empty")
    assert _run_main(monkeypatch, repo) == 0
    out = capsys.readouterr().out
    assert "警告" in out and "変更なし (基準と同一)" not in out


def test_unresolvable_base_exits_2_and_does_not_fall_back_to_head(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path, branch="zzz")
    (repo / "docs").mkdir()
    (repo / "docs" / "a.md").write_text("a\n", encoding="utf-8")
    assert _run_main(monkeypatch, repo) == 2
    captured = capsys.readouterr()
    assert "基準を決められません" in captured.err
    assert "pre-commit" not in captured.out


def test_base_is_not_needed_for_all(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path, branch="zzz")
    assert _run_main(monkeypatch, repo, "--all") == 0
    assert "基準を決められません" not in capsys.readouterr().err


def test_pr_viewer_tests_without_node_are_unverified(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    _g(repo, "switch", "-q", "-c", "feature/x")
    (repo / "apps" / "pr-viewer").mkdir(parents=True)
    (repo / "apps" / "pr-viewer" / "a.ts").write_text("x\n", encoding="utf-8")
    _g(repo, "add", ".")
    _g(repo, "commit", "-q", "-m", "ts")
    bin_dir = tmp_path / "bin"  # git だけがある PATH (node は見つからない)
    bin_dir.mkdir()
    (bin_dir / "git").symlink_to(shutil.which("git"))
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.delenv("VERIFY_ALLOW_SKIP", raising=False)
    monkeypatch.setattr(verify, "ROOT", repo)
    monkeypatch.setattr(verify, "execute", lambda *a, **k: [])
    assert verify.main([]) == 1
    captured = capsys.readouterr()
    assert "未検証" in captured.err and "node" in captured.err
    monkeypatch.setenv("VERIFY_ALLOW_SKIP", "1")
    assert verify.main([]) == 0
    captured = capsys.readouterr()
    assert "警告" in captured.err and "未検証" not in captured.err


def test_missing_prerequisites_only_for_pr_viewer_tests():
    pr = ["test/agents/test_pr_viewer_merge.py"]
    assert verify.missing_prerequisites(pr, node_ok=lambda: False)
    assert verify.missing_prerequisites(pr, node_ok=lambda: True) == []
    # 意図的に skip される別の試験は対象にしない
    assert (
        verify.missing_prerequisites(["test/agents/test_pi_judge_ts.py"], node_ok=lambda: False)
        == []
    )


# --- 閉じたモジュール (T2 の省略) ---

KCAGE_FILE = "scripts/kcage/example.py"


def _closed(*paths: str):
    return verify.closed_scope(list(paths), TEST_FILES, exists=lambda _p: True, refs={})


def test_closed_scope_accepts_only_changes_inside_the_module():
    scope = _closed(KCAGE_FILE, "test/kcage/test_cli.py", "home/dot_local/bin/executable_kcage")
    assert [m.name for m in scope] == ["kcage"]
    assert _closed(KCAGE_FILE, "docs/spec/development.md") is None  # 範囲外が 1 つでもあれば全件
    assert _closed(KCAGE_FILE, "scripts/verify.py") is None
    assert _closed("unknown/file.txt") is None  # どの規則にも当たらない
    assert _closed() is None  # 変更なしは全件のまま


def test_closed_scope_falls_back_for_deleted_paths_and_outside_readers():
    gone = verify.closed_scope([KCAGE_FILE], TEST_FILES, exists=lambda _p: False, refs={})
    assert gone is None
    outside = "test/test_zzz_outside.py"
    refs = {outside: frozenset({KCAGE_FILE})}
    files = [*TEST_FILES, outside]
    reader = verify.closed_scope([KCAGE_FILE], files, exists=lambda _p: True, refs=refs)
    assert reader is None  # モジュール外の試験が読むファイルは閉じていない


def test_full_stages_can_skip_t2():
    stages = verify.full_stages(["test/kcage/test_cli.py"], [], TEST_FILES, skip_t2=True)
    flat = [c for s in stages for c in s]
    assert not any("--ignore=" in part for c in flat for part in c)
    assert len(stages) == 2  # T0 と T1 だけ
    assert len(verify.full_stages([], [], TEST_FILES, skip_t2=True)) == 1


def _kcage_repo(tmp_path: Path, *extra: str) -> Path:
    repo = _repo(tmp_path)
    _g(repo, "switch", "-q", "-c", "feature/x")
    for rel in (KCAGE_FILE, *extra):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("x\n", encoding="utf-8")
    _g(repo, "add", ".")
    _g(repo, "commit", "-q", "-m", "change")
    return repo


def _t2_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if "--ignore=" in line]


def test_all_skips_t2_for_closed_module_changes_and_says_so(tmp_path, monkeypatch, capsys):
    repo = _kcage_repo(tmp_path)
    assert _run_main(monkeypatch, repo, "--all") == 0
    out = capsys.readouterr().out
    assert "閉じたモジュール (kcage)" in out and "mise run verify:full" in out
    assert _t2_lines(out) == []
    assert "pre-commit run --all-files" in out  # T0 は残る
    assert "test/test_verify.py" in out  # 登録ずれの検査も残る


def test_all_full_never_skips(tmp_path, monkeypatch, capsys):
    repo = _kcage_repo(tmp_path)
    assert _run_main(monkeypatch, repo, "--all", "--full") == 0
    out = capsys.readouterr().out
    assert "T2" not in out and "閉じたモジュール" not in out
    assert len(_t2_lines(out)) == 1


def test_all_runs_everything_when_a_path_is_outside_the_module(tmp_path, monkeypatch, capsys):
    repo = _kcage_repo(tmp_path, "docs/a.md")
    assert _run_main(monkeypatch, repo, "--all") == 0
    out = capsys.readouterr().out
    assert "閉じたモジュール" not in out and len(_t2_lines(out)) == 1


def test_all_runs_everything_when_the_base_is_unknown(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path, branch="zzz")
    (repo / "scripts" / "kcage").mkdir(parents=True)
    (repo / KCAGE_FILE).write_text("x\n", encoding="utf-8")
    assert _run_main(monkeypatch, repo, "--all") == 0
    out = capsys.readouterr().out
    assert "閉じたモジュール" not in out and len(_t2_lines(out)) == 1


def test_full_requires_all(capsys):
    with pytest.raises(SystemExit):
        verify.main(["--full"])


def test_stamp_notes_the_scope_when_t2_was_skipped(tmp_path, monkeypatch):
    repo = _kcage_repo(tmp_path)
    monkeypatch.setattr(verify, "ROOT", repo)
    monkeypatch.setattr(verify, "execute", lambda *a, **k: [])
    monkeypatch.setattr(verify, "acquire_all_lock", lambda *_a, **_k: None)
    written: list[str] = []

    class Stamp(_FakeStamp):
        def write_stamp(self, _root, entries=None, scope="full"):
            written.append(scope)

    monkeypatch.setattr(verify, "_stamp_module", lambda: Stamp({}))
    monkeypatch.setattr(verify, "_stamp_snapshot", dict)
    assert verify.main(["--all"]) == 0
    assert written == ["closed:kcage"]
    written.clear()
    assert verify.main(["--all", "--full"]) == 0
    assert written == ["full"]  # 従来どおり scope を渡さない (印の既定は full)


# 閉じていることの機械検査 (表 CLOSED_MODULES が正本)


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=False
    ).stdout.decode("utf-8", "replace")
    return [f for f in out.split("\0") if f and (ROOT / f).exists()]


@pytest.mark.parametrize("module", verify.CLOSED_MODULES, ids=lambda m: m.name)
def test_closed_module_globs_match_real_paths(module):
    files = _tracked_files()
    assert files
    for pattern in module.scope_paths:
        assert any(verify._match(pattern, f) for f in files), f"{module.name}: {pattern}"
    for pattern in module.shared_reads:
        assert any(verify._match(pattern, f) for f in files), f"{module.name}: {pattern}"


@pytest.mark.parametrize("module", verify.CLOSED_MODULES, ids=lambda m: m.name)
def test_closed_module_tests_read_only_inside_the_module(module):
    """モジュールの試験が読むパスは、モジュールの範囲か共有の読み取り専用に収まる。"""
    # 走査系 (scanners) はリポジトリ全体を読むので、モジュール自身の試験の検査から外す
    scanners = set(verify.resolve_tests(module.scanners, TEST_FILES))
    tests = sorted(verify.module_test_files(module, TEST_FILES) - scanners)
    assert tests
    allowed = (*module.scope_paths, *module.shared_reads)
    stray = []
    for test, refs in verify.test_references(tests).items():
        for ref in sorted(refs):
            if test == ref or any(
                verify._match(p, ref) or verify._match(p, ref + "/") for p in allowed
            ):
                continue
            stray.append(f"{test} <- {ref}")
    assert stray == []


@pytest.mark.parametrize("module", verify.CLOSED_MODULES, ids=lambda m: m.name)
def test_closed_module_files_are_not_read_by_outside_tests(module):
    """モジュールの変更パスを、モジュール外の試験が読んでいない (読むなら閉じていない)。"""
    own = verify.module_test_files(module, TEST_FILES)
    own |= set(module.ignored_readers) | {*verify.T0_PYTEST_FILES, verify.REGISTRATION_TEST}
    outside = [t for t in TEST_FILES if t not in own]
    refs = verify.test_references(outside)
    leaks = []
    for f in _tracked_files():
        if not any(verify._match(p, f) for p in module.scope_paths):
            continue
        for test, rs in refs.items():
            if any(f == r or f.startswith(r + "/") for r in rs):
                leaks.append(f"{test} <- {f}")
    assert leaks == []


@pytest.mark.parametrize("module", verify.CLOSED_MODULES, ids=lambda m: m.name)
def test_every_tracked_file_of_a_closed_module_is_closed(module):
    files = [f for f in _tracked_files() if any(verify._match(p, f) for p in module.scope_paths)]
    assert files
    for f in files:
        scope = verify.closed_scope([f], TEST_FILES)
        assert scope is not None and [m.name for m in scope] == [module.name], f


def test_closed_scope_accepts_the_modules_own_docs_with_code():
    """kcage のコードと kcage の文書だけの変更は閉じている (文書の lint は T0 が全件で回す)。"""
    paths = ["scripts/kcage/cli.py", "docs/spec/sandbox/incus-box.md"]
    hit = verify.closed_scope(paths, TEST_FILES)
    assert hit is not None and [m.name for m in hit] == ["kcage"]


def test_closed_scope_rejects_other_docs():
    """モジュール外の文書が混ざれば閉じていない (従来どおり全件)。"""
    paths = ["scripts/kcage/cli.py", "docs/spec/development.md"]
    assert verify.closed_scope(paths, TEST_FILES) is None

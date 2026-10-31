#!/usr/bin/env python3
"""変更したパスに応じて、走らせる試験・検査を選ぶ入口。

    python3 scripts/verify.py [--changed | --all] [--dry-run] [--list]

どの規則にも当たらないパス・「全件に回す領域」のパス・削除されたパスが 1 つでも
あれば全件にフォールバックする (取りこぼしより過剰な実行を選ぶ)。
試験が読むファイル (ソースの文字列・パス連結から拾う) の変更は、その試験を選ぶ。
see docs/spec/development.md#検証の方針と選択実行
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import functools
import os
import posixpath
import re
import shlex
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PYTEST_OPTS = ["-q"]
# 並列化 (pytest-xdist)。方式の選び方と実測は docs/change/closed/0028-verification-speed-and-delegation.md。
# 既定はコア数の半分 (全コアだと実行中に PC が重くなる)。VERIFY_JOBS / --jobs で上書き。
# see docs/spec/development.md#検証の方針と選択実行


def jobs() -> int:
    raw = os.environ.get("VERIFY_JOBS", "")
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return max(1, (os.cpu_count() or 4) // 2)


def parallel_opts() -> list[str]:
    return ["-n", str(jobs()), "--dist", "worksteal"]


NICE_LEVEL = 10  # 子プロセス (pytest のワーカー) が継承する。対話的な作業を重くしない
PARALLEL_MIN_FILES = 3  # 少数のファイルだけの実行では、ワーカーの起動の方が高いので直列のまま
# 登録ずれを数秒で見つける試験 (全件の T0 に入れる)
REGISTRATION_TEST = "test/test_verify.py"
# T0 の pre-push の hook (raspi-regression-local) が実行する試験。T1 と T2 からは外す (hook の entry と一致することは試験で見る)
HOOK_PYTEST_FILES = ("test/test_raspi_detection.py",)
T0_PYTEST_FILES = (REGISTRATION_TEST, *HOOK_PYTEST_FILES)
LINT_TEMPLATES = ["mise", "exec", "--", "python3", "scripts/lint_templates.py"]
LINT_DOCS = [
    "mise",
    "exec",
    "--",
    "python3",
    "home/dot_claude/skills/sdd-docs/scripts/lint_docs.py",
]
# pyyaml を足さない試験 (AGENTS.md「検証」の表の形)
NO_YAML_TESTS = frozenset({"test_windows_assets", "test_chezmoi_templates"})
WINDOWS_NOTE = "注意: Windows 実機では未検証 (docs/spec/development.md#windows-実機での検証)"

SELF_TEST = re.compile(r"^test/(?:.+/)?test_[^/]+\.py$")


@dataclass(frozen=True)
class Rule:
    """paths に当たる変更に対し、tests (stem の glob) と lint を選ぶ。

    covers=False の規則は「当たっても未知のパス扱い」(lint を足すだけ)。
    """

    name: str
    paths: tuple[str, ...]
    tests: tuple[str, ...] = ()
    lints: tuple[str, ...] = ()  # "templates" / "docs"
    full: bool = False
    covers: bool = True
    windows: bool = False


_HOOK_TESTS = (
    "test_check_bash_*",
    "test_command_policy",
    "test_decide*",
    "test_shellparse",
    "test_bashrules_tables",
    "test_preflight",
    "test_check_file_read",
    "test_redirect_tmp",
    "test_secret_lists_in_sync",
    "test_generate_hooks",
    "test_markdownlint_hook",
    "test_env_check",
)
_PI_TESTS = (
    "test_pi_harness",
    "test_pi_harness_extensions",
    "test_pi_actions_harness",
    "test_pi_action_view",
    "test_pi_actions",
    "test_pi_boundary",
    "test_pi_workspace_hide",
    "test_broker",
    "test_broker_search",
    "test_pi_broker_generate",
    "test_pi_network",
    "test_bedrock_probe",
    "test_pi_github_boundary",
    "test_pi_commit_confirm",
    "test_pi_audit",
    "test_pi_confirm",
    "test_pi_integrate_config",
    "test_pi_landlock_exec",
    "test_pi_tools_ext",
    "test_pi_model_choice",
    "test_pi_plan_role",
    "test_pi_pending_store",
    "test_pi_git_destructive",
    "test_pi_orchestrate",
    "test_pi_allow_output_quoting",
    "test_pi_deny_default_ask",
    "test_pi_model_catalog",
    "test_pi_scratch_protected",
    "test_pi_session_tmp",
    "test_tmp_hygiene",
    "test_pi_confirm_view",
    "test_pi_speed",
    "test_pi_ask_normalize",
    "test_pi_worktree",
    "test_pi_isolation",
    "test_pi_worktrees_command",
    "test_pi_subagents",
    "test_pi_shared",
    "test_pi_settings_launch",
    "test_pi_unguarded",
    "test_pi_control_files_bash",
    "test_pi_platform",
    "test_pi_judge_windows_paths",
    "test_btw_view",
)
_OC_TESTS = (
    "test_generate_opencode*",
    "test_opencode_*",
    "test_guide_*",
    "test_checkpoint*",
    "test_oc_utils",
    "test_relay",
)

RULES: tuple[Rule, ...] = (
    Rule(
        "全件に回す領域 (全試験の入力・横断設定)",
        (
            "home/dot_config/agents/common.toml.tmpl",
            "scripts/agents/generate.py",
            "scripts/agents/hooks.py",
            "pyproject.toml",
            ".pre-commit-config.yaml",
            "mise.toml",
            "conftest.py",
            "uv.lock",
            "test/agents/agents_common.py",
            "test/agents/conftest.py",
        ),
        full=True,
        windows=True,
    ),
    Rule("試験ファイル自身", ()),  # 実体は plan() が処理する (SELF_TEST)
    Rule(
        "skill の検証",
        ("scripts/agents/validate_skills.py", "home/dot_claude/skills/*/SKILL.md"),
        ("test_skill_frontmatter",),
    ),
    Rule(
        "skill 本文を直接読む試験",
        ("home/dot_claude/skills/*/SKILL.md",),
        ("test_check_bash_config", "test_opencode_commit_rules", "test_check_bash_http_github"),
    ),
    Rule(
        "agent 指示の共有本文 (pi の描画と Claude の描画を比べる)",
        ("home/.chezmoitemplates/agent-instructions.md",),
        ("test_pi_harness", "test_generate_opencode*", "test_check_bash_config"),
    ),
    Rule(
        "commit-message.js (opencode 側の写しと pi 側の本体は双方向)",
        (
            "home/dot_config/opencode/guide-plugin/commit-message.js",
            "home/dot_config/pi/harness/commit-message.js",
        ),
        ("test_pi_commit_confirm",),
    ),
    Rule(
        "文書を直接 assert する試験",
        ("docs/spec/guard/agent-command-policy.md",),
        ("test_check_bash_config",),
    ),
    Rule("modify ラッパー", ("home/*/modify_*",), ("test_modifier_wrappers",)),
    Rule(
        "導入スクリプトを読む試験",
        (
            "home/.chezmoiscripts/*_mise.*",
            "home/.chezmoiscripts/*_agent_cli.*",
            "home/.chezmoiscripts/*_herdr_integration.*",
        ),
        ("test_herdr_integration",),
    ),
    Rule(
        "websearch の鍵スクリプト",
        ("home/.chezmoiscripts/*_websearch_keys.*",),
        ("test_websearch",),
    ),
    Rule("共通設定の検証", ("scripts/agents/validate_common.py",), ("test_mcp_servers",)),
    Rule(
        "不満・摩擦の集計",
        (".agents/skills/friction-review/scripts/*.py", ".agents/skills/friction-review/SKILL.md"),
        ("test_friction_scan",),
    ),
    Rule(
        "golden",
        ("scripts/agents/export_*_golden.py", "test/agents/golden/**"),
        (
            "test_decide_golden",
            "test_pi_judge_ts",
            "test_decide",
            "test_command_policy",
            "test_check_bash_*",
        ),
    ),
    Rule(
        "hook・コマンド方針",
        (
            "home/dot_claude/hooks/**",
            "home/dot_config/agents/command_policy.py",
            "test/agents/check_bash_hook.py",
        ),
        _HOOK_TESTS,
    ),
    Rule(
        "pi 判定器",
        ("home/dot_config/pi/harness/judge/**",),
        (
            "test_pi_judge_ts",
            "test_bashrules_tables",
            "test_secret_lists_in_sync",
            "test_pi_harness",
            "test_pi_boundary",
        ),
    ),
    Rule(
        "pi ハーネス・拡張",
        (
            "home/dot_config/pi/harness/**",
            "home/dot_pi/agent/extensions/**",
            "home/dot_local/bin/executable_pis",
            "test/agents/pi/**",
        ),
        _PI_TESTS,
    ),
    Rule(
        "pi commit-confirm",
        ("home/dot_config/pi/commit-confirm/**",),
        ("test_pi_commit_parse", "test_pi_commit_confirm"),
    ),
    Rule(
        "opencode",
        (
            "home/dot_config/opencode/**",
            "home/dot_local/share/ocs/**",
            "home/dot_local/bin/executable_oc*",
        ),
        _OC_TESTS,
    ),
    Rule(
        "agents 設定 (common 以外)",
        ("home/dot_config/agents/**", "home/.chezmoiscripts/400_unix/*claude_mcp*"),
        ("test_generate_*", "test_pi_shared", "test_mcp_servers", "test_claude_mcp_registration"),
    ),
    Rule(
        "chezmoi データ・mise 設定",
        (
            "home/.chezmoiignore.tmpl",
            "home/.chezmoi.toml.tmpl",
            "home/dot_config/mise/config.toml.tmpl",
        ),
        (
            "test_chezmoi_templates",
            "test_raspi_detection",
            "test_python_requirement",
            "test_herdr_integration",
        ),
        ("templates",),
    ),
    Rule(
        "共有テンプレート",
        ("home/.chezmoitemplates/**",),
        (
            "test_check_bash_config",
            "test_generate_opencode*",
            "test_modifier_wrappers",
            "test_mcp_servers",
            "test_windows_assets",
            "test_raspi_detection",
        ),
        ("templates",),
        windows=True,
    ),
    Rule("web-search", ("home/dot_claude/skills/web-search/**",), ("test_websearch",)),
    Rule(
        "imozuru",
        ("home/dot_claude/skills/imozuru/**", "scripts/vendor/imozuru_patch.py"),
        ("test_imozuru", "test_chezmoi_templates"),
    ),
    Rule(
        "powerpoint-studio",
        ("home/dot_claude/skills/powerpoint-studio/**",),
        ("test_powerpoint_skill", "test_chezmoi_templates"),
    ),
    Rule(
        "github-operations",
        ("home/dot_claude/skills/github-operations/**",),
        ("test_github_operations_resolve",),
    ),
    Rule(
        "checkpoint skill",
        ("home/dot_claude/skills/checkpoint/**", "scripts/checkpoint.py"),
        ("test_checkpoint*",),
    ),
    Rule(
        "sdd-docs",
        ("home/dot_claude/skills/sdd-docs/**",),
        ("test_check_refs", "test_docs_state", "test_lint_docs", "test_opencode_external_read"),
        ("docs",),
    ),
    Rule("away-shift", ("home/dot_claude/skills/away-shift/**",), ("test_away_guard",)),
    Rule(
        "models の道具",
        ("scripts/models.py",),
        ("test_models_tool", "test_pi_model_catalog"),
    ),
    Rule("tmp-clean", ("home/dot_config/pi/harness/tmp_clean.py",), ("test_tmp_clean",)),
    Rule("env-check", ("home/dot_claude/skills/env-check/**",), ("test_env_check",)),
    Rule(
        "テンプレート検査器",
        ("scripts/lint_templates.py",),
        ("test_lint_templates",),
        ("templates",),
    ),
    Rule("検証の入口", ("scripts/verify.py",), ("test_verify", "test_verify_stamp")),
    Rule("検証の印", ("scripts/verify_stamp.py",), ("test_verify_stamp",)),
    Rule("並列実装の混線の検査", ("scripts/parallel_check.py",), ("test_parallel_check",)),
    Rule("skill-lab のスキル同期", ("scripts/sync_skill_lab.py",), ("test_sync_skill_lab",)),
    Rule("model-eval", ("scripts/model-eval/**",), ("test_model_eval",)),
    Rule(
        "shell 設定",
        ("home/dot_config/shell/**", "home/dot_zshenv"),
        ("test_shell_functions", "test_shell_startup", "test_zshenv_tmpdir"),
    ),
    Rule(
        "chezmoiscripts",
        ("home/.chezmoiscripts/**",),
        (
            "test_bootstrap_scripts",
            "test_authorized_keys",
            "test_wsl_timesync_script",
            "test_chezmoi_templates",
        ),
    ),
    Rule(
        "Windows 資産",
        (
            "home/.chezmoiscripts/300_windows/**",
            "home/dot_config/powershell/**",
            "scripts/windows/**",
            "*.ps1",
            "*.ps1.tmpl",
        ),
        ("test_windows_assets", "test_powershell_interactive"),
        windows=True,
    ),
    Rule(
        "Windows アプリ設定",
        ("home/AppData/**",),
        ("test_windows_terminal_settings", "test_windows_assets"),
        windows=True,
    ),
    # test_lint_docs は同じ lint の直接実行 (lints=docs) で代替する
    Rule("docs", ("docs/**",), lints=("docs",)),
    Rule(
        "ルートの文書",
        ("README.md", "AGENTS.md", "CLAUDE.md", "test/README.md"),
    ),
    # 以下は lint を足すだけ。未知のパス扱いは変えない
    Rule("*.tmpl の検査", ("*.tmpl",), lints=("templates",), covers=False),
)


@dataclass
class Plan:
    commands: list[list[str]] = field(default_factory=list)
    # 段の境界: commands[i] の後で、ここまでに失敗があれば次の段を始めない (--keep-going で続行)
    gates: list[int] = field(default_factory=list)
    full: bool = False
    windows: bool = False
    no_change: bool = False
    hits: dict[str, list[str]] = field(default_factory=dict)
    # 規則・参照で選んだ試験ファイル (全件の T1 に使う)
    selected: list[str] = field(default_factory=list)


def _match(pattern: str, path: str) -> bool:
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-2])
    return fnmatch(path, pattern)


def normalize_path(path: str) -> str:
    """リポジトリ相対の / 区切りに揃える (./・\\・絶対パス・先頭の /)。"""
    text = path.replace("\\", "/")
    prefix = ROOT.as_posix() + "/"
    if text.startswith(prefix):
        text = text[len(prefix) :]
    norm = posixpath.normpath(text.lstrip("/")) if text.strip("/") else ""
    return "" if norm == "." else norm


_ROOT_NAMES = frozenset({"ROOT", "REPO", "REPO_ROOT", "REPO_DIR", "PROJECT_ROOT"})
MIN_REF_DIR_DEPTH = 3  # "home" や "scripts" のような広いディレクトリは参照として数えない


def _join(base: str | None, part: str | None) -> str | None:
    if base is None or part is None or part.startswith("/"):
        return None
    joined = posixpath.normpath(posixpath.join(base, part))
    if joined == ".":
        return ""
    return None if joined.startswith("..") else joined


def _eval_path(node: ast.AST, env: dict[str, str], me: str) -> str | None:
    """式をリポジトリ相対パスへ評価する。静的に決まらなければ None。"""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.Name):
        if node.id == "__file__":
            return me
        return env.get(node.id, "" if node.id in _ROOT_NAMES else None)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _join(_eval_path(node.left, env, me), _eval_path(node.right, env, me))
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        base = _eval_path(node.value, env, me)
        return None if not base else posixpath.dirname(base)
    if isinstance(node, ast.Subscript):
        value, index = node.value, node.slice
        if (
            isinstance(value, ast.Attribute)
            and value.attr == "parents"
            and isinstance(index, ast.Constant)
            and isinstance(index.value, int)
            and index.value >= 0
        ):
            cur = _eval_path(value.value, env, me)
            for _ in range(index.value + 1):
                if not cur:
                    return None
                cur = posixpath.dirname(cur)
            return cur
        return None
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id == "Path" and node.args:
            cur: str | None = ""
            for arg in node.args:
                cur = _join(cur, _eval_path(arg, env, me))
            return cur
        if (
            isinstance(func, ast.Attribute)
            and func.attr in {"resolve", "absolute"}
            and not node.args
        ):
            return _eval_path(func.value, env, me)
    return None


def _ref_candidates(tree: ast.Module, me: str) -> tuple[set[str], set[str]]:
    """(式として評価できたパス, 連結の一部に現れる "/" 入りの文字列)。"""
    env: dict[str, str] = {}
    for stmt in tree.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
        ):
            value = _eval_path(stmt.value, env, me)
            if value is not None:
                env[stmt.targets[0].id] = value
    inner: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            inner.update((id(node.left), id(node.right)))
    found: set[str] = set()
    loose: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and id(node) not in inner:
            value = _eval_path(node, env, me)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "/" in node.value:
            value = _join("", node.value)
            if id(node) in inner:
                if value:
                    loose.add(value)
                continue
        else:
            continue
        if value:
            found.add(value)
    return found, loose


@functools.cache
def _scan_test_file(root: Path, rel: str) -> frozenset[str]:
    """試験ファイルが読む、実在するリポジトリ内のファイル (と十分に狭いディレクトリ)。"""
    try:
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return frozenset()
    found, loose = _ref_candidates(tree, rel)
    refs: set[str] = set()
    for cand in sorted(found | loose):
        if len(cand) > 240 or any(c.isspace() or c == "\0" for c in cand):
            continue
        target = root / cand
        try:
            narrow_dir = (
                cand in found and target.is_dir() and cand.count("/") + 1 >= MIN_REF_DIR_DEPTH
            )
            if target.is_file() or narrow_dir:
                refs.add(cand)
        except OSError:
            continue
    return frozenset(refs)


def test_references(test_files: Sequence[str], root: Path = ROOT) -> dict[str, frozenset[str]]:
    """試験ファイル → その試験が読むパスの集合。"""
    return {f: _scan_test_file(root, f) for f in test_files}


def matching_rules(path: str) -> list[Rule]:
    return [r for r in RULES if any(_match(p, path) for p in r.paths)]


def resolve_tests(patterns: Sequence[str], test_files: Sequence[str]) -> list[str]:
    """stem の glob を、実在する試験ファイル (リポジトリ相対) に解決する。"""
    return sorted({f for f in test_files if any(fnmatch(Path(f).stem, p) for p in patterns)})


def pytest_command(
    files: Sequence[str], *, yaml: bool = True, ignore: Sequence[str] = ()
) -> list[str]:
    parallel = list(files) == ["test/"] or len(files) >= PARALLEL_MIN_FILES
    cmd = ["uv", "run", "--with", "pytest"]
    if yaml:
        cmd += ["--with", "pyyaml"]
    if parallel:
        cmd += ["--with", "pytest-xdist"]
    return [
        *cmd,
        "--no-project",
        "pytest",
        *files,
        *PYTEST_OPTS,
        *[f"--ignore={f}" for f in sorted(ignore)],
        *(parallel_opts() if parallel else []),
    ]


def selected_commands(selected: Sequence[str]) -> list[list[str]]:
    """選んだ試験ファイルを、pyyaml の要否で分けた pytest コマンドにする。"""
    yaml_files = sorted(f for f in selected if Path(f).stem not in NO_YAML_TESTS)
    plain_files = sorted(set(selected) - set(yaml_files))
    commands: list[list[str]] = []
    if yaml_files:
        commands.append(pytest_command(yaml_files))
    if plain_files:
        commands.append(pytest_command(plain_files, yaml=False))
    return commands


def full_stages(
    t1_files: Sequence[str] = (),
    shell_files: Sequence[str] = (),
    test_files: Sequence[str] | None = None,
) -> list[list[list[str]]]:
    """全件を段に分ける: T0 (数秒〜数十秒の安い検査) → T1 (変更に当たる試験) → T2 (残りの全件)。

    T2 は T1 と T0 の試験を --ignore する補集合なので、取りこぼしも二重実行も出ない。
    test_files (全試験ファイル) を渡すと、補集合が空のときは T2 を省く (空のまま pytest を走らせると「試験なし」で失敗する)。
    lint_docs を直接呼ばないのは、pre-commit の hook (lint-docs-local) が --all-files で同じ検査をするため。
    """
    t0: list[list[str]] = [
        ["uv", "run", "pre-commit", "run", "--all-files"],
        # commit の stage には lint-templates-local と raspi-regression-local が無い (pre-push のみ)
        ["uv", "run", "pre-commit", "run", "--all-files", "--hook-stage", "pre-push"],
    ]
    if shell_files:
        t0.append(["mise", "exec", "shellcheck", "--", "shellcheck", *shell_files])
    t0.append(pytest_command([REGISTRATION_TEST]))
    stages = [t0]
    done = [f for f in dict.fromkeys([*t1_files, *T0_PYTEST_FILES])]
    t1 = selected_commands([f for f in t1_files if f not in T0_PYTEST_FILES])
    if t1:
        stages.append(t1)
    if test_files is None or set(test_files) - set(done):
        stages.append([pytest_command(["test/"], ignore=done)])
    return stages


def flatten_stages(stages: Sequence[Sequence[list[str]]]) -> tuple[list[list[str]], list[int]]:
    """段の列を、平らなコマンド列と、各段の最後のコマンドの位置 (最後の段を除く) にする。"""
    commands: list[list[str]] = []
    gates: list[int] = []
    for i, stage in enumerate(stages):
        commands.extend(stage)
        if i < len(stages) - 1 and stage:
            gates.append(len(commands) - 1)
    return commands, gates


def full_commands(t1_files: Sequence[str] = (), shell_files: Sequence[str] = ()) -> list[list[str]]:
    return flatten_stages(full_stages(t1_files, shell_files))[0]


def plan(
    paths: Sequence[str],
    test_files: Sequence[str],
    *,
    exists: Callable[[str], bool] | None = None,
    refs: dict[str, frozenset[str]] | None = None,
    shell_files: Sequence[str] = (),
) -> Plan:
    """変更パスの列から実行するコマンド列を決める (git も実行もしない)。

    refs は試験ファイル → 読むパス (省略時はソースから拾う)。shell_files は全件の T0 で shellcheck する対象。
    全件のときも、規則・参照で選んだ試験を T1 として先に回す (失敗の見つかる順を早める)。
    """
    paths = list(dict.fromkeys(p for p in map(normalize_path, paths) if p))
    if not paths:
        return Plan(no_change=True)
    exists = exists or (lambda p: (ROOT / p).exists())
    refs = test_references(test_files) if refs is None else refs
    result = Plan()
    selected: set[str] = set()
    lints: set[str] = set()
    for path in paths:
        if not exists(path):
            # 削除されたファイルは、他の試験の import や収集を壊しうる
            result.full = True
            result.hits[path] = ["削除 → 全件"]
            continue
        rules = matching_rules(path)
        names = [r.name for r in rules]
        covered = any(r.covers for r in rules)
        readers = sorted(
            t
            for t in test_files
            if any(path == r or path.startswith(r + "/") for r in refs.get(t, ()))
        )
        if readers:
            covered = True
            names.append("試験が参照")
            selected.update(readers)
        if SELF_TEST.match(path):
            covered = True
            names.append("試験ファイル自身")
            if path in test_files:
                selected.add(path)
        if not covered:
            names = ["未一致 → 全件"]
            result.full = True
        for rule in rules:
            result.full |= rule.full
            result.windows |= rule.windows
            lints.update(rule.lints)
            selected.update(resolve_tests(rule.tests, test_files))
        result.hits[path] = names
    result.selected = sorted(selected)
    if result.full:
        result.windows = True
        result.commands, result.gates = flatten_stages(
            full_stages(result.selected, shell_files, test_files)
        )
        return result

    # 安い検査を先に、試験を後にする (安いものが落ちたら試験を始めない)
    cheap: list[list[str]] = []
    existing = [p for p in paths if exists(p)]
    if existing:
        cheap.append(["uv", "run", "pre-commit", "run", "--files", *existing])
    if "templates" in lints:
        cheap.append(list(LINT_TEMPLATES))
    if "docs" in lints:
        cheap.append(list(LINT_DOCS))
    changed_shell = [p for p in existing if p.endswith(".sh")]
    if changed_shell:
        cheap.append(["mise", "exec", "shellcheck", "--", "shellcheck", *changed_shell])
    tests = selected_commands(sorted(selected))
    result.commands = [*cheap, *tests]
    if cheap and tests:
        result.gates = [len(cheap) - 1]
    return result


def discover_test_files(root: Path = ROOT) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in (root / "test").rglob("test_*.py"))


def collect_changed(run: Callable[[list[str]], str]) -> list[str]:
    """git から変更パスを集める。run はコマンド (引数リスト) を受けて stdout を返す。"""
    # --no-renames: リネームを旧パスの削除 + 新パスの追加として両方評価する。-z: 改行を含む名前も安全に
    out = run(["git", "diff", "--name-only", "--no-renames", "-z", "HEAD"]) + "\0"
    out += run(["git", "ls-files", "-z", "--others", "--exclude-standard"])
    return sorted({name for name in out.split("\0") if name})


def _git(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"git が失敗しました: {shlex.join(cmd)}")
    return proc.stdout


def tracked_shell_files(
    run: Callable[[list[str]], str], exists: Callable[[str], bool] | None = None
) -> list[str]:
    """全件の shellcheck の対象 (git が追跡している実在の *.sh。未ステージで消したファイルは除く)。"""
    exists = exists or (lambda p: (ROOT / p).exists())
    return sorted(n for n in run(["git", "ls-files", "-z", "*.sh"]).split("\0") if n and exists(n))


def execute(
    commands: Sequence[Sequence[str]],
    gates: Sequence[int] = (),
    *,
    keep_going: bool = False,
) -> list[list[str]]:
    """コマンドを順に実行する。失敗したコマンドを返す。

    gates の位置 (段の最後) でこれまでに失敗があれば、次の段を始めない (安い検査の失敗を、重い検査の前に見せる)。
    keep_going なら段で止めず、従来どおり失敗しても最後まで続ける。
    """
    failed: list[list[str]] = []
    for i, cmd in enumerate(commands):
        print(f"$ {shlex.join(cmd)}", flush=True)
        try:
            code = subprocess.run(list(cmd), cwd=ROOT, check=False).returncode
        except OSError as exc:
            print(f"起動できません: {exc}", file=sys.stderr)
            code = 127
        if code != 0:
            failed.append(list(cmd))
        if failed and i in gates and not keep_going:
            rest = len(commands) - i - 1
            print(
                f"この段で失敗したので、残り {rest} 件を実行しません (--keep-going で続行)",
                flush=True,
            )
            break
    return failed


def _stamp_module():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import verify_stamp

    return verify_stamp


def _stamp_snapshot():
    """全件検証の開始時の作業ツリー。取れないときは None (印を書かない)。"""
    try:
        return _stamp_module().snapshot(ROOT)
    except Exception as exc:
        print(f"警告: 検証の開始時の状態を取れませんでした: {exc}", file=sys.stderr)
        return None


def _write_stamp(started=None) -> None:
    """全件検証の成功を印に残す。失敗しても検証の結果は変えない。

    開始時の snapshot を記録し、終わりに同じ状態でなければ印を書かない
    (実行中に編集したファイルまで「検証済み」にしない)。
    """
    try:
        stamp = _stamp_module()
        if started is None:
            print("警告: 開始時の状態が無いので、検証の印を書きません", file=sys.stderr)
            return
        if stamp.snapshot(ROOT) != started:
            print(
                "警告: 実行中に作業ツリーが変わったので、検証の印を書きません (もう一度全件を回す)",
                file=sys.stderr,
            )
            return
        stamp.write_stamp(ROOT, started)
    except Exception as exc:
        print(f"警告: 検証の印を書けませんでした: {exc}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="変更に応じた試験・検査の選択実行")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--changed", action="store_true", help="変更したパスから選ぶ (既定)")
    mode.add_argument("--all", action="store_true", help="全件を実行する")
    parser.add_argument("--dry-run", action="store_true", help="実行せずコマンドを列挙する")
    parser.add_argument(
        "--list", action="store_true", help="変更パスごとの当たった規則を出す (実行しない)"
    )
    parser.add_argument("--keep-going", action="store_true", help="段で失敗しても次の段を実行する")
    parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        help="pytest の並列数 (既定: コア数の半分。VERIFY_JOBS でも指定できる)",
    )
    args = parser.parse_args(argv)
    if args.jobs > 0:
        os.environ["VERIFY_JOBS"] = str(args.jobs)

    test_files = discover_test_files()
    shell_files = tracked_shell_files(_git)
    if args.all:
        # 全件でも、変更に当たる試験を T1 として先に回す (変更が無ければ T1 は空)
        selection = plan(collect_changed(_git), test_files, shell_files=shell_files)
        commands, gates = flatten_stages(full_stages(selection.selected, shell_files, test_files))
        result = Plan(
            commands=commands,
            gates=gates,
            full=True,
            windows=True,
            hits=selection.hits,
            selected=selection.selected,
        )
    else:
        paths = collect_changed(_git)
        result = plan(paths, test_files, shell_files=shell_files)
        if args.list:
            for path, names in result.hits.items():
                print(f"{path}: {', '.join(names) or '(なし)'}")
            return 0
    if result.no_change:
        print("変更なし")
        return 0
    if result.full:
        print("全件を実行します")

    if args.dry_run:
        for i, cmd in enumerate(result.commands):
            print(shlex.join(cmd))
            if i in result.gates:
                print("# --- 段の境界 (ここまでに失敗があれば次を始めない) ---")
        return 0
    if hasattr(os, "nice"):
        with contextlib.suppress(OSError):
            os.nice(NICE_LEVEL)  # 子プロセスが継承する。失敗しても検査は続ける
    started = _stamp_snapshot() if result.full else None
    failed = execute(result.commands, result.gates, keep_going=args.keep_going)
    if result.windows:
        print(WINDOWS_NOTE)
    if failed:
        print("失敗したコマンド:")
        for cmd in failed:
            print(f"  {shlex.join(cmd)}")
        return 1
    if result.full:
        _write_stamp(started)
    print("すべて成功")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

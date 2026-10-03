"""Tests for the check_file_read hook and the shared glob matcher.

Run with: ``uv run --with pytest --no-project pytest test/agents/`` or
``python3 -m pytest test/agents/``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = ROOT / "home" / "dot_config" / "agents"
HOOK = ROOT / "home" / "dot_claude" / "hooks" / "executable_check_file_read.py"

sys.path.insert(0, str(AGENTS_DIR))
import command_policy as policy  # noqa: E402
from agents_common import agents_config_dir, load_common  # noqa: E402

COMMON_PATH = agents_config_dir() / "common.toml"
COMMON = load_common()


def run_hook(
    tool_name: str,
    path: str,
    *,
    config_dir: Path | None = None,
    hook: Path = HOOK,
) -> dict:
    """hook を実プロセスで起動し、出力 JSON を返す (無出力なら空 dict)。

    出力の有無に関わらず exit 0 かつ Traceback なしのときだけ受け付ける
    (クラッシュを許可とも、クラッシュ前に出した判定とも取り違えない)。
    """
    env = dict(os.environ)
    env["AGENTS_CONFIG_DIR"] = str(config_dir or COMMON_PATH.parent)
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": {"path": path},
        }
    )
    proc = subprocess.run(
        [sys.executable, "-B", str(hook)],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    assert proc.returncode == 0, f"hook が異常終了: {proc.stderr}"
    assert "Traceback" not in proc.stderr, f"hook が例外を出した: {proc.stderr}"
    out = proc.stdout.strip()
    if not out:
        return {}
    return json.loads(out)


def is_denied(result: dict) -> bool:
    return result.get("permissionDecision") == "deny"


_DENY_JSON = (
    '{"permissionDecision": "deny", "permissionDecisionReason": "fake",'
    ' "hookSpecificOutput": {"hookEventName": "PreToolUse",'
    ' "permissionDecision": "deny", "permissionDecisionReason": "fake"}}'
)


@pytest.mark.parametrize(
    "body",
    [
        "import sys\nsys.exit(1)\n",
        "import sys\nsys.stderr.write('Traceback (most recent call last):\\n')\n",
        f"import sys\nsys.stdout.write({_DENY_JSON!r})\nsys.exit(1)\n",
        (
            f"import sys\nsys.stdout.write({_DENY_JSON!r})\n"
            "sys.stderr.write('Traceback (most recent call last):\\n')\n"
        ),
    ],
    ids=[
        "無出力で exit 1",
        "無出力で Traceback",
        "deny を出して exit 1",
        "deny を出して Traceback",
    ],
)
def test_run_hook_rejects_crash(tmp_path, body):
    """クラッシュした hook の結果を判定として取り違えないこと (ヘルパーの回帰)."""
    hook = tmp_path / "fake_hook.py"
    hook.write_text(body, encoding="utf-8")
    with pytest.raises(AssertionError):
        run_hook("view", "README.md", hook=hook)


# ---------------------------------------------------------------------------
# glob マッチャ (Claude の Read() permission と同じ記法)
# ---------------------------------------------------------------------------


def test_double_star_crosses_directories():
    assert policy.matches_any_glob("a/b/c/server.pem", ["**/*.pem"])


def test_single_star_does_not_cross_directories():
    assert policy.matches_any_glob("a/server.pem", ["*.pem"]) is None
    assert policy.matches_any_glob("server.pem", ["*.pem"])


def test_leading_dot_slash_is_normalized():
    assert policy.matches_any_glob("./certs/server.key", ["**/*.key"])


def test_backslash_paths_are_normalized():
    # Windows から渡るパスでも同じ判定になること
    assert policy.matches_any_glob(r"certs\server.key", ["**/*.key"])


def test_home_paths_match_tilde_globs():
    home = os.path.expanduser("~")
    assert policy.matches_any_glob(f"{home}/.copilot/settings.json", ["~/.copilot/settings.json"])


def test_returns_the_matching_glob():
    assert policy.matches_any_glob("secrets/db.yaml", ["**/x", "**/secrets/**"]) == (
        "**/secrets/**"
    )


def test_empty_path_never_matches():
    assert policy.matches_any_glob("", ["**/*"]) is None


# ---------------------------------------------------------------------------
# hook の判定
# ---------------------------------------------------------------------------

SECRET_PATHS = [
    "certs/server.key",
    "certs/server.pem",
    "secrets/db.yaml",
    ".env",
    "config/service-account-prod.json",
    "app/refresh.token",
]

LEGIT_PATHS = [
    "README.md",
    "src/tokenizer.py",
    "docs/monkey-patching.md",
    "home/AppData/Roaming/Keyhac/extension/fakeymacs/keyhac.bat",
    "scripts/agents/generate.py",
]


@pytest.mark.parametrize("path", SECRET_PATHS)
def test_secret_paths_are_denied(path):
    assert is_denied(run_hook("view", path)), f"deny されていない: {path}"


@pytest.mark.parametrize("path", LEGIT_PATHS)
def test_legit_paths_are_allowed(path):
    assert not is_denied(run_hook("view", path)), f"誤検知: {path}"


@pytest.mark.parametrize("tool", ["Read", "view"])
def test_both_cli_read_tool_names_are_handled(tool):
    # Claude は Read、Copilot は view。どちらの名前でも同じ判定になること
    assert is_denied(run_hook(tool, "certs/server.key"))


@pytest.mark.parametrize("tool", ["bash", "Bash", "edit", "create", "powershell"])
def test_non_read_tools_are_ignored(tool):
    # 読み取り以外は対象外 (bash は check_bash.py、書き込みは sandbox が担当)
    assert not is_denied(run_hook(tool, "certs/server.key"))


def test_missing_path_is_ignored():
    env = dict(os.environ)
    env["AGENTS_CONFIG_DIR"] = str(AGENTS_DIR)
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "view", "tool_input": {}})
    proc = subprocess.run(
        [sys.executable, "-B", str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    assert proc.returncode == 0
    assert "Traceback" not in proc.stderr
    assert proc.stdout.strip() == ""


def test_fails_closed_when_policy_is_unreadable(tmp_path):
    # 設定を読めないときに素通りさせない (check_bash.py と同じ方針)
    assert is_denied(run_hook("view", "README.md", config_dir=tmp_path))


def test_policy_dir_falls_back_to_xdg_config_home(tmp_path):
    """AGENTS_CONFIG_DIR が無ければ $XDG_CONFIG_HOME/agents を読むこと."""
    shutil.copytree(COMMON_PATH.parent, tmp_path / "agents")
    env = {k: v for k, v in os.environ.items() if k != "AGENTS_CONFIG_DIR"}
    env["XDG_CONFIG_HOME"] = str(tmp_path)
    for path, denied in (("certs/server.key", True), ("README.md", False)):
        proc = subprocess.run(
            [sys.executable, "-B", str(HOOK)],
            input=json.dumps(
                {"hook_event_name": "PreToolUse", "tool_name": "view", "tool_input": {"path": path}}
            ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        assert proc.returncode == 0, proc.stderr
        assert "Traceback" not in proc.stderr, proc.stderr
        assert bool(proc.stdout.strip()) is denied, (path, proc.stdout, proc.stderr)


# ---------------------------------------------------------------------------
# 設定との結び付き
# ---------------------------------------------------------------------------


def test_hook_is_registered_for_copilot_only():
    hooks = {h["id"]: h for h in COMMON["hooks"]}
    entry = hooks["check_file_read"]
    assert entry["copilot_event"] == "PreToolUse"
    # Claude は同じリストから Read() deny permission を生成済みなので hook 不要。
    # 付けると全ファイル読み取りにプロセス起動コストが乗るだけ。
    assert "claude_event" not in entry, (
        "Claude には permission があるので hook を付けない "
        "(docs/adr/0007-filesystem-guard-boundary.md)"
    )


def test_hook_matcher_covers_read_tools():
    hooks = {h["id"]: h for h in COMMON["hooks"]}
    import re

    matcher = re.compile(hooks["check_file_read"]["copilot_matcher"])
    assert matcher.match("view")
    assert matcher.match("Read")
    assert not matcher.match("bash")
    assert not matcher.match("edit")


def test_hooks_never_use_permission_request_event():
    """`permissionRequest` は使わないこと。

    公式仕様では `permissionRequest` だけが
    「Hook outputs are merged with later hook outputs overriding earlier ones」
    と定義されており、読み込み順は policy → user → **project** → plugins。
    つまりリポジトリ側の hook が user 側の決定を上書きできてしまう。

    一方 `preToolUse` は
    「if any hook returns "deny", the tool is blocked」なので、
    プロジェクト設定から打ち消せない。deny を確実に効かせるため
    こちらだけを使う。
    """
    for hook in COMMON["hooks"]:
        for key in ("claude_event", "copilot_event"):
            event = hook.get(key, "")
            assert event.lower() != "permissionrequest", (
                f"{hook['id']} が permissionRequest を使っている。"
                "プロジェクト側 hook に上書きされるため preToolUse を使うこと"
            )


def test_hook_reads_the_same_list_as_claude_permissions():
    # ルールが 2 箇所に分かれると片方だけ古くなる。同じキーを見ていること。
    assert policy.load_read_deny_globs(str(COMMON_PATH)) == (COMMON["file"]["read_deny_globs"])


# ---------------------------------------------------------------------------
# deny の例外 (.env.example など。対の deny にだけ効く)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", [".env.example", "app/.env.sample", "/home/u/app/.env.template", "a/b/.env.example"]
)
def test_dotenv_samples_are_readable(path):
    assert not is_denied(run_hook("view", path)), path


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "app/.env.production",
        "app/.env.example.bak",
        # 例外は `.env.*` の deny にだけ効く。ほかの deny に当たるものは deny のまま
        ".ssh/.env.example",
        "/home/u/.ssh/.env.example",
        "app/secrets/.env.example",
        "app/.env.secret.example",
    ],
)
def test_dotenv_secrets_and_other_denies_stay_denied(path):
    assert is_denied(run_hook("view", path)), path


def test_exception_only_lifts_its_paired_deny():
    globs = ["**/.env.*", "**/.ssh/**"]
    exceptions = [{"deny": "**/.env.*", "except": ["**/.env.example"]}]
    assert policy.matches_read_deny("a/.env.example", globs, exceptions) is None
    assert policy.matches_read_deny("a/.env.local", globs, exceptions) == "**/.env.*"
    assert policy.matches_read_deny("a/.ssh/.env.example", globs, exceptions) == "**/.ssh/**"
    assert policy.matches_read_deny("a/.env.example", globs) == "**/.env.*"


def test_hook_reads_the_exceptions_from_the_same_file():
    assert policy.load_read_deny_exceptions(str(COMMON_PATH)) == COMMON["file"]["deny_exceptions"]


def _copy_policy(tmp_path: Path, body: str) -> Path:
    """command_policy.py を置いた設定ディレクトリを作る (無いと「読み込めない」で拒否される)。"""
    shutil.copy(AGENTS_DIR / "command_policy.py", tmp_path / "command_policy.py")
    (tmp_path / "common.toml").write_text(
        '[file]\nread_deny_globs = ["**/.env.*"]\n' + body, encoding="utf-8"
    )
    return tmp_path


def test_exception_config_control_is_allowed(tmp_path):
    """対照: 正常な例外の定義なら `.env.example` は読め、`.env.local` は拒否される。"""
    config = _copy_policy(
        tmp_path,
        '[[file.deny_exceptions]]\ndeny = "**/.env.*"\nexcept = ["**/.env.example"]\n',
    )
    assert not is_denied(run_hook("view", "app/.env.example", config_dir=config))
    assert is_denied(run_hook("view", "app/.env.local", config_dir=config))


@pytest.mark.parametrize(
    "body",
    [
        "deny_exceptions = 1\n",
        'deny_exceptions = [{ deny = "**/.env.*" }]\n',
        'deny_exceptions = [{ deny = "**/.env.*", except = "x" }]\n',
    ],
    ids=["配列でない", "except が無い", "except が文字列"],
)
def test_malformed_exceptions_fail_closed(tmp_path, body):
    """例外の定義が壊れていたら、読み取りは (例外の対象でも) 拒否する。理由は解釈の失敗。"""
    config = _copy_policy(tmp_path, body)
    result = run_hook("view", "app/.env.example", config_dir=config)
    assert is_denied(result)
    assert "ポリシー定義を解釈できませんでした" in result["permissionDecisionReason"]


# ---------------------------------------------------------------------------
# Windows は大小文字を区別しない (deny も例外も)
# ---------------------------------------------------------------------------

_WIN_GLOBS = COMMON["file"]["read_deny_globs"]
_WIN_EXCEPTIONS = COMMON["file"]["deny_exceptions"]


@pytest.mark.parametrize(
    ("path", "denied"),
    [
        (r"C:\repo\.SSH\.env.example", True),
        (r"C:\repo\.ENV.PRODUCTION", True),
        (r"C:\repo\.env.example", False),
        (r"C:\repo\.ENV.EXAMPLE", False),
        (r"C:\repo\.Env.Sample", False),
        (r"C:\repo\.env.example.bak", True),
        (r"C:\repo\Secrets\.env.example", True),
    ],
)
def test_windows_matching_ignores_case(monkeypatch, path, denied):
    monkeypatch.setattr(policy, "_is_windows", lambda: True)
    got = policy.matches_read_deny(path, _WIN_GLOBS, _WIN_EXCEPTIONS)
    assert (got is not None) is denied, (path, got)


def test_posix_matching_stays_case_sensitive(monkeypatch):
    monkeypatch.setattr(policy, "_is_windows", lambda: False)
    assert policy.matches_read_deny("a/.SSH/x", _WIN_GLOBS, _WIN_EXCEPTIONS) is None
    assert policy.matches_read_deny("a/.ENV.local", _WIN_GLOBS, _WIN_EXCEPTIONS) is None
    assert policy.matches_read_deny("a/.env.local", _WIN_GLOBS, _WIN_EXCEPTIONS)


def test_windows_home_prefix_ignores_case(monkeypatch):
    monkeypatch.setattr(policy, "_is_windows", lambda: True)
    monkeypatch.setattr(os.path, "expanduser", lambda p: "C:\\Users\\Tester")
    assert policy.matches_any_glob(
        "c:/users/tester/.copilot/settings.json", ["~/.copilot/settings.json"]
    )

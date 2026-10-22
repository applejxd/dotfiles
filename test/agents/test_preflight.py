"""away-shift skill の事前判定 (preflight.py) を確認する。

無人実行では、承認プロンプトが出た時点で離席時間が無駄になる。実行前に同じ
判定器へ問い合わせて避ける仕組みなので、判定が hook 本体と一致することを
押さえる。

Run with: ``uv run --with pytest --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT_PATH = (
    ROOT / "home" / "dot_claude" / "skills" / "away-shift" / "scripts" / "executable_preflight.py"
)
HOOK_PATH = ROOT / "home" / "dot_claude" / "hooks" / "executable_check_bash.py"
DECIDE_PATH = ROOT / "home" / "dot_claude" / "hooks" / "executable_decide.py"

from agents_common import agents_config_dir  # noqa: E402


def load_preflight():
    spec = importlib.util.spec_from_file_location("preflight", PREFLIGHT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["preflight"] = module
    spec.loader.exec_module(module)
    return module


preflight = load_preflight()


@pytest.fixture(autouse=True)
def use_repository_hook(monkeypatch):
    """配布先ではなくリポジトリの hook を見るようにする."""
    monkeypatch.setattr(preflight, "HOOK_PATH", HOOK_PATH)
    monkeypatch.setattr(preflight, "DECIDE_PATH", DECIDE_PATH)
    monkeypatch.setenv("AGENTS_CONFIG_DIR", str(agents_config_dir()))


@pytest.mark.parametrize(
    "command",
    ["uv sync", "git status", "uv run pytest", "ls -la", "mise install"],
)
def test_safe_commands_are_allowed(command):
    verdict, _ = preflight.decide(command, str(ROOT))
    assert verdict == "allow", f"{command!r} -> {verdict}"
    assert preflight.main([command]) == preflight.EXIT_SAFE


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("git commit -m x", "ask"),
        ("mise use -g node@22", "ask"),
        ("uv tool install ruff", "ask"),
        ("git push", "deny"),
        ("uv self update", "deny"),
        ("docker run --privileged alpine sh", "deny"),
    ],
)
def test_blocked_commands_are_reported(command, expected):
    verdict, reason = preflight.decide(command, str(ROOT))
    assert verdict == expected, f"{command!r} -> {verdict}"
    assert reason, "理由が空だとレポートに書けない"
    assert preflight.main([command]) == preflight.EXIT_BLOCKED


def test_missing_hook_is_reported(monkeypatch, tmp_path):
    """判定器が無いときに「安全」と誤答しない (fail-closed)."""
    monkeypatch.setattr(preflight, "HOOK_PATH", tmp_path / "absent.py")
    assert preflight.main(["uv sync"]) == preflight.EXIT_UNAVAILABLE


def _fake_hook(monkeypatch, tmp_path, body):
    hook = tmp_path / "fake_hook.py"
    hook.write_text(body, encoding="utf-8")
    monkeypatch.setattr(preflight, "HOOK_PATH", hook)


@pytest.mark.parametrize(
    "body",
    [
        "import nope_missing_module\n",
        "import sys; sys.exit(1)\n",
        'import sys; print(\'{"permissionDecision": "allow"}\'); sys.exit(2)\n',
        "print('not json')\n",
        "print('{\"foo\": 1}')\n",
        "print('[1]')\n",
        'print(\'{"permissionDecision": "maybe"}\')\n',
    ],
    ids=[
        "import-error",
        "nonzero-exit",
        "nonzero-with-allow",
        "invalid-json",
        "missing-key",
        "not-object",
        "unknown-verdict",
    ],
)
def test_broken_hook_is_unavailable(monkeypatch, tmp_path, body):
    """hook の異常終了・不正出力を allow にしない (fail-closed)."""
    _fake_hook(monkeypatch, tmp_path, body)
    with pytest.raises(RuntimeError):
        preflight.decide("uv sync", str(ROOT))
    assert preflight.main(["uv sync"]) == preflight.EXIT_UNAVAILABLE


def test_hook_timeout_is_unavailable(monkeypatch, tmp_path):
    _fake_hook(monkeypatch, tmp_path, "import time; time.sleep(5)\n")
    real_run = preflight.subprocess.run

    def short_run(*args, **kwargs):
        kwargs["timeout"] = 0.5
        return real_run(*args, **kwargs)

    monkeypatch.setattr(preflight.subprocess, "run", short_run)
    assert preflight.main(["uv sync"]) == preflight.EXIT_UNAVAILABLE


def test_silent_clean_exit_is_allowed(monkeypatch, tmp_path):
    _fake_hook(monkeypatch, tmp_path, "pass\n")
    assert preflight.decide("uv sync", str(ROOT)) == ("allow", "")


def test_scratch_deletion_is_allowed():
    """away-shift が使う work/ 配下の削除は事前判定でも通る."""
    verdict, _ = preflight.decide("rm -rf .tmp/away-shift/r1/work", str(ROOT))
    assert verdict == "allow"


# ─── --judge pi ──────────────────────────────────────────────────────


def _pi(command, *extra, capsys):
    code = preflight.main([command, "--judge", "pi", *extra])
    return code, capsys.readouterr().out


def test_pi_allow(capsys):
    code, out = _pi("git log --oneline -3", capsys=capsys)
    assert (code, out.strip()) == (preflight.EXIT_SAFE, "ALLOW")


@pytest.mark.parametrize(
    "command",
    ["git commit -m x", "python3 script.py", "git status"],
    ids=["rule-ask", "default-ask-python", "default-ask-status"],
)
def test_pi_ask_including_default_is_blocked(command, capsys):
    """規則に当たらない ask (source: default) も実行しない."""
    code, out = _pi(command, capsys=capsys)
    assert code == preflight.EXIT_BLOCKED
    assert out.startswith("ASK")


def test_pi_deny(capsys):
    code, out = _pi("git push", capsys=capsys)
    assert code == preflight.EXIT_BLOCKED
    assert out.startswith("DENY")


def test_pi_role_changes_the_verdict(capsys):
    command = "git status --short"
    assert _pi(command, capsys=capsys)[0] == preflight.EXIT_BLOCKED
    code, out = _pi(command, "--role", "explorer", capsys=capsys)
    assert (code, out.strip()) == (preflight.EXIT_SAFE, "ALLOW")


def test_pi_bypass_turns_ask_into_allow(capsys):
    code, _ = _pi("git commit -m x", "--bypass", capsys=capsys)
    assert code == preflight.EXIT_SAFE
    code, _ = _pi("git push", "--bypass", capsys=capsys)
    assert code == preflight.EXIT_BLOCKED


def test_pi_missing_judge_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight, "DECIDE_PATH", tmp_path / "absent.py")
    assert preflight.main(["git log", "--judge", "pi"]) == preflight.EXIT_UNAVAILABLE


def test_pi_broken_judge_is_unavailable(monkeypatch, tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("print('not json')\n", encoding="utf-8")
    monkeypatch.setattr(preflight, "DECIDE_PATH", bad)
    assert preflight.main(["git log", "--judge", "pi"]) == preflight.EXIT_UNAVAILABLE


def test_default_judge_is_still_claude(monkeypatch, tmp_path):
    """--judge 無しは pi の判定器を見ない (後方互換)."""
    monkeypatch.setattr(preflight, "DECIDE_PATH", tmp_path / "absent.py")
    assert preflight.main(["uv sync"]) == preflight.EXIT_SAFE

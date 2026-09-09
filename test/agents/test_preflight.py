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
    ROOT
    / "home"
    / "dot_claude"
    / "skills"
    / "away-shift"
    / "scripts"
    / "executable_preflight.py"
)
HOOK_PATH = ROOT / "home" / "dot_claude" / "hooks" / "executable_check_bash.py"


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
    monkeypatch.setenv("AGENTS_CONFIG_DIR", str(ROOT / "home" / "dot_config" / "agents"))


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


def test_scratch_deletion_is_allowed():
    """away-shift が使う work/ 配下の削除は事前判定でも通る."""
    verdict, _ = preflight.decide(
        "rm -rf .tmp/away-shift/r1/work", str(ROOT)
    )
    assert verdict == "allow"

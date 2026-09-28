"""test_check_bash_*.py が共有する、check_bash.py を起動するヘルパーと定数。

conftest.py は環境隔離だけに使うので、ここへ置いて各テストファイルから import する。
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = ROOT / "home" / "dot_claude" / "hooks" / "executable_check_bash.py"

sys.path.insert(0, str(ROOT / "home" / "dot_config" / "agents"))
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import command_policy as policy  # noqa: E402
import generate as gen  # noqa: E402
from agents_common import agents_config_dir, load_common  # noqa: E402

__all__ = [
    "COMMON",
    "COMMON_PATH",
    "HOOK",
    "HOOK_PATH",
    "ROOT",
    "gen",
    "policy",
    "run_hook",
    "run_hook_raw",
]

COMMON_PATH = agents_config_dir() / "common.toml"
COMMON = load_common()


def load_hook_module():
    """Import the hook by path (its filename has the chezmoi executable_ prefix)."""
    spec = importlib.util.spec_from_file_location("check_bash_under_test", HOOK_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOOK = load_hook_module()


def run_hook_raw(
    command: str, *, cwd: str | None = None, hook: Path = HOOK_PATH
) -> subprocess.CompletedProcess[str]:
    """Run the hook as a subprocess and return the unchecked process result.

    AGENTS_CONFIG_DIR points the hook at the repository copy of the agents
    config so the result does not depend on what is currently deployed to
    ~/.config.
    """
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": cwd or str(ROOT),
    }
    env = {**os.environ, "AGENTS_CONFIG_DIR": str(COMMON_PATH.parent)}
    return subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env=env,
    )


def run_hook(
    command: str, *, cwd: str | None = None, hook: Path = HOOK_PATH
) -> tuple[str | None, str]:
    """Run the hook and return (decision, reason).

    decision is None when the hook stayed silent (the command is allowed).
    Any result is only accepted from a clean exit (exit 0, no Traceback):
    CLIs treat a crashed hook as "no decision", and Claude ignores stdout
    unless the exit code is 0, so a crash must fail the test even when it
    printed a well-formed decision first.
    """
    proc = run_hook_raw(command, cwd=cwd, hook=hook)
    assert proc.returncode == 0, (
        f"hook が異常終了した (rc={proc.returncode}): "
        f"stdout={proc.stdout[-300:]!r} stderr={proc.stderr[-500:]}"
    )
    assert "Traceback" not in proc.stderr, f"hook が例外を出した: {proc.stderr[-500:]}"
    out = proc.stdout.strip()
    if not out:
        return None, proc.stderr.strip()
    data = json.loads(out)
    # Copilot 形式と Claude 形式の両方に同じ決定が入っているはず
    assert data["permissionDecision"] == data["hookSpecificOutput"]["permissionDecision"]
    assert data["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    return data["permissionDecision"], data.get("permissionDecisionReason", "")

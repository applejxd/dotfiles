"""Windows ネイティブの pi への対応のうち、OS で分かれる判断 (``platform.ts``) の試験。

``test/agents/pi/platform_driver.mjs`` が platform を引数で差し替えて呼ぶ (Linux 上で win32 を模擬する。
Windows 実機の挙動は未検証)。node の型除去を使うので、22.18 未満の node では飛ばす。
see docs/spec/guard/pi-guard.md#windows
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _judge, _node, _req

RUNNER = ROOT / "test" / "agents" / "pi" / "platform_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

GIT_BASH = r"C:\Program Files\Git\bin\bash.exe"
WSL_BASH = r"C:\Windows\System32\bash.exe"


def _run(**req):
    proc = subprocess.run(
        [_node(), str(RUNNER), json.dumps(req)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-1500:]
    return json.loads(proc.stdout)


def _bash(platform, env, exists):
    return _run(op="findBash", platform=platform, env=env, exists=exists)


# ─── 子エージェント・隔離を使えるか ─────────────────────────────


@pytest.mark.parametrize(
    ("platform", "expected"), [("win32", False), ("linux", True), ("darwin", True)]
)
def test_child_tasks_are_only_for_non_windows(platform, expected):
    assert _run(op="supportsChildTasks", platform=platform) is expected


# ─── post_edit の bash ────────────────────────────────────────


def test_non_windows_uses_bash_from_path():
    assert _bash("linux", {}, []) == "bash"


def test_windows_prefers_git_for_windows_in_program_files():
    env = {"ProgramFiles": r"C:\Program Files"}
    assert _bash("win32", env, [GIT_BASH, WSL_BASH]) == GIT_BASH


def test_windows_env_names_are_case_insensitive():
    env = {"PROGRAMFILES": r"C:\Program Files"}
    assert _bash("win32", env, [GIT_BASH]) == GIT_BASH


def test_windows_per_user_install():
    local = r"C:\Users\x\AppData\Local"
    bash = local + r"\Programs\Git\bin\bash.exe"
    assert _bash("win32", {"LOCALAPPDATA": local}, [bash]) == bash


def test_windows_derives_bash_from_git_on_path():
    root = r"D:\tools\Git"
    env = {"PATH": r"C:\x;" + root + r"\cmd"}
    assert (
        _bash("win32", env, [root + r"\cmd\git.exe", root + r"\bin\bash.exe"])
        == root + r"\bin\bash.exe"
    )


def test_windows_derives_bash_from_mingw_git_on_path():
    root = r"D:\tools\Git"
    env = {"PATH": root + r"\mingw64\bin"}
    exists = [root + r"\mingw64\bin\git.exe", root + r"\bin\bash.exe"]
    assert _bash("win32", env, exists) == root + r"\bin\bash.exe"


def test_windows_never_picks_the_wsl_launcher():
    env = {"PATH": r"C:\Windows\System32"}
    assert _bash("win32", env, [WSL_BASH, r"C:\Windows\System32\git.exe"]) is None


def test_windows_without_git_bash_is_none():
    assert _bash("win32", {"ProgramFiles": r"C:\Program Files"}, []) is None


# ─── パスの ~ 展開 ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "home", "expected"),
    [
        ("~", "/home/u", "/home/u"),
        ("~/a/b", "/home/u", "/home/u/a/b"),
        ("~\\a", r"C:\Users\u", r"C:\Users\u\a"),
        ("~/a", r"C:\Users\u", r"C:\Users\u\a"),
        ("~x/a", "/home/u", "~x/a"),
    ],
)
def test_expand_tilde(path, home, expected):
    assert _run(op="expandTilde", path=path, home=home) == expected


def test_read_input_path_expands_backslash_tilde():
    got = _run(op="resolveInputPath", path="~\\notes.txt", cwd="/w", home="/home/u")
    # posix の node では `\` は区切りではないので、ホームの後ろへ付くだけ (win32 の経路は expandTilde の試験)
    assert got.startswith("/home/u")


# ─── Windows 版の task ツール (読み取り役だけの子) の判定 ─────────


def test_task_tool_is_allowed_for_the_implementer_and_denied_for_roles_without_it():
    out = _judge(
        [
            _req("task", {"agent": "review", "task": "x"}),
            _req("task", {"agent": "review", "task": "x"}, role="reader"),
        ]
    )
    assert out[0]["decision"] == "allow"
    assert out[1]["decision"] == "deny"

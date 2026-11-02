"""pi の TUI を疑似端末 (pty) で動かし、TUI だけの経路を確かめる。

統合の必須確認が時間切れで拒否されたとき、TUI で、子でなく、action ツールがある役割のときだけ、
「再試行せず git_integrate で保存できる」という案内を足す (integration-gate.ts の integrationTimeoutGuidance)。
RPC・print では TUI にならないので、実際の pi の試験 (test_pi_integrate_index.py) では「足さない」側しか見られない。
キルスイッチが両方 true のときだけ足し、片方でも false なら足さない (C1)。
see docs/change/0055-async-approval.md
"""

# ruff: noqa: F811
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import pty
import re
import select
import struct
import sys
import termios
import time

import pytest
from test_pi_harness import FIXTURES, PI, env  # noqa: F401
from test_pi_integrate_index import _switches

pytestmark = [
    pytest.mark.skipif(PI is None, reason="pi is not installed"),
    pytest.mark.skipif(sys.platform == "win32", reason="疑似端末 (pty) は Unix だけ"),
]

ANSI = re.compile(
    r"\x1b\[[0-9;?<>=]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Za-z0-9]|\x1b[=>]"
)
FINISH = [{"name": "guarded_bash", "args": {"command": "git flow feature finish x --squash"}}]
GUIDANCE = "統合したいときは"


def _flat(buf: bytes) -> str:
    return re.sub(r"\s+", " ", ANSI.sub("", buf.decode("utf-8", "replace")))


def _tui_run(env, calls, timeout_s: float = 90.0) -> str:
    """TUI の pi に依頼 "go" を 1 回送り、偽のモデルの最終の返答 (TOOLS=… と各ツールの結果) が出るまで待つ。画面の文字列を返す"""
    args = [
        PI,
        "--no-session",
        "--model",
        "faux/spike",
        "-nbt",
        "-ne",
        "-e",
        "builtin:mcp",
        "-e",
        str(env["harness"]),
    ]
    args += ["-e", str(FIXTURES / "faux.ts")]
    child_env = {
        **env["env"],
        "FAUX_TOOL_CALLS": json.dumps(calls),
        "TERM": "xterm-256color",
        "COLUMNS": "200",
        "LINES": "60",
        # 起動時の fd のダウンロードと更新確認を止める。起動の途中 (固定 4 秒を超えると) pi は送信を断る
        # (「Startup is still in progress」。入力は編集欄に残り、go が失われる)。偽のモデルだけの試験なので網に依存させない
        "PI_OFFLINE": "1",
    }
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(env["proj"])
        os.execvpe(PI, args, child_env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 200, 0, 0))
    buf = b""
    start = time.time()
    trusted_at = None
    sent = False
    try:
        while time.time() - start < timeout_s:
            if select.select([fd], [], [], 0.5)[0]:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                buf += data
            text = _flat(buf)
            # 起動時の「このフォルダを信頼するか」には、既定 (Trust) で答える
            if trusted_at is None and "Trust project folder?" in text:
                os.write(fd, b"\r")
                trusted_at = time.time()
            if trusted_at is not None and not sent and time.time() - trusted_at > 4:
                os.write(fd, b"go\r")
                sent = True
            if sent and "TOOLS=" in text and "isError=" in text.split("TOOLS=", 1)[1]:
                time.sleep(0.5)
                while select.select([fd], [], [], 0.3)[0]:
                    try:
                        buf += os.read(fd, 65536)
                    except OSError:
                        break
                break
    finally:
        with contextlib.suppress(OSError):
            os.kill(pid, 9)
        with contextlib.suppress(OSError):
            os.waitpid(pid, 0)
    return _flat(buf)


def _result_of_bash(text: str) -> str:
    """最終の返答 (TOOLS=… の後) のうち、guarded_bash の結果の文字列"""
    assert "TOOLS=" in text, text[-1500:]
    tail = text.split("TOOLS=", 1)[1]
    assert "guarded_bash: isError=" in tail, tail[:1500]
    return tail.split("guarded_bash: isError=", 1)[1]


def test_the_timeout_guidance_reaches_the_model_in_the_tui(env):
    _switches(env, pending=True, integrate=True, modes=["tui"], confirm_timeout=2)
    result = _result_of_bash(_tui_run(env, FINISH))
    assert "確認が時間内に無かったので拒否した" in result and "再試行せず" in result, result
    assert GUIDANCE in result and "git_integrate" in result and "/pending approve" in result, result


@pytest.mark.parametrize(("pending", "integrate"), [(False, False), (True, False), (False, True)])
def test_no_guidance_unless_both_switches_are_on(env, pending, integrate):
    _switches(env, pending=pending, integrate=integrate, modes=["tui"], confirm_timeout=2)
    result = _result_of_bash(_tui_run(env, FINISH))
    assert "確認が時間内に無かったので拒否した" in result and "再試行せず" in result, (
        result
    )  # 従来の文言は保つ
    assert GUIDANCE not in result and "git_integrate" not in result, result

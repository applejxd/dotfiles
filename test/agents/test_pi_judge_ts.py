"""TS 版の判定器 (``home/dot_config/pi/harness/judge/``) が、正解データと一致すること。

正解は Python 版の判定結果 (``golden/decide_golden.jsonl``)。
bash を含む全件の一致を必須にする (``node test/agents/pi/judge_golden.mjs --bash``)。

node の型除去 (strip-types) を使う。22.18 未満の node では実行できないので飛ばす。

see docs/spec/pi-decide.md#ts-版への移植
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest
from agents_common import ROOT

RUNNER = ROOT / "test" / "agents" / "pi" / "judge_golden.mjs"
POLICY_RUNNER = ROOT / "test" / "agents" / "pi" / "policy_golden.mjs"
CHECKS_RUNNER = ROOT / "test" / "agents" / "pi" / "checks_golden.mjs"


def _node() -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    out = subprocess.run(
        [node, "--version"], capture_output=True, text=True, encoding="utf-8", check=False
    ).stdout
    match = re.match(r"v(\d+)\.(\d+)", out.strip())
    if not match:
        return None
    major, minor = int(match.group(1)), int(match.group(2))
    return node if (major, minor) >= (22, 18) else None


@pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")
def test_ts_judge_matches_the_python_golden():
    proc = subprocess.run(
        [_node(), str(RUNNER), "--bash"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-1000:]
    # 区分が空でないこと (正解データの読み込みの失敗を見逃さない)
    assert "bash " in proc.stdout and "file " in proc.stdout and "invalid" in proc.stdout


@pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")
def test_ts_policy_parts_match_the_python_golden():
    """shlex・分割・正規化・置換と関数の抽出・find_match が、Python 版と全件一致する。"""
    proc = subprocess.run(
        [_node(), str(POLICY_RUNNER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-1000:]
    assert "normalize" in proc.stdout and "shlex" in proc.stdout


@pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")
def test_ts_bashrules_parts_match_the_python_golden():
    """heredoc の分離・cd 展開・コマンドの分割・書き込み先と、移植済みの検査関数が全件一致する。"""
    proc = subprocess.run(
        [_node(), str(CHECKS_RUNNER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-1000:]
    assert "heredoc" in proc.stdout and "commands" in proc.stdout


# ─── サンドボックスの内側 (boundary / allowed) の緩和 ─────────────────────


def _judge(requests):
    import json

    proc = subprocess.run(
        [_node(), str(ROOT / "test" / "agents" / "pi" / "judge_boundary.mjs")],
        input=json.dumps({"requests": requests}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def _req(tool, input_, **extra):
    return {"tool": tool, "input": input_, "cwd": "/work/proj", "role": "implementer", **extra}


@pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")
def test_ssh_to_the_allowed_target_is_judged_by_the_remote_command():
    h = "ssh sbx@sandbox-gpu"
    cmds = [
        h + " git log",
        h + " 'git push'",
        h + " 'git log && git push'",
        h + " 'cat ~/.ssh/id_rsa'",
        h + " 'ssh other@host ls'",
        h,
        "ssh other@host ls",
        "ssh -o ProxyCommand=x sbx@sandbox-gpu ls",
        h + " ls; git push",
        h + " ls > out",
        h + ' "echo $HOME"',
    ]
    out = _judge([_req("bash", {"command": c}) for c in cmds])
    assert out[0]["decision"] == "allow"
    assert [o["decision"] for o in out[1:]] == ["deny"] * 10
    assert "git push" in out[1]["reason"] and "ssh" in out[4]["reason"]


@pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")
def test_scp_to_the_allowed_target_is_judged_as_a_local_cp():
    t = "sbx@sandbox-gpu"
    cmds = [
        f"scp a.txt {t}:/tmp/",
        f"scp {t}:/tmp/r ./r",
        f"scp {t}:/tmp/r ~/.bashrc",
        f"scp .env {t}:/tmp/",
        f"scp -o ProxyCommand=x a {t}:/tmp/",
        "scp a other@host:/tmp/",
        f"scp {t}:/a {t}:/b",
        f"scp {t}:/a ./x; git push",
    ]
    out = _judge([_req("bash", {"command": c}) for c in cmds])
    assert [o["decision"] for o in out[:2]] == ["ask", "ask"]  # cp の既定 (sandbox 内なら allow)
    assert [o["decision"] for o in out[2:]] == ["deny"] * 6
    assert "scp" not in out[2]["reason"] and "cp" in out[3]["reason"]


@pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")
def test_boundary_only_drops_the_default_ask_of_plain_shell_commands():
    out = _judge(
        [
            _req("bash", {"command": "touch made-by-pi"}),
            _req("bash", {"command": "touch made-by-pi"}, boundary=True),
            # 規則に当たる ask・deny・誘導は、サンドボックスの中でも変わらない
            _req("bash", {"command": "git commit -m x"}, boundary=True),
            _req("bash", {"command": "git push"}, boundary=True),
            _req("bash", {"command": "rm -rf ."}, boundary=True),
            _req("bash", {"command": "cat README.md"}, boundary=True),
        ]
    )
    assert (out[0]["decision"], out[0]["source"]) == ("ask", "default")
    assert out[1]["decision"] == "allow" and out[1]["sandboxed"] is True
    assert out[2]["decision"] == "ask"
    assert out[3]["decision"] == "deny" and out[4]["decision"] == "deny"
    assert out[5]["decision"] == "deny" and out[5].get("guide")


@pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")
def test_boundary_file_access_outside_the_worktree_follows_what_the_os_opened():
    allowed = {"read": ["/opt/ok"], "write": ["/opt/w"]}
    out = _judge(
        [
            _req("read", {"path": "/opt/ok/f"}, boundary=True, allowed=allowed),
            _req("read", {"path": "/opt/w/f"}, boundary=True, allowed=allowed),
            _req("read", {"path": "/opt/other/f"}, boundary=True, allowed=allowed),
            _req("write", {"path": "/opt/w/f", "content": "x"}, boundary=True, allowed=allowed),
            _req("write", {"path": "/opt/ok/f", "content": "x"}, boundary=True, allowed=allowed),
            # 許可の一覧が無い・サンドボックスと証明されていないときは、基準 (確認) のまま
            _req("read", {"path": "/opt/other/f"}, boundary=True),
            _req("read", {"path": "/opt/ok/f"}, boundary=False, allowed=allowed),
            _req("write", {"path": "/opt/w/f", "content": "x"}, allowed=allowed),
        ]
    )
    assert [r["decision"] for r in out] == [
        "allow",
        "allow",
        "deny",
        "allow",
        "deny",
        "ask",
        "ask",
        "ask",
    ]
    assert "サンドボックスの外" in out[2]["reason"] and "サンドボックスの外" in out[4]["reason"]


@pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")
def test_boundary_never_relaxes_the_common_denies_or_a_broken_request():
    import os

    ssh = os.path.expanduser("~/.ssh/id_rsa")
    allowed = {"read": [os.path.expanduser("~")], "write": [os.path.expanduser("~")]}
    out = _judge(
        [
            _req("read", {"path": ssh}, boundary=True, allowed=allowed),
            _req("bash", {"command": "cat ~/.ssh/id_rsa"}, boundary=True, allowed=allowed),
            _req("read", {"path": "/opt/ok/f"}, boundary=True, allowed={"read": "x", "write": []}),
            _req("bash", {"command": "ls"}, boundary="yes"),
        ]
    )
    assert out[0]["decision"] == "deny" and out[1]["decision"] == "deny"
    assert out[2]["decision"] == "deny" and out[2]["source"] == "error"
    assert out[3]["decision"] == "deny" and out[3]["source"] == "error"

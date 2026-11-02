"""`/board` コマンドの配線 (index.ts)。pi を RPC で動かし、拡張のスラッシュコマンドとして走り、盤面を通知することを確かめる。

盤面の中身そのもの (要対応・状態の表示) は test_pi_board.py、実物の収集は test_pi_board_collect.py が確かめる。
"""

# ruff: noqa: F811
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from test_pi_harness import FIXTURES, PI, env  # noqa: F401

GIT_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _git(cwd: Path, *args: str) -> None:
    r = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=GIT_ENV,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert r.returncode == 0, f"git {args}: {r.stderr}"


def _board_text(env, timeout: float = 30.0) -> str:
    """RPC で `/board` を送り、「盤面」を含む通知の本文を返す (無ければ空)"""
    args = [PI, "--no-session", "--model", "faux/spike", "-nbt", "-ne", "-e", "builtin:mcp"]
    args += ["-e", str(env["harness"]), "-e", str(FIXTURES / "faux.ts"), "--mode", "rpc"]
    proc = subprocess.Popen(
        args,
        cwd=env["proj"],
        env={**env["env"], "FAUX_TOOL_CALLS": "[]"},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    text = ""
    lines: queue.Queue[str | None] = queue.Queue()

    def pump() -> None:
        for raw in proc.stdout:  # type: ignore[union-attr]
            lines.put(raw)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    try:
        proc.stdin.write(json.dumps({"type": "prompt", "message": "/board"}) + "\n")
        proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                line = lines.get(timeout=max(0.1, deadline - time.time()))
            except queue.Empty:
                break
            if line is None:
                break
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if (
                event.get("type") == "extension_ui_request"
                and event.get("method") == "notify"
                and "盤面" in str(event.get("message", ""))
            ):
                text = str(event["message"])
                break
    finally:
        proc.kill()
        proc.wait()
    return text


def test_board_command_notifies_the_board_with_real_feature_state(env):
    proj = Path(env["proj"])
    _git(proj, "init", "-q", "-b", "develop")
    (proj / "base.txt").write_text("base\n", encoding="utf-8")
    _git(proj, "add", "base.txt")
    _git(proj, "commit", "-q", "-m", "base")
    wt = proj.parent / "wt-a"
    _git(proj, "worktree", "add", "-q", "-b", "feature/a", str(wt))
    (wt / "a1.txt").write_text("a1\n", encoding="utf-8")
    _git(wt, "add", "a1.txt")
    _git(wt, "commit", "-q", "-m", "a1")

    text = _board_text(env)
    assert text, "盤面の通知が来なかった (/board が登録されていない)"
    lines = text.splitlines()
    assert lines[0].startswith("盤面")
    assert any("要対応" in ln for ln in lines)  # 最上段の節
    assert any("feature a" in ln and "↑1" in ln for ln in lines), (
        text
    )  # 実物の状態 (develop より 1 commit 先)
    assert all(len(ln) <= 60 for ln in lines), (
        text
    )  # スマホの幅で読める (全角を 2 桁で数えて 44 桁)


def test_board_command_uses_the_project_source_prefixes(env):
    """index.ts が盤面の収集へ設定の既定を渡す: プロジェクトの統合元の接頭辞 (task/) で feature が拾われる"""
    proj = Path(env["proj"])
    _git(proj, "init", "-q", "-b", "develop")
    cfg = proj / ".agents" / "config" / "pi.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"integrate": {"source_prefixes": ["task/"]}}), encoding="utf-8")
    _git(proj, "add", ".agents/config/pi.json")
    _git(proj, "commit", "-q", "-m", "base")
    for branch, name in (("task/a", "wt-a"), ("feature/z", "wt-z")):
        wt = proj.parent / name
        _git(proj, "worktree", "add", "-q", "-b", branch, str(wt))
        (wt / f"{name}.txt").write_text("x\n", encoding="utf-8")
        _git(wt, "add", f"{name}.txt")
        _git(wt, "commit", "-q", "-m", name)

    text = _board_text(env)
    assert text, "盤面の通知が来なかった (/board が登録されていない)"
    lines = text.splitlines()
    assert any("feature a" in ln and "↑1" in ln for ln in lines), (
        text
    )  # task/a が統合元として拾われる
    assert not any("feature z" in ln for ln in lines), (
        text
    )  # feature/z は拾われない (接頭辞を置き換えた)
    assert any("pi.json: 有効" in ln for ln in lines), text

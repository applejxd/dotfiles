#!/usr/bin/env python3
"""偽の pis（試験専用）。ジョブの実行器（job-runner.ts）の試験で、本物の LLM・pis の代わりに起動される。

使い方: fake_pis.py <sidecar.json> [pis の引数...]
  - モードは sidecar の JSON（{"mode": "edit", ...}）で渡す。環境変数は使わない（許可リストの検査を邪魔しないため）。
  - 起動した事実は <sidecar>.record.json に書く（引数・cwd・環境・pid・pgid・子孫の pid・受けた signal）。
モード: edit・noop・fail・slow（SIGTERM を無視）・hang（SIGTERM で終わる）・flood・outside・tamper・risk・binary・symlink
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

SIDECAR = Path(sys.argv[1])
CFG = json.loads(SIDECAR.read_text(encoding="utf-8"))
RECORD = SIDECAR.with_name(SIDECAR.name + ".record.json")
REC: dict = {
    "argv": sys.argv[2:],
    "cwd": os.getcwd(),
    "env": dict(os.environ),
    "pid": os.getpid(),
    "pgid": os.getpgid(0),
    "ppid": os.getppid(),
    "stdin_is_null": os.fstat(0).st_rdev == os.stat("/dev/null").st_rdev,
    "signals": [],
    "children": [],
}


def save() -> None:
    tmp = RECORD.with_name(RECORD.name + ".tmp")
    tmp.write_text(json.dumps(REC), encoding="utf-8")
    os.replace(tmp, RECORD)


def write(rel: str, body: str | bytes) -> None:
    p = Path(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(body, bytes):
        p.write_bytes(body)
    else:
        p.write_text(body, encoding="utf-8", newline="\n")


def git(*args: str) -> None:
    subprocess.run(["git", *args], check=False, capture_output=True)


def edit() -> None:
    write("src/a.txt", "a edited by pis\n")
    write("docs/new.txt", "new file\n")


def sleep_forever() -> None:
    while True:
        time.sleep(0.05)


def spawn_children() -> None:
    """同じグループの子と、setsid で抜けた子（どちらも環境を継承する）を作る。"""
    same = subprocess.Popen(["sleep", "300"])
    escaped = subprocess.Popen(["sleep", "300"], start_new_session=True)
    REC["children"] = [same.pid, escaped.pid]


save()
mode = CFG["mode"]

if mode == "edit":
    edit()
elif mode == "noop":
    pass
elif mode == "fail":
    edit()
    print("fake pis: failing", file=sys.stderr)
    sys.exit(3)
elif mode == "slow":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)  # SIGKILL でしか止まらない
    if CFG.get("children"):
        spawn_children()
    save()
    print("slow started", flush=True)
    sleep_forever()
elif mode == "hang":

    def on_term(signum, _frame):
        REC["signals"].append(signum)
        save()
        sys.exit(0)

    signal.signal(signal.SIGTERM, on_term)
    save()
    print("hang started", flush=True)
    sleep_forever()
elif mode == "flood":
    chunk = b"x" * (1024 * 1024)
    try:
        for _ in range(200):
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            time.sleep(0.002)
    except BrokenPipeError:
        pass
    sleep_forever()
elif mode == "outside":
    edit()
    Path(CFG["target"]).write_text("escaped\n", encoding="utf-8")
elif mode == "tamper":
    what = CFG["what"]
    if what == "pointer":
        Path(".git").write_text("gitdir: /nonexistent/elsewhere\n", encoding="utf-8")
    elif what == "ref":
        git(f"--git-dir={CFG['common']}", "update-ref", "refs/heads/develop", CFG["oid"])
    elif what == "head":
        git(f"--git-dir={CFG['admin']}", "symbolic-ref", "HEAD", "refs/heads/develop")
    edit()
elif mode == "risk":
    write("docs/secret/risk.md", "risky\n")
elif mode == "binary":
    write("img.dat", b"\x00\x01\x02binary\x00")
elif mode == "symlink":
    os.symlink("/etc/passwd", "link")
elif mode == "leftover":
    # 正常終了するが、setsid で抜けた子孫を残す（終了後の掃除の確認）
    spawn_children()
    save()
    edit()
else:
    sys.exit(99)
save()

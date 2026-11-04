#!/usr/bin/env python3
"""worktree の所有を `git worktree lock` の理由欄で表明・確認・解除する。

    python3 scripts/wt_owner.py claim <worktree> --kind <k> --id <id> [--pid N]
    python3 scripts/wt_owner.py release <worktree> [--id <id>]
    python3 scripts/wt_owner.py status [<worktree>]
    python3 scripts/wt_owner.py reap

理由欄は 1 行 `owner=<kind> id=<id> pid=<pid> started=<unix 秒>`。kind は worker・job・create・train・interactive。
pid が生きている間だけ「有効」、死んでいれば「残骸」（claim は拒否して終了コード 3。reap だけが解除する）。
`owner=` で始まらない lock（人が付けたもの）は「不明の lock」として、自動では解除しない。
<worktree> は絶対パス、または名前（`.tmp/worktrees/<name>`）。リポジトリ内（どの worktree でもよい）から実行する。
仕様: docs/spec/orchestration.md#worktree-の所有の表明。TS 版（PR ビューア）は apps/pr-viewer/worktree-owner.ts で、規則は同じ。
終了コード: 0 = 成功、2 = 使い方か git の失敗、3 = 他の有効な owner・不明の lock・id の不一致で拒否。
Windows は実機で未検証（pid の生死は os.kill(pid, 0) で見る）。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

KINDS = ("worker", "job", "create", "train", "interactive")
REASON_RE = re.compile(r"^owner=(\S+) id=(\S+) pid=(\d+) started=(\d+)$")
EXIT_BUSY = 3


class OwnerError(Exception):
    """使い方か git の失敗（終了コード 2）。"""


@dataclass
class Owner:
    kind: str
    id: str
    pid: int
    started: int

    def reason(self) -> str:
        return f"owner={self.kind} id={self.id} pid={self.pid} started={self.started}"

    @property
    def alive(self) -> bool:
        return pid_alive(self.pid)


@dataclass
class State:
    """none = lock 無し / unknown = 人が付けた lock / owner = このツールの lock。"""

    kind: str
    owner: Owner | None = None
    reason: str = ""


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def parse_owner(reason: str) -> Owner | None:
    m = REASON_RE.match(reason)
    if not m or m.group(1) not in KINDS:
        return None
    return Owner(m.group(1), m.group(2), int(m.group(3)), int(m.group(4)))


def git(*args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", env=env, check=False
    )


def repo_root() -> Path:
    r = git("rev-parse", "--path-format=absolute", "--git-common-dir")
    if r.returncode != 0:
        raise OwnerError("git リポジトリの中で実行してください")
    return Path(r.stdout.strip()).parent


def resolve(arg: str) -> Path:
    """絶対パス、または名前（.tmp/worktrees/<name>）を、実在する worktree の実パスにする。"""
    p = Path(arg)
    if not p.is_absolute():
        p = repo_root() / ".tmp" / "worktrees" / arg
    if not p.exists():
        raise OwnerError(f"worktree が見つかりません: {arg}")
    return p.resolve()


def locks() -> dict[Path, str]:
    """worktree の実パス → lock の理由（理由なしの lock は空文字）。lock の無いものは含めない。"""
    r = git("worktree", "list", "--porcelain", "-z")
    if r.returncode != 0:
        raise OwnerError("git worktree list に失敗しました")
    res: dict[Path, str] = {}
    cur: Path | None = None
    for line in r.stdout.split("\0"):
        if line == "":
            cur = None
        elif line.startswith("worktree "):
            cur = Path(line[len("worktree ") :]).resolve()
        elif cur is not None and (line == "locked" or line.startswith("locked ")):
            res[cur] = line[len("locked") :].strip()
    return res


def state_of(wt: Path) -> State:
    reason = locks().get(wt)
    if reason is None:
        return State("none")
    owner = parse_owner(reason)
    return State("owner", owner) if owner else State("unknown", reason=reason)


def describe(wt: Path, st: State, now: float | None = None) -> str:
    if st.kind == "none":
        return f"{wt}: lock なし"
    if st.kind == "unknown":
        return f"{wt}: 不明の lock（人が付けたもの）: {st.reason}"
    o = st.owner
    assert o is not None
    age = int((now if now is not None else time.time()) - o.started)
    life = "生存" if o.alive else "残骸（pid が死んでいる）"
    return f"{wt}: kind={o.kind} id={o.id} pid={o.pid} {life} 経過={age}秒"


def default_owner_pid() -> int:
    """--pid が無いときの所有者。親をたどり、最初の「シェルでない」祖先（= 呼び出した AI の pi など）にする。

    呼び出し元のシェルはコマンドの後すぐ終わるので、その pid では lock がすぐ残骸になる。/proc が無ければ親の pid。
    """
    shells = {"bash", "sh", "dash", "zsh", "fish", "env"}
    pid = os.getppid()
    for _ in range(16):
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        except OSError:
            return pid
        comm = stat[stat.index("(") + 1 : stat.rindex(")")]
        ppid = int(stat[stat.rindex(")") + 2 :].split()[1])
        if comm not in shells or ppid <= 1:
            return pid
        pid = ppid
    return pid


def cmd_claim(a: argparse.Namespace) -> int:
    if not re.fullmatch(r"\S+", a.id):
        raise OwnerError("--id は空白を含まない 1 語にしてください")
    wt = resolve(a.worktree)
    owner = Owner(
        a.kind, a.id, a.pid if a.pid is not None else default_owner_pid(), int(time.time())
    )
    for _ in range(2):
        st = state_of(wt)
        if st.kind == "unknown":
            print(describe(wt, st), file=sys.stderr)
            return EXIT_BUSY
        if st.kind == "owner":
            assert st.owner is not None
            if st.owner.id == a.id:
                print(f"{wt}: すでに claim 済み（id={a.id}）")
                return 0
            if st.owner.alive:
                print(describe(wt, st), file=sys.stderr)
                return EXIT_BUSY
            # 残骸は自動で奪わない（unlock→lock は原子的でなく、古い観測で他方の新しい lock を外しうる）
            print(describe(wt, st), file=sys.stderr)
            print(
                "残骸の lock があります。`wt_owner.py reap` で解除してから claim してください",
                file=sys.stderr,
            )
            return EXIT_BUSY
        r = git("worktree", "lock", "--reason", owner.reason(), str(wt))
        if r.returncode == 0:
            print(f"{wt}: claim しました（{owner.reason()}）")
            return 0
    print(describe(wt, state_of(wt)), file=sys.stderr)
    return EXIT_BUSY


def cmd_release(a: argparse.Namespace) -> int:
    wt = resolve(a.worktree)
    st = state_of(wt)
    if st.kind == "none":
        print(f"{wt}: lock はありません")
        return 0
    if st.kind == "unknown":
        print(describe(wt, st), file=sys.stderr)
        return EXIT_BUSY
    assert st.owner is not None
    if a.id is not None and st.owner.id != a.id:
        print(f"id が違うので解除しません: {describe(wt, st)}", file=sys.stderr)
        return EXIT_BUSY
    r = git("worktree", "unlock", str(wt))
    if r.returncode != 0:
        raise OwnerError("git worktree unlock に失敗しました")
    print(f"{wt}: 解除しました")
    return 0


def cmd_status(a: argparse.Namespace) -> int:
    if a.worktree:
        wt = resolve(a.worktree)
        print(describe(wt, state_of(wt)))
        return 0
    table = locks()
    if not table:
        print("lock された worktree はありません")
    for wt, reason in sorted(table.items()):
        owner = parse_owner(reason)
        print(describe(wt, State("owner", owner) if owner else State("unknown", reason=reason)))
    return 0


def cmd_reap(_a: argparse.Namespace) -> int:
    n = 0
    for wt, reason in sorted(locks().items()):
        owner = parse_owner(reason)
        if owner is None or owner.alive:
            continue
        # 再読して、観測した理由欄と一致する場合だけ解除する（別の主体が新しく claim していたら外さない）
        if locks().get(wt) != reason:
            continue
        if git("worktree", "unlock", str(wt)).returncode == 0:
            print(f"{wt}: 残骸を解除しました（{reason}）")
            n += 1
    print(f"解除した残骸: {n} 件")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="worktree の所有の表明（git worktree lock）")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("claim", help="所有を表明する")
    c.add_argument("worktree")
    c.add_argument("--kind", required=True, choices=KINDS)
    c.add_argument("--id", required=True)
    c.add_argument("--pid", type=int, help="所有者の pid（既定は、シェルでない最初の祖先）")
    c.set_defaults(fn=cmd_claim)
    r = sub.add_parser("release", help="解除する")
    r.add_argument("worktree")
    r.add_argument("--id")
    r.set_defaults(fn=cmd_release)
    s = sub.add_parser("status", help="状態の一覧")
    s.add_argument("worktree", nargs="?")
    s.set_defaults(fn=cmd_status)
    reap = sub.add_parser("reap", help="残骸の lock をすべて解除する")
    reap.set_defaults(fn=cmd_reap)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a)
    except OwnerError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

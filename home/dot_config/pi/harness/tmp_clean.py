#!/usr/bin/env python3
"""作業ツリーの `.tmp/` を掃除する (既定は dry-run)。

**自動で消してよいのは、自分で作ったと確かめられるものだけ**:
  1. `s/<名前>/` (pi のセッションの置き場) のうち、持ち主 (`.owner`) の死亡を確証できたもの
  2. 再生成できる名前 (テスト・導入の一時。DISPOSABLE) のうち、1 日より古いもの
それ以外の直下の項目 (未知の名前) は、**一覧を出すだけで消さない**。年齢で消すのは `--all` のときだけ。
`keep/` と運用の置き場 (research・review-loop など) は、どの場合も消さない。

使い方:
  python3 tmp_clean.py                 # 一覧だけ (何も消さない)
  python3 tmp_clean.py --apply         # 1 と 2 を消す
  python3 tmp_clean.py --all --apply   # 未知の名前も、7 日より古ければ消す (手動の確認用)
  python3 tmp_clean.py --dir /path/.tmp

`.owner` は JSON: {"pid": 123, "start": "<起動時刻 (/proc の starttime)>", "pidns": "pid:[...]", "host": "<ホスト名>"}。
持ち主の死亡を確証するのは、同じホスト・同じ PID namespace で、pid が無い、または起動時刻が違う (pid の再利用) とき。
確証できなければ (別 namespace・`.owner` が無い・壊れている・/proc が無い) 残す。年齢だけでは `s/` を消さない。

see docs/change/0042-tmp-lifecycle.md
"""

from __future__ import annotations

import argparse
import contextlib
import fnmatch
import json
import os
import shutil
import socket
import stat
import sys
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None  # type: ignore[assignment]

# 運用が自前で世代管理・使っている場所と、取り込み待ち、利用者のファイルかもしれないもの。消さない
PROTECTED = (
    "keep",
    "research",
    "review-loop",
    "away-shift",
    "subagents",
    "worktrees",
    "checkpoint-*",
    ".sweep.lock",
    ".clean-stamp",
    ".keep",
    "*.png",
    "*.jpg",
)
SESSIONS = "s"

# テストや導入の残りで、再生成できるもの。短い期間 (日) で消す
DISPOSABLE = (
    "pytest-of-*",
    "agents-config-*",
    "tmp.*",
    "tmp[a-z0-9_]*",
    "tools-ext-*",
    "claude-empty-*",
    "gkinstall*",
    "ruby-build*",
    "jiti",
    "node-compile-cache",
    "pi-commit-*",
    "__pycache__",
)


def matches(name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


# ─── 持ち主の死亡の確証 ───


def proc_start(pid: int) -> str | None:
    """`/proc/<pid>/stat` の起動時刻 (22 番目の項目)。無ければ None。"""
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # コマンド名 (括弧の中。空白や括弧を含みうる) の後ろから数える
    rest = text.rsplit(")", 1)[-1].split()
    return rest[19] if len(rest) > 19 else None


def current_pidns() -> str | None:
    try:
        return os.readlink("/proc/self/ns/pid")
    except OSError:
        return None


def make_owner(pid: int | None = None) -> dict[str, str | int]:
    """自分 (または pid) の `.owner` の内容。"""
    pid = os.getpid() if pid is None else pid
    return {
        "pid": pid,
        "start": proc_start(pid) or "",
        "pidns": current_pidns() or "",
        "host": socket.gethostname(),
    }


def owner_state(owner_file: Path) -> str:
    """`dead` (死亡を確証) / `alive` / `unknown` (確証できない = 残す)。"""
    try:
        data = json.loads(owner_file.read_text(encoding="utf-8"))
        pid = int(data["pid"])
        start = str(data["start"])
        pidns = str(data["pidns"])
        host = str(data["host"])
    except (OSError, ValueError, KeyError, TypeError):
        return "unknown"  # 無い・壊れている・書きかけ
    if not start or not pidns or host != socket.gethostname():
        return "unknown"
    mine = current_pidns()
    if mine is None or mine != pidns:
        return "unknown"  # 別の PID namespace (コンテナなど) の pid は、ここからは判定できない
    now_start = proc_start(pid)
    if now_start is None:
        return "dead" if not Path(f"/proc/{pid}").exists() else "unknown"  # 権限エラーなどは残す
    return "alive" if now_start == start else "dead"  # 起動時刻が違えば、pid が再利用されている


# ─── 削除 ───


def tree_size(path: Path) -> int:
    try:
        st = os.lstat(path)
    except OSError:
        return 0
    if not stat.S_ISDIR(st.st_mode):
        return st.st_size
    total = 0
    for dirpath, _, filenames in os.walk(path, followlinks=False):
        for n in filenames:
            with contextlib.suppress(OSError):
                total += os.lstat(os.path.join(dirpath, n)).st_size
    return total


def newest_mtime(path: Path, cutoff: float, limit: int = 50000) -> float:
    """最も新しい mtime。cutoff より新しいものが見つかれば、早く返す。"""
    st = os.lstat(path)
    newest = st.st_mtime
    if not stat.S_ISDIR(st.st_mode):
        return newest
    seen = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        for n in dirnames + filenames:
            try:
                s = os.lstat(os.path.join(dirpath, n))
            except OSError:
                continue
            newest = max(newest, s.st_mtime)
            seen += 1
            if newest > cutoff or seen > limit:
                return max(newest, cutoff + 1) if seen > limit else newest
    return newest


def remove(path: Path, root_dev: int) -> str:
    """path を消す。`ok` / `other-device` (別のデバイスの中身へは降りない) / `failed`。シンボリックリンクはリンクだけ消す。"""
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        os.unlink(path)
        return "ok"
    if st.st_dev != root_dev:
        return "other-device"
    target = os.path.realpath(path)

    def inside(p: str) -> bool:
        real = os.path.realpath(p)
        return real == target or real.startswith(target + os.sep)

    def onexc(func, p, exc):  # 読み取り専用のものを直して、もう一度。対象の外には手を出さない
        try:
            parent = os.path.dirname(p)
            if inside(parent) or parent == os.path.dirname(target):
                if inside(parent):
                    os.chmod(parent, stat.S_IRWXU)
                if inside(p) and not os.path.islink(p):
                    os.chmod(p, stat.S_IRWXU)
                func(p)
        except OSError:
            pass

    shutil.rmtree(path, onexc=onexc)  # Linux では、fd を使ってリンクをたどらない版
    return "failed" if path.exists() else "ok"


# ─── 本体 ───


def plan(
    root: Path,
    *,
    include_unknown: bool,
    max_age: float,
    short_age: float,
    now: float,
    sessions_only: bool = False,
):
    """(消す, 一覧だけ, 保護) を返す。消す = (名前, 種類, 年齢日, パス)。"""
    delete: list[tuple[str, str, float, Path]] = []
    listed: list[tuple[str, float, Path]] = []
    protected: list[str] = []
    for entry in [] if sessions_only else sorted(root.iterdir()):
        name = entry.name
        if name == SESSIONS:
            continue
        if matches(name, PROTECTED):
            protected.append(name)
            continue
        short = matches(name, DISPOSABLE)
        days = short_age if short else max_age
        cutoff = now - days * 86400
        try:
            newest = newest_mtime(entry, cutoff)
        except OSError:
            continue
        if newest > cutoff:
            continue  # 最近のもの
        age = (now - newest) / 86400
        if short or include_unknown:
            delete.append((name, "再生成できる" if short else "未知 (--all)", age, entry))
        else:
            listed.append((name, age, entry))

    sdir = root / SESSIONS
    if sdir.is_dir() and not sdir.is_symlink():
        for entry in sorted(sdir.iterdir()):
            if entry.is_symlink() or not entry.is_dir():
                continue
            if owner_state(entry / ".owner") == "dead":
                age = (now - os.lstat(entry).st_mtime) / 86400
                delete.append((f"{SESSIONS}/{entry.name}", "持ち主が死んだ置き場", age, entry))
    return delete, listed, protected


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=".tmp", help="掃除する場所 (既定: ./.tmp)")
    ap.add_argument("--apply", action="store_true", help="実際に消す (既定は一覧だけ)")
    ap.add_argument(
        "--all", action="store_true", help="未知の名前も、--max-age より古ければ消す (手動の確認用)"
    )
    ap.add_argument("--max-age", type=float, default=7.0, help="--all のときの期間 (日。既定 7)")
    ap.add_argument(
        "--short-age", type=float, default=1.0, help="再生成できるものの期間 (日。既定 1)"
    )
    ap.add_argument(
        "--sessions-only",
        action="store_true",
        help="s/ (セッションの置き場) の回収だけをする (起動時の軽い掃除)",
    )
    args = ap.parse_args(argv)

    root = Path(args.dir)
    if root.is_symlink() or not root.is_dir():
        print(f"拒否: {root} はディレクトリではない、またはシンボリックリンク", file=sys.stderr)
        return 2
    root_dev = os.lstat(root).st_dev

    lock = None
    if fcntl is not None and args.apply:
        try:
            lock = open(root / ".sweep.lock", "a")  # noqa: SIM115 (掃除の間、保持する)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("別の掃除が実行中のため、何もしない")
            return 0

    now = time.time()
    delete, listed, protected = plan(
        root,
        include_unknown=args.all,
        max_age=args.max_age,
        short_age=args.short_age,
        now=now,
        sessions_only=args.sessions_only,
    )
    sizes = {str(p): tree_size(p) for _, _, _, p in delete}
    total = sum(sizes.values())
    mode = "削除" if args.apply else "削除の候補 (dry-run)"
    print(f"{mode}: {len(delete)} 件、合計 {total / 1e9:.2f} GB (場所: {root.resolve()})")
    for name, kind, age, path in sorted(delete, key=lambda r: -sizes[str(r[3])])[:20]:
        print(f"  {sizes[str(path)] / 1e6:9.1f} MB  {age:5.1f} 日  [{kind}]  {name}")
    if len(delete) > 20:
        print(f"  … ほか {len(delete) - 20} 件")
    if listed:
        lsz = {str(p): tree_size(p) for _, _, p in listed}
        print(
            f"未知の名前 (自動では消さない): {len(listed)} 件、合計 {sum(lsz.values()) / 1e9:.2f} GB。--all で消せる"
        )
        for name, age, path in sorted(listed, key=lambda r: -lsz[str(r[2])])[:10]:
            print(f"  {lsz[str(path)] / 1e6:9.1f} MB  {age:5.1f} 日  {name}")
    if protected:
        print(f"保護 (消さない): {', '.join(protected)}")

    if not args.apply:
        print("消すには --apply を付ける")
        return 0
    failed = 0
    for name, _kind, _age, path in delete:
        try:
            result = remove(path, root_dev)
        except OSError as e:
            failed += 1
            print(f"失敗: {name}: {e}", file=sys.stderr)
            continue
        if result != "ok":
            failed += 1
            why = "別のデバイス (マウント) のため" if result == "other-device" else "消せなかった"
            print(f"スキップ: {name} ({why})", file=sys.stderr)
    print(f"完了: {len(delete) - failed} 件を削除、{failed} 件が失敗・スキップ")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

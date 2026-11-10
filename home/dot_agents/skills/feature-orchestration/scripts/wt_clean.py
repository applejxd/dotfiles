#!/usr/bin/env python3
"""統合済みの worktree と枝を掃除する（PR ビューアの統合の cleanup と同じ規則）。

    python3 scripts/wt_clean.py <名前>... [--dry-run] [--repo <パス>] [--target develop]

名前は `feature/` を除いた部分（worktree は `.tmp/worktrees/<名前>`、枝は `feature/<名前>`）。
規則: docs/spec/orchestration.md#worktree-の掃除の規則
  1. 統合済み（枝が統合先の祖先）だけが対象。未統合・追跡ファイルの変更・未追跡（無視されないもの）は拒否。
  2. 無視ファイル（__pycache__・node_modules など）だけなら、それごと削除する（`--force` は使わない。git worktree remove が消す）。
  3. 削除前に無視ファイルを `<共通 git-dir>/pi-cleanup-backups/<名前>-<時刻>.tgz` へ退避する
     （上限 200 MB。超える・失敗なら残す。古い退避は 5 件まで）。
  4. 有効な owner の lock（pid が生きている）・人が付けた lock は消さない。残骸の lock は解除して消す。
  5. 枝は `git branch -d`。
  6. 枝が無く、`.tmp/worktrees/<名前>`（本体の直下 1 階層）の worktree が detached HEAD で、HEAD が統合先の祖先・
     追跡ファイルの変更なしなら、worktree だけ削除する（`finish --keepremote` で枝だけ消えた残骸）。
終了コード: 0 = 全て処理、3 = 一部を残した・拒否、2 = 使い方の誤り。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path

import wt_owner

BACKUP_LIMIT = 200 * 1024 * 1024
BACKUP_KEEP = 5
# 外部のコードを動かしうる worktree 固有の設定（見つけたら status も動かさず残す）
RISKY_KEYS = ("filter", "fsmonitor", "hookspath", "sshcommand", "editor", "pager", "askpass")


class UsageError(Exception):
    pass


@dataclass
class Result:
    name: str
    kind: str  # 削除した / 残した / 拒否
    detail: str = ""

    def line(self) -> str:
        return f"{self.name}: {self.kind}" + (f"（{self.detail}）" if self.detail else "")


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        {"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_GLOBAL": "/dev/null"}
    )
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )


def common_dir(repo: Path) -> Path:
    r = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if r.returncode != 0:
        raise UsageError("git リポジトリではありません")
    return Path(r.stdout.strip())


def worktrees(repo: Path) -> dict[str, tuple[Path, str]]:
    """枝（refs/heads/...）→ (worktree の実パス, lock の理由。lock 無しは None)。"""
    r = git(repo, "worktree", "list", "--porcelain", "-z")
    res: dict[str, tuple[Path, str | None]] = {}
    cur: Path | None = None
    lock: str | None = None
    branch: str | None = None

    def flush() -> None:
        if cur is not None and branch is not None:
            res[branch] = (cur, lock)

    for tok in r.stdout.split("\0"):
        if tok == "":
            flush()
            cur, lock, branch = None, None, None
        elif tok.startswith("worktree "):
            cur = Path(tok[len("worktree ") :]).resolve()
        elif tok.startswith("branch "):
            branch = tok[len("branch ") :]
        elif tok == "locked" or tok.startswith("locked "):
            lock = tok[len("locked") :].strip()
    flush()
    return res  # type: ignore[return-value]


def detached_worktree(repo: Path, wt: Path) -> tuple[str | None, str | None] | None:
    """実パスが wt の worktree が detached HEAD なら (HEAD の sha, lock の理由。無しは None)。

    枝つき・bare・prunable・見つからないときは None。
    """
    r = git(repo, "worktree", "list", "--porcelain", "-z")
    cur: Path | None = None
    head: str | None = None
    detached = False
    lock: str | None = None
    for tok in [*r.stdout.split("\0"), ""]:
        if tok == "":
            if cur == wt and detached and head:
                return head, lock
            cur, head, detached, lock = None, None, False, None
        elif tok.startswith("worktree "):
            cur = Path(tok[len("worktree ") :]).resolve()
        elif tok.startswith("HEAD "):
            head = tok[len("HEAD ") :]
        elif tok == "detached":
            detached = True
        elif tok == "locked" or tok.startswith("locked "):
            lock = tok[len("locked") :].strip()
    return None


def clean_detached(repo: Path, name: str, target: str, dry: bool) -> Result:
    """枝が無く detached HEAD で残った統合済みの worktree（`finish --keepremote` の後）を消す。"""
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        return Result(name, "拒否", "名前が不正（.tmp/worktrees/ の直下の 1 階層だけ）")
    main = common_dir(repo).parent.resolve()
    base = main / ".tmp" / "worktrees"
    raw = base / name
    if raw.is_symlink() or not raw.is_dir():
        return Result(
            name, "拒否", f"枝 feature/{name} も worktree も無い、またはシンボリックリンク"
        )
    wt = raw.resolve()
    if wt.parent != base.resolve() or wt == main:
        return Result(name, "拒否", ".tmp/worktrees/ の直下の worktree ではない")
    entry = detached_worktree(repo, wt)
    if entry is None:
        return Result(name, "拒否", f"枝 feature/{name} が無く、detached HEAD の worktree でもない")
    head, reason = entry
    if git(repo, "merge-base", "--is-ancestor", str(head), f"refs/heads/{target}").returncode != 0:
        return Result(name, "拒否", f"未統合（HEAD が {target} の祖先でない）")
    if reason is not None:
        owner = wt_owner.parse_owner(reason)
        if owner is None:
            return Result(name, "拒否", f"人が付けた lock がある: {reason}")
        if wt_owner.pid_alive(owner.pid):
            return Result(
                name, "拒否", f"有効な owner がいる: {owner.kind} {owner.id} pid={owner.pid}"
            )
        return Result(
            name,
            "拒否",
            f"残骸の lock がある（{owner.kind} {owner.id} pid={owner.pid}）。"
            "python3 scripts/wt_owner.py reap で解除してから、もう一度",
        )
    if risky_config(wt) or in_progress(wt):
        return Result(name, "拒否", "確かめられない設定、または merge・rebase などの途中")
    tracked = git(wt, "status", "--porcelain", "--untracked-files=no")
    if tracked.returncode != 0:
        return Result(name, "拒否", "status を確かめられない")
    if tracked.stdout.strip():
        return Result(name, "拒否", "追跡ファイルに未コミットの変更がある")
    st = git(wt, "status", "--porcelain", "--untracked-files=all")
    if st.returncode != 0 or st.stdout.strip():
        return Result(name, "拒否", "未追跡のファイルがある、または status を確かめられない")
    files = ignored_files(wt)
    if files is None:
        return Result(name, "残した", "無視ファイルを数えられない")
    if dry:
        return Result(
            name,
            "削除する",
            f"dry-run。detached の統合済み worktree。無視ファイル {len(files)} 件を退避して削除",
        )
    if files:
        why = backup(wt, name, common_dir(repo) / "pi-cleanup-backups", files)
        if why:
            return Result(name, "残した", why)
    if git(repo, "worktree", "remove", str(wt)).returncode != 0:
        return Result(name, "残した", "worktree を削除できなかった")
    git(repo, "worktree", "prune")
    return Result(name, "削除した", "detached の worktree")


def risky_config(wt: Path) -> bool:
    """worktree の gitdir の config.worktree に、外部コードを動かしうる設定があるか（読めなければ危険扱い）。"""
    r = git(wt, "rev-parse", "--absolute-git-dir")
    if r.returncode != 0:
        return True
    cfg = Path(r.stdout.strip()) / "config.worktree"
    if not cfg.exists():
        return False
    try:
        text = cfg.read_text(encoding="utf-8").lower()
    except (OSError, UnicodeDecodeError):
        return True
    return any(k in text for k in RISKY_KEYS)


def in_progress(wt: Path) -> bool:
    r = git(wt, "rev-parse", "--absolute-git-dir")
    gd = Path(r.stdout.strip())
    names = (
        "MERGE_HEAD",
        "rebase-merge",
        "rebase-apply",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "BISECT_LOG",
    )
    return any((gd / n).exists() for n in names)


def ignored_files(wt: Path) -> list[str] | None:
    r = git(wt, "ls-files", "-z", "--others", "--ignored", "--exclude-standard")
    if r.returncode != 0:
        return None
    return [x for x in r.stdout.split("\0") if x]


def backup(wt: Path, name: str, dest: Path, files: list[str]) -> str | None:
    """無視ファイルを tgz に退避する。失敗の理由を返す（成功は None）。"""
    total = 0
    try:
        for f in files:
            st = (wt / f).lstat()
            if (st.st_mode & 0o170000) == 0o100000:
                total += st.st_size
            if total > BACKUP_LIMIT:
                return "無視ファイルが退避の上限（200 MB）を超える"
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / f"{name.replace('/', '-')}-{time.strftime('%Y%m%d-%H%M%S')}.tgz"
        with tarfile.open(out, "w:gz") as tf:
            for f in files:
                tf.add(wt / f, arcname=f, recursive=False)
        olds = sorted(dest.glob("*.tgz"), key=lambda p: p.stat().st_mtime, reverse=True)
        for o in olds[BACKUP_KEEP:]:
            o.unlink()
    except OSError as e:
        return f"退避に失敗した（{type(e).__name__}）"
    return None


def clean_one(repo: Path, name: str, target: str, dry: bool) -> Result:
    branch = f"feature/{name}"
    ref = f"refs/heads/{branch}"
    if git(repo, "rev-parse", "--verify", "-q", ref).returncode != 0:
        return clean_detached(repo, name, target, dry)
    if git(repo, "merge-base", "--is-ancestor", ref, f"refs/heads/{target}").returncode != 0:
        return Result(name, "拒否", f"未統合（{branch} が {target} の祖先でない）")
    tab = worktrees(repo)
    entry = tab.get(ref)
    if entry is not None:
        wt, reason = entry
        if reason is not None:
            owner = wt_owner.parse_owner(reason)
            if owner is None:
                return Result(name, "拒否", f"人が付けた lock がある: {reason}")
            if wt_owner.pid_alive(owner.pid):
                return Result(
                    name, "拒否", f"有効な owner がいる: {owner.kind} {owner.id} pid={owner.pid}"
                )
            # 残骸（pid が死んだ lock）は解除しない。reap が理由欄を再読して解除するまで残す
            return Result(
                name,
                "拒否",
                f"残骸の lock がある（{owner.kind} {owner.id} pid={owner.pid}）。"
                "python3 scripts/wt_owner.py reap で解除してから、もう一度",
            )
        if risky_config(wt) or in_progress(wt):
            return Result(name, "拒否", "確かめられない設定、または merge・rebase などの途中")
        st = git(wt, "status", "--porcelain", "--untracked-files=all")
        if st.returncode != 0:
            return Result(name, "拒否", "status を確かめられない")
        if st.stdout.strip():
            return Result(name, "拒否", "追跡ファイルの変更、または未追跡のファイルがある")
        files = ignored_files(wt)
        if files is None:
            return Result(name, "残した", "無視ファイルを数えられない")
        if dry:
            return Result(
                name,
                "削除する",
                f"dry-run。無視ファイル {len(files)} 件を退避して worktree と枝を削除",
            )
        if files:
            why = backup(wt, name, common_dir(repo) / "pi-cleanup-backups", files)
            if why:
                return Result(name, "残した", why)
        # status が空（無視ファイルのみ）と確かめた後に、--force なしで削除する（git が無視ファイルごと消す）
        r = git(repo, "worktree", "remove", str(wt))
        if r.returncode != 0:
            return Result(name, "残した", "worktree を削除できなかった")
    elif dry:
        return Result(name, "削除する", "dry-run。worktree は無く、枝だけ削除")
    r = git(repo, "branch", "-d", branch)
    if r.returncode != 0:
        return Result(name, "残した", "worktree は削除したが、枝を削除できなかった")
    return Result(name, "削除した", "worktree と枝" if entry is not None else "枝のみ")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="統合済みの worktree と枝を掃除する")
    p.add_argument("names", nargs="+", help="feature/ を除いた名前")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--repo", default=".")
    p.add_argument("--target", default="develop")
    try:
        a = p.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    try:
        repo = Path(a.repo).resolve()
        common_dir(repo)
    except (UsageError, OSError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    bad = False
    for n in a.names:
        r = clean_one(repo, n, a.target, a.dry_run)
        print(r.line())
        bad = bad or r.kind in ("残した", "拒否")
    return 3 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

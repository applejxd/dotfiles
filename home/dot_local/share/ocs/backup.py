"""起動前の作業ツリーの退避。"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .common import HOME, _now, die

# 起動前の退避先。★境界の内側から触れない場所に置くこと。
#   内側からの書き込みは成功したように見えてホストへ届かない (R2。実測済み)。
BACKUPS = HOME / ".local/state/opencode-sandbox/backups"
# 退避の上限。★緩める方向は容量に直結する。
BACKUP_KEEP = 5  # 起動ディレクトリごとの世代数
BACKUP_MAX_BYTES = 128 * 1024 * 1024  # 起動ディレクトリごとの合計
BACKUP_TOTAL_MAX_BYTES = 1024 * 1024 * 1024  # 全体の合計 (プロジェクト数に依らず)
BACKUP_MAX_AGE_DAYS = 30  # 触らなくなったプロジェクトの分を捨てる
# ★これを超える作業ツリーは退避しない。**ハッシュする前に**測ること。
#   作ってから間引く設計だと、巨大なリポジトリで .git を肥大させたうえに
#   時間を使ってしまう (実測: 追跡対象だけで 84 GB のリポジトリがあった)。
BACKUP_MAX_SOURCE_BYTES = 256 * 1024 * 1024


def git_env(index: Path | None = None) -> dict[str, str]:
    """境界の外で動かす git の環境。利用者の ``GIT_*`` (``GIT_DIR`` など) を落とす。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    return env


def _git(workspace: Path, *args: str, index: Path | None = None):
    """境界の外で git を動かす。★実体を絶対パスで呼ぶ (PATH 差し替え対策)。"""
    return subprocess.run(
        ["/usr/bin/git", "-C", str(workspace), *args],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(index),
    )


def backup_key(workspace: Path) -> str:
    """退避先のディレクトリ名。人が読める名前 + 衝突しない識別子。"""
    digest = hashlib.sha256(str(workspace).encode("utf-8")).hexdigest()[:12]
    return f"{workspace.name}-{digest}"


def measure_source(toplevel: Path, rel: Path) -> int | None:
    """退避対象の合計サイズ。上限を超えたら打ち切って ``None`` を返す。

    ★``git add`` **の前に**測る。作ってから間引くと、巨大なリポジトリでは
      84 GB をハッシュして ``.git/objects`` を肥大させたうえで捨てることに
      なる。一覧は安い（実測: 264 ファイル / 84 GB を 0.04 秒）。
    """
    listed = _git(
        toplevel, "ls-files", "-c", "-o", "--exclude-standard", "-z", "--", rel.as_posix()
    )
    if listed.returncode != 0:
        return 0
    total = 0
    for name in listed.stdout.split("\0"):
        if not name:
            continue
        try:
            total += (toplevel / name).stat().st_size
        except OSError:
            # 消えた・辿れない分は数えない (測れないものは退避もできない)
            continue
        if total > BACKUP_MAX_SOURCE_BYTES:
            return None
    return total


def git_toplevel(workspace: Path) -> Path | None:
    """workspace を含むリポジトリの根。Git リポジトリでなければ ``None``。"""
    done = _git(workspace, "rev-parse", "--show-toplevel")
    return Path(done.stdout.strip()) if done.returncode == 0 else None


def stage_worktree(toplevel: Path, rel: Path, index: Path) -> str | None:
    """起動ディレクトリ以下の中身を表す tree を作り、その SHA を返す。

    ★作業ツリーには**一切触らない**。``git stash`` とは別物で、一時 index へ
      ``add`` して tree を書くだけ。再開時に変更が巻き戻ることはない。
    ★``git add -A`` なので ``.gitignore`` が効く。``.opencode-sandbox/`` の
      DB などは入らない。
    ★**git は親を遡る。** サブディレクトリで起動しても親リポジトリ全体を
      掴まないよう、パススペックで起動ディレクトリ以下に限る。境界が書き込みを
      許す範囲と揃える。

    退避するものが無ければ ``None``。
    """
    # 起動ディレクトリごと .gitignore されているなら退避するものは無い
    if rel != Path(".") and _git(toplevel, "check-ignore", "-q", rel.as_posix()).returncode == 0:
        return None

    # ★plumbing は **toplevel から** 走らせる。サブディレクトリから走らせると
    #   index に載るパスの基準がずれ、親のファイルが tree から落ちる (実測)。
    head = _git(toplevel, "rev-parse", "--verify", "HEAD^{tree}")
    # 一時 index は空のファイルで、git はそのままでは読めない。コミットが無ければ空で初期化する
    base = head.stdout.strip() if head.returncode == 0 else "--empty"
    read = _git(toplevel, "read-tree", base, index=index)
    if read.returncode != 0:
        die(f"作業ツリーを退避できない (read-tree): {read.stderr.strip()}")
    added = _git(toplevel, "add", "-A", "--", rel.as_posix(), index=index)
    if added.returncode != 0:
        die(f"作業ツリーを退避できない (add): {added.stderr.strip()}")
    written = _git(toplevel, "write-tree", index=index)
    if written.returncode != 0:
        die(f"作業ツリーを退避できない (write-tree): {written.stderr.strip()}")

    tree = _narrow(toplevel, written.stdout.strip(), rel)
    if tree is None:
        # 起動ディレクトリに追跡対象が 1 つも無い
        return None
    if head.returncode == 0 and tree == _narrow(toplevel, head.stdout.strip(), rel):
        # HEAD と同じ内容 = 未コミットの変更が無い
        return None
    return tree


def _narrow(toplevel: Path, tree: str, rel: Path) -> str | None:
    """tree を起動ディレクトリ以下へ絞り込む。該当が無ければ ``None``。"""
    if rel == Path("."):
        return tree
    found = _git(toplevel, "rev-parse", "--verify", f"{tree}:{rel.as_posix()}")
    return found.stdout.strip() if found.returncode == 0 else None


def _prune(paths, keep: int | None, max_bytes: int) -> None:
    """新しい順に残し、件数か合計サイズを超えた分を落とす。"""
    files = sorted(
        (p for p in paths if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    total = 0
    for position, path in enumerate(files):
        total += path.stat().st_size
        if (keep is not None and position >= keep) or total > max_bytes:
            path.unlink(missing_ok=True)


def prune_backups(directory: Path) -> None:
    """古い退避を落とす。★ここを緩めると容量に直結する。

    起動ディレクトリごとの上限だけでは、**プロジェクトが増えるほど全体が
    青天井になる**。全体の合計と期限も併せて押さえる。
    """
    cutoff = time.time() - BACKUP_MAX_AGE_DAYS * 86400
    for path in BACKUPS.rglob("*.tgz"):
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
    _prune(directory.glob("*.tgz"), BACKUP_KEEP, BACKUP_MAX_BYTES)
    _prune(BACKUPS.rglob("*.tgz"), None, BACKUP_TOTAL_MAX_BYTES)
    # 空になった置き場を片付ける (触らなくなったプロジェクトの分)
    for child in sorted(BACKUPS.glob("*")):
        if child.is_dir() and not any(child.iterdir()):
            child.rmdir()


def backup_worktree(workspace: Path, skip: bool) -> None:
    """起動前に作業ツリーを境界の外へ退避する。

    境界はワークスペースの**中**を守らない。未コミットの変更は snapshot でも
    git でも戻せないことがあるので、起動のたびに複製を外へ出しておく。

    ★退避先は境界の内側から触れない (``~/.local/state`` は deny_read の ``~``
      に入り、allowWrite にも無い)。内側からの書き込みは成功したように見えて
      ホストへ届かない (R2。実測で確認済み)。
    ★同じ内容なら同じ tree SHA になるので、変化が無い限り増えない。
    ★**退避できなかったら起動しない。** 「退避したつもり」で作業を始めるのが
      一番危ない。
    """
    if skip:
        return
    toplevel = git_toplevel(workspace)
    if toplevel is None:
        # Git リポジトリでないときは止めない（起動場所は利用者の責務）。
        # ただし退避も snapshot も効かないので、戻せないことは伝える。
        print(
            "注意: ここは Git リポジトリではない。退避も snapshot も効かず、"
            "壊した作業は戻せない",
            file=sys.stderr,
        )
        return
    rel = workspace.relative_to(toplevel)

    # ★ハッシュする前に大きさを見る。超えるなら退避も起動もしない。
    if measure_source(toplevel, rel) is None:
        die(
            f"退避対象が大きすぎる (> {BACKUP_MAX_SOURCE_BYTES // (1024 * 1024)} MiB): {workspace}",
            "退避すると .git が肥大し時間も掛かる。"
            "承知のうえで退避せず起動するなら --no-backup",
        )

    index = Path(tempfile.mkstemp(prefix="ocs-index-")[1])
    try:
        tree = stage_worktree(toplevel, rel, index)
    finally:
        index.unlink(missing_ok=True)
    if tree is None:
        return

    directory = BACKUPS / backup_key(workspace)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        die(
            f"退避先を作れない: {exc}",
            "退避せずに起動すると、壊した未コミットの変更は戻せない。"
            "承知のうえで進むなら --no-backup",
        )
    # ★内容が同じなら作り直さない。中断と再開を繰り返しても溜まらない。
    if any(directory.glob(f"*-{tree[:12]}.tgz")):
        return

    stamp = _now().replace(":", "").replace("-", "")
    target = directory / f"{stamp}-{tree[:12]}.tgz"
    done = _git(toplevel, "archive", "--format=tar.gz", "-o", str(target), tree)
    if done.returncode != 0 or not target.is_file():
        target.unlink(missing_ok=True)
        die(
            f"作業ツリーを退避できない: {done.stderr.strip()}",
            "退避せずに起動すると、壊した未コミットの変更は戻せない。"
            "承知のうえで進むなら --no-backup",
        )
    try:
        target.chmod(0o600)
        prune_backups(directory)
    except OSError as exc:
        die(f"退避の後始末に失敗した: {exc}")
    print(f"作業ツリーを退避した: {target}", file=sys.stderr)

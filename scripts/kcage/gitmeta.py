"""メインの .git/commondir の封じ込め（C14。docs/spec/sandbox/incus-box.md の git の節）。

.git/commondir に別のディレクトリを書くと、git はそこから config・hooks を読む。
箱が書ける作業ツリー内を指されると、hooks・config の読み取り専用の重ねを迂回できる。
中身が "." の commondir は無害（common dir が gitdir 自身になる）。それを読み取り専用で重ねて塞ぐ。

純粋な判定（decide・check_content）と、薄い実行層（ensure_commondir・RealOps）に分ける。
作成は kcage-root が呼び出し元の uid・gid に権限を落としてから行う。
.git が差し替えられても、利用者が書ける範囲を超えて root が書かないようにするため。
"""

from __future__ import annotations

import os
import posixpath
from typing import Protocol

from kcage.config import ConfigError

COMMONDIR_CONTENT = b".\n"

REJECT_MESSAGE = (
    ".git/commondir が別の場所を指している。ホストの git が別の config・hooks を読む恐れがある。"
    "内容を確かめて消してから再実行する"
)


def is_safe_content(content: bytes, gitdir: str) -> bool:
    """中身が "."（空白・改行を除く）または gitdir 自身の絶対パスなら無害。"""
    try:
        text = content.decode("utf-8").strip()
    except UnicodeDecodeError:
        return False
    return text == "." or (text != "" and posixpath.normpath(text) == posixpath.normpath(gitdir))


def decide(content: bytes | None, gitdir: str) -> str:
    """ "create"（無いので作る）か "ok"（何もしない）。それ以外は ConfigError（up を拒否）。"""
    if content is None:
        return "create"
    if is_safe_content(content, gitdir):
        return "ok"
    raise ConfigError(REJECT_MESSAGE)


class CommondirOps(Protocol):
    """実行層の口。試験では偽物に差し替える（実際に setuid しない）。"""

    def is_real_dir(self, path: str) -> bool: ...
    def drop(self, uid: int, gid: int) -> None: ...
    def restore(self) -> None: ...
    def read(self, path: str) -> bytes | None: ...  # 無ければ None。symlink・特殊ファイルは OSError
    def create(self, path: str, data: bytes) -> None: ...  # O_EXCL で新規作成だけ


def ensure_commondir(gitdir: str, uid: int, gid: int, ops: CommondirOps) -> str:
    """メインの gitdir（実ディレクトリ）に commondir を用意する。結果は "created" / "ok" / "skipped"。

    権限を落とす→確認・作成→戻す、の順。例外でも戻す。root が書くのは commondir の 1 ファイルだけ。
    """
    try:
        ops.drop(uid, gid)
        if not ops.is_real_dir(gitdir):
            return "skipped"
        path = posixpath.join(gitdir, "commondir")
        try:
            content = ops.read(path)
        except OSError as e:
            raise ConfigError(
                f".git/commondir を安全に読めない（symlink など）: {e.strerror}"
            ) from e
        if decide(content, gitdir) == "ok":
            return "ok"
        try:
            ops.create(path, COMMONDIR_CONTENT)
        except OSError as e:
            raise ConfigError(f".git/commondir を作れない: {e.strerror}") from e
        return "created"
    finally:
        ops.restore()


class RealOps:
    """本物の実行層。権限は effective uid・gid だけを一時的に落とす。"""

    def is_real_dir(self, path: str) -> bool:
        import stat

        try:
            return stat.S_ISDIR(os.lstat(path).st_mode)
        except OSError:
            return False

    def drop(self, uid: int, gid: int) -> None:
        os.setegid(gid)  # 先に gid（uid を落とした後は変えられない）
        os.seteuid(uid)

    def restore(self) -> None:
        try:
            os.seteuid(0)
            os.setegid(0)
        except OSError:
            os._exit(70)  # root に戻せないまま続けない

    def read(self, path: str) -> bytes | None:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        try:
            return os.read(fd, 4096)
        finally:
            os.close(fd)

    def create(self, path: str, data: bytes) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)


# ---- doctor の判定（純粋） ----

# .git の中の、追加の参照先になりうる名前（存在するだけで warn）
WARN_ENTRIES: tuple[tuple[str, str], ...] = (
    ("config.worktree", "config.worktree がある（.git/config の保護が及ばない設定がありうる）"),
    ("info/attributes", "info/attributes がある（filter 経由でコードが実行されうる）"),
    ("objects/info/alternates", "objects/info/alternates がある（別の object 置き場を参照する）"),
    ("remotes", "remotes/ がある（古い remote 定義の形式）"),
    ("branches", "branches/ がある（古い remote 定義の形式）"),
    ("modules", "modules/ がある（submodule の config は共有の .git 側にある）"),
)

OK_DETAIL = "追加の参照先なし"


def inspect_metadata(
    commondir: bytes | None, gitdir: str, present: frozenset[str]
) -> list[tuple[str, str]]:
    """(status, detail) の一覧。commondir は中身（無ければ None）。present は .git の中にある名前。"""
    out: list[tuple[str, str]] = []
    if commondir is not None and not is_safe_content(commondir, gitdir):
        out.append(("fail", '.git/commondir が "." でも自身でもない。別の config・hooks を読む'))
    out.extend(("warn", msg) for name, msg in WARN_ENTRIES if name in present)
    if not out:
        out.append(("ok", OK_DETAIL))
    return out

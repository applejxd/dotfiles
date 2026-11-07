"""テンプレートへ入れる配布物（--dist）の検証。root（box-root）が読むので厳格に行う。標準ライブラリだけ。

dotfiles 固有のものは import しない。配布物を作る側の拒否名とは独立に、汎用の拒否名・内容の型を持つ（二重の防御）。
検証するのは: 絶対パス・正規化・経路に symlink なし・呼び出し元の所有・他人から書けない・中に通常ファイルとディレクトリ
だけ（symlink・デバイス・socket・fifo・ハードリンクは拒否）・総サイズと件数の上限・拒否名・秘密らしい内容。
エラーの文言に、ファイルの内容は出さない（相対パスと理由だけ）。
"""

from __future__ import annotations

import fnmatch
import os
import posixpath
import re
import stat

MAX_TOTAL_BYTES = 500 * 1024 * 1024
MAX_ENTRIES = 200_000
MAX_SCAN_BYTES = 2_000_000

# パスの各要素（名前）への fnmatch。1 つでも当たれば拒否する
DENY_NAMES: tuple[str, ...] = (
    "auth.json",
    "sessions",
    "*.jsonl",
    ".env",
    ".env.*",
    "mcp.json",
    "models.json",
    ".ssh",
    ".aws",
    ".gnupg",
    ".netrc",
    ".npmrc",
    ".git-credentials",
    ".git",
    "credentials",
    "credentials.json",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ed25519*",
    "id_ecdsa*",
    "history",
    "*.history",
)
SECRET_PATTERNS: tuple[re.Pattern[bytes], ...] = (
    re.compile(rb"ghp_[A-Za-z0-9]{20,}"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"hf_[A-Za-z0-9]{20,}"),
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


class DistCheckError(ValueError):
    """配布物が検証に通らない。"""


def is_denied_name(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in DENY_NAMES)


def _check_path_text(path: str) -> None:
    if not isinstance(path, str) or not path.startswith("/") or "\x00" in path or "\n" in path:
        raise DistCheckError("--dist は絶対パスが必要")
    if ".." in path.split("/") or posixpath.normpath(path) != path:
        raise DistCheckError("--dist は正規化された絶対パスが必要")


def _check_ancestors(path: str) -> None:
    """経路のどの要素も symlink でないこと（最後の要素を含む）。"""
    cur = "/"
    for part in [p for p in path.split("/") if p]:
        cur = posixpath.join(cur, part)
        try:
            st = os.lstat(cur)
        except OSError as e:
            raise DistCheckError(f"--dist の経路を調べられない: {cur}") from e
        if stat.S_ISLNK(st.st_mode):
            raise DistCheckError(f"--dist の経路に symlink がある: {cur}")


def _scan_file(full: str, rel: str) -> None:
    fd = os.open(full, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_SCAN_BYTES:
            return
        data = os.read(fd, MAX_SCAN_BYTES + 1)
    finally:
        os.close(fd)
    if any(p.search(data) for p in SECRET_PATTERNS):
        raise DistCheckError(f"秘密らしい内容がある: {rel}")


def validate_dist(
    path: str, caller_uid: int, *, max_bytes: int = MAX_TOTAL_BYTES, max_entries: int = MAX_ENTRIES
) -> str:
    """検証済みの path を返す。違反は DistCheckError。"""
    _check_path_text(path)
    _check_ancestors(path)
    top = os.lstat(path)
    if not stat.S_ISDIR(top.st_mode):
        raise DistCheckError("--dist はディレクトリが必要")
    if top.st_uid != caller_uid:
        raise DistCheckError("--dist の所有者が呼び出し元ではない")
    if top.st_mode & 0o022:
        raise DistCheckError("--dist はグループ・他人から書ける")
    total = 0
    count = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        for name in [*dirs, *files]:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, path)
            count += 1
            if count > max_entries:
                raise DistCheckError("--dist の件数が上限を超えた")
            st = os.lstat(full)
            if stat.S_ISLNK(st.st_mode):
                raise DistCheckError(f"symlink を含む: {rel}")
            if not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
                raise DistCheckError(f"通常ファイル・ディレクトリ以外を含む: {rel}")
            if st.st_uid != caller_uid:
                raise DistCheckError(f"呼び出し元の所有ではない: {rel}")
            if is_denied_name(name):
                raise DistCheckError(f"拒否名を含む: {rel}")
            if stat.S_ISDIR(st.st_mode):
                continue
            if st.st_nlink > 1:
                raise DistCheckError(f"ハードリンクを含む: {rel}")
            total += st.st_size
            if total > max_bytes:
                raise DistCheckError("--dist の総サイズが上限を超えた")
            _scan_file(full, rel)
    return path

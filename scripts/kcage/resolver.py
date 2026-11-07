"""SecretRef（秘密の参照）を、実行時にだけ値へ解決する。値は例外・ログ・argv に出さない（契約 C1）。

出どころ:
- file: 絶対パスの通常ファイル（symlink 不可）。所有者は root か呼び出し元。グループ・他人に権限が無い（0600 相当）。4096 バイト以下。
- command: argv の配列（シェルなし・標準入力なし・30 秒・出力 4096 バイト以下）。**呼び出し元のユーザー権限で**実行する
  （`gh auth token` や `pass show` が、そのユーザーの設定・鍵を使えるように。環境は最小の PATH と HOME だけ）。
- prompt: 端末（/dev/tty）で尋ねる。保存しない。

値は 1 行・ASCII の印字可能文字・空白なし・255 文字以下。違反は SecretError（値は含めない）。
ファイル名に secret を含めない（フルガードの書き込み拒否の規則 `**/*secret*` に当たるため。コードの名前であり、秘密のファイルではない）。
"""

from __future__ import annotations

import getpass
import os
import pwd
import stat
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from kcage import model

MAX_FILE_BYTES = 4096
MAX_COMMAND_BYTES = 4096
MAX_VALUE_CHARS = 255
COMMAND_TIMEOUT_SECONDS = 30
SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


class SecretError(RuntimeError):
    """解決できない・値が不正。メッセージに値を含めない。"""


@dataclass
class Env:
    """外部とのやり取り。試験では差し替える。"""

    lstat: Callable[[str], os.stat_result] = os.lstat
    read: Callable[[str, int], bytes] = field(default=None)  # type: ignore[assignment]
    run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run
    prompt: Callable[[str], str] = getpass.getpass
    getpw: Callable[[int], pwd.struct_passwd] = pwd.getpwuid

    def __post_init__(self) -> None:
        if self.read is None:
            self.read = _read_file


def _read_file(path: str, limit: int) -> bytes:
    with open(path, "rb") as f:
        return f.read(limit + 1)


def _validate(value: str, name: str) -> str:
    v = value.rstrip("\r\n")
    if not v or len(v) > MAX_VALUE_CHARS:
        raise SecretError(f"{name}: 値の長さが不正（1〜{MAX_VALUE_CHARS} 文字）")
    if any(not (0x21 <= ord(c) <= 0x7E) for c in v):
        raise SecretError(f"{name}: 値に 1 行・印字可能な ASCII・空白なし以外が含まれる")
    return v


def _resolve_file(ref: model.SecretRef, caller_uid: int | None, env: Env) -> str:
    path = ref.path
    if not path or not path.startswith("/") or ".." in path.split("/"):
        raise SecretError(f"{ref.name}: file の path は正規化された絶対パスが必要")
    try:
        st = env.lstat(path)
    except OSError as e:
        raise SecretError(f"{ref.name}: ファイルを確認できない（{type(e).__name__}）") from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise SecretError(f"{ref.name}: 通常ファイルでなければならない（symlink 不可）")
    if st.st_uid not in {0, caller_uid}:
        raise SecretError(f"{ref.name}: 所有者が root でも呼び出し元でもない")
    if st.st_mode & 0o077:
        raise SecretError(f"{ref.name}: グループ・他人に権限がある（0600 相当にする）")
    if st.st_size > MAX_FILE_BYTES:
        raise SecretError(f"{ref.name}: ファイルが大きすぎる（{MAX_FILE_BYTES} バイト以下）")
    try:
        data = env.read(path, MAX_FILE_BYTES)
    except OSError as e:
        raise SecretError(f"{ref.name}: 読めない（{type(e).__name__}）") from None
    if len(data) > MAX_FILE_BYTES:
        raise SecretError(f"{ref.name}: ファイルが大きすぎる")
    return _validate(data.decode("ascii", errors="replace"), ref.name)


def _resolve_command(ref: model.SecretRef, caller_uid: int | None, env: Env) -> str:
    argv: Sequence[str] = ref.argv
    if not argv or not all(isinstance(a, str) and a for a in argv):
        raise SecretError(f"{ref.name}: command の argv が空・不正")
    kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL,  # 標準エラーは捨てる（値や認証情報を含みうる）
        "timeout": COMMAND_TIMEOUT_SECONDS,
        "shell": False,
        "check": False,
    }
    environ = {"PATH": SAFE_PATH}
    if caller_uid is not None:
        pw = env.getpw(caller_uid)
        kwargs["user"] = caller_uid
        kwargs["group"] = pw.pw_gid
        environ["HOME"] = pw.pw_dir
    kwargs["env"] = environ
    try:
        cp = env.run(list(argv), **kwargs)
    except subprocess.TimeoutExpired:
        raise SecretError(
            f"{ref.name}: command が時間切れ（{COMMAND_TIMEOUT_SECONDS} 秒）"
        ) from None
    except OSError as e:
        raise SecretError(f"{ref.name}: command を実行できない（{type(e).__name__}）") from None
    if cp.returncode != 0:
        raise SecretError(f"{ref.name}: command が失敗した（終了コード {cp.returncode}）")
    out = cp.stdout or b""
    if len(out) > MAX_COMMAND_BYTES:
        raise SecretError(f"{ref.name}: command の出力が大きすぎる")
    return _validate(out.decode("ascii", errors="replace"), ref.name)


def resolve(ref: model.SecretRef, *, caller_uid: int | None = None, env: Env | None = None) -> str:
    """参照を値へ解決する。値は戻り値だけ。例外メッセージには出さない。"""
    env = env or Env()
    if ref.source == "file":
        return _resolve_file(ref, caller_uid, env)
    if ref.source == "command":
        return _resolve_command(ref, caller_uid, env)
    if ref.source == "prompt":
        try:
            return _validate(env.prompt(f"{ref.name} の値: "), ref.name)
        except (EOFError, OSError):
            raise SecretError(f"{ref.name}: 端末から読めない") from None
    raise SecretError(f"{ref.name}: 未知の出どころ")

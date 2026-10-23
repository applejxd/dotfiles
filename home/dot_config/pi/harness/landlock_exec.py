"""Landlock で書き込み可を狭めてコマンドを実行する (pi ハーネスの子の隔離用)。

使い方: landlock_exec.py [--write PATH]... [--write-if-exists PATH]... -- COMMAND [ARGS...]
        landlock_exec.py --check
終了コード: 2 = 使い方の誤り、3 = Landlock を適用できない (ABI 3 未満を含む)、127 = COMMAND を実行できない。
ラッパー自身の標準エラーはすべて `landlock_exec: ` で始まる 1 行。
see docs/change/0029-worktree-isolation.md
"""

from __future__ import annotations

import ctypes
import errno
import os
import shutil
import sys
import tempfile

SYS_CREATE, SYS_ADD, SYS_RESTRICT = 444, 445, 446
CREATE_VERSION = 1
RULE_PATH_BENEATH = 1
PR_SET_NO_NEW_PRIVS = 38

EXEC, WFILE, RFILE, RDIR, RMDIR, RMFILE = (1 << i for i in range(6))
MKCHR, MKDIR, MKREG, MKSOCK, MKFIFO, MKBLK, MKSYM = (1 << i for i in range(6, 13))
REFER, TRUNCATE = 1 << 13, 1 << 14
READ = EXEC | RFILE | RDIR
WRITE_V1 = WFILE | RMDIR | RMFILE | MKCHR | MKDIR | MKREG | MKSOCK | MKFIFO | MKBLK | MKSYM

EXIT_USAGE, EXIT_UNAVAILABLE, EXIT_EXEC = 2, 3, 127
MIN_ABI = 3
PREFIX = "landlock_exec: "

FORBIDDEN_FIXED = (
    "/", "/usr", "/etc", "/var", "/root", "/proc", "/sys", "/dev", "/boot",
    "/opt", "/mnt", "/run", "/lib", "/lib32", "/lib64", "/libx32", "/bin", "/sbin",
)  # fmt: skip


class RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class PathBeneath(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


class UsageError(Exception):
    pass


class AbiTooOld(OSError):
    pass


_libc = None


def _get_libc():
    global _libc
    if _libc is None:
        _libc = ctypes.CDLL(None, use_errno=True)
        _libc.syscall.restype = ctypes.c_long
    return _libc


def syscall(*args):
    """試験が差し替える唯一の syscall 入口。失敗は OSError。"""
    ret = _get_libc().syscall(*args)
    if ret < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))
    return ret


def prctl(*args):
    """試験が差し替える prctl の入口。失敗は OSError。"""
    if _get_libc().prctl(*args) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))


def get_abi():
    return syscall(SYS_CREATE, None, 0, CREATE_VERSION)


def handled_access(abi):
    """版で扱う種別を変える。版 4 以降 (ネットワーク・IOCTL_DEV・スコープ) は扱わない。"""
    write = WRITE_V1 | (REFER if abi >= 2 else 0) | (TRUNCATE if abi >= 3 else 0)
    return READ | write


def access_for(path, abi):
    handled = handled_access(abi)
    if os.path.isdir(path):
        return handled
    return EXEC | WFILE | RFILE | (TRUNCATE if abi >= 3 else 0)


def parse_args(argv):
    """(writes, write_if_exists, command) を返す。誤りは UsageError。"""
    writes, optional = [], []
    i = 0
    while i < len(argv) and argv[i] != "--":
        opt = argv[i]
        if opt not in ("--write", "--write-if-exists"):
            raise UsageError(f"知らないオプション: {opt}")
        if i + 1 >= len(argv) or argv[i + 1] in ("--", ""):
            raise UsageError(f"{opt} の値がありません")
        (writes if opt == "--write" else optional).append(argv[i + 1])
        i += 2
    if i >= len(argv):
        raise UsageError("-- がありません")
    command = argv[i + 1 :]
    if not command or not command[0]:
        raise UsageError("COMMAND がありません")
    return writes, optional, command


def forbidden_paths():
    """広すぎて許可できない実体パス。$HOME とその祖先は呼出時の環境で決める。"""
    forbidden = set(FORBIDDEN_FIXED) | {os.path.realpath(p) for p in FORBIDDEN_FIXED}
    cur = os.path.realpath(os.path.expanduser("~"))
    while True:
        forbidden.add(cur)
        parent = os.path.dirname(cur)
        if parent == cur:
            return forbidden
        cur = parent


def resolve_writes(writes, optional):
    """realpath で解決した許可パスを返す。--write の不在・広すぎるパスは UsageError。"""
    forbidden = forbidden_paths()
    for path in (*writes, *optional):
        if os.path.realpath(path) in forbidden:
            raise UsageError(f"広すぎる許可パスは指定できません: {path}")
    resolved = []
    for path in writes:
        real = os.path.realpath(path)
        if not os.path.exists(real):
            raise UsageError(f"--write のパスが存在しません: {path}")
        resolved.append(real)
    for path in optional:
        real = os.path.realpath(path)
        if os.path.exists(real):
            resolved.append(real)
    return resolved


def restrict(paths):
    """Landlock を適用する。失敗は OSError (この時点では COMMAND を実行しない)。"""
    abi = get_abi()
    if abi < MIN_ABI:
        raise AbiTooOld(
            errno.ENOSYS,
            f"landlock abi {abi} は {MIN_ABI} 未満: truncate を制限できないため隔離を起動しない",
        )
    handled = handled_access(abi)
    attr = RulesetAttr(handled)
    fd = syscall(SYS_CREATE, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    try:
        rules = [("/", READ)] + [(p, access_for(p, abi)) for p in paths]
        for path, access in rules:
            pfd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = PathBeneath(access, pfd)
                syscall(SYS_ADD, fd, RULE_PATH_BENEATH, ctypes.byref(rule), 0)
            finally:
                os.close(pfd)
        prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)
        syscall(SYS_RESTRICT, fd, 0)
    finally:
        os.close(fd)
    return abi


def check():
    """使い捨てディレクトリへ fork した子で実際に適用できるかを確かめる (親には適用しない)。"""
    tmp = tempfile.mkdtemp(prefix="landlock_check_")
    try:
        abi = get_abi()
        if abi < MIN_ABI:
            raise AbiTooOld(errno.ENOSYS, f"landlock abi {abi} は {MIN_ABI} 未満")
        pid = os.fork()
        if pid == 0:
            code = 1
            try:
                restrict([os.path.realpath(tmp)])
                code = 0
            finally:
                os._exit(code)
        _, status = os.waitpid(pid, 0)
        if not (os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0):
            raise OSError(errno.EPERM, "子プロセスで適用できなかった")
    except OSError as exc:
        print(f"{PREFIX}Landlock を使えません: {exc}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"landlock abi {abi}")
    return 0


def main(argv):
    if list(argv) == ["--check"]:
        return check()
    try:
        writes, optional, command = parse_args(argv)
        paths = resolve_writes(writes, optional)
    except UsageError as exc:
        print(f"{PREFIX}{exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        restrict(paths)
    except OSError as exc:
        print(f"{PREFIX}Landlock を適用できません: {exc}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    try:
        os.execvp(command[0], command)
    except OSError as exc:
        print(f"{PREFIX}実行できません: {command[0]}: {exc}", file=sys.stderr)
        return EXIT_EXEC
    return EXIT_EXEC


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""CHG-0029 W0b: Landlock を重ねて、子の書込可を狭めてコマンドを実行する (試作。使い捨ての検査用)。

使い方: python3 w0b_landlock.py --write <dir> [--write <dir> ...] -- <command> [args...]
読み取りと実行は、親の Fence が許す範囲のまま。書き込みは --write のディレクトリの下だけ。
"""

import ctypes
import os
import sys

libc = ctypes.CDLL(None, use_errno=True)
SYS_CREATE, SYS_ADD, SYS_RESTRICT = 444, 445, 446
EXEC, WFILE, RFILE, RDIR, RMDIR, RMFILE = (1 << i for i in range(6))
MKCHR, MKDIR, MKREG, MKSOCK, MKFIFO, MKBLK, MKSYM = (1 << i for i in range(6, 13))
REFER, TRUNCATE = 1 << 13, 1 << 14
READ = EXEC | RFILE | RDIR
WRITE_V1 = WFILE | RMDIR | RMFILE | MKCHR | MKDIR | MKREG | MKSOCK | MKFIFO | MKBLK | MKSYM


class RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class PathBeneath(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def syscall(*args):
    ret = libc.syscall(*args)
    if ret < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))
    return ret


def restrict(write_dirs):
    abi = syscall(SYS_CREATE, None, 0, 1)
    write = WRITE_V1 | (REFER if abi >= 2 else 0) | (TRUNCATE if abi >= 3 else 0)
    handled = READ | write
    fd = syscall(SYS_CREATE, ctypes.byref(RulesetAttr(handled)), ctypes.sizeof(RulesetAttr), 0)
    file_ok = EXEC | WFILE | RFILE | (TRUNCATE if abi >= 3 else 0)
    rules = [("/", READ)] + [(p, handled if os.path.isdir(p) else file_ok) for p in write_dirs]
    for path, access in rules:
        pfd = os.open(path, os.O_PATH)
        syscall(SYS_ADD, fd, 1, ctypes.byref(PathBeneath(access, pfd)), 0)
        os.close(pfd)
    if libc.prctl(38, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "no_new_privs")
    syscall(SYS_RESTRICT, fd, 0)
    return abi


def main(argv):
    if "--" not in argv:
        print(__doc__)
        return 2
    sep = argv.index("--")
    opts, cmd = argv[:sep], argv[sep + 1 :]
    write_dirs = [os.path.abspath(opts[i + 1]) for i, o in enumerate(opts) if o == "--write"]
    try:
        restrict(write_dirs)
    except OSError as exc:
        print(f"landlock を適用できません: {exc}", file=sys.stderr)
        return 3
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

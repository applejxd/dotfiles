"""ホストの初期設定（root で、人が実行する。pk kcage-setup / kcage setup の本体）。

計画（plan）は純粋な関数で、副作用なし・ファイルを読まない。ホストの状態は State として呼び出し側が集める。
実行層（execute）は計画の順に実行するだけ。sudo のパスワードは保存しない（尋ねるのは sudo 自身）。
"""

from __future__ import annotations

import argparse
import grp
import os
import pwd
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ""):  # スクリプトとして実行されたとき（scripts/ を import の根にする）
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kcage import model

CONF_DIR = "/etc/kcage"
SUDOERS_DIR = "/etc/sudoers.d"
HELPER_ENTRY = f"{model.ROOT_HELPER_DIR}/kcage-root"
POLICY_TEMPLATE = """# kcage の許可表（root 所有）。リポジトリの登録は `kcage register`。
# 形式は docs/spec/sandbox/incus-box.md を参照。
[defaults]
network = "nat"
"""
HELPER_SCRIPT = f'''#!/usr/bin/env python3
"""kcage-root の入口。root 所有の配備コピーの kcage パッケージを呼ぶだけ。"""

import sys

sys.path.insert(0, "{model.ROOT_HELPER_DIR}")

from kcage.root_helper import main  # noqa: E402

sys.exit(main(sys.argv[1:]))
'''


@dataclass(frozen=True)
class State:
    """ホストの現在の状態（実行層が集める）。計画はこれだけを見て冪等にする。"""

    incus_installed: bool = False
    incus_initialized: bool = False
    subuid_has: bool = False
    subgid_has: bool = False
    policy_exists: bool = False
    user_in_incus_admin: bool = False


@dataclass(frozen=True)
class Opts:
    user: str
    uid: int
    src_dir: str  # 複製元の scripts/kcage
    gid: int | None = None  # ホストの gid（SUDO_GID）。省略は uid と同じ
    state: State = field(default_factory=State)
    sudoers_text: str = ""  # root_helper.sudoers_snippet の出力（実行層が渡す）
    update: bool = False  # 配備コピーの更新だけ
    net_steps: tuple[model.Step, ...] = ()  # W2 の net.plan_host_setup が返す host 側の準備
    allow_missing_sudoers: bool = False


def subid_line(uid: int) -> str:
    return f"root:{uid}:1"


def _op(argv: Sequence[str], desc: str, *, check: bool = True) -> model.Op:
    return model.Op(where="host", argv=tuple(argv), desc=desc, check=check)


def deploy_steps(opts: Opts) -> list[model.Step]:
    """scripts/kcage を root 所有の配備先へ複製する（作業ツリーのコードを sudo で実行しないため）。"""
    d = model.ROOT_HELPER_DIR
    return [
        _op(["install", "-d", "-m", "0755", "-o", "root", "-g", "root", d], "配備先を作る"),
        _op(["rm", "-rf", f"{d}/kcage"], "古い配備コピーを消す"),
        _op(["cp", "-r", opts.src_dir, f"{d}/kcage"], "scripts/kcage を複製する"),
        _op(
            [
                "find",
                f"{d}/kcage",
                "-name",
                "__pycache__",
                "-prune",
                "-exec",
                "rm",
                "-rf",
                "{}",
                "+",
            ],
            "キャッシュを除く",
        ),
        _op(["chown", "-R", "root:root", f"{d}/kcage"], "所有者を root にする"),
        _op(
            ["find", f"{d}/kcage", "-type", "d", "-exec", "chmod", "0755", "{}", "+"],
            "ディレクトリを 0755 にする",
        ),
        _op(
            ["find", f"{d}/kcage", "-type", "f", "-exec", "chmod", "0644", "{}", "+"],
            "ファイルを 0644 にする",
        ),
        model.FilePut(
            where="host", path=HELPER_ENTRY, mode="0755", owner="root:root", content=HELPER_SCRIPT
        ),
    ]


def sudoers_steps(opts: Opts) -> list[model.Step]:
    """検証（visudo -cf）に通ってから置く。途中のファイルは sudoers.d の無視される名前（先頭が .）にする。"""
    final = f"{SUDOERS_DIR}/kcage-{opts.user}"
    tmp = f"{SUDOERS_DIR}/.kcage-{opts.user}.new"
    return [
        model.FilePut(
            where="host", path=tmp, mode="0440", owner="root:root", content=opts.sudoers_text
        ),
        _op(["visudo", "-cf", tmp], "sudoers の雛形を検証する（失敗したら置かない）"),
        _op(["mv", "-f", tmp, final], "検証済みの雛形を置く"),
    ]


def plan(opts: Opts) -> model.Plan:
    st = opts.state
    steps: list[model.Step] = []
    if opts.update:
        steps += deploy_steps(opts)
        return model.Plan(verb="setup-update", box="", steps=tuple(steps))
    if not st.incus_installed:
        steps.append(_op(["apt-get", "install", "-y", "incus"], "Incus を導入する（Ubuntu 標準）"))
    if not st.incus_initialized:
        steps.append(_op(["incus", "admin", "init", "--minimal"], "Incus を初期化する"))
    gid = opts.uid if opts.gid is None else opts.gid
    for present, name, ident in (
        (st.subuid_has, "subuid", opts.uid),
        (st.subgid_has, "subgid", gid),
    ):
        if not present:
            line = subid_line(ident)
            f = f"/etc/{name}"
            steps.append(
                _op(
                    ["sh", "-c", f"grep -qxF {line} {f} || echo {line} >> {f}"],
                    f"{f} に {line} を足す",
                )
            )
    steps += deploy_steps(opts)
    steps.append(
        _op(
            ["install", "-d", "-m", "0755", "-o", "root", "-g", "root", CONF_DIR],
            f"{CONF_DIR} を作る",
        )
    )
    if not st.policy_exists:
        steps.append(
            model.FilePut(
                where="host",
                path=model.POLICY_PATH,
                mode="0644",
                owner="root:root",
                content=POLICY_TEMPLATE,
            )
        )
    steps += opts.net_steps
    steps += sudoers_steps(opts)
    return model.Plan(verb="setup", box="", steps=tuple(steps))


def warnings(opts: Opts, *, net_available: bool = True) -> list[str]:
    out: list[str] = []
    if opts.state.user_in_incus_admin:
        out.append(
            f"{opts.user} が incus-admin に入っている。Incus の管理権限をホストの pi に渡さないため、外すこと: "
            f"gpasswd -d {opts.user} incus-admin"
        )
    if not net_available:
        out.append(
            "kcage.net が見つからない。nat モードの host 側の準備（FORWARD の許可）は入らない"
        )
    return out


NEXT_STEPS = (
    "次: kcage template（箱の元のテンプレートを作る。初回のみ。パスワードを尋ねる）"
    " → リポジトリの中で `kcage register` → `kcage up` → `kcage selftest`"
)


def describe(p: model.Plan) -> list[str]:
    lines = []
    for i, s in enumerate(p.steps, 1):
        if isinstance(s, model.Op):
            lines.append(f"{i:2d}. {s.desc}: {' '.join(s.argv)}")
        elif isinstance(s, model.FilePut):
            lines.append(f"{i:2d}. ファイルを置く {s.path} ({s.owner} {s.mode})")
        else:
            lines.append(f"{i:2d}. {s}")
    return lines


# ---- 実行層（薄い。試験は計画で行う） ----


def execute(
    p: model.Plan,
    *,
    run: Callable[[Sequence[str]], int],
    put: Callable[[model.FilePut], None],
    remove: Callable[[str], None],
) -> int:
    """計画の順に実行する。失敗で止め、途中のファイル（.new）を消す。戻り値は終了コード。"""
    for s in p.steps:
        if isinstance(s, model.Op):
            if s.where != "host":
                continue
            rc = run(s.argv)
            if rc != 0 and s.check:
                _cleanup(p, remove)
                print(f"失敗（rc={rc}）: {s.desc}", file=sys.stderr)
                return rc
        elif isinstance(s, model.FilePut):
            put(s)
    return 0


def _cleanup(p: model.Plan, remove: Callable[[str], None]) -> None:
    for s in p.steps:
        if isinstance(s, model.FilePut) and s.path.endswith(".new"):
            remove(s.path)


def _put_file(fp: model.FilePut) -> None:
    if fp.content is None:
        raise ValueError(f"内容の無い FilePut は置けない: {fp.path}")
    path = Path(fp.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, int(fp.mode, 8))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(fp.content)
    os.chmod(path, int(fp.mode, 8))
    user, _, group = fp.owner.partition(":")
    shutil.chown(path, user, group or None)


def _remove(path: str) -> None:
    Path(path).unlink(missing_ok=True)


def _run(argv: Sequence[str]) -> int:
    return subprocess.run(list(argv), check=False).returncode


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def gather_state(user: str, uid: int, gid: int | None = None) -> State:
    line = subid_line(uid)
    gline = subid_line(uid if gid is None else gid)
    initialized = False
    if shutil.which("incus"):
        initialized = (
            subprocess.run(
                ["incus", "network", "show", model.INCUS_BRIDGE], capture_output=True, check=False
            ).returncode
            == 0
        )
    try:
        members = grp.getgrnam("incus-admin").gr_mem
    except KeyError:
        members = []
    return State(
        incus_installed=shutil.which("incus") is not None,
        incus_initialized=initialized,
        subuid_has=line in _read("/etc/subuid").splitlines(),
        subgid_has=gline in _read("/etc/subgid").splitlines(),
        policy_exists=Path(model.POLICY_PATH).exists(),
        user_in_incus_admin=user in members,
    )


def _net_steps() -> tuple[tuple[model.Step, ...], bool]:
    """W2 の net が host 側の準備を返すなら足す（遅延 import。無ければ警告だけ）。"""
    try:
        from kcage import net
    except ImportError:
        return (), False
    fn = getattr(net, "plan_host_setup", None) or getattr(net, "host_setup_plan", None)
    if fn is None:
        return (), False
    steps: Iterable[model.Step] = fn()
    return tuple(steps), True


def _sudoers_text(user: str) -> str:
    from kcage import root_helper  # W1a

    return root_helper.sudoers_snippet(user)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kcage setup", description="ホストの初期設定（root）")
    ap.add_argument("--dry-run", action="store_true", help="何もせず、やることを表示する")
    ap.add_argument("--update", action="store_true", help="root 所有の配備コピーだけを更新する")
    ap.add_argument("--user", help="対象のユーザー（省略時は SUDO_USER）")
    args = ap.parse_args(list(argv) if argv is not None else None)

    user = args.user or os.environ.get("SUDO_USER") or ""
    if not user or user == "root":
        print(
            "対象のユーザーが決まらない。一般ユーザーから sudo で実行するか --user を指定する",
            file=sys.stderr,
        )
        return 2
    if not args.dry_run and os.geteuid() != 0:
        print("root で実行する: kcage setup（sudo がパスワードを尋ねる）", file=sys.stderr)
        return 2
    uid = pwd.getpwnam(user).pw_uid
    raw_gid = os.environ.get("SUDO_GID", "")
    gid = (
        int(raw_gid)
        if raw_gid.isascii() and raw_gid.isdigit() and 1 <= int(raw_gid) <= 65535
        else uid
    )
    net_steps, net_ok = _net_steps()
    opts = Opts(
        user=user,
        uid=uid,
        gid=gid,
        src_dir=str(Path(__file__).resolve().parent),
        state=gather_state(user, uid, gid),
        sudoers_text=_sudoers_text(user),
        update=args.update,
        net_steps=net_steps,
    )
    p = plan(opts)
    for w in warnings(opts, net_available=net_ok):
        print(f"警告: {w}", file=sys.stderr)
    if args.dry_run:
        print("\n".join(describe(p)))
        return 0
    rc = execute(p, run=_run, put=_put_file, remove=_remove)
    if rc == 0:
        print("\n".join(describe(p)))
        print(NEXT_STEPS)
    return rc


if __name__ == "__main__":
    sys.exit(main())

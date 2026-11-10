"""kcage の導入物を戻す（root で、人が実行する。kcage uninstall の本体）。

構造は setup.py を踏襲する。計画（plan）は純粋な関数で、ホストの状態は State として呼び出し側が集める。
root で実行されるため、破壊の範囲は定数の許可リスト（allowed_paths）に限る。
破壊の前に preflight で全体を検査し、1 つでも満たさなければ何も実行しない。
Incus 本体（apt のパッケージ）・incus-admin グループ・`incus admin init` の結果は消さない（案内だけ出す）。
手順全体はトランザクションではない（途中で失敗したら、済んだ手順を表示して止まる）。
"""

from __future__ import annotations

import argparse
import errno
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ""):  # スクリプトとして実行されたとき（scripts/ を import の根にする）
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from kcage import trust as _trust

    try:  # 配備の根（import 経路に足すディレクトリ全体）が root 所有・書き込み不可・リンク無しでなければ、何もせず終わる
        _trust.check_tree(str(Path(__file__).resolve().parents[1]))
    except (_trust.TrustError, OSError) as _exc:
        print(f"kcage uninstall: 実行元が信頼できない: {_exc}", file=sys.stderr)
        sys.exit(2)

from kcage import model, net, setup, trust
from kcage import plan as box_plan

TEMPLATE_ALIAS = "kcage-template"
NONET_PROFILE = net.NONET_PROFILE
SUDOERS_DIR = setup.SUDOERS_DIR
SUBID_FILES = ("/etc/subuid", "/etc/subgid")
USER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,31}$")
BOX_NAME_RE = re.compile(r"^kcage-[A-Za-z0-9][A-Za-z0-9-]*$")
UNIT_RE = re.compile(r"^kcage-broker-[A-Za-z0-9._-]+\.service$")
MOUNTINFO = "/proc/self/mountinfo"

# 子プロセスの環境（利用者の PATH・INCUS_* などを継承しない）
CHILD_ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
}

# 実行層が消してよいディレクトリ・ファイル（固定）。sudoers は利用者名から作るので、別に検証する
FIXED_REMOVE_PATHS = (
    model.ROOT_HELPER_DIR,
    model.BROKER_HOST_DIR,
    setup.CONF_DIR,
    net.FORWARD_UNIT_PATH,
)

NOTES = """Incus 本体は消していない。不要なら、自分で次を実行する（ほかの用途で使っていないことを確かめてから）:
  sudo apt-get purge incus      # Incus 本体。/var/lib/incus の箱・画像・ストレージも消える
  sudo groupdel incus-admin     # incus-admin グループ（作られていて、誰も使わないとき）"""


def build_notes(p: model.Plan, *, keep_policy: bool, drop_subid: bool) -> str:
    """終わりの案内。実行した計画とフラグから作る（実際にやったことと食い違わせない）。"""
    lines = [NOTES]
    dropped = any(isinstance(s, SubidDrop) for s in p.steps)
    if dropped:
        lines.append("subuid/subgid の kcage 用の行を消した。")
    elif drop_subid:
        lines.append("subuid/subgid に kcage 用の行は無かった。")
    else:
        lines.append("subuid/subgid の行は残した（`--drop-subid` で消せる）。")
    if keep_policy:
        lines.append("許可表は /etc/kcage に残した（再導入しても引き続き使う）。")
    else:
        lines.append("許可表も消した（再導入では作り直す）。")
    if any(isinstance(s, Remove) and s.path == model.ROOT_HELPER_DIR for s in p.steps):
        lines.append("配備コピーを消した。再導入は `kcage init`。")
    return "\n".join(lines)


class UninstallError(Exception):
    pass


@dataclass(frozen=True)
class Remove:
    """許可リストのパスを消す。recursive=True はディレクトリだけ、False は通常ファイルだけ。"""

    path: str
    desc: str
    recursive: bool = False


@dataclass(frozen=True)
class SubidDrop:
    """subuid / subgid から、完全一致の 1 行だけを取り除く。"""

    path: str
    line: str
    desc: str


@dataclass(frozen=True)
class LabelGuard:
    """箱を消す直前に、ラベルが残っているかを再確認する（空なら全体を中止する）。"""

    box: str
    desc: str


Step = model.Op | Remove | SubidDrop | LabelGuard


@dataclass(frozen=True)
class State:
    """ホストの現在の状態（実行層が集める）。計画はこれだけを見て冪等にする。"""

    boxes: tuple[str, ...] = ()  # 接頭辞 kcage- かつラベルつきの箱
    broker_units: tuple[str, ...] = ()
    template_image: bool = False
    nonet_profile: bool = False
    forward_unit: bool = False
    forward_del: bool = False
    sudoers: bool = False
    helper_dir: bool = False
    run_dir: bool = False
    conf_dir: bool = False
    subuid_has: bool = False
    subgid_has: bool = False


@dataclass(frozen=True)
class Opts:
    user: str
    uid: int
    gid: int | None = None
    state: State = field(default_factory=State)
    keep_policy: bool = False
    drop_subid: bool = False


def sudoers_path(user: str) -> str:
    if not USER_RE.fullmatch(user) or user == "root":
        raise UninstallError(f"ユーザー名の形が不正: {user!r}")
    return f"{SUDOERS_DIR}/kcage-{user}"


def allowed_paths(user: str) -> frozenset[str]:
    """消してよいパスの全体。ここに無いものは、実行の直前に拒否する。"""
    return frozenset((*FIXED_REMOVE_PATHS, sudoers_path(user)))


def _op(argv: Sequence[str], desc: str, *, check: bool = True) -> model.Op:
    return model.Op(where="host", argv=tuple(argv), desc=desc, check=check)


def plan(opts: Opts) -> model.Plan:
    """順序は setup の逆。すべて冪等（状態に無いものは手順にしない）。root 所有の配備コピーは最後に消す。"""
    st = opts.state
    steps: list[Step] = []
    # a. ブローカーと箱（止められなければ以降を実行しない）
    for unit in st.broker_units:
        if not UNIT_RE.fullmatch(unit):
            raise UninstallError(f"ブローカーのユニット名の形が不正: {unit!r}")
        steps.append(_op(["systemctl", "stop", unit], f"ブローカーを止める: {unit}"))
        steps.append(
            _op(["systemctl", "reset-failed", unit], f"失敗の記録を消す: {unit}", check=False)
        )
    for box in st.boxes:
        if not BOX_NAME_RE.fullmatch(box):
            raise UninstallError(f"箱の名前の形が不正: {box!r}")
        steps.append(LabelGuard(box, f"箱のラベルを再確認する: {box}"))
        steps.append(_op(["incus", "delete", "--force", box], f"箱を消す: {box}"))
    # b. テンプレートの画像・プロファイル
    if st.template_image:
        steps.append(_op(["incus", "image", "delete", TEMPLATE_ALIAS], "テンプレートの画像を消す"))
    if st.nonet_profile:
        steps.append(_op(["incus", "profile", "delete", NONET_PROFILE], "kcage-nonet を消す"))
    # c. kcage-forward と DOCKER-USER の規則
    if st.forward_unit or st.forward_del:
        td = net.host_teardown_plan()
        steps.append(td[0])  # systemctl disable --now（check=False）
        if st.forward_del:
            steps.append(td[1])  # コメントつきの規則だけを削除
        steps.append(Remove(net.FORWARD_UNIT_PATH, "kcage-forward のユニットを消す"))
        steps.append(td[3])  # daemon-reload
    # d. sudoers（利用者名から作るのはこの 1 ファイルだけ）
    if st.sudoers:
        steps.append(Remove(sudoers_path(opts.user), "sudoers の雛形を消す"))
    # e. ソケットの置き場・許可表
    if st.run_dir:
        steps.append(Remove(model.BROKER_HOST_DIR, "ブローカーのソケットの置き場を消す", True))
    if st.conf_dir and not opts.keep_policy:
        steps.append(Remove(setup.CONF_DIR, "許可表（/etc/kcage）を消す", recursive=True))
    # f. subuid / subgid（--drop-subid のときだけ。setup が足した行と完全一致する行だけ）
    if opts.drop_subid:
        gid = opts.uid if opts.gid is None else opts.gid
        for present, path, ident in (
            (st.subuid_has, SUBID_FILES[0], opts.uid),
            (st.subgid_has, SUBID_FILES[1], gid),
        ):
            if present:
                line = setup.subid_line(ident)
                steps.append(SubidDrop(path, line, f"{path} から {line} を取り除く"))
    # g. root 所有の配備コピーは最後（途中で失敗しても、再実行の入口が残る）
    if st.helper_dir:
        steps.append(Remove(model.ROOT_HELPER_DIR, "root 所有の配備コピーを消す", recursive=True))
    allowed = allowed_paths(opts.user)
    for s in steps:
        if isinstance(s, Remove) and s.path not in allowed:
            raise UninstallError(f"許可リストに無いパスは消せない: {s.path}")
    return model.Plan(verb="uninstall", box="", steps=tuple(steps))


def describe(p: model.Plan) -> list[str]:
    lines = []
    for i, s in enumerate(p.steps, 1):
        if isinstance(s, model.Op):
            lines.append(f"{i:2d}. {s.desc}: {' '.join(s.argv)}")
        elif isinstance(s, Remove):
            lines.append(f"{i:2d}. {s.desc}: {s.path}")
        else:
            lines.append(f"{i:2d}. {s.desc}")
    if not lines:
        lines.append("戻すものは無い（導入されていない）")
    return lines


def confirm(
    boxes: Sequence[str],
    *,
    yes: bool,
    input_fn: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
) -> bool:
    """箱の一覧を見せ、端末で yes と打たせる。--yes なら尋ねない。"""
    out("消す箱: " + (", ".join(boxes) if boxes else "なし"))
    if yes:
        return True
    try:
        return input_fn("kcage の導入物を消す。続けるなら yes と打つ: ").strip() == "yes"
    except EOFError:
        return False


# ---- 破壊の前の検査（preflight） ----


def _unescape_mount(field_: str) -> str:
    """mountinfo の 8 進エスケープ（\\040 など）を解く。"""
    raw = re.sub(
        rb"\\([0-7]{3})", lambda m: bytes([int(m.group(1), 8) & 0xFF]), os.fsencode(field_)
    )
    return os.fsdecode(raw)


def parse_mountinfo(data: bytes) -> list[str]:
    """マウントポイント（第 5 フィールド）の一覧。

    bytes のまま `\\n` で分け、ASCII の空白（0x20）区切りで解析する（U+2028・CR などで分けない）。
    形の崩れたレコードは、読み飛ばさず UninstallError にする（見落とすと再帰削除が越境し得るため）。
    """
    out = []
    for n, rec in enumerate(data.split(b"\n"), 1):
        if not rec:
            continue
        parts = rec.split(b" ")
        ok = (
            len(parts) >= 10
            and parts[0].isdigit()
            and parts[1].isdigit()
            and b"-" in parts[6:]
            and parts[4].startswith(b"/")
        )
        if not ok:
            raise UninstallError(f"mountinfo の {n} 行目を解析できない")
        out.append(_unescape_mount(os.fsdecode(parts[4])))
    return out


def read_mountpoints() -> list[str]:
    try:
        with open(MOUNTINFO, "rb") as f:
            return parse_mountinfo(f.read())
    except OSError as exc:
        raise UninstallError(f"マウントの一覧を読めない: {exc}") from exc


def mounts_at_or_under(path: str, mountpoints: Sequence[str]) -> list[str]:
    prefix = path.rstrip("/") + "/"
    return [m for m in mountpoints if m == path or m.startswith(prefix)]


def preflight(
    p: model.Plan,
    *,
    check: Callable[..., None] = trust.check_trusted,
    mountpoints: Callable[[], Sequence[str]] = read_mountpoints,
    lstat: Callable[[str], os.stat_result] = os.lstat,
) -> list[str]:
    """計画の全体を、実行の前に検査する。問題の一覧（空なら通過）。"""
    problems: list[str] = []

    def chk(path: str) -> None:
        try:
            check(path, allow_missing=True)
        except (trust.TrustError, OSError) as exc:
            problems.append(str(exc))

    mps: Sequence[str] | None = None
    for s in p.steps:
        if isinstance(s, Remove):
            chk(s.path)  # 対象とその祖先だけ（中身は利用者所有があり得る）
            try:
                mode = lstat(s.path).st_mode
            except OSError:
                mode = None  # 無ければ消す対象も無い
            if mode is not None:
                if s.recursive and not stat.S_ISDIR(mode):
                    problems.append(f"ディレクトリでないので再帰削除しない: {s.path}")
                elif not s.recursive and not stat.S_ISREG(mode):
                    problems.append(f"通常ファイルでないので消さない: {s.path}")
            if s.recursive:
                if mps is None:
                    try:
                        mps = mountpoints()
                    except UninstallError as exc:
                        problems.append(str(exc))
                        mps = ()
                for m in mounts_at_or_under(s.path, mps):
                    problems.append(f"マウントポイントを含むので再帰削除しない: {m}")
        elif isinstance(s, model.Op):
            if s.argv and s.argv[0].startswith("/"):
                chk(s.argv[0])  # 実行する削除スクリプト
        elif isinstance(s, SubidDrop):
            chk(s.path)
    return list(dict.fromkeys(problems))


# ---- 実行層（薄い。試験は計画で行う） ----


def drop_line(text: str, line: str) -> str:
    """完全一致の行だけを除く。ほかの行（ほかのユーザー）はそのまま。"""
    kept = [ln for ln in text.splitlines(keepends=True) if ln.rstrip("\r\n") != line]
    return "".join(kept)


def safe_remove(
    path: str,
    allowed: frozenset[str],
    *,
    recursive: bool = False,
    root_uid: int = 0,
    mountpoints: Callable[[], Sequence[str]] = read_mountpoints,
) -> None:
    """許可リスト・非シンボリックリンク・root 所有・種別・マウントを確かめてから消す。無ければ何もしない。"""
    if path not in allowed:
        raise UninstallError(f"許可リストに無いパス: {path}")
    if os.path.islink(path) or os.path.realpath(path) != path:
        raise UninstallError(f"シンボリックリンクを含むパスは消さない: {path}")
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    if st.st_uid != root_uid:
        raise UninstallError(f"root 所有でないので消さない: {path}")
    is_dir = stat.S_ISDIR(st.st_mode)
    if recursive and not is_dir:
        raise UninstallError(f"ディレクトリでないので再帰削除しない: {path}")
    if not recursive and (is_dir or not stat.S_ISREG(st.st_mode)):
        raise UninstallError(f"通常ファイルでないので消さない: {path}")
    if recursive:
        bad = mounts_at_or_under(path, mountpoints())
        if bad:
            raise UninstallError(f"マウントポイントを含むので消さない: {bad[0]}")
        shutil.rmtree(path)  # 中のシンボリックリンクは辿らず、リンク自体を消す
    else:
        os.unlink(path)


def _read_fd(fd: int) -> str:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks = []
    while True:
        b = os.read(fd, 65536)
        if not b:
            break
        chunks.append(b)
    return b"".join(chunks).decode("utf-8")


def _write_all(fd: int, data: bytes) -> None:
    """全 bytes を書き切る（短い write で不完全なファイルを置換しない）。進まなければ OSError。"""
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        if n <= 0:
            raise OSError(errno.EIO, "書き込みが進まない")
        view = view[n:]


def safe_drop_subid(
    path: str,
    line: str,
    *,
    root_uid: int = 0,
    allowed_files: Sequence[str] = SUBID_FILES,
    before_replace: Callable[[], None] | None = None,
) -> None:
    """開いた fd で検査・読込し、置換の直前に再読込して変化があれば中止する。"""
    if path not in allowed_files:
        raise UninstallError(f"対象外のファイル: {path}")
    try:
        # O_NONBLOCK: FIFO でも開く側が止まらない（種別の検査で拒否する）
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise UninstallError(f"シンボリックリンクは書き換えない: {path}") from exc
        raise
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise UninstallError(f"通常ファイルでない: {path}")
        if st.st_uid != root_uid:
            raise UninstallError(f"root 所有でない: {path}")
        if st.st_mode & 0o022:
            raise UninstallError(f"グループ・他人から書ける: {path}")
        text = _read_fd(fd)
        new = drop_line(text, line)
        if new == text:
            return
        tfd, tmp = tempfile.mkstemp(prefix=".kcage-", dir=os.path.dirname(path))
        try:
            try:
                _write_all(tfd, new.encode("utf-8"))
                os.fchown(tfd, st.st_uid, st.st_gid)
                os.fchmod(tfd, stat.S_IMODE(st.st_mode))
                os.fsync(tfd)
            finally:
                os.close(tfd)
            if before_replace is not None:
                before_replace()
            cur = os.stat(path, follow_symlinks=False)
            if (cur.st_ino, cur.st_dev) != (st.st_ino, st.st_dev) or _read_fd(fd) != text:
                raise UninstallError(f"検査の後で内容が変わったので中止した: {path}")
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    finally:
        os.close(fd)


def execute(
    p: model.Plan,
    *,
    run: Callable[[Sequence[str]], int],
    remove: Callable[[str, bool], None],
    drop: Callable[[str, str], None],
    label: Callable[[str], str],
) -> int:
    """計画の順に実行する。失敗で止め、済んだ手順を表示する。戻り値は終了コード。"""
    done: list[str] = []

    def fail(msg: str, rc: int) -> int:
        print(msg, file=sys.stderr)
        print(
            "手順全体はトランザクションではない。ここまでに済んだ手順:"
            + ("".join(f"\n  - {d}" for d in done) if done else " なし"),
            file=sys.stderr,
        )
        return rc

    for s in p.steps:
        if isinstance(s, model.Op):
            rc = run(s.argv)
            if rc != 0 and s.check:
                return fail(f"失敗（rc={rc}）: {s.desc}", rc)
        elif isinstance(s, LabelGuard):
            try:
                lab = label(s.box)
            except UninstallError as exc:
                return fail(f"中止: ラベルを確かめられない: {s.box}: {exc}", 1)
            if not lab.strip():
                return fail(f"中止: ラベルが無くなっている（kcage の箱ではない）: {s.box}", 1)
        elif isinstance(s, Remove):
            try:
                remove(s.path, s.recursive)
            except (UninstallError, OSError) as exc:
                return fail(f"失敗: {s.desc}: {exc}", 1)
        else:
            try:
                drop(s.path, s.line)
            except (UninstallError, OSError) as exc:
                return fail(f"失敗: {s.desc}: {exc}", 1)
        done.append(s.desc)
    return 0


def _run(argv: Sequence[str]) -> int:
    return subprocess.run(list(argv), check=False, env=dict(CHILD_ENV)).returncode


def _capture(argv: Sequence[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            env=dict(CHILD_ENV),
        )
    except FileNotFoundError:
        return 127, ""  # 実行ファイルが無い = 未導入
    except OSError as exc:
        raise UninstallError(f"起動できない: {argv[0]}: {exc}") from exc
    return proc.returncode, proc.stdout


def _label(box: str) -> str:
    rc, out = _capture(["incus", "config", "get", box, box_plan.LABEL_KEY])
    return out if rc == 0 else ""


def _read(path: str) -> str:
    """subuid/subgid を読む（--drop-subid のときだけ）。通常ファイルだけ、リンクは辿らない。"""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise UninstallError(f"読めない: {path}: {exc}") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise UninstallError(f"通常ファイルでない: {path}")
        return _read_fd(fd)
    except UnicodeDecodeError as exc:
        raise UninstallError(f"UTF-8 として読めない: {path}") from exc
    finally:
        os.close(fd)


def _csv_first_fields(out: str) -> list[str]:
    return [ln.split(",", 1)[0].strip() for ln in out.splitlines() if ln.strip()]


def _available(rc: int, what: str) -> bool:
    """rc 0 は応答あり、127 は未導入（続行）、それ以外は調べられないので止める。"""
    if rc == 127:
        return False
    if rc != 0:
        raise UninstallError(f"調査できない（rc={rc}）: {what}。何も消さずに終了する")
    return True


def gather_state(
    uid: int,
    gid: int,
    user: str,
    *,
    capture: Callable[[Sequence[str]], tuple[int, str]] = _capture,
    lexists: Callable[[str], bool] = os.path.lexists,
    read: Callable[[str], str] = _read,
    drop_subid: bool = False,
) -> State:
    boxes: list[str] = []
    rc, out = capture(["incus", "list", "--format", "csv", "-c", "n"])
    if _available(rc, "incus list"):
        for name in _csv_first_fields(out):
            if not name.startswith(model.BOX_NAME_PREFIX) or not BOX_NAME_RE.fullmatch(name):
                continue
            rc2, label = capture(["incus", "config", "get", name, box_plan.LABEL_KEY])
            if _available(rc2, f"incus config get {name}") and label.strip():
                boxes.append(name)  # 接頭辞だけでは消さない。ラベルでも確かめる
    units: list[str] = []
    rc, out = capture(
        ["systemctl", "list-units", "--all", "--plain", "--no-legend", "kcage-broker-*.service"]
    )
    if _available(rc, "systemctl list-units"):
        units = [
            ln.split()[0]
            for ln in out.splitlines()
            if ln.split() and UNIT_RE.fullmatch(ln.split()[0])
        ]
    rc, out = capture(["incus", "image", "alias", "list", "--format", "csv"])
    template = _available(rc, "incus image alias list") and TEMPLATE_ALIAS in _csv_first_fields(out)
    rc, out = capture(["incus", "profile", "list", "--format", "csv"])
    nonet = _available(rc, "incus profile list") and NONET_PROFILE in _csv_first_fields(out)
    subuid_has = subgid_has = False
    if drop_subid:  # 消さないときは subuid/subgid を読まない
        subuid_has = setup.subid_line(uid) in read(SUBID_FILES[0]).splitlines()
        subgid_has = setup.subid_line(gid) in read(SUBID_FILES[1]).splitlines()
    return State(
        boxes=tuple(boxes),
        broker_units=tuple(units),
        template_image=template,
        nonet_profile=nonet,
        forward_unit=lexists(net.FORWARD_UNIT_PATH),
        forward_del=lexists(net.FORWARD_DEL_SCRIPT),
        sudoers=lexists(sudoers_path(user)),
        helper_dir=lexists(model.ROOT_HELPER_DIR),
        run_dir=lexists(model.BROKER_HOST_DIR),
        conf_dir=lexists(setup.CONF_DIR),
        subuid_has=subuid_has,
        subgid_has=subgid_has,
    )


def resolve_caller(
    env: Mapping[str, str], getpwnam: Callable[[str], object] | None = None
) -> tuple[str, int, int]:
    """(user, uid, gid)。SUDO_USER・SUDO_GID は setup と同じ検証で読む。不正なら UninstallError。"""
    user = env.get("SUDO_USER", "")
    if not user or user == "root" or not USER_RE.fullmatch(user):
        raise UninstallError("sudo を使う一般ユーザーから実行する（SUDO_USER が無い・不正）")
    try:
        uid = (getpwnam or pwd.getpwnam)(user).pw_uid  # type: ignore[attr-defined]
    except KeyError as exc:
        raise UninstallError(f"ユーザーが見つからない: {user}") from exc
    raw = env.get("SUDO_GID", "")
    gid = int(raw) if raw.isascii() and raw.isdigit() and 1 <= int(raw) <= 65535 else uid
    return user, uid, gid


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    euid: int | None = None,
    gather: Callable[..., State] = gather_state,
    run: Callable[[Sequence[str]], int] = _run,
    input_fn: Callable[[str], str] = input,
    root_uid: int = 0,
    preflight_fn: Callable[[model.Plan], list[str]] = preflight,
    label_fn: Callable[[str], str] = _label,
    mountpoints: Callable[[], Sequence[str]] = read_mountpoints,
) -> int:
    ap = argparse.ArgumentParser(prog="kcage uninstall", description="kcage の導入物を戻す（root）")
    ap.add_argument("--dry-run", action="store_true", help="何もせず、やることを表示する")
    ap.add_argument("--keep-policy", action="store_true", help="許可表（/etc/kcage）を残す")
    ap.add_argument(
        "--drop-subid",
        action="store_true",
        help="subuid/subgid の kcage 用の行も消す（既定は残す）",
    )
    ap.add_argument("--yes", action="store_true", help="確認を省く")
    args = ap.parse_args(list(argv) if argv is not None else None)

    env = os.environ if env is None else env
    if (os.geteuid() if euid is None else euid) != 0:
        print("root で実行する: kcage uninstall（sudo がパスワードを尋ねる）", file=sys.stderr)
        return 2
    try:
        user, uid, gid = resolve_caller(env)
        allowed = allowed_paths(user)
        st = gather(uid, gid, user, drop_subid=args.drop_subid)
        p = plan(
            Opts(
                user=user,
                uid=uid,
                gid=gid,
                state=st,
                keep_policy=args.keep_policy,
                drop_subid=args.drop_subid,
            )
        )
    except UninstallError as exc:
        print(f"kcage uninstall: {exc}", file=sys.stderr)
        return 2
    problems = preflight_fn(p)
    if args.dry_run:
        print("\n".join(describe(p)))
        if problems:
            print("事前検査: 失敗（実行すると何もせず終了する）")
            for msg in problems:
                print(f"  - {msg}")
        else:
            print("事前検査: 通過")
        print(build_notes(p, keep_policy=args.keep_policy, drop_subid=args.drop_subid))
        return 2 if problems else 0
    if problems:
        print("kcage uninstall: 事前検査に失敗した。何も実行していない:", file=sys.stderr)
        for msg in problems:
            print(f"  - {msg}", file=sys.stderr)
        return 2
    if not confirm(st.boxes, yes=args.yes, input_fn=input_fn):
        print("中止した（何も消していない）")
        return 1
    rc = execute(
        p,
        run=run,
        remove=lambda path, recursive: safe_remove(
            path, allowed, recursive=recursive, root_uid=root_uid, mountpoints=mountpoints
        ),
        drop=lambda path, line: safe_drop_subid(path, line, root_uid=root_uid),
        label=label_fn,
    )
    if rc == 0:
        print("\n".join(describe(p)))
        print(build_notes(p, keep_policy=args.keep_policy, drop_subid=args.drop_subid))
    return rc


if __name__ == "__main__":
    sys.exit(main())

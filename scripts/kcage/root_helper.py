"""kcage-root: root 所有の補助。sudo で呼ばれ、許可表（HostPolicy）の範囲でだけ Incus を操作する。

方針（契約 D1・C13）:
- 呼び出し側が渡せるのは verb と repo id（exec は箱の中のコマンドも）だけ。デバイス・設定は渡せない。
- 計画は呼び出し側から受け取らず、ここで kcage.toml（要求）と許可表から再計算する。
- SUDO_UID が許可表の uid と一致しないリポジトリは操作できない。
- 秘密は実行時に解決し、argv・ログ・例外メッセージに出さない。出力は Op の desc だけ。
- このファイルは root 所有の配備コピー（model.ROOT_HELPER_DIR）から実行する。

終了コード: 0 成功 / 1 拒否・失敗 / 2 引数の誤り（未知の verb・余計な引数・repo id の形違い）。
"""

from __future__ import annotations

import difflib
import os
import posixpath
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import IO, Any, Protocol

from kcage import config, distcheck, gitmeta, model, plan, policy, template
from kcage.config import ConfigError, Fs, RealFs
from kcage.plan import PlanError
from kcage.policy import REPO_ID_RE, PolicyError

VERBS = ("register", "up", "stop", "rm", "exec", "ls", "snap", "selftest", "template")
PASSWORDLESS = frozenset({"up", "stop", "exec", "ls"})

_USER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,31}$")
_DIR_RE = re.compile(r"^/[A-Za-z0-9/_.-]*$")
_MODE_RE = re.compile(r"^0?[0-7]{3,4}$")
_OWNER_RE = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_-]*):([A-Za-z0-9_][A-Za-z0-9_-]*)$")
_PORT_RE = re.compile(r"^(\d{1,5})(?:-(\d{1,5}))?$")
_HOST_FILE_ROOTS = (model.BROKER_HOST_DIR + "/",)
_MIN_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
_TERM_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
_REGISTER_FLAGS = {"--gpu"}
_REGISTER_VALUES = {
    "--path",
    "--data-root",
    "--port",
    "--broker",
    "--network",
    "--idmap",
    "--proxy-upstream",
    "--subnet",
}


class UsageError(ValueError):
    """引数の誤り（終了コード 2）。"""


class HelperError(RuntimeError):
    """拒否・実行の失敗（終了コード 1）。メッセージに秘密・argv を含めない。"""


class Runner(Protocol):
    def run(
        self, argv: Sequence[str], *, stdin: bytes | None = None, check: bool = True
    ) -> int: ...
    def capture(self, argv: Sequence[str]) -> tuple[int, str]: ...


class SubprocessRunner:
    """subprocess の実体。shell=False・環境は最小の PATH（と端末の種類）だけ。"""

    @staticmethod
    def _env() -> dict[str, str]:
        env = {"PATH": _MIN_PATH}
        term = os.environ.get("TERM", "")
        if _TERM_RE.match(term):
            env["TERM"] = term
        return env

    def run(self, argv: Sequence[str], *, stdin: bytes | None = None, check: bool = True) -> int:
        p = subprocess.run(list(argv), input=stdin, env=self._env(), shell=False, check=False)
        if check and p.returncode != 0:
            raise HelperError(f"操作が失敗した（終了コード {p.returncode}）")
        return p.returncode

    def capture(self, argv: Sequence[str]) -> tuple[int, str]:
        p = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=self._env(),
            shell=False,
            check=False,
        )
        return p.returncode, p.stdout.decode("utf-8", "replace")


# ---------------------------------------------------------------- 引数


@dataclass(frozen=True)
class Request:
    verb: str
    repo_id: str | None = None
    exec_argv: tuple[str, ...] = ()
    options: Mapping[str, Any] = field(default_factory=dict)


def _check_id(s: str) -> str:
    if not REPO_ID_RE.match(s):
        raise UsageError("repo id の形が不正")
    return s


def _parse_register(rest: Sequence[str]) -> dict[str, Any]:
    opts: dict[str, Any] = {"data_roots": [], "ports": [], "brokers": [], "gpu": False}
    single = {"--path": "path", "--network": "network", "--idmap": "idmap"}
    single |= {"--proxy-upstream": "proxy_upstream", "--subnet": "subnet"}
    i = 0
    while i < len(rest):
        flag = rest[i]
        if flag in _REGISTER_FLAGS:
            opts["gpu"] = True
            i += 1
            continue
        if flag not in _REGISTER_VALUES or i + 1 >= len(rest):
            raise UsageError("register の引数が不正")
        val = rest[i + 1]
        i += 2
        if flag == "--data-root":
            opts["data_roots"].append(val)
        elif flag == "--broker":
            opts["brokers"].append(val)
        elif flag == "--port":
            m = _PORT_RE.match(val)
            if not m:
                raise UsageError("--port は N または LO-HI")
            lo = int(m.group(1))
            hi = int(m.group(2) or lo)
            opts["ports"].append(model.PortRange(lo, hi))
        else:
            key = single[flag]
            if key in opts:
                raise UsageError(f"{flag} が重複")
            opts[key] = val
    if "path" not in opts:
        raise UsageError("register には --path が必要")
    return opts


def _parse_template(rest: Sequence[str]) -> dict[str, Any]:
    """template [--dist <絶対パス>] [--pi-version <版>]。repo id は取らない。"""
    opts: dict[str, Any] = {"dist": None, "pi_version": None}
    keys = {"--dist": "dist", "--pi-version": "pi_version"}
    i = 0
    while i < len(rest):
        flag = rest[i]
        if flag not in keys or i + 1 >= len(rest) or opts[keys[flag]] is not None:
            raise UsageError("template の引数が不正")
        opts[keys[flag]] = rest[i + 1]
        i += 2
    if opts["dist"] is not None and not opts["dist"].startswith("/"):
        raise UsageError("--dist は絶対パス")
    if opts["pi_version"] is not None and not template.PI_VERSION_RE.match(opts["pi_version"]):
        raise UsageError("--pi-version の形が不正")
    return opts


def parse_args(argv: Sequence[str]) -> Request:
    """引数を厳格に解釈する。形違い・未知の引数は UsageError。"""
    args = list(argv)
    if not args or args[0] not in VERBS:
        raise UsageError("未知の verb")
    verb, rest = args[0], args[1:]
    if verb == "template":
        return Request(verb, options=_parse_template(rest))
    if verb == "ls":
        if len(rest) > 1:
            raise UsageError("ls の引数が多すぎる")
        return Request(verb, _check_id(rest[0]) if rest else None)
    if not rest:
        raise UsageError("repo id が必要")
    rid, rest = _check_id(rest[0]), rest[1:]
    if verb == "exec":
        if len(rest) < 2 or rest[0] != "--" or any("\x00" in a for a in rest[1:]):
            raise UsageError("exec は repo id の後に -- とコマンドが必要")
        return Request(verb, rid, tuple(rest[1:]))
    if verb == "register":
        return Request(verb, rid, options=_parse_register(rest))
    if rest:
        raise UsageError(f"{verb} に余計な引数がある")
    return Request(verb, rid)


# ---------------------------------------------------------------- 実行


def _ids(owner: str) -> tuple[str, str]:
    m = _OWNER_RE.match(owner)
    if not m:
        raise HelperError("FilePut の owner の形が不正")
    names = {"root": "0", model.BOX_USER: "1000"}
    return tuple(names.get(x, x) for x in m.groups())  # type: ignore[return-value]


def _default_netplanner(mode: str, cfg: model.BoxConfig) -> model.NetPlan:
    try:
        from kcage import net
    except ImportError as e:
        raise PlanError("kcage.net が無い（ネットワーク計画を作れない）") from e
    return net.plan(cfg)  # mode は cfg.network（解決済み）


def _default_brokerplanner(
    kind: str, cfg: model.BoxConfig, policy: model.RepoPolicy
) -> model.BrokerPlan | None:
    try:
        from kcage import broker
    except ImportError:
        return None  # ブローカー未実装: 空として扱う
    return broker.plan(kind, cfg, policy)


def _default_secret_resolver(ref: model.SecretRef, caller_uid: int | None) -> str:
    from kcage import resolver  # 遅延 import（無ければ ImportError → HelperError）

    return resolver.resolve(ref, caller_uid=caller_uid)


class _Executor:
    def __init__(
        self,
        runner: Runner,
        out: IO[str],
        resolver: Callable[[model.SecretRef, int | None], str],
        caller_uid: int | None,
        sleep: Callable[[float], None],
    ) -> None:
        self.runner, self.out, self.resolver = runner, out, resolver
        self.caller_uid, self.sleep = caller_uid, sleep

    def _secret(self, ref: model.SecretRef) -> bytes:
        try:
            return self.resolver(ref, self.caller_uid).encode("ascii")
        except ImportError as e:
            raise HelperError("秘密の解決器が無い") from e

    def execute(self, p: model.Plan) -> int:
        rc = 0
        for step in p.steps:
            if isinstance(step, model.DeviceSpec):
                argv = plan.device_to_argv(p.box, step)  # 実行時にもう一度、最後の関門を通す
                print(f"[kcage] デバイス {step.name} ({step.type}) を追加", file=self.out)
                self.runner.run(argv)
            elif isinstance(step, model.FilePut):
                self._put(p.box, step)
            else:
                rc = self._op(p, step)
        return rc

    def _op(self, p: model.Plan, op: model.Op) -> int:
        argv = tuple(op.argv)
        if not argv or not all(isinstance(a, str) for a in argv):
            raise HelperError("Op の argv が不正")
        if op.where == "box":
            wait = argv == ("true",)
            argv = ("incus", "exec", p.box, "--", *argv)
        else:
            wait = False
            if (
                argv[0] == "incus"
                and tuple(argv[1:3]) in {("config", "device"), ("profile", "device")}
                and tuple(argv)
                not in plan.ALLOWED_PROFILE_OPS  # NIC なしのプロファイル用の allowlist
            ):
                raise HelperError("incus のデバイス操作は DeviceSpec 経由のみ")
        stdin = self._secret(op.stdin_secret) if op.stdin_secret is not None else None
        if p.verb != "exec":
            print(f"[kcage] {op.desc}", file=self.out)
        if wait:
            for _ in range(30):
                if self.runner.run(argv, check=False) == 0:
                    return 0
                self.sleep(1)
            raise HelperError("箱の起動待ちが時間切れ")
        return self.runner.run(argv, stdin=stdin, check=op.check and p.verb != "exec")

    def _put(self, box: str, fp: model.FilePut) -> None:
        if (fp.content is None) == (fp.secret is None):
            raise HelperError("FilePut は content か secret のどちらか一方が必要")
        if not _MODE_RE.match(fp.mode) or ".." in fp.path.split("/") or not fp.path.startswith("/"):
            raise HelperError("FilePut の mode・path が不正")
        data = fp.content.encode() if fp.content is not None else self._secret(fp.secret)  # type: ignore[arg-type]
        user, group = _ids(fp.owner)
        print(f"[kcage] ファイルを配置: {fp.path}", file=self.out)
        if fp.where == "box":
            argv = (
                "incus", "file", "push", "-", f"{box}{fp.path}", "--create-dirs",
                "--mode", fp.mode, "--uid", user, "--gid", group,
            )  # fmt: skip
        else:
            if not fp.path.startswith(_HOST_FILE_ROOTS):
                raise HelperError("ホスト側の FilePut は /run/kcage-broker/ の下だけ")
            argv = ("install", "-D", "-m", fp.mode, "-o", user, "-g", group, "/dev/stdin", fp.path)
        self.runner.run(argv, stdin=data)


def _status(runner: Runner, box: str) -> tuple[bool, bool, str | None]:
    """(存在, 起動中, 所属ラベル)。"""
    rc, out = runner.capture(("incus", "list", f"^{box}$", "--format", "csv", "-c", "s"))
    state = out.strip()
    if rc != 0 or not state:
        return False, False, None
    rc2, label = runner.capture(("incus", "config", "get", box, plan.LABEL_KEY))
    return True, state.upper() == "RUNNING", label.strip() if rc2 == 0 else None


def _selftest_plan(cfg: model.BoxConfig) -> model.Plan:
    """箱の中から、主ディストロ側の管理・秘密に届かないことの最小の確認（実体の確認は親の e2e）。"""
    home = model.BOX_HOME
    repo = shlex.quote(cfg.repo_path)
    git = posixpath.join(cfg.repo_path, ".git")
    # pin を足したとき（.git が実ディレクトのとき）だけ検査する
    pinned = any(m.source == git and m.path == git and not m.readonly for m in cfg.mounts)
    # .git が pin（マウントポイント）であること。see docs/spec/sandbox/incus-box.md（.git の差し替え）
    pin = f'cd {repo} && grep -qF " $(pwd)/.git " /proc/self/mountinfo'
    # mv が成功してしまったら元へ戻して失敗にする
    mv = (
        f"cd {repo} && if mv .git .git.kcage-selftest 2>/dev/null; "
        "then mv .git.kcage-selftest .git; exit 1; else exit 0; fi"
    )
    git_checks = (
        (("sh", "-c", pin), ".git がマウントポイント（pin）"),
        (("sh", "-c", mv), ".git を移動できない"),
    )
    checks = (
        *(git_checks if pinned else ()),
        (("test", "!", "-e", "/var/lib/incus/unix.socket"), "Incus の管理ソケットが見えない"),
        (("test", "!", "-e", f"{home}/.ssh"), "~/.ssh が無い"),
        (("test", "!", "-e", f"{home}/.aws"), "~/.aws が無い"),
        (("test", "!", "-e", f"{home}/.config/kcage"), "~/.config/kcage が無い"),
    )
    steps = tuple(model.Op("box", argv, desc) for argv, desc in checks)
    return model.Plan("selftest", cfg.name, steps)


def _atomic_write(path: str, text: str) -> None:
    d = os.path.dirname(path)
    os.makedirs(d, mode=0o755, exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.fchown(fd, 0, 0)
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.lexists(tmp):
            os.unlink(tmp)
        raise


def _tty_confirm(
    question: str,
    *,
    opener: Callable[..., Any] = open,
    stdin: IO[str] | None = None,
    stderr: IO[str] | None = None,
) -> bool:
    """人が端末で答える確認。/dev/tty を使い、開けないときは標準入力が端末のときだけそれを使う。

    パイプやファイルからは答えられない（自動化が y を流し込めない）。どちらも使えないときは、理由を示して中止する
    （黙って中止すると、プロンプトが見えないまま「中止しました」とだけ出て原因が分からない）。
    """
    err = stderr if stderr is not None else sys.stderr
    inp = stdin if stdin is not None else sys.stdin
    try:
        with opener("/dev/tty", "r+", encoding="utf-8") as tty:
            tty.write(question)
            tty.flush()
            return tty.readline().strip().lower() in ("y", "yes")
    except OSError as exc:
        reason = f"/dev/tty を開けない: {exc}"
    try:
        interactive = inp.isatty()
    except (OSError, ValueError, AttributeError):
        interactive = False
    if not interactive:
        print(f"端末で確認できないため中止する（{reason}。標準入力も端末ではない）", file=err)
        return False
    err.write(question)
    err.flush()
    return inp.readline().strip().lower() in ("y", "yes")


def _caller_uid(env: Mapping[str, str]) -> int:
    raw = env.get("SUDO_UID", "")
    if not raw.isdigit() or int(raw) < 1:
        raise HelperError("SUDO_UID が無い・不正（sudo 経由でのみ実行できる）")
    return int(raw)


def _caller_gid(env: Mapping[str, str], uid: int) -> int:
    """sudo が設定した SUDO_GID。無い・不正・範囲外なら uid にする（引数では指定できない）。"""
    raw = env.get("SUDO_GID", "")
    if raw.isascii() and raw.isdigit() and 1 <= int(raw) <= 65535 and raw == str(int(raw)):
        return int(raw)
    return uid


def _register(
    req: Request,
    *,
    uid: int,
    gid: int,
    policy_path: str,
    fs: Fs,
    out: IO[str],
    confirm: Callable[[str], bool],
    writer: Callable[[str, str], None],
) -> int:
    o = req.options
    repo_path = o["path"]
    if not repo_path.startswith("/") or not fs.isdir(repo_path) or fs.islink(repo_path):
        raise HelperError("--path は実在のディレクトリ（symlink 不可）の絶対パスが必要")
    if fs.stat_uid(repo_path) != uid:
        raise HelperError("--path の所有者が呼び出し元ではない")
    text = ""
    if fs.exists(policy_path):
        policy.check_file_safe(policy_path, fs=fs)
        text = fs.read_bytes(policy_path).decode("utf-8")
    try:
        block = policy.render_repo_block(
            req.repo_id or "",
            path=repo_path,
            data_roots=tuple(o["data_roots"]),
            ports=tuple(o["ports"]),
            brokers=tuple(o["brokers"]),
            gpu=o["gpu"],
            network=o.get("network"),
            proxy_upstream=o.get("proxy_upstream"),
            idmap=o.get("idmap", "user"),
            uid=uid,
            gid=gid,
            subnet=o.get("subnet"),
        )
        new_text = policy.add_repo(text, block)
    except PolicyError as e:
        raise HelperError(f"追記を作れない: {e}") from e
    # 追記後の許可表で、リポジトリが拒否リストに当たらないかを確かめる
    config.resolve(policy.parse(new_text), req.repo_id or "", model.RepoSpec(), fs)
    diff = difflib.unified_diff(
        text.splitlines(),
        new_text.splitlines(),
        "policy.toml (現在)",
        "policy.toml (提案)",
        lineterm="",
    )
    print("\n".join(diff), file=out)
    if not confirm("この内容を許可表へ追記しますか? [y/N] "):
        print("中止しました", file=out)
        return 1
    writer(policy_path, new_text)
    print("許可表を更新しました", file=out)
    return 0


def main(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    runner: Runner | None = None,
    policy_path: str = model.POLICY_PATH,
    fs: Fs | None = None,
    netplanner: Callable[[str, model.BoxConfig], model.NetPlan] | None = None,
    brokerplanner: Callable[[str, model.BoxConfig, model.RepoPolicy], model.BrokerPlan | None]
    | None = None,
    euid: int | None = None,
    stdout: IO[str] | None = None,
    stderr: IO[str] | None = None,
    confirm: Callable[[str], bool] | None = None,
    writer: Callable[[str, str], None] | None = None,
    sleep: Callable[[float], None] | None = None,
    secret_resolver: Callable[[model.SecretRef, int | None], str] | None = None,
    dist_checker: Callable[[str, int], str] | None = None,
    commondir_ops: gitmeta.CommondirOps | None = None,
) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    try:
        req = parse_args(argv)
        return _run(
            req,
            env=os.environ if env is None else env,
            runner=runner or SubprocessRunner(),
            policy_path=policy_path,
            fs=fs or RealFs(),
            netplanner=netplanner or _default_netplanner,
            brokerplanner=brokerplanner or _default_brokerplanner,
            euid=os.geteuid() if euid is None else euid,
            out=out,
            confirm=confirm or _tty_confirm,
            writer=writer or _atomic_write,
            sleep=sleep or time.sleep,
            resolver=secret_resolver or _default_secret_resolver,
            dist_checker=dist_checker or distcheck.validate_dist,
            commondir_ops=commondir_ops or gitmeta.RealOps(),
        )
    except UsageError as e:
        print(f"kcage-root: 引数が不正: {e}", file=err)
        return 2
    except (HelperError, PolicyError, ConfigError, PlanError) as e:
        print(f"kcage-root: 拒否・失敗: {e}", file=err)
        return 1
    except Exception as e:  # 想定外でも、値を含みうる詳細は出さない
        print(f"kcage-root: 想定外のエラー（{type(e).__name__}）", file=err)
        return 1


def _run(
    req: Request,
    *,
    env: Mapping[str, str],
    runner: Runner,
    policy_path: str,
    fs: Fs,
    netplanner: Callable[[str, model.BoxConfig], model.NetPlan],
    brokerplanner: Callable[[str, model.BoxConfig, model.RepoPolicy], model.BrokerPlan | None],
    euid: int,
    out: IO[str],
    confirm: Callable[[str], bool],
    writer: Callable[[str, str], None],
    sleep: Callable[[float], None],
    resolver: Callable[[model.SecretRef, int | None], str],
    dist_checker: Callable[[str, int], str] = distcheck.validate_dist,
    commondir_ops: gitmeta.CommondirOps | None = None,
) -> int:
    if euid != 0:
        raise HelperError("root 権限が必要（sudo 経由で実行する）")
    uid = _caller_uid(env)
    if req.verb == "register":
        return _register(
            req,
            uid=uid,
            gid=_caller_gid(env, uid),
            policy_path=policy_path,
            fs=fs,
            out=out,
            confirm=confirm,
            writer=writer,
        )

    policy.check_file_safe(policy_path, fs=fs)
    pol = policy.load(policy_path, fs=fs)

    if req.verb == "template":
        return _template(req, pol, uid, runner, out, resolver, sleep, dist_checker)

    if req.verb == "ls":
        mine = [r for r in pol.repos.values() if r.uid == uid and req.repo_id in (None, r.id)]
        if req.repo_id and not mine:
            raise HelperError("そのリポジトリは操作できない")
        for r in sorted(mine, key=lambda x: x.id):
            exists, running, _ = _status(runner, model.box_name(r.id))
            state = "RUNNING" if running else ("STOPPED" if exists else "-")
            print(f"{r.id}\t{state}", file=out)
        return 0

    rid = req.repo_id or ""
    rp = pol.repos.get(rid)
    if rp is None:
        raise HelperError("未登録の repo id")
    if rp.uid != uid:
        raise HelperError("他のユーザーのリポジトリは操作できない")

    # kcage.toml は要求。up 以外は、壊れていても止めない（stop・rm は常に実行できるように）
    try:
        spec = config.load_spec(rp.path, fs=fs)
        if req.verb == "up" and commondir_ops is not None:
            # 箱を新規に作る前に、.git/commondir を封じる（resolve が ro の重ねに加える）
            res = gitmeta.ensure_commondir(
                posixpath.join(rp.path, ".git"), uid, _caller_gid(env, uid), commondir_ops
            )
            if res == "created":
                print("[kcage] .git/commondir（中身 .）を作成", file=out)
        cfg = config.resolve(pol, rid, spec, fs)
    except ConfigError:
        if req.verb == "up":
            raise
        cfg = config.resolve(pol, rid, model.RepoSpec(), fs)

    brokers: list[model.BrokerPlan] = []
    for kind in cfg.brokers:
        bp = brokerplanner(kind, cfg, rp)
        if bp is not None:
            brokers.append(bp)

    exists, running, label = _status(runner, cfg.name)
    ex = _Executor(runner, out, resolver, uid, sleep)
    if req.verb == "up":
        net = netplanner(cfg.network, cfg)
        p = plan.plan_up(
            cfg,
            net,
            brokers,
            template=pol.template,
            exists=exists,
            running=running,
            existing_repo_label=label,
        )
        for r in p.routes:
            print(f"[kcage] 経路: {r.purpose} / {r.path}", file=out)
        return ex.execute(p) if p.steps else _noop(out)
    if exists and label != rid:
        raise HelperError("同名の箱が別のリポジトリのもの")
    if not exists:
        raise HelperError("箱が存在しない")
    if req.verb == "stop":
        return ex.execute(plan.plan_stop(cfg, brokers))
    if req.verb == "rm":
        return ex.execute(plan.plan_rm(cfg, brokers))
    if req.verb == "exec":
        return ex.execute(plan.plan_exec(cfg, req.exec_argv))
    if req.verb == "snap":
        step = model.Op("host", ("incus", "snapshot", "create", cfg.name), "スナップショットを作成")
        return ex.execute(model.Plan("snap", cfg.name, (step,)))
    if req.verb == "selftest":
        return ex.execute(_selftest_plan(cfg))
    raise UsageError("未知の verb")  # 到達しない（parse_args が検査済み）


def _template(
    req: Request,
    pol: model.HostPolicy,
    uid: int,
    runner: Runner,
    out: IO[str],
    resolver: Callable[[model.SecretRef, int | None], str],
    sleep: Callable[[float], None],
    dist_checker: Callable[[str, int], str],
) -> int:
    """テンプレートの作成。許可表の template と build_proxy だけを信じ、--dist は厳格に検証する。"""
    dist = req.options.get("dist")
    if dist is not None:
        try:
            dist = dist_checker(dist, uid)
        except distcheck.DistCheckError as e:
            raise HelperError(f"--dist を拒否: {e}") from e
    extra: tuple[model.Step, ...] = ()
    cleanup: tuple[model.Step, ...] = ()
    if pol.build_proxy:
        extra, cleanup = template.build_proxy_steps(pol.build_proxy)
    opts = template.TemplateOpts(
        alias=pol.template,
        nvidia_key_fpr=template.NVIDIA_KEY_FPR,
        dist_dir=dist,
        extra_steps=extra,
        cleanup_steps=cleanup,
        pi_version=req.options.get("pi_version"),
    )
    try:
        p = template.plan_build(opts)
    except ValueError as e:
        raise HelperError(f"テンプレートの計画を作れない: {e}") from e
    return _Executor(runner, out, resolver, uid, sleep).execute(p)


def _noop(out: IO[str]) -> int:
    print("[kcage] すでに起動中（変更なし）", file=out)
    return 0


def sudoers_snippet(user: str, *, helper_dir: str = model.ROOT_HELPER_DIR) -> str:
    """sudoers.d 用の雛形。visudo -cf を通る形。"""
    if not _USER_RE.match(user):
        raise ValueError("ユーザー名は英数と _ - のみ")
    if not _DIR_RE.match(helper_dir) or ".." in helper_dir.split("/"):
        raise ValueError("helper_dir の形が不正")
    exe = f"{helper_dir.rstrip('/')}/kcage-root"
    free = ", ".join([f"{exe} up *", f"{exe} stop *", f"{exe} exec *", f"{exe} ls", f"{exe} ls *"])
    pw_list = [f"{exe} {v} *" for v in ("register", "rm", "snap", "selftest")]
    pw_list += [f"{exe} template", f"{exe} template *"]  # 引数なしもある
    pw = ", ".join(pw_list)
    return (
        "# kcage-root の sudoers 雛形（/etc/sudoers.d/kcage に置く。visudo -cf で検査してから配備する）\n"
        "# 引数の厳密な検査は kcage-root 自身が行う。ここは動詞ごとにパスワードの要否を分けるだけ。\n"
        "\n"
        "# パスワードなし: 許可表に登録済みの箱の操作だけ（特権は増えない）\n"
        f"Cmnd_Alias BOX_FREE = {free}\n"
        "# パスワード必須: 許可表の変更・削除・スナップショット・自己試験\n"
        f"Cmnd_Alias BOX_PW = {pw}\n"
        "\n"
        "# パスワードの認証を使い回さない（直前の sudo の認証で通らないようにする）\n"
        "Defaults!BOX_PW timestamp_timeout=0\n"
        "\n"
        f"{user} ALL=(root) NOPASSWD: BOX_FREE\n"
        f"{user} ALL=(root) PASSWD: BOX_PW\n"
    )


if __name__ == "__main__":  # 配備コピーから直接呼ばれる
    raise SystemExit(main(sys.argv[1:]))

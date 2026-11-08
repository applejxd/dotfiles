"""BoxConfig から実行計画（純粋なデータ）を作る。副作用なし・秘密を読まない。

デバイスは呼び出し側が指定できず、BoxConfig から固定生成する。device_to_argv は「最後の関門」で、
生成側が誤っても（または侵害されても）許可外のデバイスが argv にならないよう、独立に再検査する。
"""

from __future__ import annotations

import ipaddress
import posixpath
import re
import unicodedata
from collections.abc import Mapping, Sequence

from kcage import model
from kcage.config import DENY_ABS, is_denied
from kcage.policy import REPO_ID_RE

_DEV_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$")
_SOCK_NAME = r"[a-z0-9][a-z0-9_-]{0,31}"
_HOST_LABEL = r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOSTNAME_RE = re.compile(rf"^{_HOST_LABEL}(\.{_HOST_LABEL})*$")
_LOOP_RE = re.compile(rf"^tcp:{re.escape(model.LOOPBACK)}:(\d{{1,5}})$")
_ANY_RE = re.compile(r"^tcp:0\.0\.0\.0:(\d{1,5})$")
_BOX_SOCK_RE = re.compile(rf"^unix:{re.escape(model.BOX_SOCK_DIR)}/{_SOCK_NAME}\.sock$")
_TCP_CONNECT_RE = re.compile(r"^tcp:([^:\[\]/]+):(\d{1,5})$")
_BROKER_SOCK_RE = re.compile(
    rf"^unix:{re.escape(model.BROKER_HOST_DIR)}/([a-z0-9][a-z0-9-]{{0,30}})/{_SOCK_NAME}\.sock$"
)
# どの形でも拒否する接続先（Incus・Docker の管理ソケットへの経路）
_FORBIDDEN_TARGETS = (
    "/var/lib/incus",
    "/var/run",
    "/run/docker",
    "docker.sock",
    "unix.socket",
    "incus.sock",
)


class PlanError(ValueError):
    """計画を作れない・デバイスが許可外。"""


# ---------------------------------------------------------------- デバイス


def _port_ok(s: str) -> bool:
    return s.isdigit() and 1 <= int(s) <= 65535


def devices_for(cfg: model.BoxConfig) -> tuple[model.DeviceSpec, ...]:
    """BoxConfig から固定生成するデバイス（マウント・GPU・ポート）。"""
    out: list[model.DeviceSpec] = []
    for i, m in enumerate(cfg.mounts):
        out.append(
            model.DeviceSpec(
                f"m-{m.kind}-{i}",
                "disk",
                {"source": m.source, "path": m.path, "readonly": "true" if m.readonly else "false"},
            )
        )
    if cfg.gpu:
        out.append(
            model.DeviceSpec(
                "gpu-dxg",
                "unix-char",
                {"source": model.GPU_DEVICE, "path": model.GPU_DEVICE, "mode": "0666"},
            )
        )
    for pf in cfg.ports:
        out.append(
            model.DeviceSpec(
                f"p-{pf.host_port}",
                "proxy",
                {
                    "bind": "host",
                    "listen": f"tcp:{model.LOOPBACK}:{pf.host_port}",
                    "connect": f"tcp:{model.LOOPBACK}:{pf.box_port}",
                },
            )
        )
    return tuple(out)


def _check_keys(dev: model.DeviceSpec, allowed: Sequence[str], required: Sequence[str]) -> None:
    keys = set(dev.config)
    extra = sorted(keys - set(allowed))
    if extra:
        raise PlanError(f"{dev.type} デバイスに許可外のキー: {', '.join(extra)}")
    missing = sorted(set(required) - keys)
    if missing:
        raise PlanError(f"{dev.type} デバイスに必須キーが無い: {', '.join(missing)}")
    for k, v in dev.config.items():
        if not isinstance(v, str) or any(ord(c) < 32 or ord(c) == 0x7F for c in v):
            raise PlanError(f"{dev.type} デバイスの値が不正: {k}")


def _check_abs(p: str, what: str) -> None:
    if not p.startswith("/") or ".." in p.split("/") or posixpath.normpath(p) != p:
        raise PlanError(f"{what} は正規化された絶対パスが必要")


def _check_proxy(cfg: Mapping[str, str]) -> None:
    listen, connect, bind = cfg["listen"], cfg["connect"], cfg["bind"]
    for target in (listen, connect):
        low = target.lower()
        if any(f in low for f in _FORBIDDEN_TARGETS):
            raise PlanError("管理ソケットへの経路は拒否")
    if bind == "host":
        for t in (listen, connect):
            m = _LOOP_RE.match(t)
            if not m or not _port_ok(m.group(1)):
                raise PlanError("bind=host の接続先は tcp:127.0.0.1:<port> のみ")
        return
    if bind != "instance":
        raise PlanError("bind は host / instance のみ")
    m1, m2 = _LOOP_RE.match(listen), _ANY_RE.match(listen)
    if m1 or m2:
        port = (m1 or m2).group(1)  # type: ignore[union-attr]
        if not _port_ok(port):
            raise PlanError("listen のポートが不正")
    elif not _BOX_SOCK_RE.match(listen):
        raise PlanError("bind=instance の listen が許可外")
    mt = _TCP_CONNECT_RE.match(connect)
    if mt:
        host, port = mt.groups()
        if not _port_ok(port):
            raise PlanError("connect のポートが不正")
        try:
            ipaddress.IPv4Address(host)
        except ValueError:
            if not _HOSTNAME_RE.match(host):
                raise PlanError("connect のホストは IPv4 か名前のみ") from None
        return
    mb = _BROKER_SOCK_RE.match(connect)
    if not mb or not REPO_ID_RE.match(mb.group(1)):
        raise PlanError("bind=instance の connect が許可外")


def device_to_argv(box: str, dev: model.DeviceSpec) -> tuple[str, ...]:
    """最後の関門。許可外のデバイスは PlanError。"""
    if not box.startswith(model.BOX_NAME_PREFIX) or not _DEV_NAME_RE.match(box):
        raise PlanError("箱の名前が不正")
    if not _DEV_NAME_RE.match(dev.name):
        raise PlanError("デバイス名が不正")
    c = dev.config
    if dev.type == "disk":
        _check_keys(dev, ("source", "path", "readonly"), ("source", "path"))
        _check_abs(c["source"], "disk の source")
        _check_abs(c["path"], "disk の path")
        if is_denied(c["source"], DENY_ABS):
            raise PlanError("disk の source が拒否リストと重なる")
        low = c["source"].lower()
        if any(f in low for f in _FORBIDDEN_TARGETS) or low.endswith(".sock"):
            raise PlanError("disk の source がソケット（管理ソケットへの経路）を指す")
        if c.get("readonly", "false") not in ("true", "false"):
            raise PlanError("disk の readonly は true / false のみ")
        order = ("source", "path", "readonly")
    elif dev.type == "unix-char":
        _check_keys(dev, ("source", "path", "mode"), ("source", "path"))
        if c["source"] != model.GPU_DEVICE or c["path"] != model.GPU_DEVICE:
            raise PlanError(f"unix-char は {model.GPU_DEVICE} のみ")
        # 既定の mode 0660（root だけ）だと uid 1000 のプロセスが GPU を開けない（e2e で判明）。ホストの /dev/dxg と同じ 0666
        if c.get("mode", "0666") != "0666":
            raise PlanError("unix-char の mode は 0666 のみ")
        order = ("source", "path", "mode")
    elif dev.type == "nic":
        _check_keys(dev, ("network", "name"), ("network", "name"))
        if c["network"] != model.INCUS_BRIDGE or not _DEV_NAME_RE.match(c["name"]):
            raise PlanError(f"nic は network={model.INCUS_BRIDGE} と妥当な name のみ")
        order = ("network", "name")
    elif dev.type == "proxy":
        _check_keys(
            dev,
            ("listen", "connect", "bind", "uid", "gid", "mode"),
            ("listen", "connect", "bind"),
        )
        _check_proxy(c)
        owner_keys = {"uid", "gid", "mode"} & set(c)
        if owner_keys:
            # uid・gid・mode は、箱の中の unix ソケットを待ち受ける proxy だけに許す
            if c["bind"] != "instance" or not _BOX_SOCK_RE.match(c["listen"]):
                raise PlanError(
                    "uid・gid・mode は unix:<箱のソケット置き場>/<名前>.sock の listen だけ"
                )
            for k in ("uid", "gid"):
                if k in c and not (
                    c[k].isdigit() and 1 <= int(c[k]) <= 65535 and str(int(c[k])) == c[k]
                ):
                    raise PlanError(f"{k} は 1〜65535 の 10 進数")
            if "mode" in c and c["mode"] not in ("0600", "0660"):
                raise PlanError("mode は 0600 / 0660 のみ")
        order = ("listen", "connect", "bind", "uid", "gid", "mode")
    else:
        raise PlanError(f"許可外のデバイス種別: {dev.type}")
    kv = tuple(f"{k}={c[k]}" for k in order if k in c)
    return ("incus", "config", "device", "add", box, dev.name, dev.type, *kv)


# ---------------------------------------------------------------- インスタンス設定

LABEL_KEY = "user." + model.LABEL_PREFIX + "repo"  # 所属の確認に使う（箱の config のキー）


_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_ENV_VALUE_RE = re.compile(r"^[^\x00-\x1f\x7f]{0,2048}$")
# コードやライブラリの読み込みに効く変数は、箱の環境変数として置かない
_ENV_DENY = frozenset(
    {"BASH_ENV", "ENV", "PATH", "NODE_OPTIONS", "PYTHONPATH", "PYTHONSTARTUP", "IFS"}
)


def _check_env(key: str, value: str) -> None:
    if not _ENV_KEY_RE.match(key) or key.upper().startswith("LD_") or key.upper() in _ENV_DENY:
        raise PlanError(f"環境変数名が不正または拒否対象: {key}")
    if not _ENV_VALUE_RE.match(value):
        raise PlanError(f"環境変数 {key} の値が不正")


def instance_config(cfg: model.BoxConfig) -> dict[str, str]:
    """incus init -c に渡す設定。特権化は常に明示的に false。"""
    gid = cfg.uid if cfg.gid is None else cfg.gid  # ホストの gid（許可表の gid。既定は uid）
    if cfg.idmap == "user":
        # ホストの uid・gid を、箱の uid・gid（ubuntu = uid と同じ値）へ対応させる
        idmap = f"uid {cfg.uid} {cfg.uid}\ngid {gid} {cfg.uid}"
    elif cfg.idmap == "root":
        idmap = f"uid {cfg.uid} 0\ngid {gid} 0"
    else:
        raise PlanError("idmap が不正")
    return {
        "security.nesting": "true",
        "security.privileged": "false",
        "raw.idmap": idmap,
        LABEL_KEY: cfg.repo_id,
    }


# ---------------------------------------------------------------- 計画


def _active_brokers(
    cfg: model.BoxConfig, brokers: Sequence[model.BrokerPlan]
) -> list[model.BrokerPlan]:
    """cfg.network で有効にならない経路を持つブローカーは外す（C15）。"""
    return [b for b in brokers if all(cfg.network in r.modes for r in b.routes)]


ALLOWED_PROFILE_SETS = (("default",), ("kcage-nonet",))
ALLOWED_PROFILE_OPS = (
    ("incus", "profile", "create", "kcage-nonet"),
    ("incus", "profile", "device", "add", "kcage-nonet", "root", "disk", "path=/", "pool=default"),
)


def _check_net_profiles(net: model.NetPlan) -> None:
    """profile_ops は root で実行されるので allowlist で検査する（NIC なしの箱用の 2 つだけ）。"""
    if tuple(net.profiles) not in ALLOWED_PROFILE_SETS:
        raise PlanError("許可外のプロファイルの組")
    for op in net.profile_ops:
        if tuple(op.argv) not in ALLOWED_PROFILE_OPS or op.where != "host":
            raise PlanError("許可外の profile_ops")


GIT_CONFIG_PATH = model.BOX_HOME + "/.config/git/config"
_GIT_NAME_MAX = 100
_GIT_EMAIL_MAX = 200
_GIT_EMAIL_RE = re.compile(r'^[^\s@<>"\\]+@[^\s@<>"\\]+$')


def _has_control(s: str) -> bool:
    return any(unicodedata.category(c) in ("Cc", "Zl", "Zp") for c in s)


def _git_quote(s: str) -> str:
    """git の設定の引用規則（バックスラッシュと二重引用符のエスケープ）。"""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def git_identity_config(name: str, email: str) -> str:
    """箱の ~/.config/git/config の内容（[user] の 2 行だけ）。信頼しない値なので検証し、違反は PlanError。"""
    if not 1 <= len(name) <= _GIT_NAME_MAX or _has_control(name) or not name.strip():
        raise PlanError("git の user.name が不正（1〜100 文字・制御文字なし）")
    if (
        not 1 <= len(email) <= _GIT_EMAIL_MAX
        or _has_control(email)
        or not _GIT_EMAIL_RE.fullmatch(email)
    ):
        raise PlanError("git の user.email が不正")
    return f"[user]\n\tname = {_git_quote(name)}\n\temail = {_git_quote(email)}\n"


def plan_up(
    cfg: model.BoxConfig,
    net: model.NetPlan,
    brokers: Sequence[model.BrokerPlan],
    *,
    template: str,
    exists: bool,
    running: bool,
    existing_repo_label: str | None = None,
    git_identity: tuple[str, str] | None = None,
) -> model.Plan:
    if net.mode != cfg.network:
        raise PlanError("NetPlan のモードが設定と一致しない")
    _check_net_profiles(net)
    if exists and existing_repo_label != cfg.repo_id:
        raise PlanError("同名の箱が別のリポジトリのもの（衝突のため拒否）")
    active = _active_brokers(cfg, brokers)
    routes = tuple(net.routes) + tuple(r for b in active for r in b.routes)
    box = cfg.name

    def broker_start() -> list[model.Step]:
        return [op for b in active for op in b.host_ops]

    def wait_and_ready() -> list[model.Step]:
        s: list[model.Step] = [model.Op("box", ("true",), "箱の起動待ち")]
        s.extend(b.readiness for b in active if b.readiness is not None)
        return s

    if exists and running:
        return model.Plan("up", box, (), routes)
    if exists:
        steps = broker_start()
        steps.append(model.Op("host", ("incus", "start", box), "箱を起動"))
        steps.extend(wait_and_ready())
        return model.Plan("up", box, tuple(steps), routes)

    cargs: list[str] = []
    for prof in net.profiles:
        cargs += ["-p", prof]
    for k, v in instance_config(cfg).items():
        cargs += ["-c", f"{k}={v}"]
    # net とブローカーの環境変数（ダミーの GH_TOKEN・HTTPS_PROXY など）。インスタンスの environment.* は incus exec にも届く
    # （/etc/environment は exec では読まれない。e2e で、定義だけで箱に入っていなかったと判明）
    env: dict[str, str] = {**net.env}
    for b in active:
        env.update(b.env)
    for k, v in sorted(env.items()):
        _check_env(k, v)
        cargs += ["-c", f"environment.{k}={v}"]
    # プロファイルは init の前に作る（e2e で、後だと「プロファイルが無い」で up が失敗した）
    steps2: list[model.Step] = [
        *net.profile_ops,
        model.Op("host", ("incus", "init", template, box, *cargs), "箱を作成"),
    ]
    devices = [*devices_for(cfg), *net.devices, *(d for b in active for d in b.devices)]
    for d in devices:
        device_to_argv(box, d)  # 早期に検査（実行時にもう一度通す）
        steps2.append(d)
    steps2.extend(net.files)
    if git_identity is not None:
        # 検証を通した値を 1 つのファイルとして置くだけ（argv には渡さない。docs/spec/sandbox/incus-box.md#箱の中の-git-のコミット者情報）
        steps2.append(
            model.FilePut(
                "box",
                GIT_CONFIG_PATH,
                "0644",
                f"{model.BOX_USER}:{model.BOX_USER}",
                content=git_identity_config(*git_identity),
            )
        )
    for b in active:
        steps2.extend(b.files)
    steps2.extend(broker_start())
    steps2.append(model.Op("host", ("incus", "start", box), "箱を起動"))
    steps2.extend(wait_and_ready())
    return model.Plan("up", box, tuple(steps2), routes)


def plan_stop(cfg: model.BoxConfig, brokers: Sequence[model.BrokerPlan]) -> model.Plan:
    steps: list[model.Step] = [
        model.Op("host", ("incus", "stop", cfg.name), "箱を停止", check=False)
    ]
    for b in brokers:
        steps.extend(b.stop_ops)
    return model.Plan("stop", cfg.name, tuple(steps))


def plan_rm(cfg: model.BoxConfig, brokers: Sequence[model.BrokerPlan]) -> model.Plan:
    steps: list[model.Step] = [op for b in brokers for op in b.stop_ops]
    steps.append(model.Op("host", ("incus", "delete", "--force", cfg.name), "箱を削除"))
    return model.Plan("rm", cfg.name, tuple(steps))


def plan_exec(cfg: model.BoxConfig, argv: Sequence[str]) -> model.Plan:
    if not argv or not all(isinstance(a, str) for a in argv):
        raise PlanError("箱の中で実行するコマンドが空")
    full = (
        "incus",
        "exec",
        cfg.name,
        "--user",
        str(cfg.uid),
        # incus exec は補助グループを設定しない。主グループを uid と同じにする
        # （既定の gid 0 だと docker のソケットに届かず、リポジトリに作るファイルのグループもホストのユーザーとずれる）
        "--group",
        str(cfg.uid),
        "--cwd",
        cfg.repo_path,
        "--env",
        "HOME=" + model.BOX_HOME,
        "--",
        *argv,
    )
    return model.Plan("exec", cfg.name, (model.Op("host", full, "箱でコマンドを実行"),))

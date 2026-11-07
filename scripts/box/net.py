"""箱の外向き通信（nat / proxy-only / offline）の計画と経路表。標準ライブラリだけ。

計画を返す関数は純粋（副作用なし）。実行は薄い層（W1a の plan_up・W1b の setup）が行う。

方針（契約 C4・C5・C15）:
- nat: 箱に NIC（incusbr0）を付ける。ホストの外へ NAT で出る。
- proxy-only（A1）: **NIC を付けない**。proxy デバイス 1 つ（bind=instance）が、箱の中の 0.0.0.0:3128 で待ち受け、
  上流プロキシ（許可表の proxy_upstream）へ中継する。直通・DNS・IPv6 の経路が構造的に無い。
- offline: NIC なし・proxy なし。外へ出る経路は無い（ブローカーの経路は別担当が返し、offline では plan_up が外す）。
- proxy-only でも、compose のコンテナにはプロキシの環境変数を既定では渡さない（~/.docker/config.json の proxies は
  作らない）。コンテナは既定で外へ出られない。外へ出すサービスだけ、compose の environment に明示する。
  「環境変数を渡したサービスだけが使える」とは言わない（サービス単位の隔離は別要件。C15）。
- pi は HTTPS_PROXY の環境変数、またはエージェントのディレクトリの設定 httpProxy で使える。ここは環境変数だけを返し、
  設定ファイルへの差し込みはテンプレート側（W1b）が行う。
- 組織固有の値（プロキシのアドレス・CA）は、コードに書かない。cfg.proxy_upstream（許可表の値）だけを使う。
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from .model import (
    BOX_SOCK_DIR,
    INCUS_BRIDGE,
    LOOPBACK,
    PROXY_BOX_PORT,
    ROOT_HELPER_DIR,
    BoxConfig,
    DeviceSpec,
    FilePut,
    NetPlan,
    Op,
    Route,
)

PROXY_DEVICE = "proxy-out"
NIC_DEVICE = "eth0"
# NIC を付けないモード用のプロファイル（root の disk だけ。default は eth0 を持つので使わない）
NONET_PROFILE = "box-nonet"
# 箱の中のプロキシ待受。0.0.0.0 にして、箱の中の docker0（172.17.0.1）からも届くようにする
PROXY_LISTEN_ALL = f"tcp:0.0.0.0:{PROXY_BOX_PORT}"
PROXY_LISTEN_LOOPBACK = f"tcp:{LOOPBACK}:{PROXY_BOX_PORT}"
PROXY_URL = f"http://{LOOPBACK}:{PROXY_BOX_PORT}"
# /run/box 以下のソケットは unix ソケットなので環境変数に入れる必要はない（NO_PROXY の対象外）
NO_PROXY = "127.0.0.1,localhost,::1,172.17.0.1,host.docker.internal"

FORWARD_COMMENT = "incus-box"
FORWARD_SERVICE = "box-forward.service"
FORWARD_ADD_SCRIPT = f"{ROOT_HELPER_DIR}/box-forward-add.sh"
FORWARD_DEL_SCRIPT = f"{ROOT_HELPER_DIR}/box-forward-del.sh"
FORWARD_UNIT_PATH = f"/etc/systemd/system/{FORWARD_SERVICE}"

_UPSTREAM_RE = re.compile(r"^[A-Za-z0-9.\-]+:(\d{1,5})$")


class NetError(ValueError):
    """外向き通信の設定が不正（ConfigError 相当）。"""


def _check_upstream(upstream: str | None) -> str:
    if not upstream:
        raise NetError("proxy-only には proxy_upstream（許可表の IP:ポート）が要る")
    m = _UPSTREAM_RE.match(upstream)
    if m is None or not 1 <= int(m.group(1)) <= 65535:
        raise NetError("proxy_upstream は IP:ポート の形で書く")
    return upstream


def proxy_env() -> dict[str, str]:
    """箱の中で使うプロキシの環境変数（127.0.0.1:3128）。"""
    return {
        "HTTP_PROXY": PROXY_URL,
        "HTTPS_PROXY": PROXY_URL,
        "http_proxy": PROXY_URL,
        "https_proxy": PROXY_URL,
        "NO_PROXY": NO_PROXY,
        "no_proxy": NO_PROXY,
    }


def routes_table(cfg: BoxConfig) -> tuple[Route, ...]:
    """cfg.network に有効な一般通信の経路表（契約 C15 の正本）。plan の routes と一致する。"""
    if cfg.network == "nat":
        return (Route("一般通信", "NAT（incusbr0 → ホストの外）", ("nat",)),)
    if cfg.network == "proxy-only":
        up = _check_upstream(cfg.proxy_upstream)
        return (Route("一般通信", "proxy デバイス → 上流プロキシ", ("proxy-only",), upstream=up),)
    return ()  # offline: 外へ出る行は無い


def _environment_file(env: Mapping[str, str]) -> str:
    return "".join(f"{k}={v}\n" for k, v in env.items())


def _proxy_files() -> tuple[FilePut, ...]:
    env = proxy_env()
    environment = (
        "# box が書く（proxy-only）。compose のコンテナには渡さない\n" + _environment_file(env)
    )
    apt = f'Acquire::http::Proxy "{PROXY_URL}";\nAcquire::https::Proxy "{PROXY_URL}";\n'
    docker = (
        "[Service]\n"
        f'Environment="HTTP_PROXY={PROXY_URL}"\n'
        f'Environment="HTTPS_PROXY={PROXY_URL}"\n'
        f'Environment="NO_PROXY={NO_PROXY}"\n'
    )
    git = f"[http]\n\tproxy = {PROXY_URL}\n"
    profile = "# box が書く（proxy-only）\n" + "".join(
        f'export {k}="{v}"\n' for k, v in env.items()
    )
    return (
        FilePut("box", "/etc/environment", "0644", "root:root", content=environment),
        FilePut("box", "/etc/apt/apt.conf.d/99box-proxy", "0644", "root:root", content=apt),
        FilePut(
            "box",
            "/etc/systemd/system/docker.service.d/box-proxy.conf",
            "0644",
            "root:root",
            content=docker,
        ),
        FilePut("box", "/etc/gitconfig", "0644", "root:root", content=git),
        FilePut("box", "/etc/profile.d/box-proxy.sh", "0644", "root:root", content=profile),
    )


def _nonet_profile_ops() -> tuple[Op, ...]:
    """NIC の無いプロファイル（冪等。既にあれば失敗を無視する）。plan_up はこの 2 つだけを許す。"""
    return (
        Op(
            "host",
            ("incus", "profile", "create", NONET_PROFILE),
            "NIC の無いプロファイルを作る（既にあれば何もしない）",
            check=False,
        ),
        Op(
            "host",
            (
                "incus",
                "profile",
                "device",
                "add",
                NONET_PROFILE,
                "root",
                "disk",
                "path=/",
                "pool=default",
            ),
            "NIC の無いプロファイルに root の disk を足す（既にあれば何もしない）",
            check=False,
        ),
    )


def plan(cfg: BoxConfig) -> NetPlan:
    """モード別の NetPlan。デバイスは固定生成（呼び出し側は任意の config を渡せない）。

    NIC を付けないモード（proxy-only・offline）は、nic の DeviceSpec を返さず、NIC の無いプロファイル
    （box-nonet）を profiles で指定する（default は eth0 を持つ）。作成の Op は profile_ops。
    """
    routes = routes_table(cfg)
    if cfg.network == "nat":
        nic = DeviceSpec(NIC_DEVICE, "nic", {"network": INCUS_BRIDGE, "name": NIC_DEVICE})
        return NetPlan("nat", devices=(nic,), routes=routes)
    if cfg.network == "proxy-only":
        upstream = _check_upstream(cfg.proxy_upstream)
        proxy = DeviceSpec(
            PROXY_DEVICE,
            "proxy",
            {"bind": "instance", "listen": PROXY_LISTEN_ALL, "connect": f"tcp:{upstream}"},
        )
        return NetPlan(
            "proxy-only",
            profiles=(NONET_PROFILE,),
            profile_ops=_nonet_profile_ops(),
            devices=(proxy,),
            files=_proxy_files(),
            env=proxy_env(),
            routes=routes,
        )
    return NetPlan(
        "offline", profiles=(NONET_PROFILE,), profile_ops=_nonet_profile_ops(), routes=routes
    )


# ---- ホスト側の準備（nat 用。契約 C5: 既存の状態を壊さない・冪等・コメントつき・削除手段あり）----

_RULE_IN = f'iifname "{INCUS_BRIDGE}" accept comment "{FORWARD_COMMENT}"'
_RULE_OUT = (
    f'oifname "{INCUS_BRIDGE}" ct state established,related accept comment "{FORWARD_COMMENT}"'
)

FORWARD_ADD_CONTENT = f"""#!/bin/sh
# box（incus-box）: 別ディストロの Docker の FORWARD drop が、incusbr0 の通信を止めるのを避ける。
# DOCKER-USER に、incusbr0 に限った許可を冪等に入れる。コメント "{FORWARD_COMMENT}" が目印。
# 削除は {FORWARD_DEL_SCRIPT}。
set -eu

# DOCKER-USER が無い（Docker が無い）環境では何もしない
if ! nft list chain ip filter DOCKER-USER >/dev/null 2>&1; then
  exit 0
fi

current=$(nft list chain ip filter DOCKER-USER)

# 同じ規則が既にあれば入れない（2 回挿入しない）
if ! printf '%s\\n' "$current" | grep -qF '{_RULE_OUT}'; then
  nft insert rule ip filter DOCKER-USER oifname {INCUS_BRIDGE} ct state related,established accept \\
    comment '"{FORWARD_COMMENT}"'
fi
if ! printf '%s\\n' "$current" | grep -qF '{_RULE_IN}'; then
  nft insert rule ip filter DOCKER-USER iifname {INCUS_BRIDGE} accept comment '"{FORWARD_COMMENT}"'
fi
"""

FORWARD_DEL_CONTENT = f"""#!/bin/sh
# box（incus-box）が入れた DOCKER-USER の規則（コメント "{FORWARD_COMMENT}"）だけを handle で削除する。
# 他の規則には触れない。DOCKER-USER が無ければ何もしない。
set -eu

if ! nft list chain ip filter DOCKER-USER >/dev/null 2>&1; then
  exit 0
fi

nft -a list chain ip filter DOCKER-USER \\
  | sed -n 's/.*comment "{FORWARD_COMMENT}".*# handle \\([0-9][0-9]*\\)$/\\1/p' \\
  | while read -r handle; do
      nft delete rule ip filter DOCKER-USER handle "$handle"
    done
"""

FORWARD_UNIT_CONTENT = f"""# box（incus-box）: incusbr0 の通信を Docker の FORWARD drop から守る許可を入れる。
# docker・incus の再起動のたびに入れ直す（PartOf）。
[Unit]
Description=box: DOCKER-USER に incusbr0 の許可を入れる
After=docker.service incus.service
PartOf=docker.service incus.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart={FORWARD_ADD_SCRIPT}
ExecStop={FORWARD_DEL_SCRIPT}

[Install]
WantedBy=multi-user.target
"""


def host_setup_plan(subnet: str | None = None) -> tuple[Op | FilePut, ...]:
    """nat のホスト側の準備（root で実行する。冪等）。subnet は policy.subnet（あれば ipv4.address に使う）。"""
    ops: list[Op | FilePut] = [
        Op(
            "host",
            ("incus", "network", "set", INCUS_BRIDGE, "ipv6.address", "none"),
            "incusbr0 の IPv6 を無効にする（箱の IPv6 の直通を作らない）",
        ),
    ]
    if subnet:
        ops.append(
            Op(
                "host",
                ("incus", "network", "set", INCUS_BRIDGE, "ipv4.address", subnet),
                "incusbr0 の IPv4 サブネットを固定する（docker0 などとの衝突回避）",
            )
        )
    ops += [
        FilePut("host", FORWARD_ADD_SCRIPT, "0755", "root:root", content=FORWARD_ADD_CONTENT),
        FilePut("host", FORWARD_DEL_SCRIPT, "0755", "root:root", content=FORWARD_DEL_CONTENT),
        FilePut("host", FORWARD_UNIT_PATH, "0644", "root:root", content=FORWARD_UNIT_CONTENT),
        Op("host", ("systemctl", "daemon-reload"), "systemd の設定を読み直す"),
        Op(
            "host",
            ("systemctl", "enable", "--now", FORWARD_SERVICE),
            "DOCKER-USER の許可（incusbr0 のみ）を有効にする",
        ),
    ]
    return tuple(ops)


def host_teardown_plan() -> tuple[Op, ...]:
    """host_setup_plan の取り消し（コメント incus-box の規則とユニットだけ）。"""
    return (
        Op(
            "host",
            ("systemctl", "disable", "--now", FORWARD_SERVICE),
            "box-forward を止める（停止時に規則も消える）",
            check=False,
        ),
        Op("host", (FORWARD_DEL_SCRIPT,), "incus-box の規則だけを削除する"),
        Op("host", ("rm", "-f", FORWARD_UNIT_PATH), "ユニットを削除する"),
        Op("host", ("systemctl", "daemon-reload"), "systemd の設定を読み直す"),
    )


__all__ = [
    "BOX_SOCK_DIR",
    "NetError",
    "host_setup_plan",
    "host_teardown_plan",
    "plan",
    "proxy_env",
    "routes_table",
]

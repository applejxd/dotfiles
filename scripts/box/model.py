"""箱（Incus）の計画の型。標準ライブラリだけで書く（独立リポジトリへの切り出しを見据える）。

I/F の正本。契約は親が管理する（.tmp/keep/plan/incus-box-impl.md）。担当は、この型を前提に実装する。
型の形を変えたいときは、自分で変えず、親へ報告する（複数の担当に波及するため）。

原則:
- 計画を返す関数は純粋（副作用なし・秘密を読まない）。実行は薄い層が行う。
- 権限は HostPolicy（root 所有の許可表）が決める。RepoSpec（リポジトリの box.toml）は、箱から書き換えられる
  ので、許可表の範囲の部分集合を選ぶ「要求」にすぎない（契約 C13）。
- デバイスは、呼び出し側が指定しない。BoxConfig から固定生成する（呼び出し側が書けるのは項目の名前だけ）。
- 秘密は SecretRef（参照）で扱い、実行時にだけ解決する。ログ・計画の表示には名前だけを出す（契約 C1）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

NetMode = Literal["nat", "proxy-only", "offline"]
IdmapMode = Literal[
    "user", "root"
]  # user: both <uid> <uid> / root: 箱の root をホストの uid に対応させる
Where = Literal["host", "box"]  # 操作の実行場所（host は box-root の中。box は箱の中）
DeviceType = Literal["disk", "proxy", "unix-char", "nic"]
MountKind = Literal["repo", "data", "gpu-lib", "gpu-drivers", "dist", "images", "state"]
BrokerKind = Literal["gh", "aws", "copilot", "hf-cache"]

# 厳しさの順。box.toml は、より厳しい方向（数値が大きい側）にだけ上書きできる
NET_STRICTNESS: Mapping[str, int] = {"nat": 0, "proxy-only": 1, "offline": 2}

# コードに固定する値（許可表にも box.toml にも書かせない。契約の「コードに固定するもの」）
LOOPBACK = "127.0.0.1"
BOX_NAME_PREFIX = "box-"
LABEL_PREFIX = "dotfiles.box."
GPU_DEVICE = "/dev/dxg"
GPU_LIB = "/usr/lib/wsl/lib"
GPU_DRIVERS = "/usr/lib/wsl/drivers"
INCUS_BRIDGE = "incusbr0"
RESERVED_PORT_MAX = 1023  # これ以下は、許可表に明記したときだけ

# 配備・ソケットの置き場（コードに固定。呼び出し側は変えられない）
POLICY_PATH = "/etc/box/policy.toml"  # root 所有の許可表
ROOT_HELPER_DIR = "/usr/local/libexec/box"  # root 所有の配備コピー（box-root はここから実行する）
BROKER_HOST_DIR = (
    "/run/box-broker"  # ホスト側のブローカーのソケット: /run/box-broker/<repo-id>/<kind>.sock
)
BOX_SOCK_DIR = "/run/box"  # 箱の中のソケット: /run/box/<kind>.sock
PROXY_BOX_PORT = 3128  # proxy-only: 箱の中の 127.0.0.1 のポート（箱の中の docker0 からも届く）
BOX_USER = "ubuntu"  # 箱の中のユーザー（uid 1000）
BOX_HOME = "/home/ubuntu"


@dataclass(frozen=True)
class SecretRef:
    """秘密の参照。値は持たない。file はパス、command は argv（シェルなし）、prompt は端末で尋ねる。"""

    name: str
    source: Literal["file", "command", "prompt"]
    path: str | None = None
    argv: tuple[str, ...] = ()

    def __repr__(self) -> str:  # ログや計画の表示に、出どころの詳細を出さない
        return f"SecretRef({self.name!r}, {self.source})"


@dataclass(frozen=True)
class PortRange:
    lo: int
    hi: int

    def contains(self, port: int) -> bool:
        return self.lo <= port <= self.hi


@dataclass(frozen=True)
class RepoPolicy:
    """許可表（HostPolicy）の 1 項目。root 所有のファイルから読む。権限の元。"""

    id: str
    path: str  # リポジトリのルート（rw で重ねるのはこの 1 つだけ）
    data_roots: tuple[
        str, ...
    ] = ()  # 読み取り専用で渡してよい根（この下のサブディレクトリを要求できる）
    ports: tuple[PortRange, ...] = ()  # 公開してよいポート（箱の中のポート。ホスト側は 127.0.0.1）
    brokers: tuple[BrokerKind, ...] = ()
    gpu: bool = False
    network: NetMode = "nat"
    proxy_upstream: str | None = None  # proxy-only の上流（許可表にだけ書く。IP:ポート）
    idmap: IdmapMode = "user"
    uid: int = 1000
    subnet: str | None = None  # incusbr0・docker0 の衝突を避けるための固定
    secrets: Mapping[str, SecretRef] = field(default_factory=dict)  # ブローカー名 -> 出どころ


@dataclass(frozen=True)
class HostPolicy:
    repos: Mapping[str, RepoPolicy]
    deny_paths: tuple[str, ...] = ()  # 根の下でも拒否するパス（ホームの秘密・ソケットなど）
    default_network: NetMode = "nat"
    template: str = "box-template"  # テンプレートのイメージの別名


@dataclass(frozen=True)
class RepoSpec:
    """リポジトリの box.toml。箱から書き換えられるので、要求にすぎない（権限ではない）。"""

    data: tuple[str, ...] = ()  # 許可された根の下の相対パス
    ports: tuple[int, ...] = ()
    brokers: tuple[BrokerKind, ...] = ()
    gpu: bool = False
    network: NetMode | None = None  # より厳しい方向にだけ上書きできる
    images: bool = False  # Orca の貼り付け画像（既定は無効）


@dataclass(frozen=True)
class Mount:
    kind: MountKind
    source: str  # ホスト側の実パス（検証済み）
    path: str  # 箱の中のパス
    readonly: bool


@dataclass(frozen=True)
class PortForward:
    """箱の中の port を、ホストの 127.0.0.1:host_port へ公開する（proxy デバイス。固定生成）。"""

    box_port: int
    host_port: int


@dataclass(frozen=True)
class BoxConfig:
    """RepoPolicy と RepoSpec を突き合わせた解決後の設定。未知のキー・範囲外は、解決の時点で拒否済み。"""

    name: str  # box-<id>
    repo_id: str
    repo_path: str
    uid: int
    idmap: IdmapMode
    mounts: tuple[Mount, ...]
    ports: tuple[PortForward, ...]
    brokers: tuple[BrokerKind, ...]
    gpu: bool
    network: NetMode
    proxy_upstream: str | None
    subnet: str | None
    labels: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DeviceSpec:
    """Incus のデバイス。BoxConfig から固定生成する。呼び出し側は、任意の config を渡せない。"""

    name: str
    type: DeviceType
    config: Mapping[str, str]


@dataclass(frozen=True)
class Op:
    """実行する操作。argv はシェルなし。秘密は stdin_secret 経由（argv・ログに出さない）。"""

    where: Where
    argv: tuple[str, ...]
    desc: str
    stdin_secret: SecretRef | None = None
    check: bool = True  # 失敗で止めるか


@dataclass(frozen=True)
class FilePut:
    """ファイルを置く。内容に秘密を直接入れない（秘密は secret で参照する）。"""

    where: Where
    path: str
    mode: str  # 例 "0644"
    owner: str  # 例 "root:root"・"1000:1000"
    content: str | None = None
    secret: SecretRef | None = None


@dataclass(frozen=True)
class Route:
    """外向き通信の経路表の 1 行。契約 C15: これが経路の正本。"""

    purpose: str  # 例 "一般通信"・"gh"・"copilot"
    path: str  # 例 "proxy デバイス → 上流プロキシ"・"unix ソケット → ホストのブローカー"
    modes: tuple[NetMode, ...]  # この経路が有効なモード
    upstream: str | None = None  # 上流（許可表の値。ログには出さない）


@dataclass(frozen=True)
class NetPlan:
    mode: NetMode
    # incus init に -p で渡すプロファイル。NIC を付けないモード（proxy-only・offline）は NIC の無いプロファイル
    # （box-nonet。profile_ops が作る）を使う。既定の default プロファイルは eth0（NIC）を持つため使えない
    profiles: tuple[str, ...] = ("default",)
    profile_ops: tuple[Op, ...] = ()
    devices: tuple[DeviceSpec, ...] = ()
    files: tuple[FilePut, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    routes: tuple[Route, ...] = ()


@dataclass(frozen=True)
class BrokerPlan:
    kind: BrokerKind
    host_ops: tuple[Op, ...] = ()  # ホスト側の起動
    devices: tuple[DeviceSpec, ...] = ()  # 箱へつなぐ proxy デバイス（固定生成）
    files: tuple[FilePut, ...] = ()
    env: Mapping[str, str] = field(
        default_factory=dict
    )  # ダミー・エンドポイントだけ（本物を入れない）
    readiness: Op | None = None  # 起動の確認
    stop_ops: tuple[Op, ...] = ()
    routes: tuple[Route, ...] = ()


Step = Op | FilePut | DeviceSpec


@dataclass(frozen=True)
class Plan:
    """box up などの計画。順に実行する。"""

    verb: str
    box: str
    steps: tuple[Step, ...]
    routes: tuple[Route, ...] = ()


def box_name(repo_id: str) -> str:
    return f"{BOX_NAME_PREFIX}{repo_id}"


def effective_network(policy_mode: NetMode, requested: NetMode | None) -> NetMode:
    """box.toml の要求は、より厳しい方向にだけ効く。"""
    if requested is None:
        return policy_mode
    return requested if NET_STRICTNESS[requested] > NET_STRICTNESS[policy_mode] else policy_mode

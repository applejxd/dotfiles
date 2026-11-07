"""テンプレート（箱の元になるイメージ）を作る計画。純粋な関数だけ（実行は親が実機で行う）。

一時の箱 box-template-build を images:ubuntu/24.04 から作り、docker・NVIDIA Container Toolkit・Node・git・pi の配布物を入れて
incus publish し、一時の箱を消す。CDI の定義はドライバの更新でパスが変わるので、箱の起動のたびに生成する（systemd ユニット）。
本体は dotfiles 固有のものを import しない。pi の配布物は、作成済みのディレクトリのパスだけを受け取る。
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Sequence
from dataclasses import dataclass

from box import model, policy

BUILD_NAME = "box-template-build"
# NVIDIA Container Toolkit の配布元の鍵（主鍵）の指紋。https://nvidia.github.io/libnvidia-container/gpgkey の主鍵
# （2017-09-28 作成。uid "NVIDIA CORPORATION (Open Source Projects) <cudatools@nvidia.com>"）。
# 副鍵 2041629BF5352FAC178A9B1F6ED91CA3AC1160CD は指紋に使わない。
# 公開の鍵の指紋（秘密ではない。nvidia.github.io/libnvidia-container の主鍵）。gitleaks の誤検出を除く
NVIDIA_KEY_FPR = "C95B321B61E88C1809C4F759DDCAE044F796ECB0"  # gitleaks:allow
PI_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([-.][0-9A-Za-z.]+)?$")
# ビルド用の一時の箱に置く proxy の設定ファイル（テンプレートには残さない）
BUILD_PROXY_FILES = (
    "/etc/apt/apt.conf.d/99box-build-proxy",
    "/etc/profile.d/box-build-proxy.sh",
    "/etc/gitconfig",
    "/root/.curlrc",
    "/root/.npmrc",
)
ENV_MARK = "# box-build-proxy"
BASE_IMAGE = "images:ubuntu/24.04"
KEYRING = "/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg"
KEY_URL = "https://nvidia.github.io/libnvidia-container/gpgkey"
REPO_LINE = (
    f"deb [signed-by={KEYRING}] https://nvidia.github.io/libnvidia-container/stable/deb/$(ARCH) /\n"
)
DIST_DEST = "/opt/box-dist"
PI_PACKAGE = "@earendil-works/pi-coding-agent"
APT_PACKAGES = ("ca-certificates", "curl", "gnupg", "git", "docker.io", "nodejs", "npm")

CDI_UNIT = """[Unit]
Description=NVIDIA の CDI 定義を生成する（起動のたびに。ドライバの更新でパスが変わるため）
ConditionPathExists=/dev/dxg
Before=docker.service

[Service]
Type=oneshot
ExecStartPre=/usr/bin/mkdir -p /etc/cdi
ExecStart=/usr/bin/nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml

[Install]
WantedBy=multi-user.target
"""
DOCKER_DAEMON_JSON = '{\n  "features": {\n    "cdi": true\n  }\n}\n'
LD_CONF = f"{model.GPU_LIB}\n"


@dataclass(frozen=True)
class TemplateOpts:
    alias: str = "box-template"  # 許可表の template
    nvidia_key_fpr: str = NVIDIA_KEY_FPR  # NVIDIA の鍵の指紋（必須。空・不正なら計画を作らない）
    dist_dir: str | None = None  # adapters で作った pi の配布物のディレクトリ（ホスト側）
    extra_steps: Sequence[
        model.Step
    ] = ()  # W2 の net.plan から受け取る（proxy の環境変数など）。起動の直後に入る
    base_image: str = BASE_IMAGE
    # 公開の前（箱が動いている間）に実行する後始末。build_proxy の設定ファイルを消す
    cleanup_steps: Sequence[model.Step] = ()
    pi_version: str | None = None  # 指定があれば pi を版つきで入れる（ホストの pi の版）


def _host(argv: Sequence[str], desc: str, *, check: bool = True) -> model.Op:
    return model.Op(where="host", argv=tuple(argv), desc=desc, check=check)


def _box(argv: Sequence[str], desc: str, *, check: bool = True) -> model.Op:
    return model.Op(where="box", argv=tuple(argv), desc=desc, check=check)


def _sh(script: str, desc: str, *, check: bool = True) -> model.Op:
    return _box(["sh", "-c", script], desc, check=check)


def _put(path: str, content: str, mode: str = "0644") -> model.FilePut:
    return model.FilePut(where="box", path=path, mode=mode, owner="root:root", content=content)


def build_proxy_steps(hostport: str) -> tuple[tuple[model.Step, ...], tuple[model.Step, ...]]:
    """build_proxy（host:port）から、(設定の Step, 公開前に消す Step) を作る。net を使わない。

    ビルド用の箱は NAT の NIC を持つので、箱の中から上流へ直接つなぐ。incus exec は /etc/environment を読まないので、
    curl・npm には /root の rc でも指定する。通常の箱の通信は net の経路表が決めるので、後始末で全部消す。
    """
    policy.validate_upstream(hostport)
    url = f"http://{hostport}"
    env = f'http_proxy="{url}"\nhttps_proxy="{url}"\nHTTP_PROXY="{url}"\nHTTPS_PROXY="{url}"\n'
    export = (
        f'export http_proxy="{url}" https_proxy="{url}" HTTP_PROXY="{url}" HTTPS_PROXY="{url}"\n'
    )
    marked = "".join(f"{ln} {ENV_MARK}\n" for ln in env.splitlines())
    setup: tuple[model.Step, ...] = (
        _put(
            "/etc/apt/apt.conf.d/99box-build-proxy",
            f'Acquire::http::Proxy "{url}";\nAcquire::https::Proxy "{url}";\n',
        ),
        _put("/etc/profile.d/box-build-proxy.sh", export),
        _put("/etc/gitconfig", f"[http]\n\tproxy = {url}\n"),
        _put("/root/.curlrc", f'proxy = "{url}"\n', "0600"),
        _put("/root/.npmrc", f"proxy={url}\nhttps-proxy={url}\n", "0600"),
        _box(["systemctl", "is-system-running", "--wait"], "起動の完了を待つ", check=False),
        _sh(
            f"printf %s {_shq(marked)} >> /etc/environment",
            "/etc/environment に build_proxy を足す（後で消す）",
        ),
    )
    cleanup: tuple[model.Step, ...] = (
        _box(["rm", "-f", *BUILD_PROXY_FILES], "ビルド用の proxy 設定ファイルを消す"),
        _sh(
            f"sed -i '/{ENV_MARK}$/d' /etc/environment",
            "/etc/environment から build_proxy を消す",
        ),
    )
    return setup, cleanup


def _shq(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def plan_build(opts: TemplateOpts) -> model.Plan:
    if opts.pi_version is not None and not PI_VERSION_RE.match(opts.pi_version):
        raise ValueError("pi_version は x.y.z（任意の接尾辞つき）の形が必要")
    pi_pkg = PI_PACKAGE if opts.pi_version is None else f"{PI_PACKAGE}@{opts.pi_version}"
    fpr = "".join(opts.nvidia_key_fpr.split()).upper()
    if not fpr or not all(c in "0123456789ABCDEF" for c in fpr):
        raise ValueError("nvidia_key_fpr（16 進の指紋）が必要。鍵を確かめずに入れない")
    name = BUILD_NAME
    steps: list[model.Step] = [
        _host(["incus", "delete", "-f", name], "前回の一時の箱が残っていれば消す", check=False),
        _host(
            ["incus", "launch", opts.base_image, name, "-c", "security.nesting=true"],
            "一時の箱を作る",
        ),
        *opts.extra_steps,
        _box(["systemctl", "is-system-running", "--wait"], "起動の完了を待つ", check=False),
        _box(["apt-get", "update"], "apt の索引を更新する"),
        _box(["apt-get", "install", "-y", *APT_PACKAGES], "docker・Node・git などを入れる"),
        # NVIDIA の鍵は、指紋を確かめてから keyring に置く
        _box(["curl", "-fsSL", "-o", "/tmp/nvidia.asc", KEY_URL], "NVIDIA の鍵を取得する"),
        _sh(
            "gpg --show-keys --with-colons /tmp/nvidia.asc | awk -F: '/^fpr/{print $10}' "
            f"| grep -qx {fpr}",
            "鍵の指紋を確かめる（一致しなければ止める）",
        ),
        _box(
            ["gpg", "--dearmor", "--yes", "-o", KEYRING, "/tmp/nvidia.asc"], "鍵を keyring に置く"
        ),
        _put("/etc/apt/sources.list.d/nvidia-container-toolkit.list", REPO_LINE),
        _box(["apt-get", "update"], "NVIDIA のリポジトリを読む"),
        _box(
            ["apt-get", "install", "-y", "nvidia-container-toolkit"],
            "nvidia-container-toolkit を入れる",
        ),
        _sh(
            f"id {model.BOX_USER} >/dev/null 2>&1 || useradd -m -u 1000 -s /bin/bash {model.BOX_USER}",
            "uid 1000 のユーザーを用意する",
        ),
        _box(["usermod", "-aG", "docker", model.BOX_USER], "docker グループへ入れる"),
        _put("/etc/ld.so.conf.d/wsl-lib.conf", LD_CONF),
        _box(["ldconfig"], "共有ライブラリの索引を更新する"),
        _put("/etc/docker/daemon.json", DOCKER_DAEMON_JSON),
        _put("/etc/systemd/system/box-cdi.service", CDI_UNIT),
        _box(
            ["systemctl", "enable", "box-cdi.service"],
            "CDI 生成のユニットを有効にする（起動のたびに実行）",
        ),
        _box(["npm", "install", "-g", pi_pkg], "pi を入れる"),
    ]
    if opts.dist_dir:
        # incus file push -r は、元のディレクトリ名のまま <宛先>/<名前> に置く（宛先が無いと Not Found。e2e で判明）。
        # 所定の名前（DIST_DEST）へは、箱の中で移す
        base = posixpath.basename(opts.dist_dir.rstrip("/"))
        steps.append(
            _host(
                ["incus", "file", "push", "-r", opts.dist_dir, f"{name}/opt/"],
                "pi の配布物を /opt へ入れる",
            )
        )
        if base != posixpath.basename(DIST_DEST):
            steps.append(
                _sh(
                    f"rm -rf {DIST_DEST} && mv /opt/{_shq(base)} {DIST_DEST}",
                    "配布物を所定の場所へ移す",
                )
            )
        steps.append(_box(["chown", "-R", "root:root", DIST_DEST], "配布物の所有者を root にする"))
    steps += [
        *opts.cleanup_steps,
        _box(["apt-get", "clean"], "apt のキャッシュを消す"),
        _host(["incus", "stop", name], "一時の箱を止める"),
        _host(
            ["incus", "image", "delete", opts.alias], "同名の古いテンプレートを消す", check=False
        ),
        _host(["incus", "publish", name, "--alias", opts.alias], "テンプレートとして公開する"),
        _host(["incus", "delete", name], "一時の箱を消す"),
    ]
    return model.Plan(verb="template", box=name, steps=tuple(steps))

"""テンプレート（箱の元になるイメージ）を作る計画。純粋な関数だけ（実行は親が実機で行う）。

一時の箱 box-template-build を images:ubuntu/24.04 から作り、docker・NVIDIA Container Toolkit・Node・git・pi の配布物を入れて
incus publish し、一時の箱を消す。CDI の定義はドライバの更新でパスが変わるので、箱の起動のたびに生成する（systemd ユニット）。
本体は dotfiles 固有のものを import しない。pi の配布物は、作成済みのディレクトリのパスだけを受け取る。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from box import model

BUILD_NAME = "box-template-build"
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
    nvidia_key_fpr: str = ""  # NVIDIA の鍵の指紋（必須。公式の公開値を呼び出し側が渡す）
    dist_dir: str | None = None  # adapters で作った pi の配布物のディレクトリ（ホスト側）
    extra_steps: Sequence[
        model.Step
    ] = ()  # W2 の net.plan から受け取る（proxy の環境変数など）。起動の直後に入る
    base_image: str = BASE_IMAGE


def _host(argv: Sequence[str], desc: str, *, check: bool = True) -> model.Op:
    return model.Op(where="host", argv=tuple(argv), desc=desc, check=check)


def _box(argv: Sequence[str], desc: str, *, check: bool = True) -> model.Op:
    return model.Op(where="box", argv=tuple(argv), desc=desc, check=check)


def _sh(script: str, desc: str, *, check: bool = True) -> model.Op:
    return _box(["sh", "-c", script], desc, check=check)


def _put(path: str, content: str, mode: str = "0644") -> model.FilePut:
    return model.FilePut(where="box", path=path, mode=mode, owner="root:root", content=content)


def plan_build(opts: TemplateOpts) -> model.Plan:
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
        _box(["npm", "install", "-g", PI_PACKAGE], "pi を入れる"),
    ]
    if opts.dist_dir:
        steps += [
            _host(
                ["incus", "file", "push", "-r", opts.dist_dir, f"{name}{DIST_DEST}"],
                "pi の配布物を入れる",
            ),
            _box(["chown", "-R", "root:root", DIST_DEST], "配布物の所有者を root にする"),
        ]
    steps += [
        _box(["apt-get", "clean"], "apt のキャッシュを消す"),
        _host(["incus", "stop", name], "一時の箱を止める"),
        _host(
            ["incus", "image", "delete", opts.alias], "同名の古いテンプレートを消す", check=False
        ),
        _host(["incus", "publish", name, "--alias", opts.alias], "テンプレートとして公開する"),
        _host(["incus", "delete", name], "一時の箱を消す"),
    ]
    return model.Plan(verb="template", box=name, steps=tuple(steps))

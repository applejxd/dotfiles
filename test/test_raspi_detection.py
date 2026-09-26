"""実機で踏んだ 4 件の不具合に対する回帰テスト。

いずれも「描画結果を見れば分かるのに、検査していなかったので通り抜けた」もの。
詳細な経緯は docs/change/closed/0008-raspi-branching.md を参照。

1. Raspberry Pi の判定が `/etc/rpi-issue` だけで、実機 (Ubuntu for Raspberry Pi)
   に当たらなかった
2. 判定を `chezmoi.toml` の `[data]` に置いたため、`chezmoi update` では
   更新されず分岐が発動しなかった
3. `all_compile` の範囲が広すぎて ruby までソースビルドになった
4. Go テンプレートのコメント内に `*/` を書いて描画が壊れた
   (`.chezmoi.toml.tmpl` は lint の除外対象なので検出されなかった)

**ホスト非依存にすること。** `is-raspi` は `/proc/device-tree/model` などを
`stat` するので、Raspberry Pi 上でこのテストを走らせると自動判定は常に true に
なる。データ上書き (`is_raspi`) は `stat` より先に短絡するので、どのホストでも
決定的に判定できる。自動判定に頼る否定ケースだけ、Pi 実機ではスキップする。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "home"
IGNORE_TEMPLATE = HOME / ".chezmoiignore.tmpl"
CONFIG_TEMPLATE = HOME / ".chezmoi.toml.tmpl"
MISE_TEMPLATE = HOME / "dot_config" / "mise" / "config.toml.tmpl"
IS_RASPI_TEMPLATE = HOME / ".chezmoitemplates" / "is-raspi"

# このホスト自身が Raspberry Pi だと、自動判定の否定ケースが成立しない
HOST_LOOKS_LIKE_PI = (
    Path("/proc/device-tree/model").exists() or Path("/etc/rpi-issue").exists()
)
skip_on_pi = pytest.mark.skipif(
    HOST_LOOKS_LIKE_PI,
    reason="実機が Raspberry Pi だと自動判定が true になり否定ケースを検証できない",
)


def chezmoi_bin() -> str:
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
    return chezmoi


def context(
    *,
    os_name: str = "linux",
    username: str = "applejxd",
    osrelease: str = "6.8.0-45-generic",
    is_raspi: bool | None = None,
    home: str = "/home/applejxd",
) -> dict:
    """描画コンテキストを組み立てる。`is_raspi` は None なら鍵ごと省く。"""
    data: dict = {
        "chezmoi": {
            "os": os_name,
            "username": username,
            "homeDir": home,
            "kernel": {"osrelease": osrelease},
        }
    }
    if is_raspi is not None:
        data["is_raspi"] = is_raspi
    return data


def render(template: Path, ctx: dict) -> str:
    """`with ... | fromJson` で文脈を丸ごと差し替えて描画する。

    `--override-data` だと実ホストのデータが混ざり、判定がホスト依存になる。
    """
    source = (
        "{{ with "
        + json.dumps(json.dumps(ctx))
        + " | fromJson }}\n"
        + template.read_text(encoding="utf-8-sig")
        + "\n{{ end }}"
    )
    result = subprocess.run(
        [chezmoi_bin(), "--source", str(ROOT), "execute-template", "--skip-secrets"],
        input=source,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"描画に失敗した:\n{result.stderr}"
    return result.stdout


def detect(ctx: dict) -> bool:
    """`is-raspi` 単体を評価する。"""
    probe = "{{ includeTemplate \"is-raspi\" . }}"
    source = (
        "{{ with " + json.dumps(json.dumps(ctx)) + " | fromJson }}" + probe + "{{ end }}"
    )
    result = subprocess.run(
        [chezmoi_bin(), "--source", str(ROOT), "execute-template"],
        input=source,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"描画に失敗した:\n{result.stderr}"
    return result.stdout.strip() == "true"


# ---------------------------------------------------------------------------
# 事故 1: Raspberry Pi の判定
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "osrelease"),
    [
        # 実機。Ubuntu for Raspberry Pi は -raspi フレーバー。
        # /etc/rpi-issue を持たないので、これを拾えないと判定が外れる
        ("Ubuntu for Raspberry Pi", "5.15.0-1034-raspi"),
        ("Ubuntu for Raspberry Pi (新)", "6.8.0-1021-raspi"),
        # Raspberry Pi OS は +rpt-rpi- を含む
        ("Raspberry Pi OS 64bit", "6.12.34+rpt-rpi-2712"),
        ("Raspberry Pi OS (別モデル)", "6.6.51+rpt-rpi-v8"),
    ],
)
def test_kernel_name_identifies_raspberry_pi(label, osrelease):
    """カーネル名だけで Raspberry Pi と判定できる。

    当初は `/etc/rpi-issue` だけを見ており、Raspberry Pi OS 専用の
    このファイルを持たない実機 (Ubuntu for Raspberry Pi) で判定が外れた。
    """
    assert detect(context(osrelease=osrelease)) is True, f"{label} を拾えていない"


@skip_on_pi
@pytest.mark.parametrize(
    "osrelease",
    [
        "6.8.0-45-generic",  # 素の Ubuntu
        "6.6.87.2-microsoft-standard-WSL2",  # WSL2
        "6.1.0-18-amd64",  # Debian
    ],
)
def test_ordinary_linux_is_not_raspberry_pi(osrelease):
    """Raspberry Pi でない Linux を誤検出しない。"""
    assert detect(context(osrelease=osrelease)) is False


@skip_on_pi
@pytest.mark.parametrize("os_name", ["darwin", "windows"])
def test_non_linux_is_never_raspberry_pi(os_name):
    """Linux 以外では判定に入らない (`.chezmoi.kernel` が無くても壊れない)。"""
    ctx = {"chezmoi": {"os": os_name, "username": "applejxd", "homeDir": "/home/x"}}
    assert detect(ctx) is False


@pytest.mark.parametrize("forced", [True, False])
def test_data_override_wins_over_detection(forced):
    """`is_raspi` を渡したら検出より優先する。

    テストと手動での強制に使う。`stat` より先に短絡するので、
    どのホストで走らせても結果が変わらない。
    """
    # 検出が真になるカーネル名を渡しても、上書きが勝つ
    assert detect(context(osrelease="6.8.0-1021-raspi", is_raspi=forced)) is forced


# ---------------------------------------------------------------------------
# 事故 2: 判定を [data] に置くと chezmoi update で更新されない
# ---------------------------------------------------------------------------


def test_config_template_does_not_emit_is_raspi():
    """`chezmoi.toml` に `is_raspi` を書き戻さない。

    `[data]` へ置くと値が書かれるのは `chezmoi init` のときだけで、
    普段使う `chezmoi update` では更新されない。実機ではこれで分岐が
    1 つも発動しなかった。判定は `.chezmoitemplates/is-raspi` が単一ソース。
    """
    result = subprocess.run(
        [chezmoi_bin(), "--source", str(ROOT), "execute-template", "--init"],
        input=CONFIG_TEMPLATE.read_text(encoding="utf-8-sig"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "is_raspi" not in result.stdout


def test_detection_lives_in_shared_template():
    """判定の実体が共有テンプレート側にある。"""
    body = IS_RASPI_TEMPLATE.read_text(encoding="utf-8")
    for marker in ("/proc/device-tree/model", "raspi", "-rpi-", "/etc/rpi-issue"):
        assert marker in body, f"{marker} を見ていない"


def test_detection_works_without_any_config_data():
    """設定データが一切無くても判定できる。

    これが「`chezmoi update` だけで効く」ことの本体。`[data]` に依存すると
    `chezmoi init` を通すまで値が現れず、実機では分岐が 1 つも発動しなかった。
    ここで渡す文脈に `is_raspi` は入っていない。
    """
    assert detect(context(osrelease="6.8.0-1021-raspi")) is True


def test_no_template_depends_on_is_raspi_data():
    """`is_raspi` をデータとして直接読むテンプレートを増やさない。

    参照側が `.is_raspi` を直に見ると、また `chezmoi init` 依存に戻る。
    分岐したいテンプレートは必ず `includeTemplate "is-raspi"` を通す。
    上書き用の鍵を解釈してよいのは共有テンプレートだけ。
    """
    offenders = []
    for path in sorted(HOME.rglob("*.tmpl")):
        if "is_raspi" in path.read_text(encoding="utf-8-sig"):
            offenders.append(path.relative_to(HOME).as_posix())
    assert offenders == [], (
        "`.is_raspi` を直接読んでいる。includeTemplate \"is-raspi\" を使うこと: "
        + ", ".join(offenders)
    )


def test_branching_templates_go_through_shared_template():
    """raspi 分岐を持つテンプレートが共有テンプレート経由になっている。"""
    for template in (IGNORE_TEMPLATE, MISE_TEMPLATE):
        body = template.read_text(encoding="utf-8-sig")
        assert 'includeTemplate "is-raspi"' in body, f"{template.name} が経由していない"


# ---------------------------------------------------------------------------
# 事故 3: all_compile の範囲が広すぎた
# ---------------------------------------------------------------------------


def test_mise_never_uses_all_compile():
    """`all_compile` は使わない。

    「全言語でプリコンパイル済みバイナリを使わない」設定で、目的の
    Tkinter (Python) に対して範囲が広すぎる。実機では ruby がソース
    ビルドになり 956 秒かけて失敗し、apply が停止した。

    生文字列ではなくキーを見る (「使わない理由」をコメントに書くため)。
    """
    for is_raspi in (True, False):
        settings = tomllib.loads(render(MISE_TEMPLATE, context(is_raspi=is_raspi)))
        assert "all_compile" not in settings.get("settings", {})


def test_mise_compiles_python_only_off_raspi():
    """Raspberry Pi 以外では Python だけソースビルドにする。"""
    rendered = render(MISE_TEMPLATE, context(is_raspi=False))
    config = tomllib.loads(rendered)
    assert config["settings"]["python"]["compile"] is True
    assert "ruby" not in config["settings"]


def test_mise_keeps_ruby_prebuilt_on_raspi():
    """Raspberry Pi では ruby をプレビルド限定にする。

    mise は既定で jdx/ruby のプレビルド (arm64 Linux 向けもある) を使い、
    無いときだけ ruby-build へ落ちる。Pi でそこへ落ちると十数分かけてから
    失敗するので、`compile = false` で即エラーにする。
    """
    rendered = render(MISE_TEMPLATE, context(is_raspi=True))
    config = tomllib.loads(rendered)
    assert config["settings"]["ruby"]["compile"] is False
    assert "python" not in config["settings"]


@pytest.mark.parametrize("is_raspi", [True, False])
def test_mise_declares_ruby_everywhere(is_raspi):
    """ruby と tmuxinator は Raspberry Pi でも宣言する。

    一度「Pi では ruby を外す」と判断したが、プレビルドが存在すると
    分かったので撤回した。再発すると tmuxinator の設定だけ配られて
    本体が無い状態になる。
    """
    config = tomllib.loads(render(MISE_TEMPLATE, context(is_raspi=is_raspi)))
    assert config["tools"]["ruby"] == "latest"
    assert config["tools"]["gem:tmuxinator"] == "latest"


def test_mise_drops_gpu_tool_on_raspi():
    """NVIDIA GPU 前提のツールは Raspberry Pi で宣言しない。"""
    assert "nvitop" not in render(MISE_TEMPLATE, context(is_raspi=True))
    assert "nvitop" in render(MISE_TEMPLATE, context(is_raspi=False))


# ---------------------------------------------------------------------------
# 事故 4: テンプレートが描画できない (lint の除外対象で気づけなかった)
# ---------------------------------------------------------------------------


def test_config_template_renders_as_valid_toml():
    """`.chezmoi.toml.tmpl` が描画でき、TOML として読める。

    このファイルは `lint_templates.py` の除外対象なので、壊れても lint では
    捕まらない。実際にコメント内の `*/` が Go テンプレートのコメントを
    早期終了させ、`comment ends before closing delimiter` で落ちた。
    """
    result = subprocess.run(
        [chezmoi_bin(), "--source", str(ROOT), "execute-template", "--init"],
        input=CONFIG_TEMPLATE.read_text(encoding="utf-8-sig"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    tomllib.loads(result.stdout)


@pytest.mark.parametrize("template", [IGNORE_TEMPLATE, CONFIG_TEMPLATE])
def test_template_comments_have_no_closing_delimiter(template):
    """Go テンプレートのコメント内に `*/` を置かない。

    `{{/* ... */}}` の中に `**/etc/...` のような `*/` があると、そこで
    コメントが閉じて残りが構文エラーになる。
    """
    body = template.read_text(encoding="utf-8-sig")
    for block in body.split("{{- /*")[1:]:
        comment = block.split("*/")[0]
        assert "*" not in comment.replace("**", "") or "/" not in comment, (
            f"{template.name} のコメントに `*/` が入りかけている"
        )


# ---------------------------------------------------------------------------
# 分岐の帰結: Raspberry Pi で何を展開しないか
# ---------------------------------------------------------------------------

RASPI_EXCLUDED = (
    ".chezmoiscripts/100_linux/110_native/",
    ".config/i3/",
    ".config/polybar/",
    ".Xmodmap",
    ".xsession",
    ".xsessionrc",
)


def ignore_entries(ctx: dict) -> set[str]:
    return {
        line.strip()
        for line in render(IGNORE_TEMPLATE, ctx).splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


@pytest.mark.parametrize("target", RASPI_EXCLUDED)
def test_raspi_excludes_gui_assets(target):
    """ヘッドレスの Raspberry Pi に GUI 資産と VS Code を配らない。"""
    assert target in ignore_entries(context(is_raspi=True))


@pytest.mark.parametrize("target", RASPI_EXCLUDED)
def test_ordinary_linux_keeps_gui_assets(target):
    """Raspberry Pi 以外の native Linux では従来どおり配る。"""
    assert target not in ignore_entries(context(is_raspi=False))


def test_wsl_script_is_excluded_on_native_linux():
    """WSL 専用スクリプトを native Linux で走らせない。

    無視パターンが `190_wsl.sh` と書かれていたがターゲット名は
    `120_wsl.sh` で、一致せず native Linux でも `/etc/wsl.conf` を
    書いていた。
    """
    entries = ignore_entries(context(is_raspi=False))
    assert ".chezmoiscripts/100_linux/120_wsl.sh" in entries

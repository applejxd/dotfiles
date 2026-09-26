"""`.chezmoiignore.tmpl` と `.chezmoi.toml.tmpl` の描画結果を検証する。

どちらも chezmoi が apply の最初に読むファイルで、壊れると apply 全体が
止まる。環境差 (Bitwarden のセッション、system Python のバージョン) で
分岐する箇所を、ここで条件ごとに固定する。
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IGNORE_TEMPLATE = ROOT / "home" / ".chezmoiignore.tmpl"
CONFIG_TEMPLATE = ROOT / "home" / ".chezmoi.toml.tmpl"
BITWARDEN_TARGETS = (".config/git/user", ".config/sops/age/keys.txt")


def chezmoi_bin() -> str:
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
    return chezmoi


def render(*, home: str, username: str = "applejxd", bw_session: str = "") -> set[str]:
    context = {
        "chezmoi": {
            "os": "linux",
            "username": username,
            "homeDir": home,
            "kernel": {"osrelease": "Linux"},
        }
    }
    template = (
        "{{ with " + json.dumps(json.dumps(context)) + " | fromJson }}\n"
        + IGNORE_TEMPLATE.read_text(encoding="utf-8")
        + "\n{{ end }}"
    )
    env = dict(os.environ)
    if bw_session:
        env["BW_SESSION"] = bw_session
    else:
        env.pop("BW_SESSION", None)
    result = subprocess.run(
        [chezmoi_bin(), "--source", str(ROOT), "execute-template"],
        input=template,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return {line.strip() for line in result.stdout.splitlines()}


@pytest.mark.parametrize("target", BITWARDEN_TARGETS)
def test_bitwarden_targets_are_skipped_without_session(tmp_path, target):
    """未ログインの環境で apply が止まらないよう、セッションが無ければ無視する。"""
    assert target in render(home=str(tmp_path))


@pytest.mark.parametrize("target", BITWARDEN_TARGETS)
def test_bitwarden_targets_expand_with_session(tmp_path, target):
    """セッションがあり未展開なら、無視せず展開対象にする。"""
    assert target not in render(home=str(tmp_path), bw_session="dummy-session")


@pytest.mark.parametrize("target", BITWARDEN_TARGETS)
def test_bitwarden_targets_are_expanded_only_once(tmp_path, target):
    """展開済みなら、セッションがあっても引き直さない (diff のたびの解錠を防ぐ)。"""
    path = tmp_path / target
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    assert target in render(home=str(tmp_path), bw_session="dummy-session")


@pytest.mark.parametrize("target", BITWARDEN_TARGETS)
def test_bitwarden_targets_are_personal_only(tmp_path, target):
    """個人 PC 以外では Bitwarden 由来のファイルを置かない。"""
    assert target in render(home=str(tmp_path), username="other", bw_session="dummy")


def render_config(*, path_dir: Path | None = None) -> str:
    """`.chezmoi.toml.tmpl` を --init で描画する。

    ``path_dir`` を渡すと PATH をそのディレクトリだけに差し替えるので、
    ``lookPath`` が何を見つけるかをテスト側で決められる。
    """
    chezmoi = chezmoi_bin()
    env = dict(os.environ)
    if path_dir is not None:
        env["PATH"] = str(path_dir)
    result = subprocess.run(
        [chezmoi, "--source", str(ROOT), "execute-template", "--init"],
        input=CONFIG_TEMPLATE.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def fake_executables(directory: Path, names: list[str]) -> Path:
    bin_dir = directory / "bin"
    bin_dir.mkdir()
    for name in names:
        target = bin_dir / name
        target.write_text("#!/bin/sh\n", encoding="utf-8")
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
    return bin_dir


def interpreter_command(rendered: str) -> str:
    lines = rendered.splitlines()
    index = lines.index("[interpreters.py]")
    return lines[index + 1].strip()


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        (["python3", "python3.11"], 'command = "python3.11"'),
        (["python3", "python3.11", "python3.13"], 'command = "python3.13"'),
        (["python3.12", "python3.14"], 'command = "python3.14"'),
    ],
)
def test_interpreter_prefers_newest_versioned_python(tmp_path, available, expected):
    """PATH に 3.11 以上があれば、その中で最も新しいものを使う。

    system の python3 が 3.10 以下だと modify script が
    `No module named 'tomllib'` で落ち、apply 全体が止まるため。
    バージョン無しの `python3` だけの場合は shim へ倒す
    (下の test_interpreter_falls_back_to_shim_without_modern_python)。
    """
    bin_dir = fake_executables(tmp_path, available)
    assert interpreter_command(render_config(path_dir=bin_dir)) == expected


@pytest.mark.parametrize("available", [[], ["python3"], ["python3", "python3.10"]])
def test_interpreter_falls_back_to_shim_without_modern_python(tmp_path, available):
    """3.11 以上が PATH に無ければ、005 が張る shim の絶対パスを指す。

    この設定が焼かれるのは `chezmoi init` の瞬間で、まっさらな機械では
    まだ 3.11 以上が無い。後から uv で入る Python は PATH に出ないので、
    `python3` を指したままだと modify script が全滅する
    (素の Ubuntu で実測: 残差分 16 件すべて modify)。
    `python3` が 3.10 の Ubuntu 22.04 でも同じ結末になる。
    """
    bin_dir = fake_executables(tmp_path, available)
    command = interpreter_command(render_config(path_dir=bin_dir))
    assert command.endswith('/.local/bin/chezmoi-python3"'), command
    # chezmoi は直接 exec するので、~ ではなく絶対パスである必要がある
    assert 'command = "/' in command, command

    # 設定側と用意する側 (005) のパス一致は
    # test/agents/test_python_requirement.py が検査する (同じことを二度書かない)

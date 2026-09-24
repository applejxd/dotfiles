"""`.chezmoiignore.tmpl` の展開範囲を検証する。

Bitwarden 由来のファイルは、セッションが無いと `bw unlock` が走って
`chezmoi apply` 全体を落とす。無視されるのは「展開済み」か「セッションが無い」
ときだけ、という条件をここで固定する。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "home" / ".chezmoiignore.tmpl"
BITWARDEN_TARGETS = (".config/git/user", ".config/sops/age/keys.txt")


def render(*, home: str, username: str = "applejxd", bw_session: str = "") -> set[str]:
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
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
        + TEMPLATE.read_text(encoding="utf-8")
        + "\n{{ end }}"
    )
    env = dict(os.environ)
    if bw_session:
        env["BW_SESSION"] = bw_session
    else:
        env.pop("BW_SESSION", None)
    result = subprocess.run(
        [chezmoi, "--source", str(ROOT), "execute-template"],
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

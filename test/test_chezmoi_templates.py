"""`.chezmoiignore.tmpl` / `.chezmoi.toml.tmpl` / `.chezmoiexternal.toml.tmpl` の
描画結果を検証する。

いずれも chezmoi が apply の最初に読むファイルで、壊れると apply 全体が
止まる。環境差 (Bitwarden のセッション、system Python のバージョン、
既に clone 済みのプラグイン) で分岐する箇所を、ここで条件ごとに固定する。
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IGNORE_TEMPLATE = ROOT / "home" / ".chezmoiignore.tmpl"
CONFIG_TEMPLATE = ROOT / "home" / ".chezmoi.toml.tmpl"
EXTERNAL_TEMPLATE = ROOT / "home" / ".chezmoiexternal.toml.tmpl"
BITWARDEN_TARGETS = (".config/git/user", ".config/sops/age/keys.txt")


def chezmoi_bin() -> str:
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
    return chezmoi


def execute_with_context(template_path: Path, context: dict, env: dict[str, str]) -> str:
    """``.chezmoi`` を ``context`` に差し替えてテンプレートを描画する。"""
    template = (
        "{{ with " + json.dumps(json.dumps(context)) + " | fromJson }}\n"
        + template_path.read_text(encoding="utf-8")
        + "\n{{ end }}"
    )
    result = subprocess.run(
        [chezmoi_bin(), "--source", str(ROOT), "execute-template"],
        input=template,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def render(
    *, home: str, username: str = "applejxd", bw_session: str = "", os_name: str = "linux"
) -> set[str]:
    context = {
        "chezmoi": {
            "os": os_name,
            "username": username,
            "homeDir": home,
            "kernel": {"osrelease": "Linux"},
        }
    }
    env = dict(os.environ)
    if bw_session:
        env["BW_SESSION"] = bw_session
    else:
        env.pop("BW_SESSION", None)
    rendered = execute_with_context(IGNORE_TEMPLATE, context, env)
    return {line.strip() for line in rendered.splitlines()}


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


@pytest.mark.parametrize(
    "target",
    ["!.config/opencode/", "!.config/opencode/**"],
)
def test_opencode_config_is_deployed_on_windows(tmp_path, target):
    """Windows でも OpenCode の permission と guide plugin を配る。

    314 が OpenCode を入れるのに設定が .config/* の除外に巻き込まれると、
    読み取り禁止も shell の制限も効かないまま動く。
    """
    rendered = render(home=str(tmp_path), os_name="windows")
    assert ".config/*" in rendered
    assert target in rendered


def test_git_user_and_ignore_are_deployed_on_windows(tmp_path):
    """★~/.gitconfig が [include] で読む ~/.config/git/ を Windows でも配る。

    Windows は .config/* を丸ごと除外しているので、戻さないと user.name / email と
    global ignore が無いままになる (b414b54 で [user] を分けたときの退行)。
    """
    rendered = render(home=str(tmp_path), os_name="windows", bw_session="session")
    assert "!.config/git/" in rendered
    # /** で戻すと Bitwarden 由来の user を毎回描画してしまう
    assert "!.config/git/**" not in rendered


def test_git_user_is_still_rendered_once_on_windows(tmp_path):
    """Windows でも、BW_SESSION が無い間と展開済みの後は user を描画しない。"""
    assert ".config/git/user" in render(home=str(tmp_path), os_name="windows")
    (tmp_path / ".config" / "git").mkdir(parents=True)
    (tmp_path / ".config" / "git" / "user").write_text("x", encoding="utf-8")
    assert ".config/git/user" in render(home=str(tmp_path), os_name="windows", bw_session="s")


@pytest.mark.parametrize(
    ("os_name", "ignored"), [("linux", False), ("windows", True), ("darwin", True)]
)
def test_ocs_launcher_is_linux_only(tmp_path, os_name, ignored):
    """ocs は bwrap で OpenCode を囲うので Ubuntu / WSL 専用 (CHG-0004)。"""
    rendered = render(home=str(tmp_path), os_name=os_name)
    targets = (
        ".local/bin/ocs",
        ".local/bin/ocs-boundary-check",
        ".local/share/ocs",
        ".local/share/ocs/**",
    )
    for target in targets:
        assert (target in rendered) is ignored, target


SHELL_PLUGINS = {
    ".z": ("git-repo", "https://github.com/rupa/z.git"),
    ".zinit/bin": ("git-repo", "https://github.com/zdharma-continuum/zinit.git"),
    ".bash_it": ("git-repo", "https://github.com/Bash-it/bash-it.git"),
    ".tmux/plugins/tpm": ("git-repo", "https://github.com/tmux-plugins/tpm.git"),
    ".vim/colors/iceberg.vim": (
        "file",
        "https://raw.githubusercontent.com/cocopon/iceberg.vim/master/colors/iceberg.vim",
    ),
}
SHELL_RC_FILES = (
    "home/dot_config/shell/shellrc.sh.tmpl",
    "home/dot_zshrc.tmpl",
    "home/dot_bashrc",
)


def render_external(*, home: Path, os_name: str = "linux") -> dict:
    context = {"chezmoi": {"os": os_name, "homeDir": str(home)}}
    return tomllib.loads(execute_with_context(EXTERNAL_TEMPLATE, context, dict(os.environ)))


@pytest.mark.parametrize("os_name", ["linux", "darwin"])
def test_shell_plugins_are_cloned_by_apply(tmp_path, os_name):
    """シェル起動時に clone していたものを apply 側で取得する。"""
    externals = render_external(home=tmp_path, os_name=os_name)
    assert set(externals) == set(SHELL_PLUGINS)
    for target, (kind, url) in SHELL_PLUGINS.items():
        assert externals[target]["type"] == kind
        assert externals[target]["url"] == url


def test_shell_plugins_are_not_fetched_on_windows(tmp_path):
    """Windows native には zsh / bash / tmux の rc を配らない。"""
    assert render_external(home=tmp_path, os_name="windows") == {}


EXISTING_PLUGIN_CASES = [
    # 既存の clone。宣言すると初回 apply で git pull が走る
    *(
        pytest.param(target, "dir", id=f"{target}-clone")
        for target, (kind, _) in SHELL_PLUGINS.items()
        if kind == "git-repo"
    ),
    # rupa/z 既定のデータファイル ~/.z。宣言すると chezmoi が消してから pull に失敗する
    pytest.param(".z", "file", id=".z-data-file"),
    pytest.param(".vim/colors/iceberg.vim", "file", id="iceberg.vim"),
]


@pytest.mark.parametrize(("target", "kind"), EXISTING_PLUGIN_CASES)
def test_existing_plugin_paths_are_left_alone(tmp_path, target, kind):
    """既に在るパスは宣言しない。

    git-repo は既存ディレクトリに初回 apply で git pull を走らせ、
    失敗 (bash-it update 後の detached HEAD など) すると apply が毎回止まる。
    ファイルがあれば chezmoi はそれを消した上で pull に失敗する
    (rupa/z 既定のデータファイル ~/.z が消える)。
    """
    path = tmp_path / target
    if kind == "dir":
        (path / ".git").mkdir(parents=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    externals = render_external(home=tmp_path)
    assert target not in externals
    assert set(externals) == set(SHELL_PLUGINS) - {target}


@pytest.mark.parametrize("rc_file", SHELL_RC_FILES)
def test_shell_rc_does_not_clone(rc_file):
    """シェルの起動をネットワークと書き込み失敗に依存させない。"""
    assert "git clone" not in (ROOT / rc_file).read_text(encoding="utf-8")


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
        encoding="utf-8",
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

"""導入スクリプトの回帰テスト。

1. リポジトリ自身への raw URL が実在しないパスを指し、初回導入が 404 で止まった
2. omp の設定取得に失敗すると空配列とみなし、既存の登録を上書きしていた
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "home"
SCRIPTS = HOME / ".chezmoiscripts" / "400_unix"
OMP_SKILLS = SCRIPTS / "run_onchange_after_420_omp_skills.sh"
OMP_CLAUDE_ASSETS = SCRIPTS / "run_onchange_after_430_omp_claude_assets.sh"

SELF_URL = re.compile(
    r"(?:raw\.githubusercontent\.com/applejxd/dotfiles"
    r"|github\.com/applejxd/dotfiles/(?:blob|raw|tree))"
    r"/(?:refs/heads/)?[^/\s]+/([^\s\"'<>)`]+)"
)
WORKING_TREE_PATH = re.compile(r"joinPath \.chezmoi\.workingTree((?: \"[^\"]+\")+)")


def tracked_text_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    files = []
    for name in result.stdout.splitlines():
        path = ROOT / name
        if path.is_file():
            files.append(path)
    return files


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return None


# ---------------------------------------------------------------------------
# 事故 1: 自分自身への raw URL が 404
# ---------------------------------------------------------------------------


def test_self_raw_urls_point_to_existing_paths():
    """リポジトリ自身を指す URL は実在するパスを指す。

    `installer/osx/brew_mas_cask.rb` を取りに行っていたが、実体は
    `scripts/osx/` へ移っており 404 になった。`curl -f` と `set -e` で
    macOS の初回導入がそこで止まる。ソースツリー内のファイルを直接使うこと。
    """
    broken = []
    for path in tracked_text_files():
        body = read_text(path)
        if body is None:
            continue
        for match in SELF_URL.finditer(body):
            target = match.group(1).split("#")[0].split("?")[0]
            if not (ROOT / target).exists():
                rel = path.relative_to(ROOT).as_posix()
                broken.append(f"{rel}: {match.group(0)}")
    assert broken == [], "実在しないパスを指している:\n" + "\n".join(broken)


def test_working_tree_paths_in_templates_exist():
    """`joinPath .chezmoi.workingTree ...` で組んだパスが実在する。

    `.chezmoiroot` が `home` なので `.chezmoi.sourceDir` は `home/` を指す。
    リポジトリ直下のファイルは `workingTree` から辿る。
    """
    seen = 0
    missing = []
    for path in sorted(HOME.rglob("*.tmpl")):
        for match in WORKING_TREE_PATH.finditer(path.read_text(encoding="utf-8-sig")):
            parts = re.findall(r"\"([^\"]+)\"", match.group(1))
            seen += 1
            if not ROOT.joinpath(*parts).exists():
                missing.append(f"{path.relative_to(ROOT).as_posix()}: {'/'.join(parts)}")
    assert seen > 0, "検査対象が見つからない (正規表現が古い)"
    assert missing == [], "実在しないパス:\n" + "\n".join(missing)


# ---------------------------------------------------------------------------
# 事故 2: omp の設定取得に失敗すると既存の登録を消す
# ---------------------------------------------------------------------------

FAKE_OMP = """#!/bin/bash
set -eu
printf '%s\\n' "$*" >>"$OMP_LOG"
if [[ "$1" == config && "$2" == get ]]; then
    case "$OMP_GET" in
        fail) exit 1 ;;
        *) printf '%s\\n' "$OMP_GET" ;;
    esac
fi
"""


def run_with_fake_omp(tmp_path: Path, script: Path, get_output: str):
    """偽の omp を `~/.local/bin/omp` に置いてスクリプトを走らせる。"""
    if os.name == "nt":
        pytest.skip("Unix 向けスクリプト")
    if shutil.which("bash") is None or shutil.which("python3") is None:
        pytest.skip("bash / python3 が無い")
    home = tmp_path / "home"
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    omp = bin_dir / "omp"
    omp.write_text(FAKE_OMP, encoding="utf-8")
    omp.chmod(0o755)
    log = tmp_path / "omp.log"
    log.touch()
    env = {
        **os.environ,
        "HOME": str(home),
        "OMP_LOG": str(log),
        "OMP_GET": get_output,
    }
    result = subprocess.run(
        ["bash", str(script)],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    sets = [
        line.split(" ", 3)[2:]
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.startswith("config set ")
    ]
    return result, home, {key: value for key, value in sets}


def value_json(key: str, value) -> str:
    return json.dumps({"key": key, "value": value, "type": "array", "description": ""})


BROKEN_OUTPUTS = [
    pytest.param("fail", id="取得失敗"),
    pytest.param("not json", id="不正な JSON"),
    pytest.param('{"key": "x", "value": "oops"}', id="配列でない value"),
    pytest.param('{"key": "x"}', id="value が無い"),
]


@pytest.mark.parametrize("output", BROKEN_OUTPUTS)
@pytest.mark.parametrize("script", [OMP_SKILLS, OMP_CLAUDE_ASSETS], ids=["420", "430"])
def test_omp_broken_config_is_not_overwritten(tmp_path, script, output):
    """取得や解析に失敗したら `omp config set` を呼ばない。

    以前は空配列とみなし、登録対象だけの配列で既存の設定を上書きしていた。
    apply 全体は止めないので終了コードは 0 のまま、警告だけ出す。
    """
    result, _, sets = run_with_fake_omp(tmp_path, script, output)
    assert result.returncode == 0, result.stderr
    assert sets == {}
    assert "警告" in result.stderr


def test_omp_skills_registers_when_unset(tmp_path):
    """未設定 (`"value": []`) なら登録する。"""
    result, home, sets = run_with_fake_omp(
        tmp_path, OMP_SKILLS, value_json("skills.customDirectories", [])
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(sets["skills.customDirectories"]) == [str(home / ".claude" / "skills")]


def test_omp_skills_keeps_existing_entries(tmp_path):
    """既存のエントリは保ったまま追記する。"""
    result, home, sets = run_with_fake_omp(
        tmp_path, OMP_SKILLS, value_json("skills.customDirectories", ["/other"])
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(sets["skills.customDirectories"]) == [
        "/other",
        str(home / ".claude" / "skills"),
    ]


def test_omp_skills_skips_when_registered(tmp_path):
    """登録済みなら書き戻さない。"""
    home = tmp_path / "home"
    registered = value_json("skills.customDirectories", [str(home / ".claude" / "skills")])
    result, _, sets = run_with_fake_omp(tmp_path, OMP_SKILLS, registered)
    assert result.returncode == 0, result.stderr
    assert sets == {}


def test_omp_claude_assets_registers_when_unset(tmp_path):
    """未設定なら claude ソースを登録し、真偽値の初期値も置く。"""
    result, _, sets = run_with_fake_omp(
        tmp_path, OMP_CLAUDE_ASSETS, value_json("enabledProviders", [])
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(sets["enabledProviders"]) == ["claude"]
    assert sets["commands.enableClaudeUser"] == "true"
    assert sets["bashInterceptor.enabled"] == "true"


def test_omp_claude_assets_keeps_existing_entries(tmp_path):
    """path スコープ付きの dict など既存のエントリを保つ。"""
    scoped = {"name": "codex", "path": "/work"}
    result, _, sets = run_with_fake_omp(
        tmp_path, OMP_CLAUDE_ASSETS, value_json("enabledProviders", [scoped])
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(sets["enabledProviders"]) == [scoped, "claude"]


@pytest.mark.parametrize("existing", ["claude", "*", "all"])
def test_omp_claude_assets_skips_when_enabled(tmp_path, existing):
    """claude を含む指定が既にあれば enabledProviders を書き戻さない。"""
    result, _, sets = run_with_fake_omp(
        tmp_path, OMP_CLAUDE_ASSETS, value_json("enabledProviders", [existing])
    )
    assert result.returncode == 0, result.stderr
    assert "enabledProviders" not in sets

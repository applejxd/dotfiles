"""導入スクリプトの回帰テスト。

1. リポジトリ自身への raw URL が実在しないパスを指し、初回導入が 404 で止まった
2. omp の設定取得に失敗すると空配列とみなし、既存の登録を上書きしていた
3. omp が後から入っても run_onchange_ の中身が変わらず、設定が一度も入らなかった
4. macOS のスクリプトが sudo のパスワードを変数に持ち回り、Homebrew を入れる前に brew を使っていた
5. omp の設定の取得に失敗した回も成功として記録され、omp が直っても走り直さなかった
6. Homebrew の取得に失敗しても 205 が成功として記録され、次の apply で走り直さなかった
7. 再実行の印をエージェントが書ける場所に置き、symlink を追って書いていた
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "home"
SCRIPTS = HOME / ".chezmoiscripts" / "400_unix"
OMP_SKILLS = SCRIPTS / "run_onchange_after_420_omp_skills.sh.tmpl"
OMP_CLAUDE_ASSETS = SCRIPTS / "run_onchange_after_430_omp_claude_assets.sh.tmpl"
AGENT_CLI = HOME / ".chezmoiscripts" / "100_linux" / "run_onchange_after_126_agent_cli.sh.tmpl"
COMMON = HOME / "dot_config" / "agents" / "common.toml.tmpl"
RETRY_DIR = ".local/share/dotfiles/retry"
RETRY_MARKERS = {
    "agent-cli-failed": AGENT_CLI,
    "omp-skills-failed": OMP_SKILLS,
    "omp-claude-assets-failed": OMP_CLAUDE_ASSETS,
}
OMP_MARKERS = {OMP_SKILLS: "omp-skills-failed", OMP_CLAUDE_ASSETS: "omp-claude-assets-failed"}


def render_with_context(
    path: Path,
    *,
    home: Path | str = "/test-home",
    os_name: str = "linux",
    path_dir: Path | None = None,
) -> str:
    """``.chezmoi`` を明示の context に差し替えて描画する。

    ``path_dir`` を渡すと PATH をそのディレクトリだけにし、``lookPath`` の結果を決める。
    """
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi が無い")
    context = {"chezmoi": {"os": os_name, "username": "applejxd", "homeDir": str(home)}}
    template = (
        "{{ with " + json.dumps(json.dumps(context)) + " | fromJson }}\n"
        + path.read_text(encoding="utf-8-sig")
        + "\n{{ end }}"
    )
    env = dict(os.environ)
    if path_dir is not None:
        env["PATH"] = str(path_dir)
    result = subprocess.run(
        [chezmoi, "--source", str(ROOT), "execute-template"],
        input=template,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.lstrip("\n")

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


def run_with_fake_omp(tmp_path: Path, script: Path, get_output: str, *, home: Path | None = None):
    """偽の omp を `~/.local/bin/omp` に置き、描画したスクリプトを走らせる。"""
    if os.name == "nt":
        pytest.skip("Unix 向けスクリプト")
    if shutil.which("bash") is None or shutil.which("python3") is None:
        pytest.skip("bash / python3 が無い")
    home = home or tmp_path / "home"
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    omp = bin_dir / "omp"
    omp.write_text(FAKE_OMP, encoding="utf-8")
    omp.chmod(0o755)
    rendered = tmp_path / script.name.removesuffix(".tmpl")
    rendered.write_text(render_with_context(script, home=home), encoding="utf-8")
    log = tmp_path / "omp.log"
    log.touch()
    env = {
        **os.environ,
        "HOME": str(home),
        "OMP_LOG": str(log),
        "OMP_GET": get_output,
    }
    result = subprocess.run(
        ["bash", str(rendered)],
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


@pytest.mark.parametrize("script", [OMP_SKILLS, OMP_CLAUDE_ASSETS], ids=lambda p: p.name[:30])
def test_omp_scripts_rerun_once_omp_appears(tmp_path, script):
    """omp の有無で描画結果が変わること。変わらないと後から入れた omp を拾えない。

    `.chezmoi.homeDir` は context で渡し、PATH は空のディレクトリにして
    `lookPath` が手元の omp を拾わないようにする (Windows でも同じ条件で描画できる)。
    """
    home = tmp_path / "home"
    home.mkdir()
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()

    absent = render_with_context(script, home=home, path_dir=empty_path)
    omp = home / ".local" / "bin" / "omp"
    omp.parent.mkdir(parents=True)
    omp.write_text("#!/bin/sh\n", encoding="utf-8")
    omp.chmod(0o755)
    present = render_with_context(script, home=home, path_dir=empty_path)

    assert "# omp: absent" in absent
    assert "# omp: present" in present


# ---------------------------------------------------------------------------
# 事故 5: omp の設定の取得に失敗した回が成功として記録され、走り直さない
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("output", ["fail", "not json"])
@pytest.mark.parametrize("script", [OMP_SKILLS, OMP_CLAUDE_ASSETS], ids=["420", "430"])
def test_omp_broken_config_leaves_a_marker_for_the_next_apply(tmp_path, script, output):
    """★run_onchange_ は exit 0 だと記録され、omp の present / absent も変わらない。

    取得・解析に失敗した回は印を書き直し、その更新時刻で次の apply の中身を変える。
    """
    home = tmp_path / "home"
    assert "# retry-marker: none" in render_with_context(script, home=home)

    result, _, sets = run_with_fake_omp(tmp_path, script, output, home=home)

    assert result.returncode == 0, result.stderr
    assert sets == {}
    marker = home / RETRY_DIR / OMP_MARKERS[script]
    assert marker.is_file()
    assert "次の chezmoi apply" in result.stderr
    rerendered = render_with_context(script, home=home)
    assert f"# retry-marker: {int(marker.stat().st_mtime)}" in rerendered


@pytest.mark.parametrize("script", [OMP_SKILLS, OMP_CLAUDE_ASSETS], ids=["420", "430"])
def test_omp_success_does_not_touch_the_marker(tmp_path, script):
    """成功した回は印に触れない。触れると次の apply でまた走り直す。"""
    home = tmp_path / "home"
    marker = home / RETRY_DIR / OMP_MARKERS[script]
    marker.parent.mkdir(parents=True)
    marker.write_text("x\n", encoding="utf-8")
    os.utime(marker, (1_000_000_000, 1_000_000_000))
    registered = {
        OMP_SKILLS: value_json("skills.customDirectories", [str(home / ".claude" / "skills")]),
        OMP_CLAUDE_ASSETS: value_json("enabledProviders", ["claude"]),
    }[script]

    result, _, _ = run_with_fake_omp(tmp_path, script, registered, home=home)

    assert result.returncode == 0, result.stderr
    assert int(marker.stat().st_mtime) == 1_000_000_000


# ---------------------------------------------------------------------------
# 事故 7: 再実行の印をエージェントが書ける場所に置き、symlink を追って書いていた
# ---------------------------------------------------------------------------


def _expand(path: str, home: str) -> str:
    return home + path[1:] if path.startswith("~/") else path


def test_retry_markers_are_outside_every_agent_write_allow():
    """★印は apply (ホスト) が書く。エージェントの sandbox から書けると、印を
    ~/.bashrc などへの symlink に差し替えてホストに中身を書き潰させられる。"""
    home = "/test-home"
    common = tomllib.loads(render_with_context(COMMON, home=home))
    sandbox = common["sandbox"]
    writable = [
        *sandbox["claude_write_allow"],
        *sandbox["copilot_write_allow"],
        *common["opencode"]["sandbox"]["write"],
    ]
    for name, script in RETRY_MARKERS.items():
        rendered = render_with_context(script, home=home)
        assert f'retry_marker="${{HOME}}/{RETRY_DIR}/{name}"' in rendered, script.name
        marker = f"{home}/{RETRY_DIR}/{name}"
        for allowed in writable:
            allowed = _expand(allowed, home).rstrip("/")
            assert marker != allowed and not marker.startswith(allowed + "/"), (
                f"{name} が write 許可 {allowed} の内側にある"
            )


def test_the_omp_marker_content_is_never_embedded(tmp_path):
    """時刻だけを埋め込む。中身を埋め込むと改行を仕込まれたときにコードが入る。"""
    home = tmp_path / "home"
    marker = home / RETRY_DIR / OMP_MARKERS[OMP_SKILLS]
    marker.parent.mkdir(parents=True)
    marker.write_text("x\necho INJECTED\n", encoding="utf-8")
    assert "INJECTED" not in render_with_context(OMP_SKILLS, home=home)


@pytest.mark.skipif(os.name == "nt", reason="Unix のスクリプト")
@pytest.mark.parametrize("kind", ["symlink", "dangling-symlink"])
def test_the_marker_is_replaced_without_following_a_symlink(tmp_path, kind):
    """印が symlink になっていても、その先 (~/.bashrc など) を書き換えない。"""
    home = tmp_path / "home"
    victim = home / ".bashrc"
    victim.parent.mkdir(parents=True)
    if kind == "symlink":
        victim.write_text("keep me\n", encoding="utf-8")
    marker = home / RETRY_DIR / OMP_MARKERS[OMP_SKILLS]
    marker.parent.mkdir(parents=True)
    marker.symlink_to(victim)

    result, _, _ = run_with_fake_omp(tmp_path, OMP_SKILLS, "fail", home=home)

    assert result.returncode == 0, result.stderr
    assert not marker.is_symlink()
    assert marker.is_file()
    if kind == "symlink":
        assert victim.read_text(encoding="utf-8") == "keep me\n"
    else:
        assert not victim.exists()


MAC_SCRIPTS = HOME / ".chezmoiscripts" / "200_mac"
KEEPALIVE = HOME / ".chezmoitemplates" / "sudo-keepalive.sh.tmpl"


@pytest.mark.parametrize("script", sorted(MAC_SCRIPTS.glob("*.tmpl")), ids=lambda p: p.name)
def test_mac_scripts_do_not_carry_the_sudo_password(script):
    """パスワードは sudo 自身に尋ねさせ、変数やパイプで持ち回らない。"""
    text = script.read_text(encoding="utf-8")
    for pattern in ("$password", "${password}", "sudo -S", "expect ", "get_sudo_password"):
        assert pattern not in text, f"{script.name} に {pattern} が残っている"


def test_homebrew_is_installed_before_any_mac_script_uses_brew():
    """210 は冒頭で brew を使う。導入が後だと新しい Mac の初回の apply で失敗する。"""
    scripts = sorted(MAC_SCRIPTS.glob("*.tmpl"))
    installer = next(p for p in scripts if "Homebrew/install" in p.read_text(encoding="utf-8"))
    users = [
        p
        for p in scripts
        if p != installer and re.search(r"\bbrew\b", p.read_text(encoding="utf-8"))
    ]
    assert users
    for user in users:
        assert installer.name < user.name, f"{user.name} が {installer.name} より先に走る"


HOMEBREW = MAC_SCRIPTS / "run_once_after_205_homebrew.sh.tmpl"


def run_homebrew(tmp_path: Path, *, curl_ok: bool) -> subprocess.CompletedProcess:
    """curl / sudo / uname を差し替えて 205 を走らせる。brew は入らない。"""
    if os.name == "nt":
        pytest.skip("Unix のスクリプト")
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash が無い")
    if Path("/opt/homebrew/bin/brew").exists():
        pytest.skip("このマシンに Homebrew が入っている")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stubs = {
        "sudo": "exit 0",
        "uname": "echo arm64",
        # 取得に成功しても、中身は brew を置かないインストーラー
        "curl": "echo 'echo installer ran'" if curl_ok else "exit 22",
    }
    for name, body in stubs.items():
        stub = bindir / name
        stub.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        stub.chmod(0o755)
    script = tmp_path / "205.sh"
    script.write_text(render_with_context(HOMEBREW, os_name="darwin"), encoding="utf-8")
    return subprocess.run(
        [bash, str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PATH": f"{bindir}:/usr/bin:/bin"},
        check=False,
        timeout=30,
    )


@pytest.mark.parametrize("curl_ok", [False, True], ids=["取得失敗", "brew が入らない"])
def test_homebrew_failure_is_not_recorded_as_success(tmp_path, curl_ok):
    """★`bash -c "$(curl …)"` は curl が失敗しても `bash -c ""` として成功し、
    `eval "$(brew shellenv)"` も brew が無いと `eval ""` で成功する。
    0 で終わると run_once_ が記録され、次の apply で走り直さない。"""
    result = run_homebrew(tmp_path, curl_ok=curl_ok)
    assert result.returncode != 0, result.stdout + result.stderr


def run_keepalive(
    tmp_path: Path, *, sudo_ok: bool
) -> tuple[subprocess.CompletedProcess, list[str]]:
    """偽の sudo を置き、keepalive を 2 回呼んでから終わるスクリプトを走らせる。"""
    if shutil.which("bash") is None:
        pytest.skip("bash が無い")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "sudo.log"
    sudo = bindir / "sudo"
    rc = 0 if sudo_ok else 1
    sudo.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\nexit {rc}\n', encoding="utf-8")
    sudo.chmod(0o755)
    script = tmp_path / "run.sh"
    script.write_text(
        "set -euo pipefail\n"
        + KEEPALIVE.read_text(encoding="utf-8")
        + '\nstart_sudo_keepalive\nstart_sudo_keepalive\necho "$sudo_keepalive_pid"\n',
        encoding="utf-8",
    )
    env = {**os.environ, "PATH": f"{bindir}:/usr/bin:/bin"}
    result = subprocess.run(
        [shutil.which("bash"), str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
        timeout=30,
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return result, calls


@pytest.mark.skipif(os.name == "nt", reason="Unix のスクリプト")
def test_keepalive_asks_once_and_stops_with_the_script(tmp_path):
    result, calls = run_keepalive(tmp_path, sudo_ok=True)
    assert result.returncode == 0, result.stderr
    assert calls.count("-v") == 1, calls
    pid = int(result.stdout.strip())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("親が終わっても延長のループが残っている")


@pytest.mark.skipif(os.name == "nt", reason="Unix のスクリプト")
def test_keepalive_stops_the_script_when_authentication_fails(tmp_path):
    result, calls = run_keepalive(tmp_path, sudo_ok=False)
    assert result.returncode != 0
    assert calls == ["-v"]
    assert result.stdout.strip() == ""


def test_mise_self_update_does_not_wait_for_a_prompt():
    """mise self-update は確認を対話で尋ねる。--yes が無いと apply が入力待ちで止まる。"""
    for script in sorted((HOME / ".chezmoiscripts").rglob("*mise*")):
        for line in script.read_text(encoding="utf-8-sig").splitlines():
            if "mise self-update" in line and not line.lstrip().startswith("#"):
                assert "--yes" in line or "-y" in line.split(), f"{script.name}: {line.strip()}"

"""導入スクリプトの回帰テスト。

1. リポジトリ自身への raw URL が実在しないパスを指し、初回導入が 404 で止まった
4. macOS のスクリプトが sudo のパスワードを変数に持ち回り、Homebrew を入れる前に brew を使っていた
6. Homebrew の取得に失敗しても 205 が成功として記録され、次の apply で走り直さなかった
7. 再実行の印を symlink にされると、その先 (~/.bashrc など) を書き潰した
8. 再実行の印が前回と同じ秒だと描画が変わらず、親の経路の symlink を追い、
   印を置けなくても成功として記録されていた
(再実行の印の仕組み retry-marker.sh.tmpl は、失敗するだけの合成のスクリプトで見る)
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "home"
SCRIPTS = HOME / ".chezmoiscripts" / "400_unix"
AGENT_CLI = HOME / ".chezmoiscripts" / "100_linux" / "run_onchange_after_126_agent_cli.sh.tmpl"
RETRY_DIR = ".local/share/dotfiles/retry"
RETRY_MARKERS = {"agent-cli-failed": AGENT_CLI}
# 再実行の印の仕組み (retry-marker.sh.tmpl) だけを呼ぶ合成のスクリプト。失敗の理由を 1 つ渡して終わる
MARKER_NAME = "test-failed"
MARKER_REASON = "config get skills.customDirectories"
MARKER_HOST = (
    '{{ template "retry-marker.sh.tmpl" (dict "homeDir" .chezmoi.homeDir "name" "'
    + MARKER_NAME
    + '") }}\nmark_for_retry "'
    + MARKER_REASON
    + '"\n'
)


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
    context = {
        "chezmoi": {
            "os": os_name,
            "username": "applejxd",
            "homeDir": str(home),
            "workingTree": str(ROOT),
        }
    }
    template = (
        "{{ with "
        + json.dumps(json.dumps(context))
        + " | fromJson }}\n"
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
# 再実行の印の仕組み (retry-marker.sh.tmpl) を、合成のスクリプトで見る
# ---------------------------------------------------------------------------


def render_marker_host(home: Path) -> str:
    """合成のスクリプトを描画する (印の時刻が埋め込まれる)。"""
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi が無い")
    context = {"chezmoi": {"os": "linux", "username": "applejxd", "homeDir": str(home)}}
    template = (
        "{{ with " + json.dumps(json.dumps(context)) + " | fromJson }}" + MARKER_HOST + "{{ end }}"
    )
    result = subprocess.run(
        [chezmoi, "--source", str(ROOT), "execute-template"],
        input=template,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def run_marker_host(
    tmp_path: Path,
    *,
    home: Path | None = None,
    path_prefix: Path | None = None,
    extra_env: dict[str, str] | None = None,
):
    """合成のスクリプトを bash で走らせる。失敗の理由を渡して印を書き直させる。"""
    if os.name == "nt":
        pytest.skip("Unix 向けスクリプト")
    if shutil.which("bash") is None:
        pytest.skip("bash が無い")
    home = home or tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "marker_host.sh"
    script.write_text("#!/bin/bash\nset -euo pipefail\n" + render_marker_host(home), encoding="utf-8")
    env = {**os.environ, "HOME": str(home), **(extra_env or {})}
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        ["bash", str(script)], env=env, capture_output=True, text=True, encoding="utf-8", check=False
    )
    return result, home


def test_a_failure_leaves_a_marker_for_the_next_apply(tmp_path):
    """★run_onchange_ は exit 0 だと記録される。失敗した回は印を書き直し、その更新時刻で次の apply の中身を変える。"""
    home = tmp_path / "home"
    assert "# retry-marker: none" in render_marker_host(home)

    result, _ = run_marker_host(tmp_path, home=home)

    assert result.returncode == 0, result.stderr
    marker = home / RETRY_DIR / MARKER_NAME
    assert marker.is_file()
    assert marker.read_text(encoding="utf-8") == MARKER_REASON + "\n"
    assert f"# retry-marker: {int(marker.stat().st_mtime)}" in render_marker_host(home)


def test_a_success_does_not_touch_the_marker(tmp_path):
    """失敗しない回 (mark_for_retry を呼ばない) は印に触れない。触れると次の apply でまた走り直す。"""
    home = tmp_path / "home"
    marker = home / RETRY_DIR / MARKER_NAME
    marker.parent.mkdir(parents=True)
    marker.write_text("x\n", encoding="utf-8")
    os.utime(marker, (1_000_000_000, 1_000_000_000))
    script = tmp_path / "ok.sh"
    script.write_text(
        "#!/bin/bash\nset -euo pipefail\n"
        + render_marker_host(home).replace(f'mark_for_retry "{MARKER_REASON}"', "true"),
        encoding="utf-8",
    )
    if os.name != "nt":
        result = subprocess.run(
            ["bash", str(script)],
            env={**os.environ, "HOME": str(home)},
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert int(marker.stat().st_mtime) == 1_000_000_000


# ---------------------------------------------------------------------------
# 事故 7: 再実行の印をエージェントが書ける場所に置き、symlink を追って書いていた
# ---------------------------------------------------------------------------


def _expand(path: str, home: str) -> str:
    return home + path[1:] if path.startswith("~/") else path


def test_retry_markers_are_outside_the_sandbox_write_allow():
    """★印は apply (ホスト) が書く。pi の囲い (pi-sandbox-runner) から書けると、印を
    ~/.bashrc などへの symlink に差し替えてホストに中身を書き潰させられる。"""
    home = "/test-home"
    runner = tomllib.loads((HOME / "dot_config" / "pi-sandbox" / "runner.toml").read_text(encoding="utf-8"))
    writable = [*runner["visible"].get("write", [])]
    assert writable, "runner.toml の [visible] write が読めない"
    for name, script in RETRY_MARKERS.items():
        rendered = render_with_context(script, home=home)
        assert f'retry_marker="${{HOME}}/{RETRY_DIR}/{name}"' in rendered, script.name
        marker = f"{home}/{RETRY_DIR}/{name}"
        for allowed in writable:
            allowed = _expand(allowed, home).rstrip("/")
            assert marker != allowed and not marker.startswith(allowed + "/"), (
                f"{name} が write 許可 {allowed} の内側にある"
            )


def test_the_marker_content_is_never_embedded(tmp_path):
    """時刻だけを埋め込む。中身を埋め込むと改行を仕込まれたときにコードが入る。"""
    home = tmp_path / "home"
    marker = home / RETRY_DIR / MARKER_NAME
    marker.parent.mkdir(parents=True)
    marker.write_text("x\necho INJECTED\n", encoding="utf-8")
    assert "INJECTED" not in render_marker_host(home)


@pytest.mark.skipif(os.name == "nt", reason="Unix のスクリプト")
@pytest.mark.parametrize("kind", ["symlink", "dangling-symlink"])
def test_the_marker_is_replaced_without_following_a_symlink(tmp_path, kind):
    """印が symlink になっていても、その先 (~/.bashrc など) を書き換えない。"""
    home = tmp_path / "home"
    victim = home / ".bashrc"
    victim.parent.mkdir(parents=True)
    if kind == "symlink":
        victim.write_text("keep me\n", encoding="utf-8")
    marker = home / RETRY_DIR / MARKER_NAME
    marker.parent.mkdir(parents=True)
    marker.symlink_to(victim)

    result, _ = run_marker_host(tmp_path, home=home)

    assert result.returncode == 0, result.stderr
    assert not marker.is_symlink()
    assert marker.is_file()
    if kind == "symlink":
        assert victim.read_text(encoding="utf-8") == "keep me\n"
    else:
        assert not victim.exists()


FROZEN_DATE = """#!/bin/sh
if [ "$#" -eq 1 ] && [ "$1" = +%s ]; then
    echo {now}
    exit 0
fi
exec {date} "$@"
"""


def _frozen_date(tmp_path: Path, now: int) -> Path:
    """``date +%s`` だけを ``now`` に固定し、ほかの引数は本物の date へ渡す stub を置く。"""
    date = shutil.which("date")
    if date is None:
        pytest.skip("date が無い")
    prefix = tmp_path / "frozen-bin"
    prefix.mkdir()
    fake = prefix / "date"
    fake.write_text(
        FROZEN_DATE.replace("{now}", str(now)).replace("{date}", shlex.quote(date)),
        encoding="utf-8",
    )
    fake.chmod(0o755)
    frozen = subprocess.run(
        [str(fake), "+%s"], capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout.strip()
    assert frozen == str(now)
    return fake


@pytest.mark.skipif(os.name == "nt", reason="Unix のスクリプト")
def test_a_failure_in_the_same_second_still_changes_the_script(tmp_path):
    """★.modTime は秒単位。前回の印と同じ秒にまた失敗すると描画が変わらず、
    その回が記録されて以後は走らない。書き直した印は前回 + 1 秒にする。

    実時間の秒の境目に頼らず、``date +%s`` を印の時刻に固定して同じ秒を作る。
    印の時刻は過去に置くので、補正しなければ書き直した印は実時間になり前回 + 1 にならない。
    """
    previous = 1_000_000_000
    home = tmp_path / "home"
    marker = home / RETRY_DIR / MARKER_NAME
    marker.parent.mkdir(parents=True)
    marker.write_text("x\n", encoding="utf-8")
    os.utime(marker, (previous, previous))
    prefix = _frozen_date(tmp_path, previous).parent

    result, _ = run_marker_host(tmp_path, home=home, path_prefix=prefix)

    assert result.returncode == 0, result.stderr
    assert int(marker.stat().st_mtime) == previous + 1
    assert marker.read_text(encoding="utf-8") == MARKER_REASON + "\n"
    rerendered = render_marker_host(home)
    assert f"# retry-marker: {previous}\n" not in rerendered
    assert f"# retry-marker: {previous + 1}\n" in rerendered


FAKE_BSD_TOUCH = """#!/bin/sh
for arg in "$@"; do
    [ "$arg" = -d ] && { echo "touch: out of range or illegal time specification" >&2; exit 1; }
done
exec {touch} "$@"
"""
FAKE_BSD_DATE = """#!/bin/sh
if [ "$1" = -u ] && [ "$2" = -r ]; then
    exec {date} -u -d "@$3" "$4"
fi
exec {date} "$@"
"""


def _is_gnu_date(date: str) -> bool:
    """GNU の date は ``--version`` に応じる。BSD (macOS) の date は不正なオプションで落ちる。"""
    try:
        result = subprocess.run(
            [date, "--version"], capture_output=True, text=True, encoding="utf-8", check=False
        )
    except OSError:
        return False
    return result.returncode == 0 and "GNU" in result.stdout


@pytest.mark.skipif(os.name == "nt", reason="Unix のスクリプト")
@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ('echo "date (GNU coreutils) 9.4"', True),
        ('echo "date: illegal option -- -" >&2; exit 1', False),
        ('echo "BusyBox v1.36"', False),
    ],
    ids=["gnu", "bsd", "other"],
)
def test_the_simulated_bsd_case_runs_only_on_gnu_date(tmp_path, version, expected):
    """模擬の date は GNU の -d @秒 に頼る。BSD の date では模擬せずネイティブで見る。"""
    fake = tmp_path / "date"
    fake.write_text(f"#!/bin/sh\n{version}\n", encoding="utf-8")
    fake.chmod(0o755)
    assert _is_gnu_date(str(fake)) is expected


@pytest.mark.skipif(os.name == "nt", reason="Unix のスクリプト")
@pytest.mark.parametrize("flavor", ["native", "simulated-bsd"])
def test_a_marker_not_older_than_now_is_moved_past_the_previous_second(tmp_path, flavor):
    """前回の印が今と同じ秒以降なら、前回 + 1 秒に進める。

    native はその環境の touch / date をそのまま使う (macOS なら BSD 版を実際に通る)。
    simulated-bsd は macOS の touch (-d に @秒を受けない) と date (-r 秒) を GNU の上で模す。
    模擬は GNU の date が要るので、GNU でなければ skip する (native が BSD を見る)。
    TZ をずらし、-t の時刻がローカル時刻で解釈されてずれないことも見る。

    実時間に頼らず、``date +%s`` を印の時刻より前に固定して「印が今より未来」を作る。
    印の時刻は過去に置くので、補正しなければ書き直した印は実時間になり前回 + 1 にならない。
    """
    home = tmp_path / "home"
    marker = home / RETRY_DIR / MARKER_NAME
    marker.parent.mkdir(parents=True)
    marker.write_text("x\n", encoding="utf-8")
    previous = 1_000_000_000
    os.utime(marker, (previous, previous))
    if flavor == "simulated-bsd":
        touch, date = shutil.which("touch"), shutil.which("date")
        if touch is None or date is None:
            pytest.skip("touch / date が無い")
        if not _is_gnu_date(date):
            pytest.skip("GNU の date が無い (BSD は native のケースで検証する)")
    frozen = _frozen_date(tmp_path, previous - 100)
    prefix = frozen.parent
    if flavor == "simulated-bsd":
        prefix = tmp_path / "bsd-bin"
        prefix.mkdir()
        # 模擬の date は -u -r を GNU の -d @秒へ変換し、それ以外は固定した date へ渡す
        for name, body in (("touch", FAKE_BSD_TOUCH), ("date", FAKE_BSD_DATE)):
            fake = prefix / name
            fake.write_text(
                body.replace("{touch}", shlex.quote(touch)).replace(
                    "{date}", shlex.quote(str(frozen))
                ),
                encoding="utf-8",
            )
            fake.chmod(0o755)
        converted = subprocess.run(
            [str(prefix / "date"), "-u", "-r", str(previous + 1), "+%Y%m%d%H%M.%S"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout.strip()
        assert converted == "200109090146.41"
        frozen_now = subprocess.run(
            [str(prefix / "date"), "+%s"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout.strip()
        assert frozen_now == str(previous - 100)

    result, _ = run_marker_host(
        tmp_path, home=home, path_prefix=prefix, extra_env={"TZ": "JST-9"}
    )

    assert result.returncode == 0, result.stderr
    assert int(marker.stat().st_mtime) == previous + 1
    assert marker.read_text(encoding="utf-8") == MARKER_REASON + "\n"


@pytest.mark.skipif(os.name == "nt", reason="Unix のスクリプト")
@pytest.mark.parametrize("link", [".local", ".local/share", ".local/share/dotfiles", RETRY_DIR])
def test_the_marker_is_not_written_through_a_symlinked_parent(tmp_path, link):
    """★親の経路が symlink だと、その先 (~/.bashrc のあるディレクトリなど) に書く。
    書かずに非ゼロで終わる。"""
    home = tmp_path / "home"
    elsewhere = tmp_path / "elsewhere"
    victim = elsewhere / Path(RETRY_DIR).relative_to(link) / MARKER_NAME
    victim.parent.mkdir(parents=True)
    victim.write_text("keep me\n", encoding="utf-8")
    (home / link).parent.mkdir(parents=True, exist_ok=True)
    (home / link).symlink_to(elsewhere, target_is_directory=True)

    result, _ = run_marker_host(tmp_path, home=home)

    assert result.returncode != 0
    assert "symlink" in result.stderr
    assert victim.read_text(encoding="utf-8") == "keep me\n"
    assert list(victim.parent.iterdir()) == [victim]


@pytest.mark.skipif(os.name == "nt", reason="Unix のスクリプト")
def test_an_unwritable_marker_fails_the_script(tmp_path):
    """★印を置けないまま 0 で終わると成功として記録され、次の apply でも走らない。
    非ゼロで終わり、記録させない。"""
    home = tmp_path / "home"
    marker = home / RETRY_DIR / MARKER_NAME
    marker.mkdir(parents=True)

    result, _ = run_marker_host(tmp_path, home=home)

    assert result.returncode != 0
    assert "再実行の印を置けません" in result.stderr
    assert MARKER_REASON in result.stderr
    assert list(marker.iterdir()) == []
    assert list(marker.parent.iterdir()) == [marker]


def test_agent_cli_installer_installs_only_pi():
    """pi 以外の AI CLI (Claude Code・Copilot CLI・OpenCode・oh-my-pi) は入れない (ADR-0037)。"""
    rendered = render_with_context(AGENT_CLI)
    assert "https://pi.dev/install.sh" in rendered
    for retired in ("claude.ai/install", "gh.io/copilot-install", "opencode.ai", "omp.sh/install"):
        assert retired not in rendered, retired
    assert 'retry_marker="${HOME}/.local/share/dotfiles/retry/agent-cli-failed"' in rendered


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

    def commands(p: Path) -> str:
        # コメントに brew の語が出るだけのスクリプト (202 の理由書きなど) は使う側に数えない
        lines = p.read_text(encoding="utf-8").splitlines()
        return "\n".join(line for line in lines if not line.lstrip().startswith("#"))

    users = [p for p in scripts if p != installer and re.search(r"\bbrew\b", commands(p))]
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


OSX = MAC_SCRIPTS / "run_once_after_210_osx.sh.tmpl"


def run_osx(
    tmp_path: Path, *, failing: tuple[str, ...]
) -> tuple[subprocess.CompletedProcess, Path]:
    """brew / sudo / uname / curl を差し替えて 210 を走らせる。`failing` の名前の導入だけ失敗させる。"""
    if os.name == "nt":
        pytest.skip("Unix のスクリプト")
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash が無い")
    if Path("/opt/homebrew/bin/brew").exists():
        pytest.skip("このマシンに Homebrew が入っている")
    home = tmp_path / "home"
    home.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fail_names = " ".join(failing)
    stubs = {
        # Rosetta (softwareupdate) を failing に含めると失敗させる
        "sudo": (
            'case "$*" in *softwareupdate*) '
            + ("exit 1" if "rosetta" in failing else "exit 0")
            + " ;; *) exit 0 ;; esac"
        ),
        "uname": "echo arm64",
        "curl": "exit 0",
        "brew": (
            'if [ "$1" = install ]; then for n in '
            + fail_names
            + '; do [ "$2" = "$n" ] && exit 1; done; fi; exit 0'
        ),
    }
    for name, body in stubs.items():
        stub = bindir / name
        stub.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        stub.chmod(0o755)
    script = tmp_path / "210.sh"
    script.write_text(render_with_context(OSX, home=home, os_name="darwin"), encoding="utf-8")
    result = subprocess.run(
        [bash, str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "HOME": str(home), "PATH": f"{bindir}:/usr/bin:/bin"},
        check=False,
        timeout=60,
    )
    return result, home / RETRY_DIR / "osx-failed"


@pytest.mark.skipif(os.name == "nt", reason="Unix のスクリプト")
def test_osx_swallowed_failures_leave_a_retry_marker(tmp_path):
    """警告で続ける失敗は、run_once_ が成功と記録すると二度と走らない。印を置いて次の apply で走り直させる。
    0 で終わる (非ゼロだと後続のスクリプトを巣き込む)。"""
    result, marker = run_osx(
        tmp_path, failing=("rosetta", "google-japanese-ime", "karabiner-elements")
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.is_file(), result.stderr
    reason = marker.read_text(encoding="utf-8").split()
    assert reason == ["rosetta", "google-japanese-ime", "karabiner-elements"], reason


@pytest.mark.skipif(os.name == "nt", reason="Unix のスクリプト")
def test_osx_without_failures_leaves_no_retry_marker(tmp_path):
    result, marker = run_osx(tmp_path, failing=())
    assert result.returncode == 0, result.stdout + result.stderr
    assert not marker.exists()


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
    sudo.write_text(
        f'#!/bin/sh\necho "$*" >> {shlex.quote(str(log))}\nexit {rc}\n', encoding="utf-8"
    )
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


TOUCHID = MAC_SCRIPTS / "run_once_after_202_touchid_sudo.sh.tmpl"
PAM_LINE = "auth       sufficient     pam_tid.so"


def run_touchid(
    tmp_path: Path, *, template: bool = True, local_text: str | None = None
) -> tuple[subprocess.CompletedProcess, Path]:
    """sudo を素通しにし、PAM の置き場を一時ディレクトリへ向けて 202 を走らせる。"""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash が無い")
    pam = tmp_path / "pam.d"
    pam.mkdir()
    if template:
        (pam / "sudo_local.template").write_text("# auth sufficient pam_tid.so\n", encoding="utf-8")
    if local_text is not None:
        (pam / "sudo_local").write_text(local_text, encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    sudo = bindir / "sudo"
    # -v と -n は認証の確認なので成功させ、それ以外は引数のコマンドをそのまま走らせる
    sudo.write_text('#!/bin/sh\ncase "$1" in -v|-n) exit 0;; esac\nexec "$@"\n', encoding="utf-8")
    sudo.chmod(0o755)
    script = tmp_path / "202.sh"
    script.write_text(
        render_with_context(TOUCHID, home=tmp_path / "home", os_name="darwin"), encoding="utf-8"
    )
    result = subprocess.run(
        [bash, str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PATH": f"{bindir}:/usr/bin:/bin", "CHEZMOI_PAM_DIR": str(pam)},
        check=False,
        timeout=60,
    )
    return result, pam / "sudo_local"


@pytest.mark.skipif(os.name == "nt", reason="Unix のスクリプト")
def test_touchid_sudo_writes_an_active_pam_tid_line(tmp_path):
    result, local_conf = run_touchid(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert local_conf.read_text(encoding="utf-8").splitlines() == [PAM_LINE]


@pytest.mark.skipif(os.name == "nt", reason="Unix のスクリプト")
def test_touchid_sudo_ignores_a_commented_line_and_appends(tmp_path):
    """sudo_local.template 由来のコメント行だけなら、有効な行を足す。"""
    result, local_conf = run_touchid(tmp_path, local_text="# auth sufficient pam_tid.so\n")
    assert result.returncode == 0, result.stdout + result.stderr
    lines = local_conf.read_text(encoding="utf-8").splitlines()
    assert lines == ["# auth sufficient pam_tid.so", PAM_LINE]


@pytest.mark.skipif(os.name == "nt", reason="Unix のスクリプト")
def test_touchid_sudo_leaves_an_existing_active_line_alone(tmp_path):
    """有効な行が既にあれば増やさない (2 回目以降の apply)。"""
    result, local_conf = run_touchid(tmp_path, local_text=PAM_LINE + "\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert local_conf.read_text(encoding="utf-8") == PAM_LINE + "\n"


@pytest.mark.skipif(os.name == "nt", reason="Unix のスクリプト")
def test_touchid_sudo_is_skipped_without_sudo_local_support(tmp_path):
    """sudo_local.template が無い (macOS 13 以前) なら何も書かず、apply を止めない。"""
    result, local_conf = run_touchid(tmp_path, template=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not local_conf.exists()


DEFAULTS = MAC_SCRIPTS / "run_once_after_250_defaults.sh.tmpl"


@pytest.mark.skipif(os.name == "nt", reason="Unix のスクリプト")
def test_defaults_enables_remote_login_with_a_launchctl_fallback(tmp_path):
    """リモートログインは systemsetup を先に試し、失敗したら daemon を直接読み込む。

    systemsetup はターミナルにフルディスクアクセスが無いと失敗する。構文が通ることも確かめる。
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash が無い")
    rendered = render_with_context(DEFAULTS, home=tmp_path / "home", os_name="darwin")
    script = tmp_path / "250.sh"
    script.write_text(rendered, encoding="utf-8")
    syntax = subprocess.run(
        [bash, "-n", str(script)], capture_output=True, text=True, encoding="utf-8", check=False
    )
    assert syntax.returncode == 0, syntax.stderr
    check = rendered.index("launchctl print system/com.openssh.sshd")
    systemsetup = rendered.index("systemsetup -setremotelogin on")
    load = rendered.index("launchctl load -w /System/Library/LaunchDaemons/ssh.plist")
    assert check < systemsetup < load

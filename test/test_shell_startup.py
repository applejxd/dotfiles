"""シェルの起動契約の回帰テスト。

全シェル共通の env (.zshenv / .bash_profile / shellenv.sh) は PATH と環境変数だけを扱い、
alias・出力・対話専用の設定は対話 rc に限る。契約は docs/spec/structure.md の
「シェルの起動契約」を参照。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHELL_DIR = ROOT / "home" / "dot_config" / "shell"

pytestmark = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None, reason="Unix の bash が無い"
)

_STARTUP_ENV = {"BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS", "ZDOTDIR"}
_USER_ENV = {"EDITOR", "VISUAL", "LC_ALL", "LANG"}


def render(source: Path) -> str:
    """テンプレートを chezmoi で描画する。"""
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
    text = source.read_text(encoding="utf-8")
    if source.suffix != ".tmpl":
        return text
    done = subprocess.run(
        [chezmoi, "--source", str(ROOT), "execute-template"],
        input=text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """配布物だけを置いた一時 HOME。zinit / mise / fzf などの外部依存は置かない。"""
    home = tmp_path / "home"
    shell = home / ".config" / "shell"
    shell.mkdir(parents=True)
    env_files = {
        "shellenv.sh": SHELL_DIR / "shellenv.sh.tmpl",
        "shellrc.sh": SHELL_DIR / "shellrc.sh.tmpl",
    }
    for name in ("osxenv.sh", "osxrc.sh", "wslenv.sh", "wslrc.sh"):
        if (SHELL_DIR / name).exists():
            env_files[name] = SHELL_DIR / name
    for name, src in env_files.items():
        (shell / name).write_text(render(src), encoding="utf-8")
    shutil.copytree(SHELL_DIR / "functions", shell / "functions")
    for name, src in {
        ".zshenv": ROOT / "home" / "dot_zshenv",
        ".zshrc": ROOT / "home" / "dot_zshrc.tmpl",
        ".bash_profile": ROOT / "home" / "dot_bash_profile",
        ".bashrc": ROOT / "home" / "dot_bashrc",
    }.items():
        (home / name).write_text(render(src), encoding="utf-8")
    return home


# shellenv.sh は LC_ALL / LANG の既定を ja_JP.UTF-8 にする。その locale を生成していない機
# (素の Ubuntu・GitHub Actions の ubuntu-24.04 runner など) では、bash 本体が
# "warning: setlocale: LC_ALL: cannot change locale (ja_JP.UTF-8)" を stderr に出す (zsh は出さない)。
# これは機の都合で出る bash の警告で、dotfiles が出した出力ではない。「alias も出力も持たない」契約の
# 検査からはこの警告だけを外す。既定値そのもの (ja_JP.UTF-8) の検査は残す。
# 別の locale の警告や、ほかの stderr は外さない。
_HOST_LOCALE_WARNING = re.compile(
    r"^[^\n]*warning: setlocale: (?:LC_[A-Z_]+|LANG): "
    r"cannot change locale \(ja_JP\.UTF-8\)[^\n]*\n?",
    re.MULTILINE,
)


def _drop_host_locale_warning(stderr: str) -> str:
    return _HOST_LOCALE_WARNING.sub("", stderr)


def run(
    argv: list[str], home: Path, *, stdin_text: str | None = None, **extra: str
) -> subprocess.CompletedProcess[str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in _STARTUP_ENV | _USER_ENV and not k.startswith("BASH_FUNC_")
    }
    env["HOME"] = str(home)
    env.update(extra)
    done = subprocess.run(
        argv,
        cwd=home,  # .zshenv が git リポジトリ内で TMPDIR を書き換えないように
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
        input=stdin_text,
        timeout=30,
    )
    done.stderr = _drop_host_locale_warning(done.stderr)
    return done


def test_host_locale_warning_filter_drops_only_the_default_locale_warning():
    prefix = "warning: setlocale: LC_ALL: cannot change locale"
    missing = f"bash: {prefix} (ja_JP.UTF-8): No such file or directory\n"
    in_script = f"/h/.config/shell/shellenv.sh: line 22: {prefix} (ja_JP.UTF-8)\n"
    other_locale = f"bash: {prefix} (de_DE.UTF-8)\n"
    assert _drop_host_locale_warning(missing) == ""
    assert _drop_host_locale_warning(in_script) == ""
    assert _drop_host_locale_warning(f"before\n{missing}after\n") == "before\nafter\n"
    assert _drop_host_locale_warning(other_locale) == other_locale
    assert _drop_host_locale_warning("echo-to-stderr\n") == "echo-to-stderr\n"


def _zsh() -> str:
    zsh = shutil.which("zsh")
    if zsh is None:
        pytest.skip("zsh is not installed")
    return zsh


# ---- 非対話 zsh (.zshenv だけ読まれる。OpenCode などの agent がこの形で起動する) ----


def _baseline_aliases(home: Path) -> str:
    """rc を一切読まない zsh (-f) が持つ alias。zsh 組み込みの run-help などが含まれる。"""
    return run([_zsh(), "-f", "-c", "alias"], home).stdout


def test_noninteractive_zsh_has_no_alias_and_no_output(home):
    done = run([_zsh(), "-c", "alias"], home)
    assert done.returncode == 0, done.stderr
    assert done.stdout == _baseline_aliases(home) and done.stderr == ""


@pytest.mark.parametrize("var", ["LC_ALL", "EDITOR", "VISUAL", "LANG"])
def test_noninteractive_zsh_keeps_explicit_env(home, var):
    done = run([_zsh(), "-c", f'print -r -- "${var}"'], home, **{var: "explicit-value"})
    assert done.stdout.strip() == "explicit-value", done.stderr


def test_noninteractive_zsh_defaults_when_unset(home):
    done = run([_zsh(), "-c", 'print -r -- "$LC_ALL $LANG $EDITOR $VISUAL"'], home)
    lc_all, lang, editor, visual = done.stdout.split()
    assert (lc_all, lang) == ("ja_JP.UTF-8", "ja_JP.UTF-8")
    assert editor and visual == editor


def test_zshrc_returns_immediately_when_noninteractive(home):
    with (home / ".zshrc").open("a", encoding="utf-8") as f:
        f.write('\necho "zshrc body ran"\n')  # 早期 return が効かないと出力される
    done = run([_zsh(), "-c", "source ~/.zshrc; echo after"], home)
    assert done.stdout == "after\n", (done.stdout, done.stderr)
    assert done.stderr == ""


def test_zshenv_does_not_source_global_zshrc(home):
    assert "/etc/zsh/zshrc" not in (home / ".zshenv").read_text(encoding="utf-8")
    assert "/etc/zsh/zshrc" in (home / ".zshrc").read_text(encoding="utf-8")


# ---- 非対話 login bash ----


def test_noninteractive_login_bash_stays_plain(home):
    script = 'alias; shopt -p dotglob nocaseglob; printf "%s\\n" "$LC_ALL"'
    done = run(["bash", "-lc", script], home)
    assert done.returncode == 0, done.stderr
    assert done.stderr == ""
    lines = done.stdout.splitlines()
    assert "shopt -u dotglob" in lines and "shopt -u nocaseglob" in lines
    assert not any(line.startswith("alias ") for line in lines)
    assert lines[-1] == "ja_JP.UTF-8"


def test_noninteractive_login_bash_keeps_explicit_env(home):
    done = run(["bash", "-lc", 'echo "$LC_ALL:$EDITOR"'], home, LC_ALL="C", EDITOR="foo")
    assert done.stdout.strip() == "C:foo", done.stderr


# ---- shellenv.sh 単体 ----


def test_shellenv_defines_no_alias_or_function(home):
    done = run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            'shopt -s expand_aliases; source "$HOME/.config/shell/shellenv.sh"; alias; declare -F',
        ],
        home,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout == "" and done.stderr == ""


@pytest.mark.skipif(sys.platform != "linux", reason="WSL の _wsl_vscode_user_bin 分岐は Linux テンプレート専用")
@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_wsl_user_vscode_bin_goes_to_the_end_of_path_once(home, shell):
    """ユーザーが書き込める VS Code の bin は、PATH の最後に 1 つだけ置く。

    wslenv.sh は場所を決めるだけで、shellenv.sh が PATH の最後へ置く。前の版が先頭へ置いたものを引き継いだ PATH でも、
    $GOPATH/bin など後から足す要素より後ろに回る (Linux 側のコマンドを隠さない)。
    """
    (home / ".go").mkdir()
    vscode = "/x/vscode/bin"
    script = f'_wsl_vscode_user_bin={vscode}; source "$HOME/.config/shell/shellenv.sh"; printf "%s" "$PATH"'
    argv = (
        [_zsh(), "-f", "-c", script]
        if shell == "zsh"
        else ["bash", "--noprofile", "--norc", "-c", script]
    )
    done = run(argv, home, PATH=f"{vscode}:/usr/bin:/bin")
    assert done.returncode == 0, done.stderr
    entries = done.stdout.split(":")
    assert entries.count(vscode) == 1, done.stdout
    assert entries[-1] == vscode, done.stdout
    assert f"{home}/.go/bin" in entries and entries.index(f"{home}/.go/bin") < entries.index(vscode)


_SPLIT = "extract zpack zunpack runcpp"


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_shellrc_loads_split_functions(home, shell):
    """functions/ に切り出した関数が shellrc.sh から読み込まれる。"""
    if shell == "zsh":
        argv = [_zsh(), "-f", "-c", 'source "$HOME/.config/shell/shellrc.sh"; whence -w ' + _SPLIT]
    else:
        argv = [
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            f'source "$HOME/.config/shell/shellrc.sh"; type -t {_SPLIT}',
        ]
    done = run(argv, home)
    assert done.returncode == 0, done.stderr
    assert done.stdout.count("function") == len(_SPLIT.split()), done.stdout


# ---- zpack ----


@pytest.fixture
def zpack(tmp_path):
    if shutil.which("zstd") is None or shutil.which("tar") is None:
        pytest.skip("zstd / tar が無い")
    work = tmp_path / "work"
    work.mkdir()
    (work / "src").mkdir()
    (work / "src" / "f.txt").write_text("hello", encoding="utf-8")
    script = f'source "{SHELL_DIR / "functions" / "archive.sh"}"\nzpack "$@"\n'

    def call(*args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        return run(["bash", "-c", script, "bash", *args], work, **extra)

    call.work = work
    return call


def test_zpack_creates_archive_without_leftover(zpack):
    done = zpack("src", "out.tar.zst", ZPACK_LEVEL="1")
    assert done.returncode == 0, done.stderr
    assert sorted(p.name for p in zpack.work.iterdir()) == ["out.tar.zst", "src"]


def test_zpack_does_not_overwrite_existing_output(zpack):
    out = zpack.work / "out.tar.zst"
    out.write_text("precious", encoding="utf-8")
    done = zpack("src", "out.tar.zst", ZPACK_LEVEL="1")
    assert done.returncode != 0
    assert out.read_text(encoding="utf-8") == "precious"
    assert sorted(p.name for p in zpack.work.iterdir()) == ["out.tar.zst", "src"]


def test_zpack_failure_leaves_no_temp_file(zpack, tmp_path):
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "zstd").write_text('#!/bin/sh\necho partial > "$4"\nexit 1\n', encoding="utf-8")
    (fake / "zstd").chmod(0o755)
    done = zpack("src", "out.tar.zst", ZPACK_LEVEL="1", PATH=f"{fake}:{os.environ['PATH']}")
    assert done.returncode != 0
    assert sorted(p.name for p in zpack.work.iterdir()) == ["src"]


# ---- runcpp ----

_OOB_CPP = """#include <bits/stdc++.h>
int main(int argc, char** argv) {
    std::vector<int> v(3);
    int i;
    std::cin >> i;
#ifdef LOCAL
    std::cout << "LOCAL ";
#endif
#ifdef ONLINE_JUDGE
    std::cout << "OJ ";
#endif
    std::cout << v[i] << " argc=" << argc << (argc > 1 ? argv[1] : "") << std::endl;
}
"""


@pytest.fixture(params=["bash", "zsh"])
def runcpp(request, tmp_path):
    if shutil.which("g++") is None:
        pytest.skip("g++ が無い")
    exe = _zsh() if request.param == "zsh" else "bash"
    work = tmp_path / "work"
    work.mkdir()
    (work / "a.cpp").write_text(_OOB_CPP, encoding="utf-8")
    script = f'source "{SHELL_DIR / "functions" / "cpp.sh"}"\nrun_stdin=$1; shift\n'
    script += 'printf "%s\\n" "$run_stdin" | runcpp "$@"\n'

    def call(stdin: str, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        argv = [exe, "-f"] if exe != "bash" else [exe, "--noprofile", "--norc"]
        return run(
            [*argv, "-c", script, "sh", stdin, *args],
            work,
            XDG_CACHE_HOME=str(tmp_path / "cache"),
            # LeakSanitizer は ptrace 下 (sandbox など) で致命的エラーになる。この試験は範囲外アクセスの検出が目的なので、
            # リーク検出だけを切る (AddressSanitizer の検出は残る)
            ASAN_OPTIONS="detect_leaks=0",
            **extra,
        )

    call.work = work
    call.cache = tmp_path / "cache" / "runcpp"
    return call


def test_runcpp_release_runs_judge_like(runcpp):
    done = runcpp("1", "a.cpp", "-r")  # オプションはソースの後ろでもよい
    assert done.returncode == 0, done.stderr
    assert done.stdout == "OJ 0 argc=1\n"
    assert sorted(p.name for p in runcpp.cache.iterdir()) == ["a-release"]
    assert sorted(p.name for p in runcpp.work.iterdir()) == ["a.cpp"]


@pytest.mark.skipif(
    sys.platform == "darwin",
    reason="macOS 26 (arm64) では -fsanitize=address のバイナリ起動が dyld 初期化デッドロックする上流不具合 (llvm/llvm-project#200447)",
)
def test_runcpp_debug_is_default_and_detects_out_of_bounds(runcpp):
    done = runcpp("1", "a.cpp")
    assert done.returncode == 0, done.stderr
    assert done.stdout == "LOCAL 0 argc=1\n"
    done = runcpp("5", "a.cpp")
    assert done.returncode != 0
    assert "out-of-bounds" in done.stderr


def test_runcpp_mode_from_env(runcpp):
    done = runcpp("1", "a.cpp", RUNCPP_MODE="release")
    assert done.stdout.startswith("OJ "), done.stderr


def test_runcpp_passes_args_after_double_dash(runcpp):
    done = runcpp("1", "-r", "a.cpp", "foo", "--", "-x")
    assert done.stdout == "OJ 0 argc=3foo\n", done.stderr


def test_runcpp_compile_failure_does_not_run_stale_binary(runcpp):
    assert runcpp("1", "-r", "a.cpp").returncode == 0
    (runcpp.work / "a.cpp").write_text("int main() { return x; }\n", encoding="utf-8")
    done = runcpp("1", "-r", "a.cpp")
    assert done.returncode != 0
    assert done.stdout == ""


@pytest.mark.parametrize(
    ("args", "env", "message"),
    [
        (("a.cpp", "-x"), {}, "unknown option"),
        (("a.cpp",), {"RUNCPP_MODE": "bogus"}, "invalid mode"),
        (("missing.cpp",), {}, "No such file"),
        ((), {}, "Usage"),
    ],
)
def test_runcpp_rejects_bad_input(runcpp, args, env, message):
    done = runcpp("1", *args, **env)
    assert done.returncode != 0
    assert message in done.stderr


# ---- code-exam (applejxd のときだけ定義する) ----

_FAKE_CODE = '#!/bin/sh\nfor a in "$@"; do echo "arg=[$a]"; done\n'


def _source_shellrc(shell: str, script: str) -> list[str]:
    if shell == "zsh":
        return [_zsh(), "-f", "-c", f'source "$HOME/.config/shell/shellrc.sh"; {script}']
    return [
        "bash",
        "--noprofile",
        "--norc",
        "-c",
        f'source "$HOME/.config/shell/shellrc.sh"; {script}',
    ]


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_code_exam_opens_dated_dir_with_profile(home, tmp_path, shell):
    if "code-exam()" not in (home / ".config" / "shell" / "shellrc.sh").read_text(encoding="utf-8"):
        pytest.skip("code-exam は applejxd のときだけ定義する")
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "code").write_text(_FAKE_CODE, encoding="utf-8")
    (fake / "code").chmod(0o755)
    done = run(_source_shellrc(shell, "code-exam"), home, PATH=f"{fake}:{os.environ['PATH']}")
    assert done.returncode == 0, done.stderr
    args = [ln[5:-1] for ln in done.stdout.splitlines() if ln.startswith("arg=[")]
    assert args[:3] == ["--disable-extensions", "--profile", "coding-test"]
    assert len(args) == 4 and re.fullmatch(
        rf"{re.escape(str(home))}/coding-test/\d{{4}}-\d{{2}}-\d{{2}}", args[3]
    )
    assert Path(args[3]).is_dir()


def test_code_exam_is_not_defined_for_other_users(tmp_path):
    source = SHELL_DIR / "shellrc.sh.tmpl"
    other = tmp_path / "shellrc.sh.tmpl"
    other.write_text(
        source.read_text(encoding="utf-8").replace(".chezmoi.username", '"someone"'),
        encoding="utf-8",
    )
    assert "code-exam" not in render(other)


def test_shellrc_defines_no_agent_alias_or_copilot_function(home):
    """AI CLI の別名・起動関数は持たない (pi だけを使う。ADR-0037)。"""
    done = run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            'shopt -s expand_aliases; source "$HOME/.config/shell/shellrc.sh"; alias agent; type -t copilot',
        ],
        home,
    )
    assert "alias agent=" not in done.stdout and "function" not in done.stdout


# ---- drypi・superpi (外部の pi が PATH にあるときだけ定義する) ----

# functions/pi.sh の _PI_DRY_ARGS。drypi も superpi も、これを pi の先頭へ渡す
_DRY_ARGS = ["--no-extensions", "--no-skills", "--no-prompt-templates", "--no-context-files", "--no-approve"]
# 渡された引数・作業ディレクトリ・HOME・PATH・エージェントの置き場・自分のパスを、そのまま出す偽の pi
_FAKE_PI = (
    '#!/bin/sh\necho "cwd=$(pwd)"\necho "self=$0"\necho "home=$HOME"\necho "path=$PATH"\n'
    'echo "agent=$PI_CODING_AGENT_DIR"\nfor a in "$@"; do echo "arg=[$a]"; done\n'
)
# 呼ばれたことを出して、環境を捨てて (sudo の env_reset に相当)、残りの引数を実行する偽の sudo。
# 本物の sudo は、パスワードを求める。HOME・PATH・エージェントの置き場を、呼ぶ側が明示して渡さないと、pi に届かない
_FAKE_SUDO = (
    '#!/bin/sh\necho "sudo-first=$1"\n'
    'exec /usr/bin/env -i HOME=/nonexistent-root PATH=/usr/bin:/bin "$@"\n'
)


def _stub(directory: Path, **bodies: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, body in bodies.items():
        (directory / name).write_text(body, encoding="utf-8")
        (directory / name).chmod(0o755)
    return directory


@pytest.fixture
def fakebin(tmp_path: Path) -> Path:
    """偽の pi と sudo を置いたディレクトリ。"""
    return _stub(tmp_path / "fakebin", pi=_FAKE_PI, sudo=_FAKE_SUDO)


def _absolute_shell(argv: list[str]) -> list[str]:
    """PATH を絞った起動では、シェル自身を PATH から探せない。先頭のシェルを絶対パスにする。"""
    return [shutil.which(argv[0]) or argv[0], *argv[1:]]


def _pi_args(stdout: str) -> list[str]:
    return [ln[5:-1] for ln in stdout.splitlines() if ln.startswith("arg=[")]


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_drypi_passes_the_dry_flags_and_keeps_the_cwd(home, fakebin, shell):
    """drypi は、切るものの一覧を先頭に付けて pi を呼ぶ。作業ディレクトリは変えず、引数は素通し。"""
    script = 'mkdir -p "$HOME/work" && cd "$HOME/work" && drypi --model m "hello world"'
    done = run(_source_shellrc(shell, script), home, PATH=f"{fakebin}:{os.environ['PATH']}")
    assert done.returncode == 0, done.stderr
    assert f"cwd={home}/work" in done.stdout.splitlines()
    assert _pi_args(done.stdout) == [*_DRY_ARGS, "--model", "m", "hello world"]


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_superpi_runs_the_dry_pi_as_root_from_the_root_directory(home, fakebin, shell):
    """superpi は、sudo env で、利用者の HOME・PATH・エージェントの置き場を明示して渡し、/ から drypi と同じ一覧で pi を呼ぶ。

    偽の sudo は環境を捨てるので、明示して渡さなかったものは pi に届かない。
    セッションは保存せず (--no-session)、起動時の通信もしない (--offline)。呼んだシェルの作業ディレクトリは変わらない。
    """
    script = (
        'mkdir -p "$HOME/work" && cd "$HOME/work" && echo "shell-path=$PATH" && superpi --model m; echo "after=$(pwd)"'
    )
    done = run(
        _source_shellrc(shell, script), home, PATH=f"{fakebin}:{os.environ['PATH']}", PI_CODING_AGENT_DIR=""
    )
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    shell_path = next(ln.removeprefix("shell-path=") for ln in lines if ln.startswith("shell-path="))
    assert "sudo-first=env" in lines
    assert "cwd=/" in lines
    assert f"self={fakebin}/pi" in lines
    assert f"home={home}" in lines and f"agent={home}/.pi/agent" in lines
    assert f"path={shell_path}" in lines
    assert _pi_args(done.stdout) == [*_DRY_ARGS, "--no-session", "--offline", "--model", "m"]
    assert f"after={home}/work" in lines


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_superpi_keeps_an_explicit_agent_dir(home, fakebin, shell):
    done = run(
        _source_shellrc(shell, "superpi"), home, PATH=f"{fakebin}:{os.environ['PATH']}", PI_CODING_AGENT_DIR="/x/agent"
    )
    assert done.returncode == 0, done.stderr
    assert "agent=/x/agent" in done.stdout.splitlines()


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_superpi_makes_a_relative_path_entry_absolute_before_changing_directory(home, tmp_path, shell):
    """PATH に相対の要素があって、そこで pi が見つかっても、cd / のあとに別の pi を探さない。

    pi.sh は、読み込み時に外部の pi が PATH に見つかる機だけ関数を定義する。相対の要素 (rel) は
    作業ディレクトリ次第なので、`rel/pi` が見える work の中で shellrc.sh を読み込む。
    (HOME で読むと pi は見つからず、関数は定義されない。実物の pi が PATH にある機では、
    別の pi で定義されて通ってしまうので、実物の pi が無い CI でだけ落ちる。)
    """
    _stub(home / "work" / "rel", pi=_FAKE_PI)
    sudo_only = _stub(tmp_path / "sudo-only", sudo=_FAKE_SUDO)
    argv = _source_shellrc(shell, "superpi")
    argv[-1] = 'cd "$HOME/work" && ' + argv[-1]
    done = run(argv, home, PATH=f"rel:{sudo_only}:{os.environ['PATH']}", PI_CODING_AGENT_DIR="")
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert f"self={home}/work/rel/pi" in lines
    assert "cwd=/" in lines


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_drypi_and_superpi_are_not_defined_without_an_external_pi(home, tmp_path, shell):
    """pi が PATH に無い機では、何も定義しない。alias・関数の pi だけがあるときも、定義しない。"""
    empty = tmp_path / "emptybin"
    empty.mkdir()
    probe = "type -t drypi superpi" if shell == "bash" else "whence -w drypi superpi"
    done = run(_absolute_shell(_source_shellrc(shell, probe)), home, PATH=str(empty))
    assert "function" not in done.stdout, done.stdout
    # 関数の pi だけがある (外部の pi は無い)
    argv = _absolute_shell(_source_shellrc(shell, probe))
    argv[-1] = "pi() { :; }; " + argv[-1]
    done = run(argv, home, PATH=str(empty))
    assert "function" not in done.stdout, done.stdout


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_superpi_refuses_without_sudo(home, tmp_path, shell):
    only_pi = _stub(tmp_path / "nosudo", pi=_FAKE_PI)
    done = run(_absolute_shell(_source_shellrc(shell, "superpi; echo rc=$?")), home, PATH=str(only_pi))
    assert "rc=1" in done.stdout.splitlines()
    assert "sudo が無い" in done.stderr
    assert "cwd=" not in done.stdout  # pi は起動しない


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_superpi_refuses_when_pi_left_the_path_after_loading(home, tmp_path, shell):
    """読み込んだあとで PATH から pi が消えたら、sudo の前に止まる。"""
    both = _stub(tmp_path / "both", pi=_FAKE_PI, sudo=_FAKE_SUDO)
    sudo_only = _stub(tmp_path / "sudo-only", sudo=_FAKE_SUDO)
    done = run(
        _absolute_shell(_source_shellrc(shell, f'PATH="{sudo_only}"; superpi; echo rc=$?')),
        home,
        PATH=str(both),
    )
    assert "rc=1" in done.stdout.splitlines()
    assert "pi の実行ファイルが PATH に無い" in done.stderr
    assert "sudo-first" not in done.stdout


# ---- pi-t3 (T3 Code が login シェルを通らずに起動する pi の入口) ----

PI_T3 = ROOT / "home" / "dot_local" / "bin" / "executable_pi-t3"
# stdout (pi との RPC と同じ口) へ、親プロセス・環境変数の値・stdin の 1 行目・受け取った引数を出し、FAKE_PI_EXIT で終わる偽の pi
_FAKE_PI_T3 = (
    "#!/bin/sh\n"
    'echo "ppid=$PPID"\necho "hf=${HF_HOME-unset}"\necho "lc=${LC_ALL-unset}"\n'
    'IFS= read -r line; echo "stdin=[$line]"\n'
    'for a in "$@"; do echo "arg=[$a]"; done\n'
    'exit "${FAKE_PI_EXIT:-0}"\n'
)


def _pi_t3_copy(tmp_path: Path) -> Path:
    """配布物の pi-t3 を、実行できる形で一時ディレクトリへ写す (git の実行ビットに依存しない)。"""
    wrapper = tmp_path / "pi-t3"
    wrapper.write_text(PI_T3.read_text(encoding="utf-8"), encoding="utf-8")
    wrapper.chmod(0o755)
    return wrapper


def _skip_windows_interop(home: Path) -> None:
    """WSL の機で描画した wslenv.sh が、実際の cmd.exe を呼ばないよう、Windows のユーザー名のキャッシュを先に置く。"""
    (home / ".cache").mkdir(exist_ok=True)
    (home / ".cache" / "win_user").write_text("x\n", encoding="utf-8")


def _isolate_host_env(monkeypatch) -> None:
    """利用者の端末の環境変数を、wrapper の試験へ混ぜない (偽の pi 以外の pi が PATH の先頭に出る・値が既に入る、を防ぐ)。"""
    for name in ("HF_HOME", "MISE_DATA_DIR", "FAKE_PI_EXIT"):
        monkeypatch.delenv(name, raising=False)


def _userenv(home: Path, body: str) -> None:
    (home / ".config" / "shell" / "userenv.sh").write_text(body, encoding="utf-8")


@pytest.fixture
def pi_t3(home, tmp_path, monkeypatch):
    """pi-t3 を、偽の pi だけが見える PATH (偽の pi の置き場 + /usr/bin:/bin) で起動する関数。

    stdin は既定で空 (偽の pi が読んでも EOF)。path= で PATH を、stdin_text= で stdin を替えられる。
    """
    _isolate_host_env(monkeypatch)
    _skip_windows_interop(home)
    bin_dir = _stub(tmp_path / "t3bin", pi=_FAKE_PI_T3)
    wrapper = _pi_t3_copy(tmp_path)

    def launch(
        *args: str, stdin_text: str = "", path: str | None = None, **env: str
    ) -> subprocess.CompletedProcess[str]:
        return run(
            [str(wrapper), *args],
            home,
            stdin_text=stdin_text,
            PATH=path or f"{bin_dir}:/usr/bin:/bin",
            **env,
        )

    launch.home = home
    return launch


def test_pi_t3_replaces_itself_with_pi_keeping_arguments_and_exit_code(pi_t3):
    """pi-t3 は exec で pi に置き換わる。引数は素通しで、終了コードも pi のものになる。stdout は pi のものだけ。"""
    done = pi_t3("--mode", "rpc", "hello world", FAKE_PI_EXIT="7")
    assert done.returncode == 7, done.stderr
    assert done.stderr == ""
    assert _pi_args(done.stdout) == ["--mode", "rpc", "hello world"]
    # wrapper の bash が親として残らない (exec)。pi が出すもの以外は stdout に無い
    assert [ln for ln in done.stdout.splitlines() if not ln.startswith("arg=[")] == [
        f"ppid={os.getpid()}",
        "hf=unset",
        "lc=ja_JP.UTF-8",
        "stdin=[]",
    ]


def test_pi_t3_gives_pi_the_variables_of_shellenv_and_userenv(pi_t3):
    """shellenv.sh の既定 (LC_ALL) と、shellenv.sh が読む userenv.sh の変数 (HF_HOME) が、pi に届く。"""
    _userenv(pi_t3.home, "export HF_HOME=/x/hf\n")
    lines = pi_t3().stdout.splitlines()
    assert "hf=/x/hf" in lines
    assert "lc=ja_JP.UTF-8" in lines


def test_pi_t3_keeps_an_explicit_lc_all(pi_t3):
    """呼び出し元 (T3 のインスタンスの環境変数など) が明示した LC_ALL は、shellenv.sh の既定で上書きしない。"""
    assert "lc=C" in pi_t3(LC_ALL="C").stdout.splitlines()


def test_pi_t3_sends_output_of_the_env_files_to_stderr_not_stdout(pi_t3):
    """stdout は pi との RPC。userenv.sh が stdout へ出しても、pi の出力には混ざらず stderr へ回る。"""
    _userenv(pi_t3.home, "echo noisy-out\necho noisy-err >&2\n")
    done = pi_t3()
    assert done.returncode == 0, done.stderr
    assert "noisy" not in done.stdout
    assert "noisy-out" in done.stderr and "noisy-err" in done.stderr


def test_pi_t3_does_not_give_stdin_to_the_env_files(pi_t3):
    """stdin も pi との RPC。userenv.sh が stdin を読んでも、pi 向けの入力は消費されず、pi に届く。"""
    _userenv(pi_t3.home, "cat >/dev/null\n")
    done = pi_t3(stdin_text="rpc-request\n")
    assert done.returncode == 0, done.stderr
    assert "stdin=[rpc-request]" in done.stdout.splitlines()


def test_pi_t3_ignores_inherited_bash_env_and_shellopts(pi_t3, tmp_path):
    """継承した BASH_ENV (stdout へ出しうる) と SHELLOPTS (errexit など) を無視する。#!/bin/bash -p の効き目。"""
    bash_env = tmp_path / "bash_env.sh"
    bash_env.write_text("echo bash-env-ran\n", encoding="utf-8")
    _userenv(pi_t3.home, "false\nexport HF_HOME=/x/hf\n")  # errexit が効くと、ここで止まる
    done = pi_t3(BASH_ENV=str(bash_env), SHELLOPTS="errexit")
    assert done.returncode == 0, done.stderr
    assert "bash-env-ran" not in done.stdout + done.stderr
    assert "hf=/x/hf" in done.stdout.splitlines()


def test_pi_t3_starts_pi_even_if_userenv_returns_nonzero(pi_t3):
    """set -e を付けない。userenv.sh が非 0 を返しても、そこまでの変数を持って pi を起動する。"""
    _userenv(pi_t3.home, "export HF_HOME=/x/hf\nreturn 3\n")
    done = pi_t3()
    assert done.returncode == 0, done.stderr
    assert "hf=/x/hf" in done.stdout.splitlines()


def test_pi_t3_starts_pi_without_shellenv(pi_t3):
    """shellenv.sh が無い機 (Windows など) でも、何も足さずに pi を起動する。"""
    (pi_t3.home / ".config" / "shell" / "shellenv.sh").unlink()
    done = pi_t3("x")
    assert done.returncode == 0, done.stderr
    assert _pi_args(done.stdout) == ["x"]
    assert "lc=unset" in done.stdout.splitlines()


@pytest.mark.parametrize("bad_home", ["", "."])
def test_pi_t3_reads_nothing_from_an_empty_or_relative_home(pi_t3, bad_home):
    """HOME が空・相対のときは、`/.config/…` や作業ディレクトリの下のファイルを読まず、pi だけ起動する。

    作業ディレクトリ (一時 HOME) には shellenv.sh があるので、相対の "." のまま読むと LC_ALL が入る。
    """
    done = pi_t3(HOME=bad_home)
    assert done.returncode == 0, done.stderr
    assert "lc=unset" in done.stdout.splitlines()


def test_pi_t3_finds_pi_on_the_path_that_shellenv_builds(pi_t3):
    """pi は、shellenv.sh を読んだ後の PATH で探す (~/bin は shellenv.sh が PATH の先頭へ足す)。"""
    _stub(pi_t3.home / "bin", pi=_FAKE_PI_T3)
    done = pi_t3("x", path="/usr/bin:/bin")
    assert done.returncode == 0, done.stderr
    assert _pi_args(done.stdout) == ["x"]


def test_pi_t3_fails_with_127_and_empty_stdout_when_pi_is_missing(home, tmp_path, monkeypatch):
    """PATH に pi が無いときは、stdout に何も出さず 127 で終わる (原因は stderr)。"""
    _isolate_host_env(monkeypatch)
    _skip_windows_interop(home)
    empty = tmp_path / "emptybin"
    empty.mkdir()
    done = run([str(_pi_t3_copy(tmp_path))], home, PATH=str(empty))
    assert done.returncode == 127
    assert done.stdout == ""
    assert "pi" in done.stderr


# ---- ROS setup の選び方 ----


def _ros_func(path: Path) -> str:
    m = re.search(r"^__ros_pick\(\) \{.*?^\}\n", path.read_text(encoding="utf-8"), re.S | re.M)
    assert m, f"__ros_pick が {path} に無い"
    return m.group(0)


_ROS_SHELLS = {
    "bash": ("bash", ROOT / "home" / "dot_bashrc", "printf '%s\\n' \"$_ros_setup\""),
    "zsh": (
        "zsh",
        ROOT / "home" / "dot_zshrc.d" / "20_external_envs.zsh",
        'print -r -- "$_ros_setup"',
    ),
}


@pytest.fixture(params=list(_ROS_SHELLS))
def ros(request, home, tmp_path):
    """偽の ROS ルートで __ros_pick を呼び、選ばれた setup の「ルートからの相対パス」を返す。"""
    shell, path, show = _ROS_SHELLS[request.param]
    exe = _zsh() if shell == "zsh" else shell
    root = tmp_path / "ros"
    root.mkdir()

    def pick(**extra: str) -> str:
        script = _ros_func(path) + f'\n__ros_pick "$1"\n{show}\n'
        done = run([exe, "-c", script, "x", str(root)], home, **extra)
        assert done.returncode == 0 and done.stderr == "", done.stderr
        return done.stdout.strip().removeprefix(f"{root}/")

    def make(*names: str) -> None:
        for n in names:
            (root / n).mkdir()
            (root / n / f"setup.{shell}").write_text("", encoding="utf-8")

    pick.make = make
    pick.root = root
    pick.shell = shell
    return pick


def test_ros_empty_root_selects_nothing(ros):
    assert ros() == ""


def test_ros_single_distro_is_selected(ros):
    ros.make("humble")
    assert ros() == f"humble/setup.{ros.shell}"


def test_ros_multiple_without_distro_selects_nothing(ros):
    ros.make("humble", "jazzy")
    assert ros() == ""


def test_ros_distro_is_preferred(ros):
    ros.make("humble", "jazzy")
    assert ros(ROS_DISTRO="humble") == f"humble/setup.{ros.shell}"


def test_ros_unknown_distro_falls_back_to_single(ros):
    ros.make("humble")
    assert ros(ROS_DISTRO="nope") == f"humble/setup.{ros.shell}"


def test_ros_dir_without_setup_is_ignored(ros):
    (ros.root / "empty").mkdir()
    assert ros() == ""


def test_bashrc_leaves_no_ros_residue(home):
    """/opt/ros が無い・あっても非対話で、変数・関数・出力を残さない。"""
    script = (
        "source ~/.bashrc; declare -F __ros_pick; compgen -v | grep -x -e ros_dir -e _ros_setup"
    )
    done = run(["bash", "--noprofile", "--norc", "-c", script], home)
    assert done.stdout == "" and done.stderr == ""


# ---- mise の shims (非対話でも mise のツールを cwd の版で解決させる) ----

_SHELLS = {
    "zsh": lambda: [_zsh(), "-c", 'print -r -- "$PATH"'],
    "login-bash": lambda: [shutil.which("bash") or "/bin/bash", "-lc", 'printf "%s\\n" "$PATH"'],
}


@pytest.fixture(params=list(_SHELLS))
def shims_path(request, home, tmp_path):
    """MISE_DATA_DIR を一時ディレクトリへ向け、起動後の PATH 要素のリストを返す関数を渡す。"""
    data = tmp_path / "mise-data"

    def path_of(
        *, make: bool = True, path: str = "/usr/bin:/bin", **extra: str
    ) -> tuple[str, list[str]]:
        if make:
            (data / "shims").mkdir(parents=True, exist_ok=True)
        done = run(_SHELLS[request.param](), home, MISE_DATA_DIR=str(data), PATH=path, **extra)
        assert done.returncode == 0, done.stderr
        return str(data / "shims"), done.stdout.strip().split(":")

    return path_of


def test_shims_are_first_and_unique(shims_path):
    shims, entries = shims_path()
    assert entries[0] == shims
    assert entries.count(shims) == 1


def test_shims_inherited_in_path_are_moved_to_front_without_duplicates(shims_path, tmp_path):
    shims = str(tmp_path / "mise-data" / "shims")
    inherited = f"/opt/x:{shims}:/usr/bin:{shims}:{shims}:/bin"
    _, entries = shims_path(path=inherited)
    assert entries[0] == shims
    assert entries.count(shims) == 1
    assert entries.index("/opt/x") < entries.index("/usr/bin")  # 他の要素の順序は保つ


def test_venv_bin_stays_ahead_of_shims(shims_path, tmp_path):
    shims = str(tmp_path / "mise-data" / "shims")
    venv = str(tmp_path / "venv")
    _, entries = shims_path(path=f"{venv}/bin:/usr/bin:{shims}", VIRTUAL_ENV=venv)
    assert entries.index(f"{venv}/bin") < entries.index(shims)
    assert entries.index(shims) < entries.index("/usr/bin")
    assert entries.count(shims) == 1


def test_no_shims_dir_leaves_path_alone(shims_path, tmp_path):
    shims, entries = shims_path(make=False)
    assert shims not in entries

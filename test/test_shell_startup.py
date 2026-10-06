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


def run(argv: list[str], home: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in _STARTUP_ENV | _USER_ENV and not k.startswith("BASH_FUNC_")
    }
    env["HOME"] = str(home)
    env.update(extra)
    return subprocess.run(
        argv,
        cwd=home,  # .zshenv が git リポジトリ内で TMPDIR を書き換えないように
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
        timeout=30,
    )


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


def test_shellrc_defines_agent_alias(home):
    done = run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            'shopt -s expand_aliases; source "$HOME/.config/shell/shellrc.sh"; alias agent',
        ],
        home,
    )
    assert "alias agent=" in done.stdout, done.stderr


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


# ---- copilot 起動関数 (既定値の正本は common.toml.tmpl の [agent_env]) ----

_AGENT_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_EDITOR": "false",
    "GCM_INTERACTIVE": "never",
}
_FAKE_COPILOT = """#!/bin/sh
for v in GIT_TERMINAL_PROMPT GIT_EDITOR GCM_INTERACTIVE; do
    eval "if [ -n \\"\\${$v+x}\\" ]; then echo \\"$v=[\\$$v]\\"; else echo \\"$v=<unset>\\"; fi"
done
exit "${FAKE_EXIT:-0}"
"""
_FAKE_COPILOT = _FAKE_COPILOT.replace(
    'exit "${FAKE_EXIT:-0}"',
    'for a in "$@"; do echo "arg=[$a]"; done\n'
    'if [ -n "${FAKE_STDIN:-}" ]; then echo "stdin=[$(cat)]"; fi\n'
    'exit "${FAKE_EXIT:-0}"',
)


@pytest.fixture(params=["bash", "zsh"])
def copilot_call(request, home, tmp_path, monkeypatch):
    """偽の copilot を PATH に置き、一時 HOME の対話シェルで script を実行する関数を返す。"""
    for var in _AGENT_ENV:
        monkeypatch.delenv(var, raising=False)
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "copilot").write_text(_FAKE_COPILOT, encoding="utf-8")
    (fake / "copilot").chmod(0o755)
    exe = _zsh() if request.param == "zsh" else "bash"

    def call(script: str, **extra: str) -> subprocess.CompletedProcess[str]:
        path = f"{fake}:{os.environ['PATH']}"
        return run([exe, "-ic", script], home, PATH=path, **extra)

    return call


def _seen(done: subprocess.CompletedProcess[str]) -> dict[str, str]:
    return dict(line.split("=", 1) for line in done.stdout.splitlines() if "=" in line)


def test_copilot_function_sets_defaults_when_unset(copilot_call):
    done = copilot_call("copilot")
    assert done.returncode == 0, done.stderr
    assert _seen(done) == {k: f"[{v}]" for k, v in _AGENT_ENV.items()}


def test_copilot_function_keeps_explicit_value(copilot_call):
    seen = _seen(copilot_call("copilot", GIT_EDITOR="vim"))
    assert seen["GIT_EDITOR"] == "[vim]"
    assert seen["GIT_TERMINAL_PROMPT"] == "[0]"


def test_copilot_function_keeps_empty_value(copilot_call):
    assert _seen(copilot_call("copilot", GIT_TERMINAL_PROMPT=""))["GIT_TERMINAL_PROMPT"] == "[]"


def test_copilot_function_does_not_leak_into_parent_shell(copilot_call):
    done = copilot_call('copilot >/dev/null; echo "after=${GIT_EDITOR-unset}"')
    assert "after=unset" in done.stdout.splitlines()


def test_copilot_function_passes_exit_status(copilot_call):
    assert copilot_call("copilot", FAKE_EXIT="7").returncode == 7


def test_agent_alias_goes_through_copilot_function(copilot_call):
    if "copilot" not in copilot_call("alias agent").stdout:
        pytest.skip("agent alias が copilot を指さない (applejxd 以外)")
    assert _seen(copilot_call("agent"))["GIT_EDITOR"] == "[false]"


def test_copilot_function_passes_arguments_verbatim(copilot_call):
    done = copilot_call("""copilot 'a b' 'q"x' '$HOME' '*' "it's" ''""")
    args = [ln for ln in done.stdout.splitlines() if ln.startswith("arg=")]
    assert args == ["arg=[a b]", 'arg=[q"x]', "arg=[$HOME]", "arg=[*]", "arg=[it's]", "arg=[]"]


def test_copilot_function_passes_stdin(copilot_call):
    done = copilot_call("echo hello | copilot", FAKE_STDIN="1")
    assert "stdin=[hello]" in done.stdout.splitlines()


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_copilot_function_quotes_special_default_values(shell, tmp_path):
    """既定値に引用符・$・*・空白・バックスラッシュを含んでも、描画後の関数がそのまま渡す。"""
    value = 'it\'s $HOME *  \\n "q" `x`'
    src = (SHELL_DIR / "shellrc.sh.tmpl").read_text(encoding="utf-8")
    old = '{{- $common := includeTemplate "dot_config/agents/common.toml.tmpl" . | fromToml }}'
    assert old in src
    literal = value.replace("\\", "\\\\").replace('"', '\\"')
    new = '{{- $common := dict "agent_env" (dict "GIT_EDITOR" "' + literal + '") }}'
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
    done = subprocess.run(
        [chezmoi, "--source", str(ROOT), "execute-template"],
        input=src.replace(old, new),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert done.returncode == 0, done.stderr
    func = re.search(r"^function copilot\(\) \{\n.*?^\}\n", done.stdout, re.S | re.M)
    assert func, "copilot が描画結果に無い"
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "copilot").write_text('#!/bin/sh\nprintf "%s" "$GIT_EDITOR"\n', encoding="utf-8")
    (fake / "copilot").chmod(0o755)
    exe = _zsh() if shell == "zsh" else "bash"
    env = {k: v for k, v in os.environ.items() if k != "GIT_EDITOR"}
    env["PATH"] = f"{fake}:{env['PATH']}"
    out = subprocess.run(
        [exe, "-c", func.group(0) + "\ncopilot"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
        cwd=tmp_path,
        timeout=30,
    )
    assert out.stdout == value, out.stderr


def test_noninteractive_shells_do_not_define_copilot_function(home):
    assert "function" not in run([_zsh(), "-c", "whence -w copilot"], home).stdout
    assert run(["bash", "-lc", "type -t copilot"], home).stdout.strip() != "function"


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
    "login-bash": lambda: ["bash", "-lc", 'printf "%s\\n" "$PATH"'],
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

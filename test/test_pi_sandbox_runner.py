"""home/dot_local/bin/executable_pi-sandbox-runner: pi の sandbox 拡張の runnerCommand 用ラッパー。

設定 (runner.toml) の検証と、bwrap の引数の組み立て (純粋な部分)、CLI の fail-closed、
実際の bwrap での効き目 (bwrap が使える環境だけ) を確かめる。
実機の GPU・docker・実拡張の確認は scripts/pi_sandbox_selftest.py (docs/spec/sandbox/pi-sandbox-runner.md)。
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "home" / "dot_local" / "bin" / "executable_pi-sandbox-runner"
SHIPPED_CONFIG = ROOT / "home" / "dot_config" / "pi-sandbox" / "runner.toml"

_loader = importlib.machinery.SourceFileLoader("pi_sandbox_runner_under_test", str(RUNNER))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
assert _spec
runner = importlib.util.module_from_spec(_spec)
sys.modules[_loader.name] = runner
_loader.exec_module(runner)

PIB = ROOT / "home" / "dot_local" / "bin" / "executable_pib"
SPEC = ROOT / "docs" / "spec" / "sandbox" / "pi-sandbox-runner.md"

_pib_loader = importlib.machinery.SourceFileLoader("pib_under_test", str(PIB))
_pib_spec = importlib.util.spec_from_loader(_pib_loader.name, _pib_loader)
assert _pib_spec
pib = importlib.util.module_from_spec(_pib_spec)
sys.modules[_pib_loader.name] = pib
_pib_loader.exec_module(pib)

MINIMAL = "version = 1\n"

# runner は bwrap と os.getuid() を使う Linux 専用。設定の検証と引数の組み立て (純粋な部分) だけは、どの OS でも回す
linux_only = pytest.mark.skipif(
    sys.platform != "linux", reason="runner は Linux 専用 (bwrap・getuid)"
)


class FakeHost:
    """ファイルシステムを、与えた集合で置き換える。dirs / socks / files の和が「存在するもの」。"""

    def __init__(self, *, dirs=(), files=(), socks=(), links=None, uid=1000, home="/home/u"):
        self.dirs, self.files, self.socks = set(dirs), set(files), set(socks)
        self.links = dict(links or {})
        self.uid, self.home = uid, home

    def exists(self, p: str) -> bool:
        return p in self.dirs or p in self.files or p in self.socks

    def isdir(self, p: str) -> bool:
        return p in self.dirs

    def issock(self, p: str) -> bool:
        return p in self.socks

    def realpath(self, p: str) -> str:
        return self.links.get(p, p)

    def glob(self, pattern: str) -> list[str]:
        prefix = pattern.split("[")[0]
        return sorted(p for p in self.files if p.startswith(prefix) and p[len(prefix) :].isdigit())

    def host(self):
        return runner.Host(
            home=self.home,
            uid=self.uid,
            exists=self.exists,
            isdir=self.isdir,
            issock=self.issock,
            realpath=self.realpath,
            glob=self.glob,
        )


def config(text: str = MINIMAL):
    return runner.parse_config(text)


# --- 設定の検証 ---------------------------------------------------------------


def test_minimal_config_has_safe_defaults():
    cfg = config()
    assert cfg.gpu_devices == ()
    assert cfg.hide_dirs == () and cfg.hide_files == ()
    assert cfg.docker_block is True and cfg.git_protect is True


def test_shipped_config_is_valid_and_hides_credentials():
    cfg = runner.parse_config(SHIPPED_CONFIG.read_text(encoding="utf-8"))
    assert cfg.gpu_devices == ("auto",)
    assert cfg.docker_block and cfg.git_protect
    assert "~/.ssh" in cfg.hide_dirs and "~/.config/gh" in cfg.hide_dirs
    assert "~/.pi/agent/auth.json" in cfg.hide_files


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "version"),
        ("version = 2\n", "version"),
        ('version = "1"\n', "version"),
        ("version = true\n", "version"),
        ("version = 1.0\n", "version"),
        ("version = 1\nextra_args = []\n", "未知のキー"),
        ("version = 1\n[gpu]\nextra = 1\n", "未知のキー"),
        ("version = 1\n[hide]\ndirs = 'x'\n", "文字列の配列"),
        ("version = 1\n[hide]\ndirs = [1]\n", "文字列の配列"),
        ("version = 1\n[docker]\nblock = 'yes'\n", "true / false"),
        ("version = 1\n[git]\nprotect = 1\n", "true / false"),
        ("version = 1\ngpu = 3\n", "表にする"),
        ("version = 1\n[gpu]\ndevices = ['/etc/passwd']\n", "gpu.devices"),
        ("version = 1\n[gpu]\ndevices = ['/dev/../etc/passwd']\n", "gpu.devices"),
        ("version = 1\n[gpu]\ndevices = ['nvidia0']\n", "gpu.devices"),
        ("version = 1\n[gpu]\ndevices = ['/dev/']\n", "gpu.devices"),
        ("version = 1\n[gpu]\ndevices = ['/dev']\n", "gpu.devices"),
        ("version = 1\n[gpu]\ndevices = ['/dev//nvidia0']\n", "gpu.devices"),
        ("version = 1\n[gpu]\ndevices = ['/dev/dri/']\n", "gpu.devices"),
        ("version = 1\n[hide]\nfiles = ['relative/path']\n", "hide のパス"),
        ("version = 1\n[hide]\ndirs = ['/']\n", "hide のパス"),
        ("version = 1\n[hide]\ndirs = ['~/']\n", "hide のパス"),
        ("version = [\n", "TOML"),
    ],
)
def test_invalid_config_is_rejected(text, message):
    with pytest.raises(runner.RunnerError, match=message):
        config(text)


def test_explicit_device_under_dev_is_accepted():
    cfg = config('version = 1\n[gpu]\ndevices = ["/dev/dri/renderD128", "auto"]\n')
    assert cfg.gpu_devices == ("/dev/dri/renderD128", "auto")


# --- 引数の分割 ---------------------------------------------------------------


def test_split_args_uses_first_separator():
    pre, cmd = runner.split_args(["--ro-bind", "/", "/", "--", "sh", "-c", "echo -- x"])
    assert pre == ["--ro-bind", "/", "/"]
    assert cmd == ["sh", "-c", "echo -- x"]


@pytest.mark.parametrize("argv", [[], ["--ro-bind", "/", "/"], ["--ro-bind", "/", "/", "--"]])
def test_split_args_requires_separator_and_command(argv):
    with pytest.raises(runner.RunnerError):
        runner.split_args(argv)


# --- bwrap の引数の組み立て ---------------------------------------------------


def test_gpu_auto_binds_only_existing_devices_with_dev_bind():
    fake = FakeHost(
        files={"/dev/dxg", "/dev/nvidiactl", "/dev/nvidia0", "/dev/nvidia1", "/dev/null"}
    )
    extra = runner.build_extra(config('version = 1\n[gpu]\ndevices = ["auto"]\n'), [], fake.host())
    assert extra == [
        "--dev-bind", "/dev/dxg", "/dev/dxg",
        "--dev-bind", "/dev/nvidiactl", "/dev/nvidiactl",
        "--dev-bind", "/dev/nvidia0", "/dev/nvidia0",
        "--dev-bind", "/dev/nvidia1", "/dev/nvidia1",
    ]  # fmt: skip


def test_gpu_off_and_missing_devices_add_nothing():
    fake = FakeHost(files={"/dev/dxg"})
    assert runner.build_extra(config(), [], fake.host()) == []
    cfg = config('version = 1\n[gpu]\ndevices = ["/dev/dri/renderD128"]\n')
    assert runner.build_extra(cfg, [], fake.host()) == []


def test_gpu_devices_come_after_the_dev_mount_and_before_the_separator(tmp_path):
    """--dev /dev の後に置かないと、デバイスが隠れる。拡張の引数の後ろに足すことで保証する。

    引数の並びは @yuru7/pi-sandbox 0.5.0 の bwrapProfileArgs (src/runners.ts) と同じ。
    拡張を更新したら、この並びが今も同じかを確かめる (docs/spec/sandbox/pi-sandbox-runner.md#版の固定と更新)。
    """
    conf = tmp_path / "runner.toml"
    conf.write_text('version = 1\n[gpu]\ndevices = ["auto"]\n', encoding="utf-8")
    profile = [
        *("--ro-bind", "/", "/", "--dev", "/dev", "--unshare-pid", "--proc", "/proc"),
        *("--die-with-parent", "--bind", "/tmp", "/tmp", "--bind", "/w/ws", "/w/ws"),
    ]
    fake = FakeHost(files={"/dev/dxg"})
    command = runner.build_command(
        [*profile, "--", "python3", "job.py"], {"PI_SANDBOX_RUNNER_CONFIG": str(conf)}, fake.host()
    )
    assert command[: 1 + len(profile)] == ["bwrap", *profile]  # 拡張の引数は並びを変えずに先頭
    assert command.index("--dev") < command.index("--dev-bind") < command.index("--")
    assert command[-3:] == ["--", "python3", "job.py"]


def test_hide_covers_only_existing_paths_by_kind():
    fake = FakeHost(
        dirs={"/home/u/.ssh", "/home/u/.config/gh"},
        files={"/home/u/.netrc", "/home/u/.pi/agent/auth.json"},
    )
    cfg = config(
        """
        version = 1
        [hide]
        dirs = ["~/.ssh", "~/.aws", "~/.netrc"]
        files = ["~/.netrc", "~/.pi/agent/auth.json", "~/.vault-token", "~/.config/gh"]
        """
    )
    extra = runner.build_extra(cfg, [], fake.host())
    assert extra == [
        "--tmpfs", "/home/u/.ssh",  # 存在するディレクトリ
        "--ro-bind", "/dev/null", "/home/u/.netrc",  # ファイルは /dev/null で覆う
        "--ro-bind", "/dev/null", "/home/u/.pi/agent/auth.json",
    ]  # fmt: skip
    # dirs に書いた「ファイル」(~/.netrc) と、files に書いた「ディレクトリ」(~/.config/gh) は覆わない


def test_docker_block_hides_run_dir_and_sockets_once_per_target():
    fake = FakeHost(
        dirs={"/run/user/1000"},
        socks={"/run/docker.sock", "/var/run/docker.sock"},
        links={"/var/run/docker.sock": "/run/docker.sock"},
    )
    extra = runner.build_extra(config(), [], fake.host())
    assert extra == [
        "--tmpfs", "/run/user/1000",
        "--ro-bind", "/dev/null", "/run/docker.sock",
    ]  # fmt: skip


def test_docker_block_can_be_turned_off():
    fake = FakeHost(dirs={"/run/user/1000"}, socks={"/run/docker.sock"})
    cfg = config("version = 1\n[docker]\nblock = false\n")
    assert runner.build_extra(cfg, [], fake.host()) == []


def test_git_protect_makes_hooks_and_config_read_only_for_writable_git_dirs():
    wt = "/w/wt"
    common = "/w/main/.git"
    fake = FakeHost(
        dirs={wt, common, f"{common}/hooks", f"{common}/objects", "/tmp"},
        files={
            f"{common}/HEAD",
            f"{common}/config",
            f"{wt}/.git",  # worktree の .git はファイル (hooks / config を持たない)
            "/tmp/config",  # git ディレクトリではない場所の config には触らない
        },
    )
    pre = [
        "--ro-bind",
        "/",
        "/",
        "--bind",
        "/tmp",
        "/tmp",
        "--bind",
        wt,
        wt,
        "--bind",
        common,
        common,
    ]
    extra = runner.build_extra(config(), pre, fake.host())
    assert extra == [
        "--ro-bind", f"{common}/hooks", f"{common}/hooks",
        "--ro-bind", f"{common}/config", f"{common}/config",
    ]  # fmt: skip


def test_git_protect_covers_dot_git_directory_of_the_workspace():
    ws = "/w/repo"
    fake = FakeHost(
        dirs={ws, f"{ws}/.git", f"{ws}/.git/hooks", f"{ws}/.git/objects"},
        files={f"{ws}/.git/HEAD", f"{ws}/.git/config", f"{ws}/.git/config.worktree"},
    )
    extra = runner.build_extra(config(), ["--bind", ws, ws], fake.host())
    assert extra == [
        "--ro-bind", f"{ws}/.git/hooks", f"{ws}/.git/hooks",
        "--ro-bind", f"{ws}/.git/config", f"{ws}/.git/config",
        "--ro-bind", f"{ws}/.git/config.worktree", f"{ws}/.git/config.worktree",
    ]  # fmt: skip


def test_git_protect_ignores_binds_to_a_different_target_and_can_be_off():
    ws = "/w/repo"
    fake = FakeHost(dirs={ws, f"{ws}/hooks", f"{ws}/objects"}, files={f"{ws}/HEAD", f"{ws}/config"})
    assert runner.build_extra(config(), ["--bind", ws, "/elsewhere"], fake.host()) == []
    off = config("version = 1\n[git]\nprotect = false\n")
    assert runner.build_extra(off, ["--bind", ws, ws], fake.host()) == []


def test_extra_order_is_gpu_git_hide_docker():
    fake = FakeHost(
        dirs={"/home/u/.ssh", "/run/user/1000", "/w/ws", "/w/ws/hooks", "/w/ws/objects"},
        files={"/dev/dxg", "/w/ws/HEAD", "/w/ws/config"},
    )
    cfg = config('version = 1\n[gpu]\ndevices = ["auto"]\n[hide]\ndirs = ["~/.ssh"]\n')
    extra = runner.build_extra(cfg, ["--bind", "/w/ws", "/w/ws"], fake.host())
    kinds = [a for a in extra if a.startswith("--")]
    assert kinds == ["--dev-bind", "--ro-bind", "--ro-bind", "--tmpfs", "--tmpfs"]
    # 順に: GPU → git (hooks と config) → 隠蔽 (~/.ssh) → docker (/run/user)


def test_hide_comes_after_git_protection_so_a_hidden_git_dir_stays_hidden():
    """隠す場所の中に git の bind があっても、後から重ねる隠蔽が勝つ (git の bind が再び見せない)。"""
    ws = "/w/ws"
    fake = FakeHost(
        dirs={ws, f"{ws}/.git", f"{ws}/.git/hooks", f"{ws}/.git/objects"},
        files={f"{ws}/.git/HEAD", f"{ws}/.git/config"},
    )
    cfg = config(f'version = 1\n[hide]\ndirs = ["{ws}/.git"]\n')
    extra = runner.build_extra(cfg, ["--bind", ws, ws], fake.host())
    assert extra[-2:] == ["--tmpfs", f"{ws}/.git"]
    assert extra.index("--tmpfs") > max(i for i, a in enumerate(extra) if a == "--ro-bind")


def test_git_protect_only_covers_targets_that_exist():
    """限界 (docs): 無い hooks・config.worktree は覆えない。内側から新規作成できる。"""
    ws = "/w/ws"
    fake = FakeHost(dirs={ws, f"{ws}/objects"}, files={f"{ws}/HEAD", f"{ws}/config"})
    extra = runner.build_extra(config(), ["--bind", ws, ws], fake.host())
    assert extra == ["--ro-bind", f"{ws}/config", f"{ws}/config"]


def test_hide_uses_the_resolved_path_of_symlinks():
    """リンクのままだと bwrap が失敗する。実体のパスで覆う。"""
    fake = FakeHost(
        dirs={"/data/ssh"},
        files={"/data/netrc"},
        links={"/home/u/.ssh": "/data/ssh", "/home/u/.netrc": "/data/netrc"},
    )
    cfg = config('version = 1\n[hide]\ndirs = ["~/.ssh"]\nfiles = ["~/.netrc"]\n')
    extra = runner.build_extra(cfg, [], fake.host())
    assert extra == ["--tmpfs", "/data/ssh", "--ro-bind", "/dev/null", "/data/netrc"]


# --- CLI (exec しない) ---------------------------------------------------------


def run_cli(args, env_extra=None, cwd=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PI_SANDBOX_RUNNER_")}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(RUNNER), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=cwd,
        timeout=30,
        check=False,
    )


# --- このマシンだけの追記 (runner.local.toml) ---------------------------------

LOCAL_EXAMPLE = ROOT / "home" / "dot_config" / "pi-sandbox" / "runner.local.toml.example"


def test_local_example_is_valid_and_adds_nothing_until_edited():
    """同梱の見本は、そのままコピーしても有効で、何も足さない (見本の行はコメントアウトしてある)。"""
    assert runner.parse_local(LOCAL_EXAMPLE.read_text(encoding="utf-8")) == ((), ())


def test_local_config_adds_after_the_shared_entries_without_duplicates():
    shared = config('version = 1\n[gpu]\ndevices = ["auto"]\n[hide]\ndirs = ["~/.ssh"]\n')
    local = runner.parse_local('[hide]\ndirs = ["~/notes", "~/.ssh"]\nfiles = ["~/.tok"]\n')
    merged = runner.merge_local(shared, local)
    assert merged.gpu_devices == ("auto",)  # デバイスは local から増えない
    assert merged.hide_dirs == ("~/.ssh", "~/notes")  # 共有が先。重複は 1 つ
    assert merged.hide_files == ("~/.tok",)
    assert merged.docker_block is shared.docker_block and merged.git_protect is shared.git_protect


@pytest.mark.parametrize(
    ("table", "body"),
    [
        ("docker", "block = true"),
        ("git", "protect = true"),
        (
            "gpu",
            'devices = ["/dev/nvidia0"]',
        ),  # デバイスの公開は緩める方向なので、local からは足せない
        ("gpu", 'devices = ["/dev/"]'),
    ],
)
def test_local_config_cannot_touch_the_settings_that_could_loosen_the_shared_ones(table, body):
    with pytest.raises(runner.RunnerError, match=f"\\[{table}\\] を変えられない"):
        runner.parse_local(f"[{table}]\n{body}\n")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("extra_args = []\n", "未知のキー"),
        ("version = 2\n", "version"),
        ('version = "1"\n', "version"),
        ("[hide]\ndirs = ['/']\n", "hide のパス"),
        ("[hide]\nfiles = ['relative']\n", "hide のパス"),
        ("[hide]\nextra = 1\n", "未知のキー"),
        ("[hide\n", "TOML"),
    ],
)
def test_invalid_local_config_is_rejected(text, message):
    with pytest.raises(runner.RunnerError, match=message):
        runner.parse_local(text)


def test_local_config_may_omit_version_and_may_be_empty():
    assert runner.parse_local("") == ((), ())
    assert runner.parse_local("version = 1\n") == ((), ())


def test_load_config_reads_the_local_file_next_to_the_shared_one(tmp_path):
    shared = tmp_path / "runner.toml"
    shared.write_text('version = 1\n[hide]\ndirs = ["~/.ssh"]\n', encoding="utf-8")
    assert runner.load_config(shared).hide_dirs == ("~/.ssh",)  # 無くてよい
    (tmp_path / "runner.local.toml").write_text('[hide]\ndirs = ["~/notes"]\n', encoding="utf-8")
    assert runner.load_config(shared).hide_dirs == ("~/.ssh", "~/notes")


@linux_only
def test_dry_run_command_contains_the_local_additions(tmp_path):
    (tmp_path / "runner.toml").write_text(MINIMAL, encoding="utf-8")
    notes = tmp_path / "notes"
    notes.mkdir()
    (tmp_path / "runner.local.toml").write_text(f'[hide]\ndirs = ["{notes}"]\n', encoding="utf-8")
    env = {
        "PI_SANDBOX_RUNNER_CONFIG": str(tmp_path / "runner.toml"),
        "PI_SANDBOX_RUNNER_DRYRUN": "1",
    }
    result = run_cli(["--ro-bind", "/", "/", "--", "true"], env)
    assert result.returncode == 0, result.stderr
    command = json.loads(result.stdout)
    assert ["--tmpfs", str(notes.resolve())] == command[command.index("--tmpfs") :][:2]


@linux_only
@pytest.mark.parametrize(
    ("local_bytes", "needle"),
    [
        (b"[docker]\nblock = false\n", "[docker]"),
        (b"[hide\n", "TOML"),
        (b"# \xff\xfe\n", "設定を読めない"),
    ],
)
def test_cli_fails_closed_when_the_local_config_is_broken(tmp_path, local_bytes, needle):
    (tmp_path / "runner.toml").write_text(MINIMAL, encoding="utf-8")
    (tmp_path / "runner.local.toml").write_bytes(local_bytes)
    env = {"PI_SANDBOX_RUNNER_CONFIG": str(tmp_path / "runner.toml")}
    result = run_cli(["--", "true"], env)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("pi-sandbox-runner:")
    assert needle in result.stderr
    assert "Traceback" not in result.stderr


@linux_only
@pytest.mark.parametrize("kind", ["broken_symlink", "directory", "symlink_loop"])
def test_cli_fails_closed_when_the_local_entry_exists_but_cannot_be_read(tmp_path, kind):
    """エントリがあるのに読めないものを「設定なし」にしない (隠す指定が黙って消えるため)。"""
    (tmp_path / "runner.toml").write_text(MINIMAL, encoding="utf-8")
    entry = tmp_path / "runner.local.toml"
    if kind == "broken_symlink":
        entry.symlink_to(tmp_path / "gone.toml")
    elif kind == "directory":
        entry.mkdir()
    else:
        entry.symlink_to(entry.name)  # 自分自身を指すリンク
    env = {"PI_SANDBOX_RUNNER_CONFIG": str(tmp_path / "runner.toml")}
    result = run_cli(["--", "true"], env)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("pi-sandbox-runner:")
    assert "runner.local.toml" in result.stderr
    assert "Traceback" not in result.stderr


def test_load_config_follows_a_valid_symlink_for_the_local_file(tmp_path):
    (tmp_path / "runner.toml").write_text(MINIMAL, encoding="utf-8")
    real = tmp_path / "elsewhere.toml"
    real.write_text('[hide]\ndirs = ["~/notes"]\n', encoding="utf-8")
    (tmp_path / "runner.local.toml").symlink_to(real)
    assert runner.load_config(tmp_path / "runner.toml").hide_dirs == ("~/notes",)


@linux_only
def test_cli_dry_run_prints_final_command(tmp_path):
    conf = tmp_path / "runner.toml"
    conf.write_text(
        "version = 1\n[docker]\nblock = false\n[git]\nprotect = false\n", encoding="utf-8"
    )
    env = {"PI_SANDBOX_RUNNER_CONFIG": str(conf), "PI_SANDBOX_RUNNER_DRYRUN": "1"}
    result = run_cli(["--ro-bind", "/", "/", "--", "echo", "hi"], env)
    assert result.returncode == 0, result.stderr
    command = json.loads(result.stdout)
    assert command[0] == "bwrap"
    assert command[1:4] == ["--ro-bind", "/", "/"]
    assert command[-3:] == ["--", "echo", "hi"]


@linux_only
@pytest.mark.parametrize(
    ("args", "conf_text", "needle"),
    [
        (["--", "true"], None, "設定を読めない"),
        (["--", "true"], "version = 9\n", "version"),
        (["--ro-bind", "/", "/"], MINIMAL, "区切り"),
        (["--ro-bind", "/", "/", "--"], MINIMAL, "コマンドが無い"),
    ],
)
def test_cli_fails_closed_before_running_anything(tmp_path, args, conf_text, needle):
    conf = tmp_path / "runner.toml"
    if conf_text is not None:
        conf.write_text(conf_text, encoding="utf-8")
    env = {"PI_SANDBOX_RUNNER_CONFIG": str(conf)}
    result = run_cli(args, env)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("pi-sandbox-runner:")  # runnerFailureSignatures と揃える
    assert needle in result.stderr


@linux_only
def test_cli_rejects_a_config_that_is_not_utf8_without_a_traceback(tmp_path):
    conf = tmp_path / "runner.toml"
    conf.write_bytes(b"version = 1\n# \xff\xfe\n")
    result = run_cli(["--", "true"], {"PI_SANDBOX_RUNNER_CONFIG": str(conf)})
    assert result.returncode == 2
    assert result.stderr.startswith("pi-sandbox-runner:")
    assert "Traceback" not in result.stderr


@linux_only
def test_config_defaults_to_the_users_directory_not_the_working_tree(tmp_path):
    """設定は ~/.config/pi-sandbox だけを読む。作業ツリーに置いた設定は読まない。"""
    home, work = tmp_path / "home", tmp_path / "work"
    (home / ".config" / "pi-sandbox").mkdir(parents=True)
    work.mkdir()
    (work / "runner.toml").write_text(MINIMAL, encoding="utf-8")
    (work / ".pi").mkdir()
    (work / ".pi" / "runner.toml").write_text(MINIMAL, encoding="utf-8")
    env = {"HOME": str(home), "XDG_CONFIG_HOME": "", "PI_SANDBOX_RUNNER_DRYRUN": "1"}
    result = run_cli(["--", "true"], env, cwd=work)
    assert result.returncode == 2  # ホスト側に設定が無いので、作業ツリーのものでは動かない
    (home / ".config" / "pi-sandbox" / "runner.toml").write_text(MINIMAL, encoding="utf-8")
    assert run_cli(["--", "true"], env, cwd=work).returncode == 0


# --- 実際の bwrap (使える環境だけ) --------------------------------------------


def _bwrap_usable() -> bool:
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        return False
    probe = subprocess.run(
        [bwrap, "--ro-bind", "/", "/", "true"], capture_output=True, timeout=30, check=False
    )
    return probe.returncode == 0


needs_bwrap = pytest.mark.skipif(
    sys.platform != "linux" or not _bwrap_usable(),
    reason="bwrap が使えない (user namespace が無いなど)",
)


def run_in_sandbox(tmp_path, conf_text, extra_binds, script, home=None):
    conf = tmp_path / "runner.toml"
    conf.write_text(conf_text, encoding="utf-8")
    env = {
        "PI_SANDBOX_RUNNER_CONFIG": str(conf),
        "HOME": str(home or tmp_path / "home"),
        "PATH": os.environ["PATH"],
    }
    args = ["--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--die-with-parent"]
    for path in extra_binds:
        args += ["--bind", str(path), str(path)]
    return run_cli([*args, "--", "sh", "-c", script], env)


@needs_bwrap
def test_real_sandbox_hides_configured_paths(tmp_path):
    home = tmp_path / "home"
    (home / "secret").mkdir(parents=True)
    (home / "secret" / "token").write_text("TOKEN", encoding="utf-8")
    (home / "cred").write_text("CRED", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    conf = 'version = 1\n[hide]\ndirs = ["~/secret"]\nfiles = ["~/cred"]\n'
    script = (
        f'ls -A "{home}/secret" | wc -l; cat "{home}/cred" | wc -c; touch "{work}/ok" && echo wrote'
    )
    result = run_in_sandbox(tmp_path, conf, [work], script, home=home)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["0", "0", "wrote"]
    assert (work / "ok").exists()
    assert (home / "secret" / "token").read_text(encoding="utf-8") == "TOKEN"  # 外側は無傷


@needs_bwrap
@pytest.mark.skipif(shutil.which("git") is None, reason="git が無い")
def test_real_sandbox_protects_git_hooks_and_config_but_allows_commit(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    env = {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "PATH": os.environ["PATH"],
    }
    subprocess.run(["git", "init", "-q", str(work)], check=True, env=env)
    script = (
        f'cd "{work}"; '
        "echo x > .git/hooks/pre-commit 2>/dev/null && echo hooks=writable || echo hooks=ro; "
        "echo x >> .git/config 2>/dev/null && echo config=writable || echo config=ro; "
        "git -c user.name=t -c user.email=t@example.invalid commit --allow-empty -qm t "
        "&& echo commit=ok || echo commit=failed"
    )
    result = run_in_sandbox(tmp_path, MINIMAL, [work], script)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["hooks=ro", "config=ro", "commit=ok"]
    assert not (work / ".git" / "hooks" / "pre-commit").exists()


@needs_bwrap
def test_real_sandbox_follows_symlinks_when_hiding(tmp_path):
    """隠す場所がシンボリックリンクでも bwrap は失敗せず、リンクからも実体からも見えない。"""
    home = tmp_path / "home"
    real_dir, real_file = tmp_path / "data" / "dir", tmp_path / "data" / "file"
    real_dir.mkdir(parents=True)
    home.mkdir()
    (real_dir / "token").write_text("TOKEN", encoding="utf-8")
    real_file.write_text("CRED", encoding="utf-8")
    (home / "link-dir").symlink_to(real_dir)
    (home / "link-file").symlink_to(real_file)
    work = tmp_path / "work"
    work.mkdir()
    conf = 'version = 1\n[hide]\ndirs = ["~/link-dir"]\nfiles = ["~/link-file"]\n'
    script = (
        f'ls -A "{home}/link-dir" | wc -l; ls -A "{real_dir}" | wc -l; '
        f'cat "{home}/link-file" 2>/dev/null | wc -c; cat "{real_file}" 2>/dev/null | wc -c'
    )
    result = run_in_sandbox(tmp_path, conf, [work], script, home=home)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["0", "0", "0", "0"]


@needs_bwrap
def test_real_sandbox_keeps_a_hidden_git_dir_hidden(tmp_path):
    """git の保護の bind が、隠した .git の中身 (config) を再び見せない。"""
    work = tmp_path / "work"
    (work / ".git" / "hooks").mkdir(parents=True)
    (work / ".git" / "objects").mkdir()
    (work / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (work / ".git" / "config").write_text("[core]\n\tDUMMY = 1\n", encoding="utf-8")
    conf = f'version = 1\n[hide]\ndirs = ["{work}/.git"]\n'
    script = (
        f'ls -A "{work}/.git" | wc -l; grep -c DUMMY "{work}/.git/config" 2>/dev/null || echo 0'
    )
    result = run_in_sandbox(tmp_path, conf, [work], script)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["0", "0"]


# --- pib (拡張つきの起動) ------------------------------------------------------


def make_setup(tmp_path, *, settings=None, runner=True, config=True):
    """配備済みの HOME を作る。settings が None なら正しい拡張の設定を置く。"""
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".config" / "pi-sandbox").mkdir(parents=True)
    (home / ".pi" / "agent").mkdir(parents=True)
    if runner:
        path = home / ".local" / "bin" / "pi-sandbox-runner"
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        path.chmod(0o755)
    if config:
        (home / ".config" / "pi-sandbox" / "runner.toml").write_text(MINIMAL, encoding="utf-8")
    if settings is None:
        settings = {
            "runnerCommand": [str(home / ".local" / "bin" / "pi-sandbox-runner")],
            "runnerFailureSignatures": ["pi-sandbox-runner:", "bwrap:"],
        }
    if settings is not False:
        (home / ".pi" / "agent" / "pi-sandbox.json").write_text(
            json.dumps(settings), encoding="utf-8"
        )
    return home


def test_pib_pins_the_extension_version_written_in_the_docs():
    assert pib.EXTENSION.startswith("npm:@yuru7/pi-sandbox@")
    assert pib.EXTENSION in SPEC.read_text(encoding="utf-8")


def test_pib_accepts_a_complete_setup(tmp_path):
    assert pib.problems({}, make_setup(tmp_path)) == []


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"runner": False}, "runner が無い"),
        ({"config": False}, "runner の設定が無い"),
        ({"settings": False}, "拡張の設定を読めない"),
        ({"settings": {}}, "runnerCommand"),
        (
            {"settings": {"runnerCommand": ["/usr/bin/bwrap"], "runnerFailureSignatures": ["x"]}},
            "runnerCommand",
        ),
        ({"settings": {"runnerCommand": ["/x/pi-sandbox-runner"]}}, "runnerFailureSignatures"),
        ({"settings": []}, "runnerCommand"),
    ],
)
def test_pib_names_what_is_missing(tmp_path, kwargs, needle):
    found = pib.problems({}, make_setup(tmp_path, **kwargs))
    assert any(needle in line for line in found), found


def test_pib_honours_the_agent_dir_and_config_overrides(tmp_path):
    home = make_setup(tmp_path, settings=False, config=False)
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / "pi-sandbox.json").write_text(
        json.dumps({"runnerCommand": ["/x/pi-sandbox-runner"], "runnerFailureSignatures": ["x"]}),
        encoding="utf-8",
    )
    conf = tmp_path / "elsewhere.toml"
    conf.write_text(MINIMAL, encoding="utf-8")
    env = {"PI_CODING_AGENT_DIR": str(agent), "PI_SANDBOX_RUNNER_CONFIG": str(conf)}
    assert pib.problems(env, home) == []


def run_pib(home, fake_pi_dir, args=()):
    env = {"HOME": str(home), "PATH": f"{fake_pi_dir}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run(
        [sys.executable, str(PIB), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
        check=False,
    )


def fake_pi(tmp_path):
    """引数を記録するだけの pi。"""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    pi = bin_dir / "pi"
    pi.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{tmp_path}/pi-args"\n', encoding="utf-8")
    pi.chmod(0o755)
    return bin_dir


@linux_only
def test_pib_runs_pi_with_the_pinned_extension_and_passes_arguments_through(tmp_path):
    result = run_pib(make_setup(tmp_path), fake_pi(tmp_path), ["-p", "hello"])
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "pi-args").read_text(encoding="utf-8").split("\n")[:-1] == [
        "-e",
        pib.EXTENSION,
        "-p",
        "hello",
    ]


@linux_only
def test_pib_does_not_start_pi_when_the_setup_is_incomplete(tmp_path):
    result = run_pib(make_setup(tmp_path, runner=False), fake_pi(tmp_path))
    assert result.returncode == 2
    assert result.stderr.startswith("pib:")
    assert not (tmp_path / "pi-args").exists()  # pi は起動していない

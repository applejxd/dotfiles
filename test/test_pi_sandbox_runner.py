"""home/dot_local/bin/executable_pi-sandbox-runner・executable_pib・executable_pib-shell: pi のコマンド実行を包む囲い。

設定 (runner.toml・runner.local.toml) の検証、bwrap の引数の組み立て (純粋な部分)、CLI の fail-closed、
実際の bwrap での効き目 (bwrap が使える環境だけ)、pib と pib-shell の起動を確かめる。
実機の GPU・docker・実際の pi での確認は scripts/pi_sandbox_selftest.py (docs/spec/sandbox/pi-sandbox-runner.md)。
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import posixpath
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "home" / "dot_local" / "bin" / "executable_pi-sandbox-runner"
PIB = ROOT / "home" / "dot_local" / "bin" / "executable_pib"
PIB_SHELL = ROOT / "home" / "dot_local" / "bin" / "executable_pib-shell"
SHIPPED_CONFIG = ROOT / "home" / "dot_config" / "pi-sandbox" / "runner.toml"
LOCAL_EXAMPLE = ROOT / "home" / "dot_config" / "pi-sandbox" / "runner.local.toml.example"
SPEC = ROOT / "docs" / "spec" / "sandbox" / "pi-sandbox-runner.md"


def _load(name: str, path: Path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


runner = _load("pi_sandbox_runner_under_test", RUNNER)
pib = _load("pib_under_test", PIB)

MINIMAL = "version = 1\n"

# runner は bwrap と os.getuid() を使う Linux 専用。設定の検証と引数の組み立て (純粋な部分) だけは、どの OS でも回す
linux_only = pytest.mark.skipif(
    sys.platform != "linux", reason="runner は Linux 専用 (bwrap・getuid)"
)


class FakeHost:
    """ファイルシステムを、与えた集合で置き換える。dirs / socks / files の和が「存在するもの」。"""

    def __init__(
        self, *, dirs=(), files=(), socks=(), links=None, texts=None, uid=1000, home="/home/u"
    ):
        self.dirs, self.files, self.socks = set(dirs), set(files), set(socks)
        self.links = dict(links or {})
        self.texts = dict(texts or {})
        self.uid, self.home = uid, home

    def exists(self, p: str) -> bool:
        return p in self.dirs or p in self.files or p in self.socks

    def isdir(self, p: str) -> bool:
        return p in self.dirs

    def issock(self, p: str) -> bool:
        return p in self.socks

    def realpath(self, p: str) -> str:
        p = posixpath.normpath(p)  # 実際の realpath と同じく、末尾の / などを整える
        return self.links.get(p, p)

    def islink(self, p: str) -> bool:
        return p in self.links and self.links[p] != p

    def glob(self, pattern: str) -> list[str]:
        prefix = pattern.split("[")[0]
        return sorted(p for p in self.files if p.startswith(prefix) and p[len(prefix) :].isdigit())

    def read_text(self, p: str) -> str:
        return self.texts.get(p, "")

    def host(self):
        return runner.Host(
            home=self.home,
            uid=self.uid,
            exists=self.exists,
            isdir=self.isdir,
            issock=self.issock,
            realpath=self.realpath,
            islink=self.islink,
            glob=self.glob,
            read_text=self.read_text,
        )


def config(text: str = MINIMAL):
    return runner.parse_config(text)


# --- 設定の検証 ---------------------------------------------------------------


def test_minimal_config_has_safe_defaults():
    cfg = config()
    assert cfg.gpu_devices == ()
    assert cfg.hide_dirs == () and cfg.hide_files == ()
    assert cfg.visible_read == () and cfg.visible_write == () and cfg.env_unset == ()
    assert cfg.docker_block is True and cfg.git_protect is True


def test_shipped_config_is_valid_and_hides_credentials():
    cfg = runner.parse_config(SHIPPED_CONFIG.read_text(encoding="utf-8"))
    assert cfg.gpu_devices == ("auto",)
    assert cfg.docker_block and cfg.git_protect
    assert "~/.ssh" in cfg.hide_dirs and "~/.config/gh" in cfg.hide_dirs
    assert "~/.pi/agent/auth.json" in cfg.hide_files
    # store ヘルパーの認証 (git の push に使われる) は、ファイルが見える場所にあっても隠す
    assert "~/.git-credentials" in cfg.hide_files and "~/.config/git/credentials" in cfg.hide_files
    assert {"GH_TOKEN", "GITHUB_TOKEN", "SSH_AUTH_SOCK"} <= set(cfg.env_unset)


def test_shipped_config_never_makes_the_whole_huggingface_cache_writable():
    """~/.cache/huggingface には認証 (token・stored_tokens) が同居する。モデルとデータセットの下だけを書き込み可にする。"""
    cfg = runner.parse_config(SHIPPED_CONFIG.read_text(encoding="utf-8"))
    shown = (*cfg.visible_read, *cfg.visible_write)
    assert "~/.cache/huggingface" not in shown and "~/.cache" not in shown
    assert "~/.cache/huggingface/hub" in cfg.visible_write
    # 利用者が上の親を見せても、認証は隠れる
    assert {"~/.cache/huggingface/token", "~/.cache/huggingface/stored_tokens"} <= set(
        cfg.hide_files
    )


def test_shipped_config_shows_git_settings_but_never_the_whole_git_directory():
    """~/.config/git を丸ごと見せると、store ヘルパーの認証 (credentials) も見える。設定のファイルだけを見せる。"""
    cfg = runner.parse_config(SHIPPED_CONFIG.read_text(encoding="utf-8"))
    shown = (*cfg.visible_read, *cfg.visible_write)
    assert "~/.config/git" not in shown
    assert "~/.config/git/config" in cfg.visible_read
    assert not any(p in ("~/.config", "~/.local", "~/.cache", "~/.pi") for p in shown)
    assert all(not p.startswith("~/.ssh") and not p.startswith("~/.config/gh") for p in shown)


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
        ("version = 1\n[visible]\nextra = 1\n", "未知のキー"),
        ("version = 1\n[env]\nextra = 1\n", "未知のキー"),
        ("version = 1\n[hide]\ndirs = 'x'\n", "文字列の配列"),
        ("version = 1\n[hide]\ndirs = [1]\n", "文字列の配列"),
        ("version = 1\n[visible]\nread = 'x'\n", "文字列の配列"),
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
        ("version = 1\n[hide]\nfiles = ['relative/path']\n", "hide.files のパス"),
        ("version = 1\n[hide]\ndirs = ['/']\n", "hide.dirs のパス"),
        ("version = 1\n[hide]\ndirs = ['~/']\n", "hide.dirs のパス"),
        ("version = 1\n[visible]\nread = ['/']\n", "visible.read のパス"),
        ("version = 1\n[visible]\nwrite = ['~/']\n", "visible.write のパス"),
        ("version = 1\n[visible]\nread = ['relative']\n", "visible.read のパス"),
        ("version = 1\n[visible]\nread = ['~/a/../b']\n", r"\.\. は書けない"),
        ("version = 1\n[visible]\nwrite = ['/mnt/d/../c']\n", r"\.\. は書けない"),
        ("version = 1\n[hide]\nfiles = ['~/../x']\n", r"\.\. は書けない"),
        ("version = 1\n[env]\nunset = ['A B']\n", "環境変数の名前"),
        ("version = 1\n[env]\nunset = ['1ABC']\n", "環境変数の名前"),
        ("version = 1\n[env]\nunset = ['A=B']\n", "環境変数の名前"),
        ("version = [\n", "TOML"),
    ],
)
def test_invalid_config_is_rejected(text, message):
    with pytest.raises(runner.RunnerError, match=message):
        config(text)


def test_explicit_device_under_dev_is_accepted():
    cfg = config('version = 1\n[gpu]\ndevices = ["/dev/dri/renderD128", "auto"]\n')
    assert cfg.gpu_devices == ("/dev/dri/renderD128", "auto")


# --- コマンドラインの分割 -----------------------------------------------------


def test_parse_cli_takes_dash_c_and_optional_offline():
    assert runner.parse_cli(["-c", "echo hi"]) == (False, "echo hi")
    assert runner.parse_cli(["--offline", "-c", "echo hi"]) == (True, "echo hi")


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["-c"],
        ["-c", "  "],
        ["echo", "hi"],  # pi は -c でしか呼ばない。bash の他の使い方は受け付けない
        ["-i"],
        ["-c", "echo", "extra"],
        ["--offline"],
        ["-c", "x", "--offline"],
    ],
)
def test_parse_cli_rejects_everything_else(argv):
    with pytest.raises(runner.RunnerError):
        runner.parse_cli(argv)


# --- bwrap の引数の組み立て (GPU・隠蔽・docker・git) --------------------------


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


# --- シェルモードの土台 (許可リスト型) -----------------------------------------

BASE = [
    "--die-with-parent", "--new-session", "--unshare-pid",
    "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
]  # fmt: skip


def shell_fake(**kw):
    dirs = {
        "/tmp",
        "/var/tmp",
        "/mnt",
        "/media",
        "/run/user",
        "/home/u",
        "/w/ws",
        *kw.pop("dirs", ()),
    }
    return FakeHost(dirs=dirs, **kw)


def test_shell_pre_starts_with_the_fixed_base_then_masks_then_home():
    pre, notes = runner.build_shell_pre(config(), "/w/ws", shell_fake().host())
    assert pre[: len(BASE)] == BASE
    assert pre[len(BASE) :] == [
        "--tmpfs", "/tmp", "--tmpfs", "/var/tmp", "--tmpfs", "/mnt", "--tmpfs", "/media",
        "--tmpfs", "/run/user", "--tmpfs", "/home/u",
        "--bind", "/w/ws", "/w/ws", "--chdir", "/w/ws",
    ]  # fmt: skip
    assert notes == []


def test_shell_pre_masks_only_places_that_exist():
    fake = FakeHost(dirs={"/tmp", "/home/u", "/w/ws"})
    pre, _ = runner.build_shell_pre(config(), "/w/ws", fake.host())
    assert [pre[i + 1] for i, a in enumerate(pre) if a == "--tmpfs"] == ["/tmp", "/home/u"]
    gone = FakeHost(
        dirs={"/tmp", "/w/ws"}
    )  # ホームが無ければ覆えない (読み取り専用のルートに作れない)
    pre, _ = runner.build_shell_pre(config(), "/w/ws", gone.host())
    assert "/home/u" not in pre


def test_shell_pre_shows_only_existing_visible_paths_after_masking_home():
    fake = shell_fake(
        dirs={"/home/u/.local/bin", "/home/u/.cache/uv"}, files={"/home/u/.gitconfig"}
    )
    cfg = config(
        """
        version = 1
        [visible]
        read = ["~/.local/bin", "~/.gitconfig", "~/.cargo", "/opt/missing"]
        write = ["~/.cache/uv", "~/.npm"]
        """
    )
    pre, _ = runner.build_shell_pre(cfg, "/w/ws", fake.host())
    home_mask = pre.index("/home/u")
    shown = [(pre[i], pre[i + 1]) for i, a in enumerate(pre) if a in ("--ro-bind", "--bind")]
    assert shown == [
        ("--ro-bind", "/"),
        ("--ro-bind", "/home/u/.local/bin"),
        ("--ro-bind", "/home/u/.gitconfig"),
        ("--bind", "/home/u/.cache/uv"),
        ("--bind", "/w/ws"),
    ]
    assert pre.index("/home/u/.local/bin") > home_mask  # 覆った後に重ねる (先だと隠れる)
    assert pre.index("/w/ws") > pre.index("/home/u/.cache/uv")  # 作業ディレクトリが最後


def test_shell_pre_resolves_symlinks_of_home_work_and_visible_paths():
    fake = FakeHost(
        dirs={"/tmp", "/data/home", "/data/ws", "/data/mise"},
        links={"/home/u": "/data/home", "/w/ws": "/data/ws", "/data/home/.mise": "/data/mise"},
    )
    cfg = config('version = 1\n[visible]\nread = ["~/.mise"]\n')
    fake.links["/home/u/.mise"] = "/data/mise"
    pre, _ = runner.build_shell_pre(cfg, "/w/ws", fake.host())
    assert "/data/home" in pre and "/data/ws" in pre and "/data/mise" in pre
    assert "/home/u" not in pre and "/w/ws" not in pre


def test_shell_pre_recreates_the_symlink_of_a_visible_path_inside_the_masked_home():
    """~/papers -> /data/papers を見せるとき、実体を重ねるだけでは ~/papers が内側に無い。リンクも作り直す。"""
    fake = shell_fake(dirs={"/data/papers"}, links={"/home/u/papers": "/data/papers"})
    cfg = config('version = 1\n[visible]\nread = ["~/papers"]\n')
    pre, _ = runner.build_shell_pre(cfg, "/w/ws", fake.host())
    i = pre.index("--symlink")
    assert pre[i : i + 3] == ["--symlink", "/data/papers", "/home/u/papers"]
    assert pre[i + 3 : i + 6] == ["--ro-bind", "/data/papers", "/data/papers"]  # リンクの先を重ねる
    assert i > pre.index("/home/u")  # ホームを覆った後に作る


def test_shell_pre_recreates_the_first_symlink_on_the_path_when_a_parent_is_a_link():
    fake = shell_fake(
        dirs={"/mnt/d/data/sub"},
        links={"/home/u/data": "/mnt/d/data", "/home/u/data/sub": "/mnt/d/data/sub"},
    )
    cfg = config('version = 1\n[visible]\nwrite = ["~/data/sub"]\n')
    pre, _ = runner.build_shell_pre(cfg, "/w/ws", fake.host())
    assert pre[pre.index("--symlink") : pre.index("--symlink") + 3] == [
        "--symlink",
        "/mnt/d/data",
        "/home/u/data",
    ]
    assert pre[pre.index("/mnt/d/data/sub") - 1 : pre.index("/mnt/d/data/sub") + 2] == [
        "--bind",
        "/mnt/d/data/sub",
        "/mnt/d/data/sub",
    ]


def test_shell_pre_does_not_mistake_normalisation_for_a_symlink():
    """~/./papers や // は、リンクではない。--symlink を作らず、通常どおり実体を重ねる。"""
    fake = shell_fake(dirs={"/home/u/papers"})
    for raw in ("~/./papers", "~//papers", "/home/u/./papers"):
        cfg = config(f'version = 1\n[visible]\nread = ["{raw}"]\n')
        pre, _ = runner.build_shell_pre(cfg, "/w/ws", fake.host())
        assert "--symlink" not in pre, raw
        assert pre[pre.index("/home/u/papers") - 1 : pre.index("/home/u/papers") + 2] == [
            "--ro-bind",
            "/home/u/papers",
            "/home/u/papers",
        ], raw


def test_shell_pre_recreates_a_chain_of_symlinks_through_masked_places():
    """~/a -> /mnt/a、/mnt/a/b -> /srv/b のとき、~/a/b から使えるよう、両方のリンクを作り直す。"""
    fake = shell_fake(
        dirs={"/srv/b", "/mnt/a"},
        links={"/home/u/a": "/mnt/a", "/mnt/a/b": "/srv/b", "/home/u/a/b": "/srv/b"},
    )
    cfg = config('version = 1\n[visible]\nread = ["~/a/b"]\n')
    pre, _ = runner.build_shell_pre(cfg, "/w/ws", fake.host())
    links = [pre[i : i + 3] for i, a in enumerate(pre) if a == "--symlink"]
    assert links == [
        ["--symlink", "/mnt/a", "/home/u/a"],
        ["--symlink", "/srv/b", "/mnt/a/b"],
    ]
    binds = [pre[i : i + 3] for i, a in enumerate(pre) if a == "--ro-bind"]
    assert ["--ro-bind", "/srv/b", "/srv/b"] in binds


def test_shell_pre_recreates_a_link_for_a_path_with_exactly_two_leading_slashes():
    """//home/u/papers (先頭がちょうど 2 本の /) でも、書いた名前から読めるよう、リンクを作り直す。normpath は先頭の // を残す。"""
    fake = shell_fake(dirs={"/srv/papers"}, links={"/home/u/papers": "/srv/papers"})
    cfg = config('version = 1\n[visible]\nread = ["//home/u/papers"]\n')
    pre, _ = runner.build_shell_pre(cfg, "/w/ws", fake.host())
    assert pre[pre.index("--symlink") : pre.index("--symlink") + 3] == [
        "--symlink",
        "/srv/papers",
        "/home/u/papers",
    ]


def test_shell_pre_recreates_a_link_when_home_has_a_trailing_slash():
    """HOME=/home/u/ (末尾の /) でも、書いた名前 ~/papers から読めるよう、リンクを作り直す。"""
    fake = FakeHost(
        dirs={"/tmp", "/home/u", "/w/ws", "/srv/papers"},
        links={"/home/u/papers": "/srv/papers"},
        home="/home/u/",
    )
    cfg = config('version = 1\n[visible]\nread = ["~/papers"]\n')
    pre, _ = runner.build_shell_pre(cfg, "/w/ws", fake.host())
    assert pre[pre.index("--symlink") : pre.index("--symlink") + 3] == [
        "--symlink",
        "/srv/papers",
        "/home/u/papers",
    ]


def test_shell_pre_maps_an_absolute_path_through_a_symlinked_home():
    """HOME 自体がリンク (/home/u -> /data/home) のとき、絶対表記 /home/u/papers でも、覆ったホームの中にリンクを作る。"""
    fake = FakeHost(
        dirs={"/tmp", "/data/home", "/w/ws", "/data/papers"},
        links={
            "/home/u": "/data/home",
            "/home/u/papers": "/data/papers",
            "/data/home/papers": "/data/papers",
        },
    )
    cfg = config('version = 1\n[visible]\nread = ["/home/u/papers"]\n')
    pre, _ = runner.build_shell_pre(cfg, "/w/ws", fake.host())
    assert pre[pre.index("--symlink") : pre.index("--symlink") + 3] == [
        "--symlink",
        "/data/papers",
        "/data/home/papers",
    ]


def test_shell_pre_adds_no_symlink_for_links_outside_the_masked_places():
    fake = shell_fake(dirs={"/srv/x"}, links={"/opt/x": "/srv/x"})
    cfg = config('version = 1\n[visible]\nread = ["/opt/x"]\n')
    pre, _ = runner.build_shell_pre(cfg, "/w/ws", fake.host())
    assert "--symlink" not in pre  # 覆っていない場所のリンクは、ルートの重ねに残っている
    assert pre[pre.index("/srv/x") - 1 : pre.index("/srv/x") + 2] == [
        "--ro-bind",
        "/srv/x",
        "/srv/x",
    ]


@pytest.mark.parametrize("cwd", ["/", "/home", "/home/u"])
def test_shell_pre_refuses_a_workspace_that_contains_the_home(cwd):
    fake = shell_fake(dirs={"/home"})
    with pytest.raises(runner.RunnerError, match="広すぎる"):
        runner.build_shell_pre(config(), cwd, fake.host())


@pytest.mark.parametrize("entry", ["/home", "/home/u"])
@pytest.mark.parametrize("key", ["read", "write"])
def test_shell_pre_refuses_visible_paths_that_would_show_the_whole_home(key, entry):
    fake = shell_fake(dirs={"/home"})
    cfg = config(f'version = 1\n[visible]\n{key} = ["{entry}"]\n')
    with pytest.raises(runner.RunnerError, match="visible"):
        runner.build_shell_pre(cfg, "/w/ws", fake.host())


def test_shell_pre_allows_a_workspace_inside_a_masked_root_and_visible_outside_home():
    fake = FakeHost(dirs={"/tmp", "/mnt", "/mnt/d", "/mnt/d/data", "/home/u", "/mnt/d/proj"})
    cfg = config('version = 1\n[visible]\nread = ["/mnt/d/data"]\n')
    pre, _ = runner.build_shell_pre(cfg, "/mnt/d/proj", fake.host())
    assert (
        pre.index("/mnt") < pre.index("/mnt/d/data") < pre.index("/mnt/d/proj")
    )  # 覆った後に重ねる


def worktree_fake(**texts):
    base = {
        "/w/wt/.git": "gitdir: /w/main/.git/worktrees/wt\n",
        "/w/main/.git/worktrees/wt/gitdir": "/w/wt/.git\n",
        "/w/main/.git/worktrees/wt/commondir": "../..\n",
    }
    base.update(texts)
    return shell_fake(
        dirs={"/w/wt", "/w/main/.git", "/w/main/.git/objects", "/w/main/.git/worktrees/wt"},
        files={
            "/w/wt/.git",
            "/w/main/.git/HEAD",
            "/w/main/.git/worktrees/wt/HEAD",
            "/w/main/.git/worktrees/wt/gitdir",
            "/w/main/.git/worktrees/wt/commondir",
        },
        texts=base,
    )


def test_shell_pre_gives_a_worktree_its_shared_git_directory():
    pre, notes = runner.build_shell_pre(config(), "/w/wt", worktree_fake().host())
    assert notes == []
    assert pre[pre.index("/w/wt") + 2 : pre.index("--chdir")] == [
        "--bind",
        "/w/main/.git",
        "/w/main/.git",
        "--bind",
        "/w/main/.git/worktrees/wt",
        "/w/main/.git/worktrees/wt",
    ]


def test_shell_pre_protects_hooks_and_config_of_a_worktree_through_build_extra():
    fake = worktree_fake()
    fake.dirs |= {"/w/main/.git/hooks"}
    fake.files |= {"/w/main/.git/config", "/w/main/.git/worktrees/wt/config.worktree"}
    pre, _ = runner.build_shell_pre(config(), "/w/wt", fake.host())
    extra = runner.build_extra(config(), pre, fake.host())
    protected = [extra[i + 1] for i, a in enumerate(extra) if a == "--ro-bind"]
    assert "/w/main/.git/hooks" in protected and "/w/main/.git/config" in protected
    assert "/w/main/.git/worktrees/wt/config.worktree" in protected


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        # エージェントが .git ファイルを書き換えて、他の場所を指させても、渡さない
        ({"/w/wt/.git": "gitdir: /home/u/.ssh\n"}, "形でない"),
        ({"/w/wt/.git": "gitdir: /w/other/.git\n"}, "形でない"),
        ({"/w/wt/.git": "not a gitdir line\n"}, "gitdir: で始まらない"),
        (
            {"/w/main/.git/worktrees/wt/gitdir": "/w/elsewhere/.git\n"},
            "back-reference",
        ),  # 登録先が別
        ({"/w/main/.git/worktrees/wt/commondir": ""}, "commondir が無い"),
        ({"/w/main/.git/worktrees/wt/commondir": "../../../x\n"}, "位置から決まる"),
    ],
)
def test_shell_pre_does_not_trust_a_rewritten_git_file(override, reason):
    pre, notes = runner.build_shell_pre(config(), "/w/wt", worktree_fake(**override).host())
    assert len([a for a in pre if a == "--bind"]) == 1  # 作業ディレクトリだけ
    assert any(reason in n for n in notes), notes


def test_shell_pre_does_not_trust_a_registration_forged_inside_the_workspace():
    """作業ディレクトリの中に、.git・gitdir・commondir を作って自己証明しても、外の場所を書き込み可にしない。

    (祖先 /srv/shared に HEAD と objects があれば、形の検証だけでは通ってしまう)
    """
    work = "/srv/shared/worktrees/job"
    fake = shell_fake(
        dirs={work, "/srv/shared", "/srv/shared/objects"},
        files={f"{work}/.git", "/srv/shared/HEAD", f"{work}/HEAD"},
        texts={
            f"{work}/.git": "gitdir: .\n",
            f"{work}/gitdir": f"{work}/.git\n",
            f"{work}/commondir": "../..\n",
        },
    )
    pre, notes = runner.build_shell_pre(config(), work, fake.host())
    assert "/srv/shared" not in pre
    assert any("書ける場所" in n for n in notes), notes


def test_shell_pre_does_not_trust_a_registration_inside_a_writable_visible_directory():
    """形 (<共有 .git>/worktrees/<名前>) を満たしても、登録が書き込み可の visible の中にあれば信じない。"""
    reg, common = "/w/cache/main/.git/worktrees/reg", "/w/cache/main/.git"
    fake = worktree_fake(
        **{
            "/w/wt/.git": f"gitdir: {reg}\n",
            f"{reg}/gitdir": "/w/wt/.git\n",
            f"{reg}/commondir": "../..\n",
        }
    )
    fake.dirs |= {"/w/cache", common, f"{common}/objects", reg}
    fake.files |= {f"{common}/HEAD", f"{reg}/HEAD", f"{reg}/gitdir", f"{reg}/commondir"}
    cfg = config('version = 1\n[visible]\nwrite = ["/w/cache"]\n')
    pre, notes = runner.build_shell_pre(cfg, "/w/wt", fake.host())
    binds = [pre[i + 1] for i, a in enumerate(pre) if a == "--bind"]
    assert binds == [
        "/w/cache",
        "/w/wt",
    ]  # visible.write と作業ディレクトリだけ。git の領域は渡さない
    assert any("書ける場所" in n for n in notes), notes


def test_shell_pre_does_not_give_a_shared_git_directory_that_contains_the_workspace():
    fake = worktree_fake(**{"/w/main/.git/sub/.git": "gitdir: /w/main/.git/worktrees/wt\n"})
    fake.files |= {"/w/main/.git/sub/.git"}
    fake.texts["/w/main/.git/worktrees/wt/gitdir"] = "/w/main/.git/sub/.git\n"
    pre, notes = runner.build_shell_pre(config(), "/w/main/.git/sub", fake.host())
    assert len([a for a in pre if a == "--bind"]) == 1  # 作業ディレクトリだけ
    assert any("含む" in n for n in notes), notes


def test_shell_pre_requires_the_gitdir_to_be_a_direct_child_of_worktrees():
    """gitdir は <共有 .git>/worktrees/<名前> の直接の子。深い場所や別の名前の場所を、祖先の git ディレクトリの登録に見せかけられない。"""
    victim = "/srv/victim"  # HEAD と objects のある、別の git ディレクトリ
    for gitdir in (f"{victim}/x/y", f"{victim}/worktrees/a/b", f"{victim}/worktree/y"):
        fake = worktree_fake(
            **{
                "/w/wt/.git": f"gitdir: {gitdir}\n",
                f"{gitdir}/gitdir": "/w/wt/.git\n",
                f"{gitdir}/commondir": "../..\n",
            }
        )
        fake.dirs |= {victim, f"{victim}/objects", gitdir}
        fake.files |= {
            f"{victim}/HEAD",
            f"{gitdir}/HEAD",
            f"{gitdir}/gitdir",
            f"{gitdir}/commondir",
        }
        pre, notes = runner.build_shell_pre(config(), "/w/wt", fake.host())
        assert victim not in pre, gitdir
        assert any("形でない" in n for n in notes), (gitdir, notes)


def test_shell_pre_does_not_follow_a_rewritten_commondir_to_another_git_directory():
    """正規の登録を一度渡した後 (gitdir は書き込み可)、commondir を書き換えて別の git ディレクトリへ向けても、渡さない。"""
    victim = "/srv/victim"
    fake = worktree_fake(**{"/w/main/.git/worktrees/wt/commondir": "../../../../../srv/victim\n"})
    fake.dirs |= {victim, f"{victim}/objects"}
    fake.files |= {f"{victim}/HEAD"}
    pre, notes = runner.build_shell_pre(config(), "/w/wt", fake.host())
    assert victim not in pre
    assert any("commondir" in n for n in notes), notes


@pytest.mark.parametrize("which", ["gitdir", "commondir"])
def test_shell_pre_does_not_trust_registration_files_that_are_writable_even_alone(which):
    """登録のディレクトリが書けなくても、読む 2 つのファイルだけが書き込み可 (visible.write) なら、中身を偽造できる。"""
    reg = "/w/main/.git/worktrees/wt"
    fake = worktree_fake()
    cfg = config(f'version = 1\n[visible]\nwrite = ["{reg}/{which}"]\n')
    pre, notes = runner.build_shell_pre(cfg, "/w/wt", fake.host())
    assert (
        len([a for a in pre if a == "--bind"]) == 2
    )  # visible.write の 1 件と作業ディレクトリ。git の領域は渡さない
    assert any("書ける場所" in n for n in notes), notes


def test_shell_pre_does_not_trust_a_registration_file_that_links_into_the_workspace():
    fake = worktree_fake()
    fake.links["/w/main/.git/worktrees/wt/gitdir"] = "/w/wt/forged-gitdir"
    pre, notes = runner.build_shell_pre(config(), "/w/wt", fake.host())
    assert "/w/main/.git" not in pre
    assert any("書ける場所" in n for n in notes), notes


# --- --status (いま効いている設定の一覧) -----------------------------------------


def _lines(result):
    """describe の戻り値 (行, 起動できるか) の、行だけ。"""
    return result[0]


def _status_env(tmp_path, shared="version = 1\n", local=None):
    conf = tmp_path / "runner.toml"
    conf.write_text(shared, encoding="utf-8")
    if local is not None:
        (tmp_path / "runner.local.toml").write_text(local, encoding="utf-8")
    return {runner.CONFIG_ENV: str(conf)}


def test_status_flags_only_missing_entries_added_on_this_machine(tmp_path):
    """無い場所は黙って飛ばされる。このマシンの追記だけ ✗ で警告し、共有の既定 (入れていない道具) は - にとどめる。"""
    env = _status_env(
        tmp_path,
        shared='version = 1\n[visible]\nread = ["~/.cargo"]\n[hide]\ndirs = ["~/.kube"]\n',
        local='version = 1\n[visible]\nread = ["~/papres", "~/papers"]\n[hide]\nfiles = ["~/typo-token"]\n',
    )
    fake = shell_fake(dirs={"/home/u/papers"})
    text = "\n".join(_lines(runner.describe(env, fake.host(), "/w/ws", offline=False)))
    assert "~/papres ✗ 存在しない (綴りを確かめる)" in text  # 追記の綴りの誤り
    assert (
        "~/typo-token ✗ 存在しない (綴りを確かめる)" in text
    )  # hide の綴りの誤りは、秘密を隠せないので特に重要
    assert "~/papers ✓" in text
    assert "~/.cargo -" in text and "~/.kube -" in text  # 共有の既定。警告しない
    assert "~/.cargo ✗" not in text and "~/.kube ✗" not in text
    assert "runner.local.toml: あり" in text


def test_status_reports_network_gpu_workdir_and_env(tmp_path):
    env = _status_env(
        tmp_path, 'version = 1\n[gpu]\ndevices = ["auto"]\n[env]\nunset = ["A_TOKEN"]\n'
    )
    fake = shell_fake(files={"/dev/dxg"})
    on = "\n".join(_lines(runner.describe(env, fake.host(), "/w/ws", offline=False)))
    off = "\n".join(_lines(runner.describe(env, fake.host(), "/w/ws", offline=True)))
    assert "通信: 開いている" in on and "通信: 遮断 (--offline)" in off
    assert "GPU: /dev/dxg" in on
    assert "作業ディレクトリ: /w/ws (書き込み可)" in on
    assert "消す環境変数: A_TOKEN" in on
    assert "runner.local.toml: なし" in on


def test_status_says_so_when_no_gpu_is_passed(tmp_path):
    env = _status_env(tmp_path, 'version = 1\n[gpu]\ndevices = ["auto"]\n')
    text = "\n".join(_lines(runner.describe(env, shell_fake().host(), "/w/ws", offline=False)))
    assert "GPU: 渡さない (設定のデバイスが見つからない)" in text


def test_status_explains_why_the_workdir_cannot_start(tmp_path):
    """ホームを含む場所では起動できない。起動してから知るのではなく、--status で理由を見る。戻り値でも、起動できないと伝える。"""
    env = _status_env(tmp_path)
    lines, startable = runner.describe(env, shell_fake().host(), "/home", offline=False)
    assert "この場所では起動できない" in "\n".join(lines)
    assert startable is False
    assert runner.describe(env, shell_fake().host(), "/w/ws", offline=False)[1] is True


def test_status_shows_the_git_note_for_the_workdir(tmp_path):
    """worktree の .git を渡せない理由 (git が動かない理由) も、作業ディレクトリの注意として見える。"""
    env = _status_env(tmp_path)
    fake = worktree_fake(**{"/w/wt/.git": "gitdir: /home/u/.ssh\n"})
    text = "\n".join(_lines(runner.describe(env, fake.host(), "/w/wt", offline=False)))
    assert "注意: .git の領域を渡さない" in text


@linux_only
def test_status_fails_when_the_config_is_broken(tmp_path, capsys):
    env = _status_env(tmp_path, "version = 2\n")
    code = runner.main(["--status"], {**env, "HOME": str(tmp_path)})
    assert code == 2
    assert "pi-sandbox-runner:" in capsys.readouterr().err


@linux_only
@pytest.mark.parametrize(
    ("args", "offline"), [(["--status"], False), (["--offline", "--status"], True)]
)
def test_status_main_prints_and_never_starts_bwrap(tmp_path, capsys, monkeypatch, args, offline):
    env = _status_env(tmp_path)

    def boom(*_a, **_k):
        raise AssertionError("--status は bwrap を起動しない")

    monkeypatch.setattr(runner.os, "execv", boom)
    monkeypatch.setattr(runner.shutil, "which", boom)
    monkeypatch.chdir(tmp_path)
    code = runner.main(args, {**env, "HOME": str(tmp_path.parent)})
    out = capsys.readouterr().out
    assert code == 0
    assert ("通信: 遮断" in out) is offline


@linux_only
@pytest.mark.parametrize("where", ["home", "above_home", "visible_is_home"])
def test_status_main_fails_when_the_workdir_cannot_start(tmp_path, capsys, monkeypatch, where):
    """起動できない場所・設定では、一覧を出したうえで、成功 (0) を返さない。"""
    home = tmp_path / "home"
    (home / "sub").mkdir(parents=True)
    visible = (
        f'version = 1\n[visible]\nread = ["{home}"]\n'
        if where == "visible_is_home"
        else "version = 1\n"
    )
    env = _status_env(tmp_path, visible)
    monkeypatch.chdir(
        {"home": home, "above_home": tmp_path, "visible_is_home": home / "sub"}[where]
    )
    code = runner.main(["--status"], {**env, "HOME": str(home)})
    captured = capsys.readouterr()
    assert code == 2
    if where == "visible_is_home":
        assert "起動できない" in captured.out
    else:
        assert "この場所では起動できない" in captured.out


@linux_only
@pytest.mark.parametrize("args", [["--status", "x"], ["--status", "-c", "true"], ["--statuss"]])
def test_status_is_not_mixed_with_other_arguments(tmp_path, capsys, args):
    env = _status_env(tmp_path)
    assert runner.main(args, {**env, "HOME": str(tmp_path)}) == 2
    assert "使い方" in capsys.readouterr().err


def test_shell_pre_needs_nothing_for_a_plain_git_directory_inside_the_workspace():
    fake = shell_fake(dirs={"/w/ws/.git"}, files={"/w/ws/.git/HEAD"})
    pre, notes = runner.build_shell_pre(config(), "/w/ws", fake.host())
    assert notes == [] and len([a for a in pre if a == "--bind"]) == 1


# --- 最終のコマンド ------------------------------------------------------------


def test_build_command_puts_extras_after_the_dev_mount_and_before_the_separator(tmp_path):
    """--dev /dev の後に置かないと、GPU のデバイスが隠れる。"""
    conf = tmp_path / "runner.toml"
    conf.write_text('version = 1\n[gpu]\ndevices = ["auto"]\n', encoding="utf-8")
    fake = shell_fake(files={"/dev/dxg"})
    command, _ = runner.build_command(
        ["-c", "python3 job.py"], {"PI_SANDBOX_RUNNER_CONFIG": str(conf)}, fake.host(), "/w/ws"
    )
    assert command[0] == "bwrap"
    assert command.index("--dev") < command.index("--dev-bind") < command.index("--")
    assert command[-4:] == ["--", "/bin/bash", "-c", "python3 job.py"]


def test_build_command_orders_visible_before_hide_so_hide_wins(tmp_path):
    conf = tmp_path / "runner.toml"
    conf.write_text(
        'version = 1\n[visible]\nread = ["~/.config/git"]\n[hide]\nfiles = ["~/.config/git/credentials"]\n',
        encoding="utf-8",
    )
    fake = shell_fake(dirs={"/home/u/.config/git"}, files={"/home/u/.config/git/credentials"})
    command, _ = runner.build_command(
        ["-c", "true"], {"PI_SANDBOX_RUNNER_CONFIG": str(conf)}, fake.host(), "/w/ws"
    )
    shown = command.index("/home/u/.config/git")
    hidden = command.index("/home/u/.config/git/credentials")
    assert shown < hidden and command[hidden - 2 : hidden + 1] == [
        "--ro-bind",
        "/dev/null",
        "/home/u/.config/git/credentials",
    ]


def test_build_command_adds_env_and_offline_flags(tmp_path):
    conf = tmp_path / "runner.toml"
    conf.write_text('version = 1\n[env]\nunset = ["GH_TOKEN", "SSH_AUTH_SOCK"]\n', encoding="utf-8")
    env = {"PI_SANDBOX_RUNNER_CONFIG": str(conf)}
    online, _ = runner.build_command(["-c", "true"], env, shell_fake().host(), "/w/ws")
    assert "--unshare-net" not in online
    assert online[online.index("--unsetenv") : online.index("--setenv")] == [
        "--unsetenv",
        "GH_TOKEN",
        "--unsetenv",
        "SSH_AUTH_SOCK",
    ]
    assert online[online.index("--setenv") : online.index("--setenv") + 3] == [
        "--setenv", "MISE_STATE_DIR", "/tmp/pib-mise-state",
    ]  # fmt: skip
    offline, _ = runner.build_command(
        ["--offline", "-c", "true"], env, shell_fake().host(), "/w/ws"
    )
    assert "--unshare-net" in offline and offline.index("--unshare-net") < offline.index("--")


def test_build_command_passes_the_command_as_one_argument(tmp_path):
    (tmp_path / "runner.toml").write_text(MINIMAL, encoding="utf-8")
    env = {"PI_SANDBOX_RUNNER_CONFIG": str(tmp_path / "runner.toml")}
    cmd = "echo 'a b'; cat <<EOF\n$HOME\nEOF"
    command, _ = runner.build_command(["-c", cmd], env, shell_fake().host(), "/w/ws")
    assert command[-3:] == ["/bin/bash", "-c", cmd]


# --- このマシンだけの追記 (runner.local.toml) ---------------------------------


def test_local_example_is_valid_and_adds_nothing_until_edited():
    """同梱の見本は、そのままコピーしても有効で、何も足さない (見本の行はコメントアウトしてある)。"""
    assert runner.parse_local(LOCAL_EXAMPLE.read_text(encoding="utf-8")) == runner.Additions()


def test_local_config_adds_after_the_shared_entries_without_duplicates():
    shared = config(
        'version = 1\n[gpu]\ndevices = ["auto"]\n[hide]\ndirs = ["~/.ssh"]\n'
        '[visible]\nread = ["~/.local/bin"]\n[env]\nunset = ["GH_TOKEN"]\n'
    )
    local = runner.parse_local(
        '[hide]\ndirs = ["~/notes", "~/.ssh"]\nfiles = ["~/.tok"]\n'
        '[visible]\nread = ["/mnt/d/data", "~/.local/bin"]\nwrite = ["/mnt/d/out"]\n'
        '[env]\nunset = ["MY_TOKEN", "GH_TOKEN"]\n'
    )
    merged = runner.merge_local(shared, local)
    assert merged.gpu_devices == ("auto",)  # デバイスは local から増えない
    assert merged.hide_dirs == ("~/.ssh", "~/notes")  # 共有が先。重複は 1 つ
    assert merged.hide_files == ("~/.tok",)
    assert merged.visible_read == ("~/.local/bin", "/mnt/d/data")
    assert merged.visible_write == ("/mnt/d/out",)
    assert merged.env_unset == ("GH_TOKEN", "MY_TOKEN")
    assert merged.docker_block is shared.docker_block and merged.git_protect is shared.git_protect


@pytest.mark.parametrize(
    ("table", "body"),
    [
        ("docker", "block = true"),
        ("git", "protect = true"),
        ("gpu", 'devices = ["/dev/nvidia0"]'),  # デバイスの公開は、local からは足せない
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
        ("[hide]\ndirs = ['/']\n", "hide.dirs のパス"),
        ("[hide]\nfiles = ['relative']\n", "hide.files のパス"),
        ("[hide]\nextra = 1\n", "未知のキー"),
        ("[visible]\nread = ['/']\n", "visible.read のパス"),
        ("[visible]\nwrite = ['relative']\n", "visible.write のパス"),
        ("[env]\nunset = ['A B']\n", "環境変数の名前"),
        ("[hide\n", "TOML"),
    ],
)
def test_invalid_local_config_is_rejected(text, message):
    with pytest.raises(runner.RunnerError, match=message):
        runner.parse_local(text)


def test_local_config_may_omit_version_and_may_be_empty():
    assert runner.parse_local("") == runner.Additions()
    assert runner.parse_local("version = 1\n") == runner.Additions()


def test_load_config_reads_the_local_file_next_to_the_shared_one(tmp_path):
    shared = tmp_path / "runner.toml"
    shared.write_text('version = 1\n[hide]\ndirs = ["~/.ssh"]\n', encoding="utf-8")
    assert runner.load_config(shared).hide_dirs == ("~/.ssh",)  # 無くてよい
    (tmp_path / "runner.local.toml").write_text('[hide]\ndirs = ["~/notes"]\n', encoding="utf-8")
    assert runner.load_config(shared).hide_dirs == ("~/.ssh", "~/notes")


def test_load_config_follows_a_valid_symlink_for_the_local_file(tmp_path):
    (tmp_path / "runner.toml").write_text(MINIMAL, encoding="utf-8")
    real = tmp_path / "elsewhere.toml"
    real.write_text('[hide]\ndirs = ["~/notes"]\n', encoding="utf-8")
    (tmp_path / "runner.local.toml").symlink_to(real)
    assert runner.load_config(tmp_path / "runner.toml").hide_dirs == ("~/notes",)


# --- CLI (exec しない) ---------------------------------------------------------


def run_cli(args, env_extra=None, cwd=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PI_SANDBOX_RUNNER_", "PIB_"))}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(RUNNER), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=cwd,
        timeout=60,
        check=False,
    )


@linux_only
def test_cli_dry_run_prints_final_command_for_the_current_directory(tmp_path):
    conf = tmp_path / "runner.toml"
    conf.write_text(
        "version = 1\n[docker]\nblock = false\n[git]\nprotect = false\n", encoding="utf-8"
    )
    work = tmp_path / "work"
    work.mkdir()
    env = {
        "PI_SANDBOX_RUNNER_CONFIG": str(conf),
        "PI_SANDBOX_RUNNER_DRYRUN": "1",
        "HOME": str(tmp_path / "home"),
    }
    result = run_cli(["-c", "echo hi"], env, cwd=work)
    assert result.returncode == 0, result.stderr
    command = json.loads(result.stdout)
    assert command[0] == "bwrap"
    assert command[1 : 1 + len(BASE)] == BASE
    assert command[command.index("--chdir") + 1] == str(work.resolve())
    assert command[-4:] == ["--", "/bin/bash", "-c", "echo hi"]


@linux_only
def test_cli_dry_run_contains_the_local_additions(tmp_path):
    (tmp_path / "runner.toml").write_text(MINIMAL, encoding="utf-8")
    notes = tmp_path / "notes"
    notes.mkdir()
    (tmp_path / "runner.local.toml").write_text(f'[hide]\ndirs = ["{notes}"]\n', encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    env = {
        "PI_SANDBOX_RUNNER_CONFIG": str(tmp_path / "runner.toml"),
        "PI_SANDBOX_RUNNER_DRYRUN": "1",
        "HOME": str(tmp_path / "home"),
    }
    result = run_cli(["-c", "true"], env, cwd=work)
    assert result.returncode == 0, result.stderr
    command = json.loads(result.stdout)
    assert ["--tmpfs", str(notes.resolve())] in [
        command[i : i + 2] for i in range(len(command) - 1)
    ]


@linux_only
@pytest.mark.parametrize(
    ("args", "conf_text", "needle"),
    [
        (["-c", "true"], None, "設定を読めない"),
        (["-c", "true"], "version = 9\n", "version"),
        (["echo", "hi"], MINIMAL, "使い方"),
        (["-c"], MINIMAL, "使い方"),
        (["-c", ""], MINIMAL, "コマンドが無い"),
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
    assert result.stderr.startswith("pi-sandbox-runner:")
    assert needle in result.stderr


@linux_only
def test_cli_refuses_to_run_with_the_home_as_the_working_directory(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / "runner.toml").write_text(MINIMAL, encoding="utf-8")
    env = {"PI_SANDBOX_RUNNER_CONFIG": str(tmp_path / "runner.toml"), "HOME": str(home)}
    result = run_cli(["-c", "true"], env, cwd=home)
    assert result.returncode == 2 and "広すぎる" in result.stderr


@linux_only
def test_cli_rejects_a_config_that_is_not_utf8_without_a_traceback(tmp_path):
    conf = tmp_path / "runner.toml"
    conf.write_bytes(b"version = 1\n# \xff\xfe\n")
    result = run_cli(["-c", "true"], {"PI_SANDBOX_RUNNER_CONFIG": str(conf)})
    assert result.returncode == 2
    assert result.stderr.startswith("pi-sandbox-runner:")
    assert "Traceback" not in result.stderr


@linux_only
@pytest.mark.parametrize(
    ("local_bytes", "needle"),
    [
        (b"[docker]\nblock = false\n", "[docker]"),
        (b"[gpu]\ndevices = ['/dev/']\n", "[gpu]"),
        (b"[hide\n", "TOML"),
        (b"# \xff\xfe\n", "設定を読めない"),
    ],
)
def test_cli_fails_closed_when_the_local_config_is_broken(tmp_path, local_bytes, needle):
    (tmp_path / "runner.toml").write_text(MINIMAL, encoding="utf-8")
    (tmp_path / "runner.local.toml").write_bytes(local_bytes)
    env = {"PI_SANDBOX_RUNNER_CONFIG": str(tmp_path / "runner.toml")}
    result = run_cli(["-c", "true"], env)
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
    result = run_cli(["-c", "true"], env)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("pi-sandbox-runner:")
    assert "runner.local.toml" in result.stderr
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
    result = run_cli(["-c", "true"], env, cwd=work)
    assert result.returncode == 2  # ホスト側に設定が無いので、作業ツリーのものでは動かない
    (home / ".config" / "pi-sandbox" / "runner.toml").write_text(MINIMAL, encoding="utf-8")
    assert run_cli(["-c", "true"], env, cwd=work).returncode == 0


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


def unmasked_dir(prefix: str) -> Path:
    """囲いが覆わない場所 (ルートの読み取り専用の重ねで見える所) に、使い捨てのディレクトリを作る。

    tmp_path は /tmp の下にあることがあり、そこは覆われて何も見えない (偽の合格になる)。リポジトリの .tmp を使う。
    """
    base = ROOT / ".tmp"
    base.mkdir(exist_ok=True)
    if str(base.resolve()).startswith(runner.MASK_ROOTS):
        pytest.skip("リポジトリが、囲いの覆う場所の下にある")
    return Path(tempfile.mkdtemp(prefix=prefix, dir=base))


def run_in_sandbox(
    tmp_path, conf_text, script, *, work=None, home=None, args=("-c",), extra_env=None
):
    """実際の runner を、作業ディレクトリ work (無ければ tmp_path/work) で動かす。"""
    conf = tmp_path / "runner.toml"
    conf.write_text(conf_text, encoding="utf-8")
    work = work or tmp_path / "work"
    work.mkdir(exist_ok=True)
    home = home or tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        "PI_SANDBOX_RUNNER_CONFIG": str(conf),
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        **(extra_env or {}),
    }
    return run_cli([*args, script], env, cwd=work)


@needs_bwrap
def test_real_sandbox_shows_only_the_workspace_and_what_the_config_lists(tmp_path):
    home = tmp_path / "home"
    (home / "tools").mkdir(parents=True)
    (home / "tools" / "tool").write_text("T", encoding="utf-8")
    (home / "cache").mkdir()
    (home / "secret").mkdir()
    (home / "secret" / "token").write_text("TOKEN", encoding="utf-8")
    (home / ".bash_history").write_text("history", encoding="utf-8")
    shared_tmp = Path(
        tempfile.mkdtemp(prefix="pib-test-", dir="/tmp")
    )  # ホストと共有の /tmp (内側では見えない)
    outside = shared_tmp / "outside.txt"
    outside.write_text("OUT", encoding="utf-8")
    conf = 'version = 1\n[visible]\nread = ["~/tools"]\nwrite = ["~/cache"]\n'
    script = (
        f'cat "{home}/tools/tool"; echo; '
        f'touch "{home}/tools/new" 2>/dev/null && echo tools=writable || echo tools=ro; '
        f'touch "{home}/cache/new" && echo cache=writable; '
        f'ls "{home}/secret" >/dev/null 2>&1 && echo secret=visible || echo secret=hidden; '
        f'test -e "{home}/.bash_history" && echo history=visible || echo history=hidden; '
        f'test -e "{outside}" && echo outside=visible || echo outside=hidden; '
        "touch ./ok && echo work=writable"
    )
    try:
        result = run_in_sandbox(tmp_path, conf, script, home=home)
    finally:
        shutil.rmtree(shared_tmp, ignore_errors=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [
        "T", "tools=ro", "cache=writable", "secret=hidden", "history=hidden", "outside=hidden", "work=writable",
    ]  # fmt: skip
    assert (tmp_path / "work" / "ok").exists()
    assert (home / "cache" / "new").exists()  # 書き込み可の場所は、外側に反映される
    assert not (home / "tools" / "new").exists()
    assert (home / "secret" / "token").read_text(encoding="utf-8") == "TOKEN"  # 外側は無傷


@needs_bwrap
def test_real_sandbox_hides_a_secret_inside_a_visible_directory(tmp_path):
    """見せた場所の中の秘密 (例: ~/.config/git/credentials) は、hide が後から勝って見えない。"""
    home = tmp_path / "home"
    (home / "git").mkdir(parents=True)
    (home / "git" / "config").write_text("[user]\n", encoding="utf-8")
    (home / "git" / "credentials").write_text("https://u:SECRET@h\n", encoding="utf-8")
    conf = 'version = 1\n[visible]\nread = ["~/git"]\n[hide]\nfiles = ["~/git/credentials"]\n'
    script = f'cat "{home}/git/config" | wc -c; cat "{home}/git/credentials" 2>/dev/null | wc -c'
    result = run_in_sandbox(tmp_path, conf, script, home=home)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["7", "0"]


@needs_bwrap
def test_real_sandbox_hides_configured_paths_and_follows_symlinks(tmp_path):
    """隠す場所がシンボリックリンクでも bwrap は失敗せず、リンクからも実体からも見えなくなる。隠す前は読める (陽性対照)。"""
    home = tmp_path / "home"
    real_dir, real_file = tmp_path / "data" / "dir", tmp_path / "data" / "file"
    real_dir.mkdir(parents=True)
    home.mkdir()
    (real_dir / "token").write_text("TOKEN", encoding="utf-8")
    real_file.write_text("CRED", encoding="utf-8")
    (home / "link-dir").symlink_to(real_dir)
    (home / "link-file").symlink_to(real_file)
    shown = 'version = 1\n[visible]\nread = ["~/link-dir", "~/link-file"]\n'
    script = (
        f'cat "{home}/link-dir/token" 2>/dev/null | wc -c; cat "{real_dir}/token" 2>/dev/null | wc -c; '
        f'cat "{home}/link-file" 2>/dev/null | wc -c; cat "{real_file}" 2>/dev/null | wc -c'
    )
    before = run_in_sandbox(tmp_path, shown, script, home=home)
    assert before.returncode == 0, before.stderr
    assert before.stdout.split() == ["5", "5", "4", "4"]  # リンクからも実体からも読める
    hidden = shown + '[hide]\ndirs = ["~/link-dir"]\nfiles = ["~/link-file"]\n'
    after = run_in_sandbox(tmp_path, hidden, script, home=home)
    assert after.returncode == 0, after.stderr
    assert after.stdout.split() == ["0", "0", "0", "0"]


@needs_bwrap
def test_real_sandbox_shows_a_symlinked_visible_path_under_its_written_name(tmp_path):
    """~/papers が実体 (別の場所) へのリンクでも、設定に書いた ~/papers から内側で使える。"""
    home = tmp_path / "home"
    home.mkdir()
    real = tmp_path / "data" / "papers"
    real.mkdir(parents=True)
    (real / "a.txt").write_text("PAPER", encoding="utf-8")
    (home / "papers").symlink_to(real)
    conf = 'version = 1\n[visible]\nread = ["~/papers"]\n'
    script = f'cat "{home}/papers/a.txt"; echo; touch "{home}/papers/new" 2>/dev/null && echo write=ok || echo write=ro'
    result = run_in_sandbox(tmp_path, conf, script, home=home)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["PAPER", "write=ro"]


@needs_bwrap
def test_real_sandbox_follows_a_chain_of_symlinks_through_masked_places(tmp_path):
    """~/a -> /tmp/…/a (覆われる)、/tmp/…/a/b -> 覆われない場所の b。設定に書いた ~/a/b から、中身が読める。"""
    home = tmp_path / "home"
    home.mkdir()
    shared = Path(tempfile.mkdtemp(prefix="pib-chain-", dir="/tmp"))
    target = unmasked_dir("pib-target-")
    try:
        (shared / "a").mkdir()
        (target / "b").mkdir()
        (target / "b" / "f.txt").write_text("CHAIN", encoding="utf-8")
        (shared / "a" / "b").symlink_to(target / "b")
        (home / "a").symlink_to(shared / "a")
        conf = 'version = 1\n[visible]\nread = ["~/a/b"]\n'
        result = run_in_sandbox(tmp_path, conf, f'cat "{home}/a/b/f.txt"', home=home)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "CHAIN"
    finally:
        shutil.rmtree(shared, ignore_errors=True)
        shutil.rmtree(target, ignore_errors=True)


@needs_bwrap
@pytest.mark.parametrize("spelling", ["~/./papers", "~//papers"])
def test_real_sandbox_accepts_a_visible_path_written_with_dots_or_double_slashes(
    tmp_path, spelling
):
    """リンクでないディレクトリを ~/./papers と書いても、リンクと取り違えず、そのまま見える。"""
    home = tmp_path / "home"
    (home / "papers").mkdir(parents=True)
    (home / "papers" / "a.txt").write_text("PAPER", encoding="utf-8")
    conf = f'version = 1\n[visible]\nread = ["{spelling}"]\n'
    result = run_in_sandbox(tmp_path, conf, f'cat "{home}/papers/a.txt"', home=home)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PAPER"


@needs_bwrap
def test_real_sandbox_keeps_a_token_in_a_visible_cache_directory_hidden_and_unwritable(tmp_path):
    """認証が同居するキャッシュ (Hugging Face など) を見せても、token は読めず、ホストの token は書き換えられない。"""
    home = tmp_path / "home"
    hf = home / ".cache" / "huggingface"
    (hf / "hub").mkdir(parents=True)
    (hf / "hub" / "model.bin").write_text("MODEL", encoding="utf-8")
    (hf / "token").write_text("HF-SECRET", encoding="utf-8")
    conf = (
        'version = 1\n[visible]\nwrite = ["~/.cache/huggingface"]\n'
        '[hide]\nfiles = ["~/.cache/huggingface/token"]\n'
    )
    script = (
        f'cat "{hf}/hub/model.bin"; echo; cat "{hf}/token" 2>/dev/null | wc -c; '
        f'echo overwritten > "{hf}/token" 2>/dev/null; echo write-attempted'
    )
    result = run_in_sandbox(tmp_path, conf, script, home=home)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["MODEL", "0", "write-attempted"]
    assert (hf / "token").read_text(encoding="utf-8") == "HF-SECRET"  # ホストの認証は無傷


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
        "echo x > .git/hooks/pre-commit 2>/dev/null && echo hooks=writable || echo hooks=ro; "
        "echo x >> .git/config 2>/dev/null && echo config=writable || echo config=ro; "
        "git -c user.name=t -c user.email=t@example.invalid commit --allow-empty -qm t "
        "&& echo commit=ok || echo commit=failed"
    )
    result = run_in_sandbox(
        tmp_path, MINIMAL, script, work=work, extra_env={"GIT_CONFIG_GLOBAL": os.devnull}
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["hooks=ro", "config=ro", "commit=ok"]
    assert not (work / ".git" / "hooks" / "pre-commit").exists()


@needs_bwrap
@pytest.mark.skipif(shutil.which("git") is None, reason="git が無い")
def test_real_sandbox_lets_a_worktree_commit_and_protects_the_shared_hooks(tmp_path):
    env = {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "PATH": os.environ["PATH"],
    }
    main, wt = tmp_path / "main", tmp_path / "wt"
    ident = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run(["git", "init", "-q", str(main)], check=True, env=env)
    subprocess.run(
        ["git", *ident, "-C", str(main), "commit", "--allow-empty", "-qm", "base"],
        check=True,
        env=env,
    )
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", str(wt)], check=True, env=env)
    script = (
        f'echo x > "{main}/.git/hooks/pre-commit" 2>/dev/null && echo hooks=writable || echo hooks=ro; '
        f'echo x >> "{main}/.git/config" 2>/dev/null && echo config=writable || echo config=ro; '
        "git -c user.name=t -c user.email=t@example.invalid commit --allow-empty -qm in-wt "
        "&& echo commit=ok || echo commit=failed"
    )
    result = run_in_sandbox(
        tmp_path, MINIMAL, script, work=wt, extra_env={"GIT_CONFIG_GLOBAL": os.devnull}
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["hooks=ro", "config=ro", "commit=ok"]
    log = subprocess.run(
        ["git", "-C", str(wt), "log", "--format=%s"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=True,
    )
    assert log.stdout.split("\n")[0] == "in-wt"  # 外側にも反映される


@needs_bwrap
def test_real_sandbox_ignores_a_git_file_rewritten_to_point_elsewhere(tmp_path):
    """エージェントが .git ファイルを書き換えて他の場所を指させても、その場所を書き込み可で渡さない (back-reference が合わない)。"""
    home = tmp_path / "home"
    in_home = home / "victim"  # ホームの中は覆われるので、渡されなければ見えない
    outside = unmasked_dir(
        "pib-victim-"
    )  # 覆われない場所は、読み取り専用で見える。書き込めてはいけない
    try:
        for victim in (in_home, outside):
            (victim / "objects").mkdir(parents=True, exist_ok=True)
            (victim / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            (victim / "marker").write_text("PRIVATE", encoding="utf-8")
        seen = {}
        for name, victim in (("home", in_home), ("outside", outside)):
            work = tmp_path / f"work-{name}"
            work.mkdir()
            (work / ".git").write_text(f"gitdir: {victim}\n", encoding="utf-8")
            script = (
                f'test -e "{victim}/marker" && echo read=visible || echo read=hidden; '
                f'touch "{victim}/new" 2>/dev/null && echo write=ok || echo write=denied'
            )
            result = run_in_sandbox(tmp_path, MINIMAL, script, work=work, home=home)
            assert result.returncode == 0, result.stderr
            assert "git の領域を渡さない" in result.stderr  # 理由を知らせる
            assert not (victim / "new").exists()
            seen[name] = result.stdout.split()
        assert seen["home"] == ["read=hidden", "write=denied"]
        assert seen["outside"] == [
            "read=visible",
            "write=denied",
        ]  # 見える (読み取り専用) が、書けない
    finally:
        shutil.rmtree(outside, ignore_errors=True)


@needs_bwrap
def test_real_sandbox_ignores_a_registration_forged_inside_the_workspace(tmp_path):
    """作業ディレクトリの中に .git・gitdir・commondir を作って自己証明しても、祖先の HEAD・objects のある場所を書き込み可にしない。"""
    shared = unmasked_dir("pib-shared-")
    try:
        (shared / "objects").mkdir()
        (shared / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        work = shared / "worktrees" / "job"
        work.mkdir(parents=True)
        (work / ".git").write_text("gitdir: .\n", encoding="utf-8")
        (work / "gitdir").write_text(f"{work}/.git\n", encoding="utf-8")
        (work / "commondir").write_text("../..\n", encoding="utf-8")
        script = f'touch "{shared}/pwned" 2>/dev/null && echo write=ok || echo write=denied'
        result = run_in_sandbox(tmp_path, MINIMAL, script, work=work)
        assert result.returncode == 0, result.stderr
        assert result.stdout.split() == ["write=denied"]
        assert not (shared / "pwned").exists()
        assert "書ける場所" in result.stderr
    finally:
        shutil.rmtree(shared, ignore_errors=True)


@needs_bwrap
def test_real_sandbox_isolates_the_environment_and_shared_places(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    conf = 'version = 1\n[env]\nunset = ["GH_TOKEN"]\n'
    script = (
        "printenv GH_TOKEN >/dev/null && echo gh=set || echo gh=unset; "
        "printenv KEEP_ME || echo keep=missing; printenv MISE_STATE_DIR; "
        "ls -A /mnt 2>/dev/null | wc -l; ls -A /run/user/* 2>/dev/null | wc -l"
    )
    result = run_in_sandbox(
        tmp_path, conf, script, home=home, extra_env={"GH_TOKEN": "secret", "KEEP_ME": "kept"}
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["gh=unset", "kept", "/tmp/pib-mise-state", "0", "0"]


@needs_bwrap
def test_real_sandbox_offline_removes_the_network_interfaces(tmp_path):
    # /proc は内側の名前空間のもの (/sys はホストのものが見えるので使わない)
    script = "awk -F: 'NR>2 {gsub(/ /, \"\", $1); print $1}' /proc/net/dev"
    result = run_in_sandbox(tmp_path, MINIMAL, script, args=("--offline", "-c"))
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["lo"]


@needs_bwrap
def test_real_sandbox_passes_the_exit_code_and_stderr_of_the_command(tmp_path):
    result = run_in_sandbox(tmp_path, MINIMAL, "echo out; echo err >&2; exit 7")
    assert result.returncode == 7
    assert result.stdout.strip() == "out" and "err" in result.stderr


# --- pib-shell (shellPath に差す) ---------------------------------------------


def install_bin(tmp_path, *, runner_body=None):
    """~/.local/bin の代わり。pib-shell と、(runner_body があれば) 偽の runner を置く。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    shell = bin_dir / "pib-shell"
    shell.write_text(PIB_SHELL.read_text(encoding="utf-8"), encoding="utf-8")
    shell.chmod(0o755)
    if runner_body is not None:
        fake = bin_dir / "pi-sandbox-runner"
        fake.write_text(runner_body, encoding="utf-8")
        fake.chmod(0o755)
    return bin_dir


def run_shell(bin_dir, args, env_extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PIB_")}
    env.update(env_extra or {})
    return subprocess.run(
        [str(bin_dir / "pib-shell"), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
        check=False,
    )


RECORDING_RUNNER = '#!/bin/sh\nprintf "%s\\n" "$@" > "$RECORD"\n'


@linux_only
def test_pib_shell_is_a_plain_bash_when_the_sandbox_is_not_requested(tmp_path):
    bin_dir = install_bin(tmp_path, runner_body=RECORDING_RUNNER)
    result = run_shell(bin_dir, ["-c", "echo plain"], {"RECORD": str(tmp_path / "rec")})
    assert result.returncode == 0 and result.stdout.strip() == "plain"
    assert not (tmp_path / "rec").exists()  # runner は呼ばれていない


@linux_only
@pytest.mark.parametrize(
    ("mode", "expected"), [("1", ["-c", "echo hi"]), ("offline", ["--offline", "-c", "echo hi"])]
)
def test_pib_shell_hands_the_command_to_the_runner_next_to_it(tmp_path, mode, expected):
    bin_dir = install_bin(tmp_path, runner_body=RECORDING_RUNNER)
    result = run_shell(
        bin_dir, ["-c", "echo hi"], {"PIB_SANDBOX": mode, "RECORD": str(tmp_path / "rec")}
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "rec").read_text(encoding="utf-8").split("\n")[:-1] == expected


@linux_only
def test_pib_shell_does_not_fall_back_to_plain_bash_when_the_runner_is_missing(tmp_path):
    """囲いを通すと決まったのに runner が無いときは、囲いなしで実行せずに失敗する。"""
    bin_dir = install_bin(tmp_path)  # runner を置かない
    result = run_shell(bin_dir, ["-c", "echo SHOULD-NOT-RUN"], {"PIB_SANDBOX": "1"})
    assert result.returncode != 0
    assert "SHOULD-NOT-RUN" not in result.stdout


@linux_only
def test_pib_shell_finds_the_runner_through_a_symlink_to_itself(tmp_path):
    bin_dir = install_bin(tmp_path, runner_body=RECORDING_RUNNER)
    link_dir = tmp_path / "links"
    link_dir.mkdir()
    (link_dir / "pib-shell").symlink_to(bin_dir / "pib-shell")
    result = run_shell(link_dir, ["-c", "x"], {"PIB_SANDBOX": "1", "RECORD": str(tmp_path / "rec")})
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "rec").exists()


@needs_bwrap
def test_pib_shell_and_the_real_runner_work_together(tmp_path):
    bin_dir = install_bin(tmp_path)
    runner_copy = bin_dir / "pi-sandbox-runner"
    runner_copy.write_text(RUNNER.read_text(encoding="utf-8"), encoding="utf-8")
    runner_copy.chmod(0o755)
    (tmp_path / "runner.toml").write_text(MINIMAL, encoding="utf-8")
    work, home = tmp_path / "work", tmp_path / "home"
    work.mkdir()
    home.mkdir()
    result = subprocess.run(
        [str(bin_dir / "pib-shell"), "-c", 'touch "$PWD/made" && echo inside'],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(home),
            "PIB_SANDBOX": "1",
            "PI_SANDBOX_RUNNER_CONFIG": str(tmp_path / "runner.toml"),
        },
        cwd=work,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "inside" and (work / "made").exists()


# --- pib (起動) ---------------------------------------------------------------


def make_setup(tmp_path, *, settings=None, runner=True, shell=True, config=True, bwrap=True):
    """配備済みの HOME と、bwrap の入った PATH を作る。settings が None なら正しい shellPath を置く。"""
    home = tmp_path / "home"
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    (home / ".config" / "pi-sandbox").mkdir(parents=True)
    (home / ".pi" / "agent").mkdir(parents=True)
    for name, wanted in (("pi-sandbox-runner", runner), ("pib-shell", shell)):
        if wanted:
            path = bin_dir / name
            path.write_text("#!/bin/sh\n", encoding="utf-8")
            path.chmod(0o755)
    if config:
        (home / ".config" / "pi-sandbox" / "runner.toml").write_text(MINIMAL, encoding="utf-8")
    if settings is None:
        settings = {"shellPath": str(bin_dir / "pib-shell")}
    if settings is not False:
        (home / ".pi" / "agent" / "settings.json").write_text(
            json.dumps(settings), encoding="utf-8"
        )
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir(exist_ok=True)
    if bwrap:
        (fake_bin / "bwrap").write_text("#!/bin/sh\n", encoding="utf-8")
        (fake_bin / "bwrap").chmod(0o755)
    return home, {"PATH": str(fake_bin)}


@linux_only
@pytest.mark.parametrize("args", [["--help"], ["-h"], ["--offline", "--help"]])
def test_pib_help_is_japanese_and_overrides_the_help_of_pi(tmp_path, args):
    """pib --help は pib の使い方 (pi のヘルプを上書きする。pi のヘルプは pi --help)。pi は起動しない。"""
    home, _ = make_setup(tmp_path)
    result = run_pib(home, fake_pi(tmp_path), args, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    for word in (
        "pib —",
        "--offline",
        "--status",
        "runner.local.toml",
        "pi --help",
        "囲い",
        "読み取り専用で見える",
    ):
        assert word in result.stdout, word
    assert not (tmp_path / "pi-args").exists()  # pi を起動していない


@linux_only
def test_pib_help_works_even_when_the_setup_is_broken(tmp_path):
    """ヘルプは、配備が壊れていても読める (検査より先に出す)。"""
    home, _ = make_setup(tmp_path, runner=False, shell=False, config=False, settings=False)
    result = run_pib(home, fake_pi(tmp_path), ["--help"], cwd=tmp_path)
    assert result.returncode == 0 and "使い方" in result.stdout


@linux_only
def test_pib_passes_help_to_pi_when_it_is_not_the_first_argument(tmp_path):
    """先頭でない --help は、pi の引数 (pib のヘルプにしない)。"""
    home, _ = make_setup(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    result = run_pib(home, fake_pi(tmp_path), ["-p", "--help"], cwd=work)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "pi-args").read_text(encoding="utf-8").split("\n")[:-1] == [
        "1",
        "--no-approve",
        "-p",
        "--help",
    ]


@linux_only
@pytest.mark.parametrize(
    ("args", "expect"),
    [(["--status"], "--status"), (["--offline", "--status"], "--offline --status")],
)
def test_pib_status_reports_readiness_and_runs_the_runner_status(tmp_path, args, expect):
    home, _ = make_setup(tmp_path)
    runner_path = home / ".local" / "bin" / "pi-sandbox-runner"
    runner_path.write_text('#!/bin/sh\necho "RUNNER-ARGS: $*"\n', encoding="utf-8")
    runner_path.chmod(0o755)
    work = tmp_path / "work"
    work.mkdir()
    result = run_pib(home, fake_pi(tmp_path), args, cwd=work)
    assert result.returncode == 0, result.stderr
    assert "囲い: 使える" in result.stdout
    assert f"RUNNER-ARGS: {expect}" in result.stdout
    assert not (tmp_path / "pi-args").exists()  # pi を起動していない


@linux_only
def test_pib_status_counts_a_runner_that_cannot_start_as_not_ready(tmp_path):
    """runner が「この場所では起動できない」と答えたら、見出しを『使える』にせず、終了コード 2。"""
    home, _ = make_setup(tmp_path)
    runner_path = home / ".local" / "bin" / "pi-sandbox-runner"
    runner_path.write_text(
        '#!/bin/sh\necho "作業ディレクトリ: x -> この場所では起動できない"\nexit 2\n',
        encoding="utf-8",
    )
    runner_path.chmod(0o755)
    result = run_pib(home, fake_pi(tmp_path), ["--status"], cwd=tmp_path)
    assert result.returncode == 2
    assert "囲い: 使えない" in result.stdout
    assert "この場所では起動できない" in result.stdout  # 詳細も見える
    assert "囲い: 使える" not in result.stdout


@linux_only
def test_pib_status_lists_what_is_wrong_and_fails(tmp_path):
    home, _ = make_setup(tmp_path, config=False)
    result = run_pib(home, fake_pi(tmp_path), ["--status"], cwd=tmp_path)
    assert result.returncode == 2
    assert "囲い: 使えない" in result.stdout and "runner の設定が無い" in result.stdout


@linux_only
def test_pib_status_takes_no_other_arguments(tmp_path):
    home, _ = make_setup(tmp_path)
    result = run_pib(home, fake_pi(tmp_path), ["--status", "-p", "x"], cwd=tmp_path)
    assert result.returncode == 2
    assert "--status に他の引数は付けられない" in result.stderr


def test_pib_accepts_a_complete_setup(tmp_path):
    home, env = make_setup(tmp_path)
    assert pib.problems(env, home, tmp_path / "work") == []


def test_pib_accepts_a_tilde_shell_path(tmp_path):
    home, env = make_setup(tmp_path, settings={"shellPath": "~/.local/bin/pib-shell"})
    assert pib.problems(env, home, tmp_path / "work") == []


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"runner": False}, "runner が無い"),
        ({"shell": False}, "シェルが無い"),
        ({"config": False}, "runner の設定が無い"),
        ({"bwrap": False}, "bwrap が見つからない"),
        ({"settings": False}, "shellPath が"),  # 設定ファイルが無ければ、shellPath も無い
        ({"settings": {}}, "shellPath が"),
        ({"settings": {"shellPath": "/bin/bash"}}, "shellPath が"),  # 囲いなしのシェルを指している
        ({"settings": {"shellPath": 3}}, "shellPath が"),
        ({"settings": []}, "設定を読めない"),  # オブジェクトでない設定は、読めないものとして扱う
    ],
)
def test_pib_names_what_is_missing(tmp_path, kwargs, needle):
    home, env = make_setup(tmp_path, **kwargs)
    found = pib.problems(env, home, tmp_path / "work")
    assert any(needle in line for line in found), found


def test_pib_refuses_a_broken_settings_file(tmp_path):
    home, env = make_setup(tmp_path, settings=False)
    (home / ".pi" / "agent" / "settings.json").write_text("{not json", encoding="utf-8")
    assert any("読めない" in line for line in pib.problems(env, home, tmp_path / "work"))


def test_pib_refuses_a_project_setting_that_overrides_the_shell(tmp_path):
    """プロジェクトの設定は利用者の設定を上書きする。ここで shellPath を替えられると、囲いなしで動く。"""
    home, env = make_setup(tmp_path)
    work = tmp_path / "work"
    (work / ".pi").mkdir(parents=True)
    (work / ".pi" / "settings.json").write_text(
        json.dumps({"shellPath": "/bin/bash"}), encoding="utf-8"
    )
    found = pib.problems(env, home, work)
    assert any("囲いを外している" in line for line in found), found
    # 同じ pib-shell を指すだけなら、問題にしない
    (work / ".pi" / "settings.json").write_text(
        json.dumps({"shellPath": str(home / ".local" / "bin" / "pib-shell")}), encoding="utf-8"
    )
    assert pib.problems(env, home, work) == []


@pytest.mark.parametrize(
    "value", [None, False, 0, "", [], {}, "/bin/bash", "bash", "~/.local/bin/other"]
)
def test_pib_refuses_every_project_shell_path_that_is_not_the_deployed_shell(tmp_path, value):
    """pi は null・false・0 なども上書きの値として保ち、通常の bash を選ぶ。キーがあれば、値を問わず検査する。"""
    home, env = make_setup(tmp_path)
    work = tmp_path / "work"
    (work / ".pi").mkdir(parents=True)
    (work / ".pi" / "settings.json").write_text(json.dumps({"shellPath": value}), encoding="utf-8")
    found = pib.problems(env, home, work)
    assert any("囲いを外している" in line for line in found), found


@pytest.mark.parametrize(
    "content",
    [b"{not json", b"\xef\xbb\xbf{not json", b"[]", b"3", b"\xff\xfe", b""],
)
def test_pib_refuses_a_project_setting_it_cannot_read(tmp_path, content):
    """読めない設定を「shellPath が無い」とみなして通さない (pi が読めるかもしれない)。"""
    home, env = make_setup(tmp_path)
    work = tmp_path / "work"
    (work / ".pi").mkdir(parents=True)
    (work / ".pi" / "settings.json").write_bytes(content)
    found = pib.problems(env, home, work)
    assert any("プロジェクトの設定を読めない" in line for line in found), found


def test_pib_refuses_a_project_setting_that_is_a_directory(tmp_path):
    home, env = make_setup(tmp_path)
    work = tmp_path / "work"
    (work / ".pi" / "settings.json").mkdir(parents=True)
    assert any("読めない" in line for line in pib.problems(env, home, work))


def test_pib_reads_settings_with_a_bom_the_way_pi_does(tmp_path):
    """pi は BOM を取り除いて読む。BOM 付きで囲いを外す値を書いても、通さない。BOM 付きの正しい値は通す。"""
    home, env = make_setup(tmp_path)
    shell = str(home / ".local" / "bin" / "pib-shell")
    work = tmp_path / "work"
    (work / ".pi").mkdir(parents=True)
    path = work / ".pi" / "settings.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"shellPath": "/bin/bash"}).encode())
    assert any("囲いを外している" in line for line in pib.problems(env, home, work))
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"shellPath": shell}).encode())
    assert pib.problems(env, home, work) == []
    user = home / ".pi" / "agent" / "settings.json"
    user.write_bytes(b"\xef\xbb\xbf" + json.dumps({"shellPath": shell}).encode())
    assert pib.problems(env, home, work) == []


def test_pib_requires_the_deployed_path_itself_not_an_alias_of_it(tmp_path):
    """別名 (シンボリックリンク) は、内側から別のシェルへ付け替えられる。配備先の絶対パスそのものだけを認める。"""
    home, env = make_setup(tmp_path)
    shell = home / ".local" / "bin" / "pib-shell"
    work = tmp_path / "work"
    (work / ".pi").mkdir(parents=True)
    alias = work / ".pi" / "shell"
    alias.symlink_to(shell)
    (work / ".pi" / "settings.json").write_text(
        json.dumps({"shellPath": str(alias)}), encoding="utf-8"
    )
    assert any("囲いを外している" in line for line in pib.problems(env, home, work))
    # 付け替え後 (次の起動) も、同じ検査で止まる
    alias.unlink()
    alias.symlink_to("/bin/bash")
    assert any("囲いを外している" in line for line in pib.problems(env, home, work))
    # 利用者の設定が、別名を指していても同じ
    (work / ".pi" / "settings.json").unlink()
    user_alias = tmp_path / "user-alias"
    user_alias.symlink_to(shell)
    (home / ".pi" / "agent" / "settings.json").write_text(
        json.dumps({"shellPath": str(user_alias)}), encoding="utf-8"
    )
    found = pib.problems(env, home, work)
    assert any("絶対パスそのもの" in line for line in found), found


def test_pib_resolves_the_agent_dir_the_way_pi_does(tmp_path, monkeypatch):
    """pi は PI_CODING_AGENT_DIR の ~ と ~/ を展開する。展開せずに読むと、作業ディレクトリの偽の設定を検査してしまう。"""
    home, env = make_setup(
        tmp_path, settings={"shellPath": "/bin/bash"}
    )  # 実際の設定は、囲いを外している
    work = tmp_path / "work"
    fake = work / "~" / ".pi" / "agent"
    fake.mkdir(parents=True)
    (fake / "settings.json").write_text(
        json.dumps({"shellPath": str(home / ".local" / "bin" / "pib-shell")}), encoding="utf-8"
    )
    monkeypatch.chdir(work)  # 展開せずに読むと、この偽の設定が読まれる (cwd からの相対)
    found = pib.problems({**env, "PI_CODING_AGENT_DIR": "~/.pi/agent"}, home, work)
    assert any("絶対パスそのもの" in line for line in found), (
        found
    )  # ホーム側の本物の設定を検査して、止める


@pytest.mark.parametrize(
    ("value", "relative"),
    [("~", ""), ("~/agent", "agent"), (None, ".pi/agent")],
)
def test_pib_agent_dir_follows_the_tilde_rules_of_pi(tmp_path, value, relative):
    env = {} if value is None else {"PI_CODING_AGENT_DIR": value}
    got, problem = pib._agent_dir(env, tmp_path)
    assert problem is None and got == tmp_path / relative


@pytest.mark.parametrize(
    "value",
    [
        "~//tmp/pib-agent",
        "/abs/link/../agent",
        "/abs//agent",
        "/abs/agent/",
        "/abs/./agent",
        "//abs/agent",
    ],
)
def test_pib_refuses_agent_dirs_that_pi_and_the_os_could_read_differently(tmp_path, value):
    """pi は文字列だけで整え (Node の join)、OS は link を辿ってから .. を解く。解釈を合わせず、食い違いうる表記を拒否する。"""
    got, problem = pib._agent_dir({"PI_CODING_AGENT_DIR": value}, tmp_path)
    assert got is None and problem and "PI_CODING_AGENT_DIR" in problem


@pytest.mark.parametrize(
    "home_text",
    ["/t/link/../home", "/home/u/", "//home/u", "/home/./u", "/home//u", "relative/home"],
)
def test_pib_refuses_a_home_that_pi_and_the_os_could_resolve_differently(tmp_path, home_text):
    """HOME に link をまたぐ .. などがあると、既定の設定ディレクトリ (HOME/.pi/agent) も、~/ の shellPath も食い違いうる。"""
    home, env = make_setup(tmp_path)
    found = pib.problems({**env, "HOME": home_text}, home, tmp_path / "work")
    assert any(line.startswith("HOME は") for line in found), found


def test_pib_agent_dir_accepts_an_absolute_path_as_is(tmp_path):
    got, problem = pib._agent_dir({"PI_CODING_AGENT_DIR": "/abs/agent"}, tmp_path)
    assert problem is None and got == Path("/abs/agent")


@pytest.mark.parametrize(
    "value", ["relative/agent", "file:///home/u/.pi/agent", "./agent", "~user/agent"]
)
def test_pib_refuses_an_agent_dir_it_cannot_resolve_the_way_pi_does(tmp_path, value):
    home, env = make_setup(tmp_path)
    found = pib.problems({**env, "PI_CODING_AGENT_DIR": value}, home, tmp_path / "work")
    assert any("PI_CODING_AGENT_DIR" in line for line in found), found


def test_pib_honours_the_agent_dir_and_config_overrides(tmp_path):
    home, env = make_setup(tmp_path, settings=False, config=False)
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / "settings.json").write_text(
        json.dumps({"shellPath": str(home / ".local" / "bin" / "pib-shell")}), encoding="utf-8"
    )
    conf = tmp_path / "elsewhere.toml"
    conf.write_text(MINIMAL, encoding="utf-8")
    env = {**env, "PI_CODING_AGENT_DIR": str(agent), "PI_SANDBOX_RUNNER_CONFIG": str(conf)}
    assert pib.problems(env, home, tmp_path / "work") == []


def test_pib_parses_the_offline_flag_only_at_the_front():
    assert pib.parse_args(["--offline", "-p", "x"]) == (True, ["-p", "x"], None)
    assert pib.parse_args(["-p", "--offline"]) == (False, ["-p", "--offline"], None)
    assert pib.parse_args([]) == (False, [], None)


@pytest.mark.parametrize("flag", ["-a", "--approve"])
def test_pib_refuses_the_approve_flag_because_it_would_load_project_settings(flag):
    """--approve は、プロジェクトの .pi/settings.json (shellPath を上書きできる) を読ませる。pib は --no-approve で起動する。"""
    assert pib.parse_args(["--offline", "-p", flag, "x"])[2] is not None
    assert pib.parse_args([flag])[2] is not None
    assert pib.parse_args(["--no-approve"])[2] is None


def fake_pi(tmp_path):
    """引数と、PIB_SANDBOX を記録するだけの pi。"""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    pi = bin_dir / "pi"
    pi.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$PIB_SANDBOX" "$@" > "{tmp_path}/pi-args"\n', encoding="utf-8"
    )
    pi.chmod(0o755)
    return bin_dir


def run_pib(home, fake_dir, args=(), cwd=None, env_extra=None):
    env = {"HOME": str(home), "PATH": f"{fake_dir}{os.pathsep}{os.environ['PATH']}"}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(PIB), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=cwd,
        timeout=30,
        check=False,
    )


@linux_only
@pytest.mark.parametrize(
    ("args", "mode", "passed"),
    [
        (["-p", "hello"], "1", ["--no-approve", "-p", "hello"]),
        (["--offline", "-p", "hello"], "offline", ["--no-approve", "-p", "hello"]),
    ],
)
def test_pib_runs_pi_with_the_sandbox_requested_and_passes_arguments_through(
    tmp_path, args, mode, passed
):
    home, _ = make_setup(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    result = run_pib(home, fake_pi(tmp_path), args, cwd=work)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "pi-args").read_text(encoding="utf-8").split("\n")[:-1] == [mode, *passed]


@linux_only
def test_pib_does_not_start_pi_when_the_setup_is_incomplete(tmp_path):
    home, _ = make_setup(tmp_path, runner=False)
    work = tmp_path / "work"
    work.mkdir()
    result = run_pib(home, fake_pi(tmp_path), cwd=work)
    assert result.returncode == 2
    assert result.stderr.startswith("pib:")
    assert not (tmp_path / "pi-args").exists()  # pi は起動していない


# --- 仕様・配備との整合 -------------------------------------------------------


def test_spec_documents_the_entry_point_and_the_environment_variable():
    spec = SPEC.read_text(encoding="utf-8")
    for word in ("shellPath", "PIB_SANDBOX", "pib-shell", "許可リスト", "--offline"):
        assert word in spec, word


def test_the_shell_script_has_a_shebang_and_no_fallback_to_the_unsandboxed_shell_inside_the_branch():
    text = PIB_SHELL.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/bash\n")
    branch = text.split('if [ -n "${PIB_SANDBOX:-}" ]; then', 1)[1].split("\nfi\n", 1)[0]
    assert "/bin/bash" not in branch  # 囲いを通す枝の中で、素の bash を呼ばない

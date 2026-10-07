"""隔離起動 ``ocs`` のランチャーに関するテスト。

Run with: ``uv run --with pytest --no-project pytest test/agents/`` or
``python3 -m pytest test/agents/``.

see docs/spec/opencode-sandbox.md
"""

from __future__ import annotations

import contextlib
import gzip
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402

# ocs は bwrap で囲うので Ubuntu / WSL 専用。他の OS には配らない
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="ocs は Linux 専用")
from agents_common import load_common  # noqa: E402

LAUNCHER = ROOT / "home" / "dot_local" / "bin" / "executable_ocs"
LIB = ROOT / "home" / "dot_local" / "share" / "ocs"
MODULES = ("common", "boundary", "check", "backup", "config", "cli")
COMMON = load_common()


def _generated(tmp_path: Path) -> dict:
    """Fence の無い機械でも生成結果を得るため、runtime だけダミーに差し替える。"""
    runtime = tmp_path / "fence"
    runtime.write_text("", "utf-8")
    common = {
        **COMMON,
        "opencode": {
            **COMMON["opencode"],
            "sandbox": {**COMMON["opencode"]["sandbox"], "runtime_path": str(runtime)},
        },
    }
    sandbox = gen.opencode_sandbox(common)
    assert sandbox is not None, "境界の設定が生成されない"
    return sandbox


def _entry() -> dict:
    """入口の定義だけ取り出す (main は動かさない)。"""
    namespace: dict = {"__name__": "probe"}
    exec(compile(LAUNCHER.read_text(encoding="utf-8"), "launcher", "exec"), namespace)
    return namespace


def _launcher() -> SimpleNamespace:
    """ランチャーの本体を source state から読み込む。配備先 (~/.local/share/ocs) は読まない。

    入口と同じ ``load`` を使い、テストごとに読み直す (monkeypatch を持ち越さない)。
    source state へ ``__pycache__`` を作らないよう、読み込みの間だけ書き出しを止める。
    """
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        _entry()["load"](LIB)
    finally:
        sys.dont_write_bytecode = saved
    launcher = SimpleNamespace(**{name: sys.modules[f"ocs_lib.{name}"] for name in MODULES})
    if _IMPL_GIT_HOME is not None:
        real = launcher.backup.git_env
        launcher.backup.git_env = lambda index=None: _isolated_git_env(real(index), _IMPL_GIT_HOME)
    return launcher


def _isolated_git_env(env: dict[str, str], home: str) -> dict[str, str]:
    """``env`` に、git が実行者の system / global 設定を読まないための変数を足す。

    ★``GIT_CONFIG_GLOBAL`` だけでは既定の ``~/.config/git/ignore`` / ``attributes`` が
      残るので、``HOME`` / ``XDG_CONFIG_HOME`` も空の一時領域へ向ける。
    """
    return {
        **env,
        "HOME": home,
        "XDG_CONFIG_HOME": os.path.join(home, ".config"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }


_IMPL_GIT_HOME: str | None = None


@pytest.fixture(autouse=True)
def _isolate_launcher_git(request, monkeypatch, tmp_path_factory):
    """ランチャーが動かす git (退避・``git_common_dir``) も実行者の git 設定から切り離す。

    ★実装の ``git_env()`` は ``GIT_*`` をまとめて落とすので、conftest で入れた
      ``GIT_CONFIG_GLOBAL`` / ``GIT_CONFIG_NOSYSTEM`` もそこで消える。放っておくと
      利用者の global ignore (例: ``*.bin``) で退避の中身が変わる。
    ``_launcher()`` が返す ``backup.git_env`` を包む。``git_env()`` 自体の契約を
    見るテストは ``raw_git_env`` の印で外す。
    """
    if request.node.get_closest_marker("raw_git_env") is None:
        home = str(tmp_path_factory.mktemp("git-home"))
        monkeypatch.setitem(globals(), "_IMPL_GIT_HOME", home)


def _sandbox(tmp_path: Path, **overrides) -> dict:
    """隔離版の設定の素材に、書き出し先だけ差し替えたものを返す。"""
    base = _generated(tmp_path)
    return {
        "config_dir": str(tmp_path / "config"),
        "permissions": base["permissions"],
        "policies": base.get("policies", []),
        "plugins": base.get("plugins", []),
        "system_prompt": base.get("system_prompt", "境界の説明"),
        "model_preference": base.get("model_preference", []),
        "agent": base.get("agent", {}),
        "agents": base.get("agents", {}),
        "commands": base.get("commands", {}),
        **overrides,
    }


def _project(tmp_path: Path) -> dict:
    """cwd で選ばれるプロジェクト 1 つ分。"""
    return {
        "workspace": str(tmp_path / "ws"),
        "data_dir": str(tmp_path / "data" / "opencode"),
        "db": str(tmp_path / "opencode.db"),
        "config": {"network": {"allowedDomains": []}, "filesystem": {"denyWrite": []}},
    }


def _seed_db(path: Path, integration: str = "github-copilot") -> None:
    con = sqlite3.connect(str(path))
    con.execute("create table credential (id text, integration_id text)")
    con.execute("insert into credential values ('cred_x', ?)", (integration,))
    con.commit()
    con.close()


def test_managed_keys_are_replaced_every_time(tmp_path):
    """緩和に関わるキーは、内側で書き換えられても毎回戻ること。"""
    launcher = _launcher()
    sandbox = _sandbox(tmp_path)
    project = _project(tmp_path)
    launcher.config.write_isolated_config(sandbox, project)

    target = Path(sandbox["config_dir"]) / "opencode.json"
    tampered = json.loads(target.read_text(encoding="utf-8"))
    tampered["permissions"] = []  # 緩めた想定
    tampered["snapshots"] = False
    target.write_text(json.dumps(tampered), encoding="utf-8")

    launcher.config.write_isolated_config(sandbox, project)
    after = json.loads(target.read_text(encoding="utf-8"))
    assert after["permissions"] == sandbox["permissions"], "permissions が戻っていない"
    assert after["snapshots"] is True, "snapshots が戻っていない"


def test_unmanaged_keys_survive(tmp_path):
    """★こちらが管理しないキーは残すこと。

    丸ごと上書きすると、TUI で選んだモデルが起動のたびに消える。
    """
    launcher = _launcher()
    sandbox = _sandbox(tmp_path)
    project = _project(tmp_path)
    launcher.config.write_isolated_config(sandbox, project)

    target = Path(sandbox["config_dir"]) / "opencode.json"
    config = json.loads(target.read_text(encoding="utf-8"))
    config["model"] = "github-copilot/claude-sonnet-5"
    config["username"] = "alice"
    target.write_text(json.dumps(config), encoding="utf-8")

    launcher.config.write_isolated_config(sandbox, project)
    after = json.loads(target.read_text(encoding="utf-8"))
    assert after.get("model") == "github-copilot/claude-sonnet-5", "model が消えた"
    assert after.get("username") == "alice", "宣言外のキーが消えた"


def test_broken_config_is_rebuilt(tmp_path):
    """壊れた JSON は作り直す。読めないまま残すと起動できない。"""
    launcher = _launcher()
    sandbox = _sandbox(tmp_path)
    project = _project(tmp_path)
    config_dir = Path(sandbox["config_dir"])
    config_dir.mkdir(parents=True)
    (config_dir / "opencode.json").write_text("{これは JSON ではない", encoding="utf-8")

    launcher.config.write_isolated_config(sandbox, project)
    after = json.loads((config_dir / "opencode.json").read_text(encoding="utf-8"))
    assert after["permissions"] == sandbox["permissions"]


def test_default_model_only_on_first_write(tmp_path):
    """既定モデルは初回だけ置き、以降は利用者の選択を尊重する。"""
    launcher = _launcher()
    sandbox = _sandbox(
        tmp_path,
        model_preference=[{"provider": "github-copilot", "model": "claude-opus-5"}],
    )
    project = _project(tmp_path)
    _seed_db(Path(project["db"]))
    target = Path(sandbox["config_dir"]) / "opencode.json"

    def current_model() -> str:
        return json.loads(target.read_text(encoding="utf-8"))["model"]

    launcher.config.write_isolated_config(sandbox, project)
    assert current_model() == "github-copilot/claude-opus-5"

    config = json.loads(target.read_text(encoding="utf-8"))
    config["model"] = "github-copilot/claude-sonnet-5"
    target.write_text(json.dumps(config), encoding="utf-8")
    launcher.config.write_isolated_config(sandbox, project)
    assert current_model() == "github-copilot/claude-sonnet-5"


def test_model_preference_order_wins(tmp_path):
    """★資格情報がある provider を、宣言した順で選ぶこと。

    無い provider を既定にすると、起動しても応答が来ない。
    """
    launcher = _launcher()
    sandbox = _sandbox(
        tmp_path,
        model_preference=[
            {"provider": "amazon-bedrock", "model": "sonnet-5"},
            {"provider": "github-copilot", "model": "claude-opus-5"},
        ],
    )
    project = _project(tmp_path)
    # bedrock の資格情報は無く、copilot だけある状況
    _seed_db(Path(project["db"]), integration="github-copilot")
    assert launcher.config.pick_model(sandbox, project) == "github-copilot/claude-opus-5"


def test_model_is_absent_without_credentials(tmp_path):
    """資格情報が無ければ既定を置かない (誤った provider を固定しない)。"""
    launcher = _launcher()
    sandbox = _sandbox(
        tmp_path,
        model_preference=[{"provider": "amazon-bedrock", "model": "sonnet-5"}],
    )
    project = _project(tmp_path)
    _seed_db(Path(project["db"]), integration="github-copilot")
    assert launcher.config.pick_model(sandbox, project) is None


def _base_sandbox(tmp_path: Path, **base) -> dict:
    """境界の素材。パスは tmp_path の下に作る (無いパスは境界へ渡らないため)。"""
    shared = tmp_path / "shared"
    shared.mkdir(exist_ok=True)
    return {
        "base": {
            "read": [str(shared)],
            "work_read": [],
            "write": [],
            "deny_read": [],
            "unsafe_workspace": ["/home/u", "/mnt", "/tmp"],
            "protected": [".opencode"],
            "network": {
                "allowedDomains": ["github.com"],
                "deniedDomains": [],
                "allowLocalBinding": False,
            },
            **base,
        },
    }


def _request(workspace: Path, body: str) -> Path:
    path = workspace / ".opencode" / "sandbox.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_launch_directory_is_always_writable(tmp_path):
    """★起動ディレクトリ以下は無条件に書ける。読み取りも開ける。"""
    launcher = _launcher()
    where = tmp_path / "undeclared" / "deep"
    where.mkdir(parents=True)
    filesystem = launcher.boundary.build_boundary(_base_sandbox(tmp_path), where)["filesystem"]
    assert str(where) in filesystem["allowWrite"]
    assert str(where) in filesystem["allowRead"]


def test_reads_are_denied_by_default(tmp_path):
    """★読み取りは既定で拒否し、並べた所だけを開ける。

    名指しで隠す形では、新しくできた秘密の置き場が既定で見える。
    """
    launcher = _launcher()
    (tmp_path / "ws").mkdir()
    filesystem = launcher.boundary.build_boundary(_base_sandbox(tmp_path), tmp_path / "ws")[
        "filesystem"
    ]
    assert filesystem["defaultDenyRead"] is True


def test_missing_paths_are_not_passed_to_fence(tmp_path):
    """無いパスは Fence へ渡さない (機械ごとに無い作業用ディレクトリがあってよい)。"""
    launcher = _launcher()
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "src").mkdir()
    sandbox = _base_sandbox(
        tmp_path,
        work_read=[str(tmp_path / "src"), str(tmp_path / "papers")],
        write=[str(tmp_path / "cache")],
    )
    filesystem = launcher.boundary.build_boundary(sandbox, ws)["filesystem"]
    assert str(tmp_path / "src") in filesystem["allowRead"], "作業用の親ディレクトリが読めない"
    assert str(tmp_path / "papers") not in filesystem["allowRead"]
    assert str(tmp_path / "cache") not in filesystem["allowWrite"]


def test_data_dir_is_shared_but_state_is_not(tmp_path):
    """★DB を共有するので XDG_DATA_HOME/opencode は読み書きできる。

    ``~/.local/state/opencode`` (常駐サービスの接続情報) は開けない。
    """
    launcher = _launcher()
    ws = tmp_path / "ws"
    ws.mkdir()
    data = tmp_path / "share" / "opencode"
    data.mkdir(parents=True)
    filesystem = launcher.boundary.build_boundary(_base_sandbox(tmp_path), ws, None, data)[
        "filesystem"
    ]
    assert str(data) in filesystem["allowWrite"]
    opened = " ".join(filesystem["allowRead"] + filesystem["allowWrite"])
    assert ".local/state/opencode" not in opened


def test_generated_read_list_does_not_open_opencode_state(tmp_path):
    """★生成された素材も ``~/.local/state`` と ``~/.config/opencode`` を丸ごとは開けない。"""
    base = _generated(tmp_path)["base"]
    home = str(Path.home())
    opened = [*base["read"], *base["work_read"], *base["write"]]
    assert f"{home}/.config/opencode" not in opened, "service.json まで読める"
    assert not any(p.startswith(f"{home}/.local/state") for p in opened)


def test_work_roots_are_declared(tmp_path):
    """利用者が決めた作業用の親ディレクトリを読めるようにする (CHG-0009 段 5)。"""
    work = _generated(tmp_path)["base"]["work_read"]
    home = str(Path.home())
    for rel in ("src", "worktrees", "papers", ".local/share/chezmoi"):
        assert f"{home}/{rel}" in work, f"~/{rel} が work_read に無い"


def test_secrets_inside_opened_dirs_are_hidden(tmp_path, monkeypatch):
    """★開けた場所の内側の秘密は denyRead で隠す。開けていない所は元から見えない。"""
    launcher = _launcher()
    home = tmp_path / "home"
    chezmoi = home / ".config/chezmoi"
    chezmoi.mkdir(parents=True)
    (chezmoi / "key.txt").write_text("x", encoding="utf-8")
    (home / ".ssh").mkdir()
    run_user = tmp_path / "run" / "user"
    run_user.mkdir(parents=True)
    monkeypatch.setattr(launcher.boundary, "HOME", home)
    ws = home / "ws"
    ws.mkdir()
    sandbox = _base_sandbox(
        tmp_path,
        read=[str(chezmoi)],
        deny_read=[
            str(chezmoi / "key.txt"),
            str(home / ".ssh"),
            str(home / ".gnupg"),
            str(run_user),
        ],
    )
    deny = launcher.boundary.build_boundary(sandbox, ws)["filesystem"]["denyRead"]
    assert str(chezmoi / "key.txt") in deny, "開けた場所の内側の秘密が隠れていない"
    assert str(home / ".ssh") not in deny, "開けていない場所を Fence へ渡している"
    assert str(home / ".gnupg") not in deny, "無い場所を Fence へ渡している"
    assert str(run_user) in deny, "ホームの外の既定で見える場所が隠れていない"


def test_secrets_are_hidden_when_home_is_a_symlink(tmp_path, monkeypatch):
    """★ホームが symlink だと起動ディレクトリは実体になる。秘密を実体で比べて隠すこと。"""
    launcher = _launcher()
    root = tmp_path.resolve()
    real = root / "data" / "user"
    gh = real / ".config" / "gh"
    gh.mkdir(parents=True)
    (gh / "hosts.yml").write_text("x", encoding="utf-8")
    (root / "home").mkdir()
    home = root / "home" / "user"
    home.symlink_to(real)
    monkeypatch.setattr(launcher.boundary, "HOME", home)
    sandbox = _base_sandbox(tmp_path, deny_read=[str(home / ".config/gh/hosts.yml")])
    deny = launcher.boundary.build_boundary(sandbox, gh)["filesystem"]["denyRead"]
    assert str(gh / "hosts.yml") in deny, "起動ディレクトリの中の秘密が隠れていない"


def test_secret_linked_outside_home_is_hidden(tmp_path, monkeypatch):
    """★ホームの中の秘密がホームの外 (Fence が既定で見せる場所) を指す symlink でも隠すこと。"""
    launcher = _launcher()
    root = tmp_path.resolve()
    home = root / "home"
    (home / ".config" / "gh").mkdir(parents=True)
    outside = root / "opt" / "hosts.yml"
    outside.parent.mkdir()
    outside.write_text("x", encoding="utf-8")
    (home / ".config" / "gh" / "hosts.yml").symlink_to(outside)
    ws = home / "ws"
    ws.mkdir()
    monkeypatch.setattr(launcher.boundary, "HOME", home)
    sandbox = _base_sandbox(tmp_path, deny_read=[str(home / ".config/gh/hosts.yml")])
    deny = launcher.boundary.build_boundary(sandbox, ws)["filesystem"]["denyRead"]
    assert str(outside) in deny, "ホームの外を指す秘密が隠れていない"


def test_shared_secret_list_reaches_the_boundary(tmp_path):
    """★[sandbox] deny の秘密 (glob 以外) は隔離起動でも隠す対象になる。"""
    deny = _generated(tmp_path)["base"]["deny_read"]
    home = str(Path.home())
    assert f"{home}/.config/chezmoi/key.txt" in deny
    assert f"{home}/.ssh" in deny
    assert not [p for p in deny if "*" in p], "glob を Fence へ渡している"


@pytest.mark.parametrize(
    "where",
    ["/home/u", "/home", "/", "/tmp", "/mnt"],
    ids=["unsafe_workspace そのもの", "その祖先", "ルート", "/tmp", "/mnt"],
)
def test_too_broad_workspace_is_rejected(tmp_path, where):
    """★起動ディレクトリは書けるので、ホームや /tmp では起動しない。"""
    launcher = _launcher()
    with pytest.raises(SystemExit):
        launcher.boundary.reject_unsafe_workspace(_base_sandbox(tmp_path), Path(where))


@pytest.mark.parametrize(
    "where",
    ["/home/u/work/repo", "/tmp/scratch", "/opt/shared/x"],
    ids=["ホーム配下", "/tmp 配下", "対象の外"],
)
def test_workspace_below_unsafe_roots_is_allowed(tmp_path, where):
    launcher = _launcher()
    launcher.boundary.reject_unsafe_workspace(_base_sandbox(tmp_path), Path(where))


def test_symlinked_home_is_rejected_by_its_real_path(tmp_path):
    """★起動ディレクトリは実体パスになる。ホームが symlink でも拒否できること。"""
    launcher = _launcher()
    root = tmp_path.resolve()
    real = root / "data" / "user"
    (real / "work").mkdir(parents=True)
    (root / "home").mkdir()
    (root / "home" / "user").symlink_to(real)
    sandbox = _base_sandbox(tmp_path, unsafe_workspace=[str(root / "home" / "user")])
    for where in (real, root / "data"):
        with pytest.raises(SystemExit):
            launcher.boundary.reject_unsafe_workspace(sandbox, where)
    launcher.boundary.reject_unsafe_workspace(sandbox, real / "work")


@pytest.mark.parametrize("exists", [True, False], ids=["在る", "無い"])
def test_unsafe_path_through_a_symlinked_parent_is_rejected(tmp_path, exists):
    """途中のディレクトリが symlink でも、無いパスでも、正規化できる範囲で比べる。"""
    launcher = _launcher()
    root = tmp_path.resolve()
    (root / "real").mkdir()
    (root / "link").symlink_to(root / "real")
    if exists:
        (root / "real" / "scratch").mkdir()
    sandbox = _base_sandbox(tmp_path, unsafe_workspace=[str(root / "link" / "scratch")])
    for where in (root / "real" / "scratch", root / "real"):
        with pytest.raises(SystemExit):
            launcher.boundary.reject_unsafe_workspace(sandbox, where)


def test_generated_unsafe_workspace_covers_home_and_tmp(tmp_path):
    unsafe = _generated(tmp_path)["base"]["unsafe_workspace"]
    for required in (str(Path.home()), "/mnt", "/tmp"):
        assert required in unsafe, f"unsafe_workspace に {required} が無い"


def _control_home(tmp_path: Path) -> tuple[Path, dict]:
    """配備先を持つホーム。置き場は ``~/.config/opencode`` と ``~/.local/share/ocs``。

    兄弟として ``~/.local/share/chezmoi`` と ``~/src/repo`` も作る。
    """
    home = tmp_path.resolve() / "home"
    for rel in (
        ".config/opencode/guide-plugin",
        ".local/share/ocs",
        ".local/share/chezmoi",
        "src/repo",
    ):
        (home / rel).mkdir(parents=True)
    sandbox = _base_sandbox(
        tmp_path,
        unsafe_workspace=[str(home)],
        control_dirs=[str(home / ".config/opencode"), str(home / ".local/share/ocs")],
    )
    return home, sandbox


@pytest.mark.parametrize(
    "rel",
    [".config/opencode/guide-plugin", ".config/opencode", ".local/share/ocs", ".config", ".local"],
    ids=["子孫", "そのもの", "そのもの (本体)", "祖先", "祖先 (本体)"],
)
def test_launch_overlapping_control_dirs_is_refused(tmp_path, capsys, rel):
    """★配備済みの制御ファイルの置き場は、そのもの・祖先・子孫のどこで起動しても書けてしまう。

    子孫 (``~/.config/opencode/guide-plugin``) で起動すると rules.json (次回の境界の入力) が書ける。
    """
    launcher = _launcher()
    home, sandbox = _control_home(tmp_path)
    with pytest.raises(SystemExit):
        launcher.boundary.reject_control_dirs(sandbox, home / rel)
    assert "ocs を使わずに" in capsys.readouterr().err


@pytest.mark.parametrize(
    "rel", [".local/share/chezmoi", "src/repo"], ids=["~/.local/share/chezmoi", "~/src"]
)
def test_launch_beside_control_dirs_is_allowed(tmp_path, rel):
    """兄弟 (制御ファイルの置き場と重ならない場所) では起動できる。"""
    launcher = _launcher()
    home, sandbox = _control_home(tmp_path)
    launcher.boundary.reject_control_dirs(sandbox, home / rel)
    launcher.boundary.reject_unsafe_workspace(sandbox, home / rel)


@pytest.mark.parametrize(
    "rel", ["dotfiles/opencode/guide-plugin", "dotfiles"], ids=["子孫", "祖先"]
)
def test_symlinked_control_dir_is_refused_at_its_real_path(tmp_path, rel):
    """★置き場が symlink でも、実体側での起動を拒否する (起動ディレクトリは実体パスになる)。"""
    launcher = _launcher()
    root = tmp_path.resolve()
    (root / "dotfiles/opencode/guide-plugin").mkdir(parents=True)
    (root / "home/.config").mkdir(parents=True)
    (root / "home/.config/opencode").symlink_to(root / "dotfiles/opencode")
    sandbox = _base_sandbox(tmp_path, control_dirs=[str(root / "home/.config/opencode")])
    with pytest.raises(SystemExit):
        launcher.boundary.reject_control_dirs(sandbox, root / rel)


@pytest.mark.parametrize(
    "write",
    [".config/opencode/guide-plugin/rules.json", ".config/opencode", ".config", "src/repo/link"],
    ids=["子孫", "そのもの", "祖先", "symlink 経由"],
)
def test_requested_write_overlapping_control_dirs_is_refused(tmp_path, capsys, write):
    """★``.opencode/sandbox.toml`` の ``write`` が置き場と重なるときも起動しない。"""
    launcher = _launcher()
    home, sandbox = _control_home(tmp_path)
    ws = home / "src/repo"
    (ws / "link").symlink_to(home / ".config/opencode")
    _request(ws, f'write = ["{home / write}"]\n')
    request = launcher.boundary.read_request(ws)
    with pytest.raises(SystemExit):
        launcher.boundary.reject_control_dirs(sandbox, ws, request)
    assert "ocs を使わずに" in capsys.readouterr().err


def test_requested_write_beside_control_dirs_is_allowed(tmp_path):
    launcher = _launcher()
    home, sandbox = _control_home(tmp_path)
    ws = home / "src/repo"
    _request(ws, f'write = ["{home / ".local/share/chezmoi"}"]\n')
    launcher.boundary.reject_control_dirs(sandbox, ws, launcher.boundary.read_request(ws))


def test_no_request_means_no_extras(tmp_path):
    """要求が無ければ追加はゼロ。共通分だけで動く。"""
    launcher = _launcher()
    (tmp_path / "gamma").mkdir()
    boundary = launcher.boundary.build_boundary(_base_sandbox(tmp_path), tmp_path / "gamma")
    assert boundary["filesystem"]["allowRead"] == [
        str(tmp_path / "gamma"),
        str(tmp_path / "shared"),
    ]
    assert boundary["network"]["allowedDomains"] == ["github.com"]


def test_request_adds_only_to_its_own_workspace(tmp_path):
    """★要求は、それを置いたワークスペースにしか効かない。"""
    launcher = _launcher()
    alpha, beta = tmp_path / "alpha", tmp_path / "beta"
    alpha.mkdir()
    beta.mkdir()
    data = tmp_path / "d" / "alpha"
    data.mkdir(parents=True)
    _request(alpha, f'read = ["{data}"]\nnetwork_allow = ["api.alpha.test"]\n')

    build, read = launcher.boundary.build_boundary, launcher.boundary.read_request
    got = build(_base_sandbox(tmp_path), alpha, read(alpha))
    assert str(data) in got["filesystem"]["allowRead"]
    assert "api.alpha.test" in got["network"]["allowedDomains"]

    other = build(_base_sandbox(tmp_path), beta, read(beta))
    assert str(data) not in other["filesystem"]["allowRead"]
    assert "api.alpha.test" not in other["network"]["allowedDomains"]


def test_request_is_applied_without_approval(tmp_path, monkeypatch, capsys):
    """★要求は確認なしで適用し、足した分を起動時に表示する (承認の記録は持たない)。"""
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    _request(ws, f'write = ["{out}"]\nnetwork_allow = ["api.alpha.test"]\n')
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    request = launcher.boundary.read_request(ws)
    launcher.boundary.announce_request(request)
    got = launcher.boundary.build_boundary(_base_sandbox(tmp_path), ws, request)
    assert str(out) in got["filesystem"]["allowWrite"]
    shown = capsys.readouterr().err
    assert str(out) in shown and "api.alpha.test" in shown
    assert str(ws / ".opencode" / "sandbox.toml") in shown
    assert not hasattr(launcher.boundary, "ensure_trusted"), "承認の仕組みが残っている"


def test_request_is_not_inherited_by_subdirectories(tmp_path):
    """★親の要求で子を動かさない。要求はその場のものだけを見る。"""
    launcher = _launcher()
    outer = tmp_path / "repo"
    inner = outer / "pkg"
    inner.mkdir(parents=True)
    _request(outer, f'read = ["{tmp_path}"]\n')
    assert launcher.boundary.read_request(inner) is None


def test_request_paths_are_resolved(tmp_path):
    """``~`` と相対パスは展開してから境界へ渡す。"""
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, 'read = ["~/datasets", "sub/dir", "../other"]\n')
    extras = launcher.boundary.read_request(ws)["extras"]["read"]
    assert extras == [str(Path.home() / "datasets"), str(ws / "sub/dir"), str(tmp_path / "other")]


def test_unknown_keys_in_request_refuse_to_start(tmp_path):
    """知らない項目は黙って無視しない。"""
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, 'read = ["/mnt/d/alpha"]\nallow_all = true\n')
    with pytest.raises(SystemExit):
        launcher.boundary.read_request(ws)


def test_request_values_must_be_string_lists(tmp_path):
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, 'write = "/mnt/d/out"\n')
    with pytest.raises(SystemExit):
        launcher.boundary.read_request(ws)


@pytest.mark.parametrize("key", ["read", "write", "network_allow"])
@pytest.mark.parametrize("value", ["false", "0", '""', '["/mnt/d/x", 1]'])
def test_falsy_or_mixed_request_values_refuse_to_start(tmp_path, key, value):
    """★``false``・``0``・空文字を空の配列として通さないこと (文字列の配列だけを受ける)。"""
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, f"{key} = {value}\n")
    with pytest.raises(SystemExit):
        launcher.boundary.read_request(ws)


@pytest.mark.parametrize("body", ["", "read = []\nwrite = []\nnetwork_allow = []\n"])
def test_absent_or_empty_request_values_are_accepted(tmp_path, body):
    """未指定と空の配列は正しい宣言として通す (足す分が無ければ ``None``)。"""
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, body)
    assert launcher.boundary.read_request(ws) is None


def test_protected_paths_are_workspace_relative(tmp_path):
    """保護対象は起動ディレクトリと組み合わせる。"""
    launcher = _launcher()
    where = tmp_path / "gamma"
    where.mkdir()
    deny_write = launcher.boundary.build_boundary(_base_sandbox(tmp_path), where)["filesystem"][
        "denyWrite"
    ]
    assert str(where / ".opencode") in deny_write


def test_missing_protected_dir_is_created_before_launch(tmp_path):
    """★Fence の denyWrite は無いパスに効かない。無い ``.opencode`` は先に作って塞ぐ。

    親が無いもの (別のリポジトリの ``home/dot_config/agents`` など) は作らず、渡さない。
    """
    launcher = _launcher()
    ws = tmp_path / "ws"
    ws.mkdir()
    sandbox = _base_sandbox(tmp_path, protected=[".opencode", "home/dot_config/agents"])
    deny_write = launcher.boundary.build_boundary(sandbox, ws)["filesystem"]["denyWrite"]
    assert (ws / ".opencode").is_dir(), ".opencode を作っていない"
    assert str(ws / ".opencode") in deny_write
    assert not (ws / "home").exists(), "親の無い保護対象まで作った"
    assert str(ws / "home/dot_config/agents") not in deny_write


REPO_PROTECTED = [
    ".opencode",
    "home/dot_config/agents",
    "home/dot_local/share/ocs",
    "scripts/agents",
]


def _setup_git(*args: str) -> None:
    """テストの準備に使う git。実行者の ``GIT_*`` と git の設定から切り離して走らせる。

    ``HOME`` / ``XDG_CONFIG_HOME`` も空の一時領域へ向ける (既定の
    ``~/.config/git/ignore`` で ``add -A`` の対象が変わらないように)。
    """
    with tempfile.TemporaryDirectory(prefix="git-home-") as home:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        subprocess.run(
            ["git", *args], env=_isolated_git_env(env, home), check=True, capture_output=True
        )


def _dotfiles_repo(root: Path) -> Path:
    """保護対象の一部を持つリポジトリ (``scripts/agents`` は置かない)。"""
    for rel in ("home/dot_config/agents", "home/dot_local/share/ocs", "docs"):
        (root / rel).mkdir(parents=True)
    _setup_git("init", "-q", str(root))
    return root


def test_repo_protected_paths_are_found_from_a_subdirectory(tmp_path):
    """★下位ディレクトリで起動しても、リポジトリの根を基準にした保護対象を塞ぐ。

    起動ディレクトリの外にあるもの (``.opencode`` やこの場合の ``scripts/agents``) は
    元から書けないので、作らず、渡さない。
    """
    launcher = _launcher()
    repo = _dotfiles_repo(tmp_path.resolve() / "repo")
    ws = repo / "home"
    sandbox = _base_sandbox(tmp_path, protected=REPO_PROTECTED)
    deny_write = launcher.boundary.build_boundary(sandbox, ws)["filesystem"]["denyWrite"]
    assert str(repo / "home/dot_config/agents") in deny_write
    assert str(repo / "home/dot_local/share/ocs") in deny_write
    assert str(ws / ".opencode") in deny_write
    assert not (repo / ".opencode").exists(), "起動ディレクトリの外に保護対象を作った"
    assert not (repo / "scripts").exists(), "起動ディレクトリの外に保護対象を作った"
    outside = [p for p in deny_write if not Path(p).is_relative_to(ws)]
    assert all(Path(p).parent == repo / ".git" for p in outside), outside


def test_repo_protected_paths_follow_the_linked_worktree(tmp_path):
    """linked worktree では、その worktree の根を基準にする。"""
    launcher = _launcher()
    _common, wt = _worktree(tmp_path)
    (wt / "home/dot_config/agents").mkdir(parents=True)
    sandbox = _base_sandbox(tmp_path, protected=REPO_PROTECTED)
    ws = (wt / "home").resolve()
    deny_write = launcher.boundary.build_boundary(sandbox, ws)["filesystem"]["denyWrite"]
    assert str(ws / "dot_config/agents") in deny_write


def test_repo_protected_paths_inside_requested_write_are_blocked(tmp_path):
    """``.opencode/sandbox.toml`` でリポジトリの根を書けるようにしても、保護対象は塞ぐ。"""
    launcher = _launcher()
    repo = _dotfiles_repo(tmp_path.resolve() / "repo")
    ws = repo / "docs"
    _request(ws, f'write = ["{repo}"]\n')
    sandbox = _base_sandbox(tmp_path, protected=REPO_PROTECTED)
    request = launcher.boundary.read_request(ws)
    deny_write = launcher.boundary.build_boundary(sandbox, ws, request)["filesystem"]["denyWrite"]
    assert str(repo / "home/dot_config/agents") in deny_write
    assert str(repo / ".opencode") in deny_write


def test_repo_protected_paths_inside_a_symlinked_write_are_blocked(tmp_path):
    """書ける場所を symlink で足しても、実体で比べて中の保護対象を塞ぐ。"""
    launcher = _launcher()
    repo = _dotfiles_repo(tmp_path.resolve() / "repo")
    alias = tmp_path.resolve() / "alias"
    alias.symlink_to(repo)
    ws = repo / "docs"
    _request(ws, f'write = ["{alias}"]\n')
    sandbox = _base_sandbox(tmp_path, protected=REPO_PROTECTED)
    request = launcher.boundary.read_request(ws)
    deny_write = launcher.boundary.build_boundary(sandbox, ws, request)["filesystem"]["denyWrite"]
    assert str(repo / "home/dot_config/agents") in deny_write


def _symlinked_protected_repo(root: Path) -> Path:
    """保護対象 ``home/dot_local/share/ocs`` が、同じリポジトリの ``lib/ocs`` への symlink。"""
    repo = _dotfiles_repo(root)
    (repo / "home/dot_local/share/ocs").rmdir()
    (repo / "lib/ocs").mkdir(parents=True)
    (repo / "home/dot_local/share/ocs").symlink_to(repo / "lib/ocs")
    return repo


@pytest.mark.parametrize("where", ["", "lib"], ids=["根", "実体の親"])
def test_symlinked_protected_dir_is_blocked_at_its_real_path(tmp_path, where):
    """★保護対象が symlink なら、実体を塞ぐ (symlink 経由の書き込みも実体で止まる)。

    実体の親で起動すると、書いた形の保護対象は起動ディレクトリの外に見えるが、実体は中にある。
    """
    launcher = _launcher()
    repo = _symlinked_protected_repo(tmp_path.resolve() / "repo")
    ws = repo / where
    sandbox = _base_sandbox(tmp_path, protected=REPO_PROTECTED)
    deny_write = launcher.boundary.build_boundary(sandbox, ws)["filesystem"]["denyWrite"]
    assert str(repo / "lib/ocs") in deny_write


@pytest.mark.parametrize(
    "write",
    [
        "../scripts/agents/generate.py",
        "../scripts/agents",
        "../home/dot_local/share/ocs",
        "../lib/ocs/cli.py",
        "../home/dot_local/share/ocs/cli.py",
    ],
    ids=[
        "保護対象の中のファイル",
        "保護対象そのもの",
        "symlink の保護対象",
        "その実体の中",
        "symlink 経由でその中",
    ],
)
def test_requested_write_inside_a_protected_dir_is_refused(tmp_path, write):
    """★``write`` に保護対象の中を足す宣言は拒否する (塞ぐと書けず、塞がないと守れない)。

    保護対象を含む広い ``write`` は塞いで守れるので、狭い許可で守れない逆転を起こさない。
    """
    launcher = _launcher()
    repo = _symlinked_protected_repo(tmp_path.resolve() / "repo")
    (repo / "scripts/agents").mkdir(parents=True)
    (repo / "scripts/agents/generate.py").write_text("", encoding="utf-8")
    ws = repo / "docs"
    _request(ws, f'write = ["{write}"]\n')
    sandbox = _base_sandbox(tmp_path, protected=REPO_PROTECTED)
    request = launcher.boundary.read_request(ws)
    with pytest.raises(SystemExit):
        launcher.boundary.reject_protected_workspace(sandbox, ws, request)


def test_requested_write_outside_protected_dirs_is_allowed(tmp_path):
    launcher = _launcher()
    repo = _dotfiles_repo(tmp_path.resolve() / "repo")
    ws = repo / "docs"
    _request(ws, f'write = ["{repo}", "../home"]\n')
    sandbox = _base_sandbox(tmp_path, protected=REPO_PROTECTED)
    request = launcher.boundary.read_request(ws)
    launcher.boundary.reject_protected_workspace(sandbox, ws, request)


@pytest.mark.parametrize(
    "rel",
    ["home/dot_local/share/ocs", "home/dot_local/share/ocs/sub", ".opencode/plugins"],
    ids=["保護対象そのもの", "その中", "根の .opencode の中"],
)
def test_launch_inside_a_protected_dir_is_refused(tmp_path, rel):
    """★起動ディレクトリは塞げない。保護対象の中では起動しない。"""
    launcher = _launcher()
    repo = _dotfiles_repo(tmp_path.resolve() / "repo")
    ws = repo / rel
    ws.mkdir(parents=True, exist_ok=True)
    sandbox = _base_sandbox(tmp_path, protected=REPO_PROTECTED)
    with pytest.raises(SystemExit):
        launcher.boundary.reject_protected_workspace(sandbox, ws)


@pytest.mark.parametrize(
    "rel",
    ["lib/ocs", "home/dot_local/share/ocs", "lib/ocs/sub"],
    ids=["実体", "symlink 経由", "実体の中"],
)
def test_launch_inside_a_symlinked_protected_dir_is_refused(tmp_path, rel):
    """★保護対象が symlink でも、実体 (起動ディレクトリは実体パスになる) で起動を拒否する。"""
    launcher = _launcher()
    repo = _symlinked_protected_repo(tmp_path.resolve() / "repo")
    (repo / "lib/ocs/sub").mkdir()
    sandbox = _base_sandbox(tmp_path, protected=REPO_PROTECTED)
    with pytest.raises(SystemExit):
        launcher.boundary.reject_protected_workspace(sandbox, (repo / rel).resolve())


@pytest.mark.parametrize("rel", ["", "home", "docs"], ids=["根", "保護対象の親", "無関係"])
def test_launch_outside_protected_dirs_is_allowed(tmp_path, rel):
    launcher = _launcher()
    repo = _dotfiles_repo(tmp_path.resolve() / "repo")
    sandbox = _base_sandbox(tmp_path, protected=REPO_PROTECTED)
    launcher.boundary.reject_protected_workspace(sandbox, repo / rel if rel else repo)


def test_system_prompt_is_written(tmp_path):
    launcher = _launcher()
    sandbox = _sandbox(tmp_path)
    project = _project(tmp_path)
    launcher.config.write_isolated_config(sandbox, project)
    agents = Path(sandbox["config_dir"]) / "AGENTS.md"
    assert agents.is_file(), "AGENTS.md が書かれていない"
    assert agents.read_text(encoding="utf-8").strip(), "AGENTS.md が空"


@pytest.mark.parametrize("stage", ["空", "未指定"])
def test_emptied_managed_keys_leave_no_residue(tmp_path, stage):
    """★管理キーは空または未指定になったら取り除くこと。

    空のとき既存を残すと、生成側で外した plugin・policy・説明が隔離版に居座る。
    管理外のキーと利用者が選んだモデルは残す。
    どちらの段階も**値がある状態から**始める (続けて当てると 2 つ目は素通りする)。
    """
    launcher = _launcher()
    project = _project(tmp_path)
    full = _sandbox(
        tmp_path,
        policies=[{"statement": "x"}],
        plugins=["/opt/plugin.js"],
        system_prompt="境界の説明",
        agent={"bypass": {"permission": "allow"}},
        agents={"commit": {"description": "c"}},
        commands={"fleet": {"template": "t"}},
    )
    config_dir = Path(full["config_dir"])
    target = config_dir / "opencode.json"
    agents = config_dir / "AGENTS.md"

    launcher.config.write_isolated_config(full, project)
    config = json.loads(target.read_text(encoding="utf-8"))
    assert config["plugins"] == ["/opt/plugin.js"]
    assert config["experimental"]["policies"] == [{"statement": "x"}]
    assert config["agent"] == {"bypass": {"permission": "allow"}}
    assert agents.is_file()
    config["model"] = "github-copilot/claude-sonnet-5"
    config["username"] = "alice"
    config["experimental"]["other"] = True
    target.write_text(json.dumps(config), encoding="utf-8")

    managed = ("policies", "plugins", "system_prompt", "agent", "agents", "commands")
    if stage == "空":
        sandbox = {
            **full,
            "policies": [],
            "plugins": [],
            "system_prompt": "",
            "agent": {},
            "agents": {},
            "commands": {},
        }
    else:
        sandbox = {k: v for k, v in full.items() if k not in managed}
    launcher.config.write_isolated_config(sandbox, project)
    after = json.loads(target.read_text(encoding="utf-8"))
    assert "plugins" not in after, "plugins が残った"
    for key in ("agent", "agents", "commands"):
        assert key not in after, f"{key} が残った"
    assert after.get("experimental") == {"other": True}, (
        "policies が残ったか、管理外の experimental が消えた"
    )
    assert not agents.exists(), "AGENTS.md が残った"
    assert after["model"] == "github-copilot/claude-sonnet-5", "model が消えた"
    assert after["username"] == "alice", "宣言外のキーが消えた"
    assert after["permissions"] == full["permissions"]


def test_experimental_is_dropped_when_only_policies_were_in_it(tmp_path):
    """policies だけだった ``experimental`` は、空の入れ物を残さない。"""
    launcher = _launcher()
    project = _project(tmp_path)
    sandbox = _sandbox(tmp_path, policies=[{"statement": "x"}])
    launcher.config.write_isolated_config(sandbox, project)
    launcher.config.write_isolated_config({**sandbox, "policies": []}, project)
    target = Path(sandbox["config_dir"]) / "opencode.json"
    assert "experimental" not in json.loads(target.read_text(encoding="utf-8"))


def test_common_agents_and_commands_are_written(tmp_path):
    """★common.toml のエージェント・コマンドが隔離版の設定に入ること (CHG-0010)。"""
    launcher = _launcher()
    sandbox = _sandbox(tmp_path)
    project = _project(tmp_path)
    launcher.config.write_isolated_config(sandbox, project)
    config = json.loads((Path(sandbox["config_dir"]) / "opencode.json").read_text(encoding="utf-8"))
    # 全 allow は持たない (bypass の ask は plugin が allow にする)。子の起動は許可リスト
    assert "*" not in config["agent"]["bypass"]["permission"]
    task = config["agent"]["bypass"]["permission"]["task"]
    assert task["*"] == "deny"
    assert {name for name, effect in task.items() if effect == "allow"} == {
        "bypass-worker",
        "bypass-fleet-worker",
        "explore",
        "review",
        "commit",
    }
    assert "bypass-worker" in config["agent"]
    assert {"commit", "review", "fleet-worker", "bypass-fleet-worker", "explore", "plan"} <= set(
        config["agents"]
    )
    assert "fleet" in config["commands"]


def test_agents_outside_common_are_dropped(tmp_path):
    """★隔離版のエージェント・コマンドは common.toml の宣言で丸ごと差し替えること。

    隔離版の設定は境界の内から書けないので、残るのは外で足したものか、
    common.toml から外した古い定義だけ。後者が残ると、外したはずの
    全部 allow のエージェントが隔離版に居座る。
    """
    launcher = _launcher()
    sandbox = _sandbox(tmp_path)
    project = _project(tmp_path)
    launcher.config.write_isolated_config(sandbox, project)

    target = Path(sandbox["config_dir"]) / "opencode.json"
    config = json.loads(target.read_text(encoding="utf-8"))
    config["agent"]["stale"] = {"permission": "allow", "mode": "all"}
    config["agent"]["bypass"]["mode"] = "all"
    config["agents"]["stale"] = {"description": "x"}
    config["commands"]["stale"] = {"template": "x"}
    target.write_text(json.dumps(config), encoding="utf-8")

    launcher.config.write_isolated_config(sandbox, project)
    after = json.loads(target.read_text(encoding="utf-8"))
    assert after["agent"] == sandbox["agent"], "agent が宣言どおりに戻っていない"
    assert after["agents"] == sandbox["agents"], "agents が宣言どおりに戻っていない"
    assert after["commands"] == sandbox["commands"], "commands が宣言どおりに戻っていない"


def test_host_agents_are_not_carried_into_the_isolated_config(tmp_path, monkeypatch):
    """通常版の opencode.json で手で足したエージェント・コマンドは入らないこと。"""
    launcher = _launcher()
    host = tmp_path / "host.json"
    host.write_text(
        json.dumps(
            {
                "agent": {"handmade": {"permission": "allow"}},
                "agents": {"handmade": {"description": "x"}},
                "commands": {"handmade": {"template": "x"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher.config, "HOST_CONFIG", host)
    sandbox = _sandbox(tmp_path)
    launcher.config.write_isolated_config(sandbox, _project(tmp_path))
    config = json.loads((Path(sandbox["config_dir"]) / "opencode.json").read_text(encoding="utf-8"))
    for key in ("agent", "agents", "commands"):
        assert "handmade" not in config[key], f"通常版の {key} が入った"


def test_provider_settings_keep_other_keys(tmp_path):
    """接続設定は宣言したプロバイダの settings をキー単位で差し替え、他は残すこと。

    settings の中の宣言外のキー (利用者が足した ``endpoint`` など) も残す。
    通常版の ``merge_opencode_providers`` と同じ方針。
    """
    launcher = _launcher()
    project = _project(tmp_path)
    declared = {"amazon-bedrock": {"settings": {"profile": "default", "region": "us-east-1"}}}
    sandbox = _sandbox(tmp_path, providers=declared)
    target = Path(sandbox["config_dir"]) / "opencode.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps(
            {
                "providers": {
                    "amazon-bedrock": {
                        "baseURL": "https://x",
                        "settings": {"region": "old", "endpoint": "https://e"},
                    },
                    "custom": {"baseURL": "https://y"},
                }
            }
        ),
        encoding="utf-8",
    )
    launcher.config.write_isolated_config(sandbox, project)
    after = json.loads(target.read_text(encoding="utf-8"))["providers"]
    assert after["amazon-bedrock"]["settings"] == {
        "profile": "default",
        "region": "us-east-1",
        "endpoint": "https://e",
    }, "宣言したキーが上書きされていないか、宣言外の settings のキーが消えた"
    assert after["amazon-bedrock"]["baseURL"] == "https://x"
    assert after["custom"] == {"baseURL": "https://y"}

    launcher.config.write_isolated_config({**sandbox, "providers": {}}, project)
    assert json.loads(target.read_text(encoding="utf-8"))["providers"] == after


# --- git worktree ------------------------------------------------------------


def _worktree(tmp_path: Path) -> tuple[Path, Path]:
    """linked worktree を 1 つ作り、(共有 .git, worktree) を返す。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: _setup_git("-C", str(repo), *a)  # noqa: E731
    _setup_git("init", "-q", str(repo))
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (repo / "a.txt").write_text("hi", encoding="utf-8")
    run("add", "-A")
    run("commit", "-qm", "init")
    run("worktree", "add", "-q", str(tmp_path / "wt"), "-b", "feat")
    return repo / ".git", tmp_path / "wt"


def test_worktree_shares_the_main_git_dir(tmp_path):
    """★linked worktree の .git は起動ディレクトリの外を指す。

    足さないと `git status` すら `not a git repository` で落ちる (実測)。
    """
    launcher = _launcher()
    common, wt = _worktree(tmp_path)
    filesystem = launcher.boundary.build_boundary(_base_sandbox(tmp_path), wt)["filesystem"]
    assert str(common) in filesystem["allowWrite"], "共有 .git が書けない"


def test_worktree_git_hooks_and_config_stay_protected(tmp_path):
    """★共有 .git を開けても hooks と config は閉じたままにする。

    ここへ書けると **ホストで実行されるコード** を仕込める。
    """
    launcher = _launcher()
    common, wt = _worktree(tmp_path)
    deny_write = launcher.boundary.build_boundary(_base_sandbox(tmp_path), wt)["filesystem"][
        "denyWrite"
    ]
    assert str(common / "hooks") in deny_write
    assert str(common / "config") in deny_write


def test_plain_repository_adds_nothing(tmp_path):
    """通常のリポジトリでは足すものが無い (起動ディレクトリの中にある)。"""
    launcher = _launcher()
    repo = tmp_path / "plain"
    repo.mkdir()
    _setup_git("init", "-q", str(repo))
    assert launcher.boundary.git_common_dir(repo) is None


def test_git_common_dir_ignores_git_env(tmp_path, monkeypatch):
    """★GIT_DIR などを利用者の環境から通すと、別のリポジトリが allowWrite に入る。"""
    launcher = _launcher()
    other = tmp_path / "other"
    _setup_git("init", "-q", str(other))
    repo = tmp_path / "plain"
    _setup_git("init", "-q", str(repo))
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    assert launcher.boundary.git_common_dir(repo) is None


# --- 境界の定義と残骸 ---------------------------------------------------------


def test_boundary_file_lives_outside_the_workspace():
    """★境界の定義と Fence の TMPDIR をワークスペース内に置かないこと。

    内側から書ける場所だと、Fence が読む前に書き換えられる。
    """
    launcher = _launcher()
    for path in (launcher.cli.BOUNDARIES, launcher.cli.FENCE_TMP):
        assert ".local/state/opencode-sandbox" in str(path), f"状態領域の外: {path}"
        assert "/.tmp" not in str(path), "TMPDIR 配下に置いている"


def test_prune_drops_only_stale_files(tmp_path, monkeypatch):
    """★残骸だけ捨て、稼働中のものは残すこと。

    execve で finally が走らないため自分では消せない。次の起動が前回の分を捨てる。
    Fence は起動ごとに seccomp のフィルタを TMPDIR に残す。
    """
    launcher = _launcher()
    boundaries = tmp_path / "boundaries"
    seccomp = tmp_path / "tmp" / "fence-seccomp"
    boundaries.mkdir()
    seccomp.mkdir(parents=True)
    monkeypatch.setattr(launcher.cli, "BOUNDARIES", boundaries)
    monkeypatch.setattr(launcher.cli, "FENCE_TMP", tmp_path / "tmp")
    monkeypatch.setattr(launcher.cli, "BOUNDARY_MAX_AGE_SECONDS", 3600)
    monkeypatch.setattr(launcher.cli, "SECCOMP_MAX_AGE_SECONDS", 60)

    stale = boundaries / "opencode-boundary-old.json"
    fresh = boundaries / "opencode-boundary-new.json"
    other = boundaries / "checked.json"
    old_bpf = seccomp / "fence-seccomp-1.bpf"
    new_bpf = seccomp / "fence-seccomp-2.bpf"
    for p in (stale, fresh, other, old_bpf, new_bpf):
        p.write_text("{}", encoding="utf-8")
    os.utime(stale, (0, time.time() - 7200))
    os.utime(old_bpf, (0, time.time() - 120))

    launcher.cli.prune_leftovers()

    assert not stale.exists(), "古い境界の定義が残っている"
    assert not old_bpf.exists(), "古い seccomp のフィルタが残っている"
    assert fresh.exists() and new_bpf.exists(), "稼働中のものを消した"
    assert other.exists(), "対象外のファイルを消した"


# --- 通常版から引き継ぐ設定 --------------------------------------------------


def test_ui_keys_are_inherited_but_never_overwritten(tmp_path, monkeypatch):
    """見た目・操作感は引き継ぎ、隔離版で選んだ値は残す。"""
    launcher = _launcher()
    host = tmp_path / "host.json"
    host.write_text(json.dumps({"theme": "dark", "model": "p/host"}), encoding="utf-8")
    monkeypatch.setattr(launcher.config, "HOST_CONFIG", host)
    got = launcher.config.inherit_ui({"model": "p/chosen"})
    assert got["theme"] == "dark", "テーマが引き継がれていない"
    assert got["model"] == "p/chosen", "隔離版の選択が上書きされた"


def test_security_keys_are_never_inherited(tmp_path, monkeypatch):
    """★緩和に関わるキーを通常版から持ち込まないこと。

    持ち込めると、境界の外の設定で境界の内側の permission を決められる。
    """
    launcher = _launcher()
    host = tmp_path / "host.json"
    host.write_text(
        json.dumps(
            {
                "permissions": [],
                "plugins": ["evil"],
                "mcp": {"x": {}},
                "agent": {"a": {}},
                "agents": {"a": {}},
                "commands": {"a": {}},
                "providers": {"a": {}},
                "experimental": {"policies": []},
                "tools": {"bash": True},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher.config, "HOST_CONFIG", host)
    got = launcher.config.inherit_ui({})
    assert got == {}, f"引き継いではいけないキーが入った: {sorted(got)}"


def test_skill_roots_are_readable_inside_the_boundary(tmp_path):
    """★skill 置き場と git の利用者設定が read に載っていること。"""
    read = _generated(tmp_path)["base"]["read"]
    joined = " ".join(read)
    for needle in (".claude/skills", ".agents/skills", ".gitconfig", ".config/git"):
        assert needle in joined, f"{needle} が読めない"


# --- 起動前の退避 ------------------------------------------------------------


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _setup_git("init", "-q", str(repo))
    for key, value in (("user.email", "t@t"), ("user.name", "t")):
        _setup_git("-C", str(repo), "config", key, value)
    (repo / "a.txt").write_text("base\n", encoding="utf-8")
    _setup_git("-C", str(repo), "add", "-A")
    _setup_git("-C", str(repo), "commit", "-qm", "init")
    return repo


def _backups(launcher: SimpleNamespace) -> list[Path]:
    return sorted(launcher.backup.BACKUPS.rglob("*.tgz"))


def test_backup_never_touches_the_worktree(tmp_path, monkeypatch):
    """★`git stash` とは別物。作業ツリーを巻き戻さないこと。

    再開のたびに変更が消えるなら、退避ではなく破壊になる。
    """
    launcher = _launcher()
    monkeypatch.setattr(launcher.backup, "BACKUPS", tmp_path / "store")
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("changed\n", encoding="utf-8")
    (repo / "b.txt").write_text("untracked\n", encoding="utf-8")

    launcher.backup.backup_worktree(repo, False)

    assert (repo / "a.txt").read_text(encoding="utf-8") == "changed\n", "変更が巻き戻った"
    assert (repo / "b.txt").is_file(), "未追跡ファイルが消えた"


def test_backup_is_skipped_when_nothing_is_uncommitted(tmp_path, monkeypatch):
    """未コミットの変更が無ければ退避しない。"""
    launcher = _launcher()
    monkeypatch.setattr(launcher.backup, "BACKUPS", tmp_path / "store")
    launcher.backup.backup_worktree(_repo(tmp_path), False)
    assert _backups(launcher) == []


def test_identical_content_is_not_backed_up_twice(tmp_path, monkeypatch):
    """★中断と再開を繰り返しても溜まらないこと。

    同じ内容なら同じ tree SHA になるので作り直さない。
    """
    launcher = _launcher()
    monkeypatch.setattr(launcher.backup, "BACKUPS", tmp_path / "store")
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("changed\n", encoding="utf-8")

    launcher.backup.backup_worktree(repo, False)
    launcher.backup.backup_worktree(repo, False)
    assert len(_backups(launcher)) == 1, "同じ内容で 2 つ作られた"

    (repo / "a.txt").write_text("changed again\n", encoding="utf-8")
    launcher.backup.backup_worktree(repo, False)
    assert len(_backups(launcher)) == 2, "内容が変わったのに退避されていない"


def _archive_outputs(launcher: SimpleNamespace, monkeypatch, on_archive=None) -> list[Path]:
    """``git archive -o`` の書き込み先を記録する。``on_archive`` は実行の前に呼ぶ。"""
    real_git = launcher.backup._git
    outputs: list[Path] = []

    def spy(workspace, *args, **kwargs):
        if args and args[0] == "archive":
            outputs.append(Path(args[args.index("-o") + 1]))
            if on_archive is not None:
                on_archive(outputs[-1])
        return real_git(workspace, *args, **kwargs)

    monkeypatch.setattr(launcher.backup, "_git", spy)
    return outputs


def test_backup_is_written_under_a_temporary_name(tmp_path, monkeypatch):
    """★git archive は確定名 (*.tgz) ではなく同じ置き場の一時名へ書くこと。

    確定名へ直接書くと、途中で落ちた不完全なファイルが退避に見える。
    """
    launcher = _launcher()
    monkeypatch.setattr(launcher.backup, "BACKUPS", tmp_path / "store")
    outputs = _archive_outputs(launcher, monkeypatch)
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("changed\n", encoding="utf-8")

    launcher.backup.backup_worktree(repo, False)

    (written,) = outputs
    (final,) = _backups(launcher)
    assert not written.match("*.tgz"), f"確定名へ直接書いている: {written}"
    assert written.parent == final.parent, "一時名が別の置き場にある (置き換えが原子的でない)"
    assert not written.exists(), "一時ファイルが残っている"


def test_interrupted_backup_is_not_taken_as_done(tmp_path, monkeypatch):
    """★退避の途中で強制終了した残骸を「退避済み」と見なさないこと。

    確定名に残った不完全なファイルが次回の重複判定に当たり、退避しないまま
    起動していた。
    """
    import tarfile

    class Killed(BaseException):
        pass

    def kill(output: Path) -> None:
        raise Killed

    launcher = _launcher()
    monkeypatch.setattr(launcher.backup, "BACKUPS", tmp_path / "store")
    real_git = launcher.backup._git
    outputs = _archive_outputs(launcher, monkeypatch, kill)
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("precious\n", encoding="utf-8")

    with pytest.raises(Killed):
        launcher.backup.backup_worktree(repo, False)
    # SIGKILL では後始末が走らないので、書きかけの残骸を置き直す
    (leftover,) = outputs
    leftover.write_bytes(b"\x1f\x8b\x08\x00truncated")
    monkeypatch.setattr(launcher.backup, "_git", real_git)

    launcher.backup.backup_worktree(repo, False)

    (archive_path,) = _backups(launcher)
    with tarfile.open(archive_path) as archive:
        member = archive.extractfile("a.txt")
        assert member is not None and member.read() == b"precious\n", "退避が作られていない"


@pytest.mark.parametrize("damage", ["half", "empty", "no_trailer"])
def test_truncated_backup_of_the_same_tree_is_redone(tmp_path, monkeypatch, damage):
    """確定名で残った不完全な退避 (修正前の版の残骸・空のファイル) は、作り直すこと。"""
    import tarfile

    launcher = _launcher()
    monkeypatch.setattr(launcher.backup, "BACKUPS", tmp_path / "store")
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("precious\n", encoding="utf-8")
    launcher.backup.backup_worktree(repo, False)
    (first,) = _backups(launcher)
    data = first.read_bytes()
    damaged = {"half": data[: len(data) // 2], "empty": b"", "no_trailer": data[:-8]}
    first.write_bytes(damaged[damage])

    launcher.backup.backup_worktree(repo, False)

    (archive_path,) = _backups(launcher)
    with tarfile.open(archive_path) as archive:
        member = archive.extractfile("a.txt")
        assert member is not None and member.read() == b"precious\n", "壊れた退避のまま"
    with gzip.open(archive_path, "rb") as stream:
        stream.read()  # 末尾 (CRC と長さ) まで読めること


def test_stale_partial_backups_are_swept_but_fresh_ones_are_kept(tmp_path, monkeypatch):
    """書きかけの残骸は古いものだけ片付けること。新しいものは同時起動の書き込み途中かもしれない。"""
    launcher = _launcher()
    store = tmp_path / "store"
    monkeypatch.setattr(launcher.backup, "BACKUPS", store)
    other = store / "other-000000000000"
    other.mkdir(parents=True)
    stale = other / ".20200101T000000+0000-deadbeefcafe.abc.partial"
    fresh = other / ".29990101T000000+0000-deadbeefcafe.def.partial"
    for path in (stale, fresh):
        path.write_bytes(b"\x1f\x8b")
    old = time.time() - launcher.backup.BACKUP_PARTIAL_STALE_SECONDS - 60
    os.utime(stale, (old, old))

    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("changed\n", encoding="utf-8")
    launcher.backup.backup_worktree(repo, False)

    assert not stale.exists(), "古い書きかけが残っている"
    assert fresh.exists(), "書き込み途中かもしれないものを消した"


def test_backup_excludes_ignored_files(tmp_path, monkeypatch):
    """.gitignore が効くこと (隔離用 DB などを巻き込まない)。"""
    import tarfile

    launcher = _launcher()
    monkeypatch.setattr(launcher.backup, "BACKUPS", tmp_path / "store")
    repo = _repo(tmp_path)
    (repo / ".gitignore").write_text("heavy/\n", encoding="utf-8")
    (repo / "heavy").mkdir()
    (repo / "heavy" / "db.bin").write_text("x" * 1000, encoding="utf-8")

    launcher.backup.backup_worktree(repo, False)
    with tarfile.open(_backups(launcher)[0]) as archive:
        names = archive.getnames()
    assert "heavy/db.bin" not in names, f"無視されるはずのものが入った: {names}"
    assert ".gitignore" in names


def test_backup_is_restorable(tmp_path, monkeypatch):
    """★退避から中身が戻せること。ファイルが在ることを合格にしない。"""
    import tarfile

    launcher = _launcher()
    monkeypatch.setattr(launcher.backup, "BACKUPS", tmp_path / "store")
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("precious\n", encoding="utf-8")

    launcher.backup.backup_worktree(repo, False)
    out = tmp_path / "restored"
    with tarfile.open(_backups(launcher)[0]) as archive:
        archive.extractall(out, filter="data")
    assert (out / "a.txt").read_text(encoding="utf-8") == "precious\n"


def test_old_backups_are_pruned(tmp_path, monkeypatch):
    """世代数で頭を押さえること。"""
    launcher = _launcher()
    monkeypatch.setattr(launcher.backup, "BACKUPS", tmp_path / "store")
    monkeypatch.setattr(launcher.backup, "BACKUP_KEEP", 3)
    repo = _repo(tmp_path)
    for i in range(6):
        (repo / "a.txt").write_text(f"rev {i}\n", encoding="utf-8")
        launcher.backup.backup_worktree(repo, False)
    assert len(_backups(launcher)) == 3


def _backup_once(launcher: SimpleNamespace, repo: Path, content: str, mtime: float) -> Path:
    """1 回退避し、作られた退避の mtime を揃えて返す (同じ tick で並びが揺れないように)。"""
    before = set(_backups(launcher))
    (repo / "a.txt").write_text(content, encoding="utf-8")
    launcher.backup.backup_worktree(repo, False)
    (created,) = set(_backups(launcher)) - before
    os.utime(created, (mtime, mtime))
    return created


def test_prune_by_size_keeps_the_newest_and_drops_the_oldest(tmp_path, monkeypatch):
    """合計サイズで間引くときは、新しいものを残し古いものから消すこと。"""
    launcher = _launcher()
    monkeypatch.setattr(launcher.backup, "BACKUPS", tmp_path / "store")
    repo = _repo(tmp_path)
    now = time.time()
    first = _backup_once(launcher, repo, "rev 0\n", now - 100)
    monkeypatch.setattr(launcher.backup, "BACKUP_MAX_BYTES", first.stat().st_size * 5 // 2)

    made = [first] + [
        _backup_once(launcher, repo, f"rev {i}\n", now - 100 + i) for i in range(1, 5)
    ]

    assert _backups(launcher) == sorted(made[-2:]), "新しい 2 件だけが残るはず"


@pytest.mark.parametrize("limit", ["BACKUP_MAX_BYTES", "BACKUP_TOTAL_MAX_BYTES"])
def test_oversized_latest_backup_refuses_launch_and_keeps_older(
    tmp_path, monkeypatch, capsys, limit
):
    """★今回の退避だけで上限を超えるなら起動を断り、既存の世代は消さないこと。

    間引きが今回の退避ごと既存の世代まで消し、「退避した」と表示して起動していた。
    """
    launcher = _launcher()
    store = tmp_path / "store"
    monkeypatch.setattr(launcher.backup, "BACKUPS", store)
    repo = _repo(tmp_path)
    now = time.time()
    older = [_backup_once(launcher, repo, f"rev {i}\n", now - 10 + i) for i in range(2)]
    monkeypatch.setattr(launcher.backup, limit, 4096)
    (repo / "noise.bin").write_bytes(os.urandom(16384))  # 圧縮しても上限を超える
    capsys.readouterr()

    with pytest.raises(SystemExit):
        launcher.backup.backup_worktree(repo, False)
    assert _backups(launcher) == sorted(older), "既存の世代が消えたか、超過分が残った"
    left = sorted(p for p in store.rglob("*") if p.is_file())
    assert left == sorted(older), f"書きかけが残っている: {left}"
    err = capsys.readouterr().err
    assert "退避が上限を超える" in err, "間引く前に断っていない"
    assert "作業ツリーを退避した" not in err


def test_launch_is_refused_when_pruning_drops_the_latest_backup(tmp_path, monkeypatch, capsys):
    """★間引きが今回の退避を消したら、「退避した」と表示せず起動を断ること。"""
    launcher = _launcher()
    monkeypatch.setattr(launcher.backup, "BACKUPS", tmp_path / "store")

    def overzealous(directory: Path, current: Path) -> None:
        current.unlink()

    monkeypatch.setattr(launcher.backup, "prune_backups", overzealous)
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("changed\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        launcher.backup.backup_worktree(repo, False)
    assert "作業ツリーを退避した" not in capsys.readouterr().err


def test_prune_does_not_count_dropped_files(tmp_path, monkeypatch):
    """間引きの容量と世代数は、残したものだけで数えること。

    消した分まで数えると、大きい 1 件より古いものが全て巻き添えで消える。
    """
    launcher = _launcher()
    now = time.time()
    files = {}
    for age, (name, size) in enumerate(
        (("newest", 100), ("big", 300), ("middle", 100), ("oldest", 100))
    ):
        path = tmp_path / f"{name}.tgz"
        path.write_bytes(b"x" * size)
        os.utime(path, (now - age, now - age))
        files[name] = path

    launcher.backup._prune(list(files.values()), 2, 250)

    assert sorted(p.stem for p in tmp_path.glob("*.tgz")) == ["middle", "newest"]


def test_latest_backup_survives_newer_backups_of_other_projects(tmp_path, monkeypatch):
    """★全体の上限で間引くとき、今回の退避を残すこと。

    並行して起動した別プロジェクトの退避の方が新しくても、今回の分を消して
    「退避した」と表示してはいけない。
    """
    launcher = _launcher()
    store = tmp_path / "store"
    monkeypatch.setattr(launcher.backup, "BACKUPS", store)
    other = store / "other-000000000000"
    other.mkdir(parents=True)
    newer = other / "29990101T000000+0000-deadbeefcafe.tgz"
    newer.write_bytes(b"x" * 1024)
    future = time.time() + 3600
    os.utime(newer, (future, future))
    monkeypatch.setattr(launcher.backup, "BACKUP_TOTAL_MAX_BYTES", 1024)

    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("mine\n", encoding="utf-8")
    launcher.backup.backup_worktree(repo, False)

    mine = [p for p in _backups(launcher) if p.parent.name != other.name]
    assert len(mine) == 1, "今回の退避が消えた"
    assert not newer.exists(), "全体の上限を超えたまま"


def test_oversized_worktree_is_measured_before_hashing(tmp_path, monkeypatch):
    """★大きすぎる作業ツリーは、**ハッシュする前に**断ること。

    作ってから間引くと、巨大なリポジトリで .git を肥大させたうえに
    時間を使う（実測で追跡対象だけ 84 GB のリポジトリがあった）。
    """
    launcher = _launcher()
    monkeypatch.setattr(launcher.backup, "BACKUPS", tmp_path / "store")
    monkeypatch.setattr(launcher.backup, "BACKUP_MAX_SOURCE_BYTES", 1024)
    repo = _repo(tmp_path)
    (repo / "big.bin").write_text("x" * 4096, encoding="utf-8")

    before = _git_object_count(repo)
    with pytest.raises(SystemExit):
        launcher.backup.backup_worktree(repo, False)
    assert _backups(launcher) == [], "断ったのに退避が残っている"
    assert _git_object_count(repo) == before, "断る前に .git へ書き込んでいる"


def _git_object_count(repo: Path) -> int:
    done = subprocess.run(
        ["git", "-C", str(repo), "count-objects", "-v"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    for line in done.stdout.splitlines():
        if line.startswith("count:"):
            return int(line.split()[1])
    return 0


def test_total_size_is_capped_across_projects(tmp_path, monkeypatch):
    """★起動ディレクトリごとの上限だけでは全体が青天井になる。

    プロジェクトが増えても合計で頭を押さえること。
    """
    launcher = _launcher()
    store = tmp_path / "store"
    monkeypatch.setattr(launcher.backup, "BACKUPS", store)
    now = time.time()
    made = []
    for i, name in enumerate(("one", "two", "three")):
        repo = _repo(tmp_path / name)
        made.append(_backup_once(launcher, repo, f"{name}\n", now - 10 + i))
        if i == 0:
            # 1 件は収まり 2 件は収まらない大きさ
            cap = made[0].stat().st_size * 3 // 2
            monkeypatch.setattr(launcher.backup, "BACKUP_TOTAL_MAX_BYTES", cap)
    assert _backups(launcher) == [made[-1]], "全体の上限が効いていない"


def test_expired_backups_are_dropped(tmp_path, monkeypatch):
    """触らなくなったプロジェクトの分を期限で捨てること。"""
    launcher = _launcher()
    store = tmp_path / "store"
    monkeypatch.setattr(launcher.backup, "BACKUPS", store)
    stale = store / "abandoned-000000000000"
    stale.mkdir(parents=True)
    old = stale / "20200101T000000+0000-deadbeefcafe.tgz"
    old.write_bytes(b"old")
    ancient = time.time() - (launcher.backup.BACKUP_MAX_AGE_DAYS + 1) * 86400
    os.utime(old, (ancient, ancient))

    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("fresh\n", encoding="utf-8")
    launcher.backup.backup_worktree(repo, False)

    assert not old.exists(), "期限切れの退避が残っている"
    assert not stale.exists(), "空になった置き場が残っている"


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root は読み取り専用ディレクトリにも書ける"
)
def test_launch_is_refused_when_the_backup_fails(tmp_path, monkeypatch):
    """★退避できなければ**起動しない**。

    「退避したつもり」で作業を始めるのが一番危ない。
    """
    launcher = _launcher()
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o500)
    monkeypatch.setattr(launcher.backup, "BACKUPS", blocked)
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("changed\n", encoding="utf-8")
    try:
        with pytest.raises(SystemExit):
            launcher.backup.backup_worktree(repo, False)
    finally:
        blocked.chmod(0o700)


def test_backup_location_is_outside_the_workspace(tmp_path, monkeypatch):
    """★退避先が境界の内側にあってはいけない。

    内側から消せるなら復旧元にならない。
    """
    launcher = _launcher()
    repo = _repo(tmp_path)
    assert repo not in launcher.backup.BACKUPS.parents, "退避先がワークスペースの中にある"
    assert str(launcher.backup.BACKUPS).startswith(str(Path.home() / ".local/state"))


def test_backup_is_scoped_to_the_launch_directory(tmp_path, monkeypatch):
    """★git は親を遡る。サブディレクトリで起動しても親全体を掴まないこと。

    境界が書き込みを許すのは起動ディレクトリ以下なので、退避も揃える。
    """
    import tarfile

    launcher = _launcher()
    monkeypatch.setattr(launcher.backup, "BACKUPS", tmp_path / "store")
    repo = _repo(tmp_path)
    pkg = repo / "pkg"
    pkg.mkdir()
    (pkg / "inner.txt").write_text("work\n", encoding="utf-8")

    launcher.backup.backup_worktree(pkg, False)

    with tarfile.open(_backups(launcher)[0]) as archive:
        names = archive.getnames()
    assert "inner.txt" in names, f"起動ディレクトリの中身が入っていない: {names}"
    assert "a.txt" not in names, f"親リポジトリまで退避した: {names}"


def test_untracked_only_directory_does_not_block_launch(tmp_path, monkeypatch):
    """退避するものが無くても起動を止めないこと。

    Git リポジトリでない場所や、中身が全て .gitignore の場所が当たる。
    """
    launcher = _launcher()
    monkeypatch.setattr(launcher.backup, "BACKUPS", tmp_path / "store")
    repo = _repo(tmp_path)
    (repo / ".gitignore").write_text("skip/\n", encoding="utf-8")
    _setup_git("-C", str(repo), "add", "-A")
    _setup_git("-C", str(repo), "commit", "-qm", "ignore")
    skipped = repo / "skip"
    skipped.mkdir()
    (skipped / "junk.txt").write_text("junk\n", encoding="utf-8")

    launcher.backup.backup_worktree(skipped, False)  # 例外を出さないこと
    assert _backups(launcher) == []


def _extract(launcher: SimpleNamespace, out: Path) -> Path:
    import tarfile

    (archive_path,) = _backups(launcher)
    with tarfile.open(archive_path) as archive:
        archive.extractall(out, filter="data")
    return out


def test_backup_matches_the_worktree(tmp_path, monkeypatch):
    """退避は ``git add -A`` と同じ中身になること (削除・実行権・symlink)。

    ★symlink は辿らない。辿った先の中身をワークスペースの .git へ取り込むと、
      境界の内側から読める。
    """
    launcher = _launcher()
    monkeypatch.setattr(launcher.backup, "BACKUPS", tmp_path / "store")
    repo = _repo(tmp_path)
    secret = tmp_path / "outside"
    secret.mkdir()
    (secret / "f.txt").write_text("secret\n", encoding="utf-8")
    (repo / "d").mkdir()
    (repo / "d" / "f.txt").write_text("tracked\n", encoding="utf-8")
    (repo / "gone.txt").write_text("gone\n", encoding="utf-8")
    (repo / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    for args in (("add", "-A"), ("commit", "-qm", "more")):
        _setup_git("-C", str(repo), *args)

    (repo / "gone.txt").unlink()
    (repo / "run.sh").chmod(0o755)
    (repo / "d" / "f.txt").unlink()
    (repo / "d").rmdir()
    (repo / "d").symlink_to(secret)
    (repo / "link").symlink_to(secret / "f.txt")
    (repo / "new dir").mkdir()
    (repo / "new dir" / "n.txt").write_text("new\n", encoding="utf-8")

    launcher.backup.backup_worktree(repo, False)

    import tarfile

    (archive_path,) = _backups(launcher)
    with tarfile.open(archive_path) as archive:
        members = {m.name: m for m in archive.getmembers() if not m.isdir()}
        new = archive.extractfile(members["new dir/n.txt"]).read()
    assert sorted(members) == ["a.txt", "d", "link", "new dir/n.txt", "run.sh"], members
    assert members["d"].issym() and members["d"].linkname == str(secret)
    assert members["link"].issym() and members["link"].linkname == str(secret / "f.txt")
    assert new == b"new\n"
    assert members["run.sh"].mode & 0o111, "実行権が落ちた"
    assert not members["a.txt"].mode & 0o111
    blobs = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "--batch-all-objects", "--batch"],
        check=True,
        capture_output=True,
    ).stdout
    assert b"secret\n" not in blobs, "symlink の先を .git へ取り込んだ"


def test_backup_works_before_the_first_commit(tmp_path, monkeypatch):
    """コミットが 1 つも無いリポジトリでも退避できること (一時 index は空で始まる)。"""
    launcher = _launcher()
    monkeypatch.setattr(launcher.backup, "BACKUPS", tmp_path / "store")
    repo = tmp_path / "fresh"
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    (repo / "a.txt").write_text("first\n", encoding="utf-8")

    launcher.backup.backup_worktree(repo, False)

    out = _extract(launcher, tmp_path / "restored")
    assert (out / "a.txt").read_text(encoding="utf-8") == "first\n"


@pytest.mark.raw_git_env
def test_backup_git_does_not_inherit_git_env(monkeypatch):
    """★利用者の環境の GIT_DIR などは、退避の対象のリポジトリを差し替える。"""
    launcher = _launcher()
    for key, value in {
        "GIT_DIR": "./elsewhere",
        "GIT_WORK_TREE": "./elsewhere",
        "GIT_INDEX_FILE": "./index",
    }.items():
        monkeypatch.setenv(key, value)
    assert not [k for k in launcher.backup.git_env() if k.startswith("GIT_")]
    index = Path("/tmp/ocs-index")
    assert launcher.backup.git_env(index) == {
        **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        "GIT_INDEX_FILE": str(index),
    }


# --- 境界チェック -------------------------------------------------------------

CHECK_SCRIPT = ROOT / "home" / "dot_local" / "bin" / "executable_ocs-boundary-check"


def _check_project(workspace: Path, protected: list[str]) -> dict:
    return {
        "workspace": str(workspace),
        "data_dir": str(workspace / "data"),
        "config": {
            "network": {"allowedDomains": ["allowed.test"]},
            "filesystem": {"denyWrite": protected},
        },
    }


def _run_check_script(
    tmp_path: Path, launcher: SimpleNamespace, protected: list[str], hidden: dict
) -> subprocess.CompletedProcess:
    """検査スクリプトを境界なしで走らせる。環境はランチャーが組んだものを使う。

    curl は偽物に差し替え、許可済みドメインだけ通る状況を作る。
    """
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir(exist_ok=True)
    curl = fakebin / "curl"
    curl.write_text(
        '#!/bin/sh\ncase "$*" in *allowed.test*) exit 0 ;; esac\nexit 7\n', encoding="utf-8"
    )
    curl.chmod(0o755)
    base = {"PATH": f"{fakebin}:{os.environ.get('PATH', '/usr/bin:/bin')}"}
    env = launcher.check.check_environment(_check_project(ws, protected), base, hidden)
    env["BOUNDARY_CURL"] = str(curl)
    return subprocess.run(
        ["/bin/sh", str(CHECK_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )


def test_protected_paths_with_spaces_and_globs_reach_the_check_intact(tmp_path):
    """★空白や glob 文字を含む保護対象を、分割も展開もせずに検査すること。

    境界なしで走らせるので、全て「書けてしまう」が正しい結果になる。
    """
    launcher = _launcher()
    ws = tmp_path / "ws"
    spaced_dir = ws / "dir with space"
    spaced_dir.mkdir(parents=True)
    spaced_file = ws / "file name.txt"
    spaced_file.write_text("keep\n", encoding="utf-8")
    (ws / "globX").write_text("", encoding="utf-8")
    glob = ws / "glob*"

    done = _run_check_script(
        tmp_path,
        launcher,
        [str(spaced_dir), str(spaced_file), str(glob)],
        {"present": [], "absent": []},
    )

    assert f"保護対象へ書けてしまう: {spaced_dir}\n" in done.stdout, done.stdout
    assert f"保護対象へ書けてしまう: {spaced_file}\n" in done.stdout, done.stdout
    assert f"保護対象を作れてしまう: {glob}\n" in done.stdout, done.stdout
    assert "globX" not in done.stdout, f"glob が展開された: {done.stdout}"
    assert spaced_file.read_text(encoding="utf-8") == "keep\n", "保護対象の中身を壊した"
    assert not glob.exists(), "検査で作ったものを片付けていない"
    assert done.returncode == 1


def test_hidden_paths_with_spaces_reach_the_check_intact(tmp_path):
    """★読めてはいけない対象も、空白で割らずに検査すること。"""
    launcher = _launcher()
    visible = tmp_path / "secret dir"
    visible.mkdir()
    (visible / "id").write_text("x", encoding="utf-8")
    gone = tmp_path / "gone dir"
    done = _run_check_script(
        tmp_path, launcher, [], {"present": [str(visible)], "absent": [str(gone)]}
    )
    assert f"★NG  {visible} の中が見えている\n" in done.stdout, done.stdout
    assert f"SKIP {gone} はホストに無いので検査しない\n" in done.stdout, done.stdout
    assert done.returncode == 1


def test_hidden_check_judges_by_readability(tmp_path):
    """★在るかではなく読めるかで判定する (WSL の /mnt/c は stat だけ通る)。

    隠した結果の空のディレクトリと /dev/null は合格、読めるファイルは不合格。
    """
    launcher = _launcher()
    emptied = tmp_path / "masked dir"
    emptied.mkdir()
    readable = tmp_path / "key.txt"
    readable.write_text("x", encoding="utf-8")
    done = _run_check_script(
        tmp_path,
        launcher,
        [],
        {"present": [str(emptied), "/dev/null", str(readable)], "absent": []},
    )
    assert f"OK   {emptied} は読めない\n" in done.stdout, done.stdout
    assert "OK   /dev/null は読めない\n" in done.stdout, done.stdout
    assert f"★NG  {readable} を開ける\n" in done.stdout, done.stdout


def test_hidden_check_follows_a_symlinked_directory(tmp_path):
    """★秘密のディレクトリが symlink でも、参照先の中身が見えれば不合格にする。

    ``find`` は既定で開始点の symlink をたどらないので、中身が読めても空に見える。
    """
    launcher = _launcher()
    real = tmp_path / "real secrets"
    real.mkdir()
    (real / "id").write_text("x", encoding="utf-8")
    link = tmp_path / "linked secrets"
    link.symlink_to(real, target_is_directory=True)
    done = _run_check_script(tmp_path, launcher, [], {"present": [str(link)], "absent": []})
    assert f"★NG  {link} の中が見えている\n" in done.stdout, done.stdout
    assert done.returncode == 1


def test_check_script_reports_every_failure_before_exiting(tmp_path):
    """★``set -eu`` を入れても集計が途中で切れないこと。"""
    launcher = _launcher()
    visible = tmp_path / "secret"
    visible.mkdir()
    (visible / "id").write_text("x", encoding="utf-8")
    writable = tmp_path / "ws" / "protected dir"
    writable.mkdir(parents=True)
    done = _run_check_script(
        tmp_path, launcher, [str(writable)], {"present": [str(visible)], "absent": []}
    )
    assert done.stdout.count("★NG") == 2, done.stdout
    assert "OK   許可外ドメインへ到達しない" in done.stdout, "途中で打ち切られた"
    assert "境界チェック: 不合格" in done.stdout
    assert done.returncode == 1


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root は読み取り専用ディレクトリにも書ける"
)
def test_check_script_passes_when_nothing_leaks(tmp_path):
    """漏れが無ければ合格すること (``set -eu`` で正常系が落ちないこと)。"""
    launcher = _launcher()
    locked = tmp_path / "locked dir"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        done = _run_check_script(
            tmp_path,
            launcher,
            [str(locked / "not created")],
            {"present": [str(tmp_path / "hidden inside")], "absent": []},
        )
    finally:
        locked.chmod(0o700)
    assert "境界チェック: 合格" in done.stdout, done.stdout + done.stderr
    data = tmp_path / "ws" / "data"
    assert f"OK   {data} へ書ける" in done.stdout, "データディレクトリを検査していない"
    assert done.returncode == 0


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root は読み取り専用ディレクトリにも書ける"
)
def test_check_script_fails_when_the_data_dir_is_not_writable(tmp_path):
    """★DB と snapshot の置き場へ書けなければ不合格 (共有の DB が使えない)。"""
    launcher = _launcher()
    data = tmp_path / "ws" / "data"
    data.mkdir(parents=True)
    data.chmod(0o500)
    try:
        done = _run_check_script(tmp_path, launcher, [], {"present": [], "absent": []})
    finally:
        data.chmod(0o700)
    assert f"★NG  {data} へ書けない" in done.stdout, done.stdout
    assert done.returncode == 1


def _network_check_environment(launcher: SimpleNamespace, allowed: list[str]) -> dict:
    project = _check_project(Path("/w"), [])
    project["config"]["network"]["allowedDomains"] = allowed
    return launcher.check.check_environment(project, {}, {"present": [], "absent": []})


@pytest.mark.parametrize(
    ("allowed", "denied"),
    [
        pytest.param(["github.com"], "example.com", id="default"),
        pytest.param(["github.com", "example.com"], "example.net", id="exact"),
        pytest.param(["github.com", "EXAMPLE.COM."], "example.net", id="case-and-dot"),
        pytest.param(["github.com", "*.example.com"], "example.net", id="wildcard"),
        pytest.param(["github.com", "example.com", "*.example.net"], "example.org", id="two-taken"),
    ],
)
def test_denied_probe_avoids_the_allowed_domains(allowed, denied):
    """★拒否を確かめる通信先は、プロジェクトが許可したドメインから外す。

    許可に足したドメインへ向けると、正しい境界でも「到達した」で不合格になる。
    ``*.example.com`` は Fence では親ドメインを含まないが、安全側で親も避ける。
    """
    env = _network_check_environment(_launcher(), allowed)
    assert env["BOUNDARY_DENIED_HOST"] == denied


def test_check_script_probes_the_chosen_denied_host(tmp_path):
    """★選び直した検査先が、検査スクリプトの curl の呼び出しまで届くこと。

    許可した ``example.com`` へ向けたままだと、正しい境界でも「到達した」で落ちる。
    """
    launcher = _launcher()
    env = _network_check_environment(launcher, ["allowed.test", "example.com"])
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    log = tmp_path / "curl.log"
    curl = tmp_path / "curl"
    curl.write_text(
        '#!/bin/sh\nfor a; do url=$a; done\nprintf \'%s\\n\' "$url" >> "$CURL_LOG"\n'
        'case "$url" in https://allowed.test|https://example.com) exit 0 ;; esac\nexit 7\n',
        encoding="utf-8",
    )
    curl.chmod(0o755)
    env.update(
        BOUNDARY_WORKSPACE=str(ws),
        BOUNDARY_DATA_DIR=str(ws / "data"),
        BOUNDARY_CURL=str(curl),
        CURL_LOG=str(log),
    )
    done = subprocess.run(
        ["/bin/sh", str(CHECK_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    assert log.read_text(encoding="utf-8").splitlines() == [
        "https://allowed.test",
        "https://example.net",
    ], "拒否の確認が選び直した検査先へ向いていない"
    assert "OK   許可外ドメインへ到達しない" in done.stdout, done.stdout
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.parametrize(
    "allowed",
    [
        pytest.param(["*"], id="everything"),
        pytest.param(["example.com", "example.net", "example.org"], id="all-candidates"),
    ],
)
def test_network_denial_is_skipped_when_every_probe_is_allowed(tmp_path, allowed):
    """★許可外の検査先が残らなければ、その項目だけ SKIP と明示して判定しない。"""
    launcher = _launcher()
    env = _network_check_environment(launcher, ["allowed.test", *allowed])
    assert env["BOUNDARY_DENIED_HOST"] == ""

    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    curl = tmp_path / "curl"
    curl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    curl.chmod(0o755)
    env.update(
        BOUNDARY_WORKSPACE=str(ws), BOUNDARY_DATA_DIR=str(ws / "data"), BOUNDARY_CURL=str(curl)
    )
    done = subprocess.run(
        ["/bin/sh", str(CHECK_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    assert "SKIP 許可外ドメイン" in done.stdout, done.stdout
    assert "到達した" not in done.stdout, done.stdout
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.parametrize(
    "missing", ["BOUNDARY_HIDDEN", "BOUNDARY_PROTECTED", "BOUNDARY_DENIED_HOST"]
)
def test_check_script_refuses_without_the_path_lists(tmp_path, missing):
    """★ランチャーと検査スクリプトの受け渡しが食い違ったら合格にしない。

    正常な環境一式から 1 つだけ外す (他の必須変数で先に落ちると、この確認が素通りする)。
    """
    launcher = _launcher()
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    curl = tmp_path / "curl"
    curl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    curl.chmod(0o755)
    env = launcher.check.check_environment(
        _check_project(ws, []),
        {"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        {"present": [], "absent": []},
    )
    env["BOUNDARY_CURL"] = str(curl)
    del env[missing]
    done = subprocess.run(
        ["/bin/sh", str(CHECK_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    assert done.returncode != 0
    assert missing in done.stderr, done.stderr
    assert "合格" not in done.stdout


def test_path_with_newline_is_refused(tmp_path):
    """★区切りが改行なので、改行を含むパスは渡さずに止める。"""
    launcher = _launcher()
    with pytest.raises(SystemExit):
        launcher.check.check_environment(
            _check_project(tmp_path, ["/w/a\nb"]), {}, {"present": [], "absent": []}
        )


def test_hidden_targets_are_split_by_host_presence(tmp_path, monkeypatch):
    """★ホストに無いものは「読めない」を合格の根拠にしない。"""
    launcher = _launcher()
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    state = tmp_path / "state"
    (state / "opencode").mkdir(parents=True)
    (state / "opencode" / "service.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(launcher.check, "HOME", home)
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setattr(launcher.check, "_is_wsl", lambda: False)
    got = launcher.check.hidden_targets()
    canary = home / launcher.check.CANARY_REL
    assert got["present"] == [
        str(canary),
        str(home / ".ssh"),
        str(state / "opencode" / "service.json"),
    ]
    assert str(home / ".git-credentials") in got["absent"]
    assert not any(p.startswith("/mnt/c") for p in got["present"] + got["absent"])


def test_canary_is_always_checked_even_without_host_secrets(tmp_path, monkeypatch):
    """★~/.ssh などが 1 つも無い機械でも、目印の分だけは本当に検査する。"""
    launcher = _launcher()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(launcher.check, "HOME", home)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(launcher.check, "_is_wsl", lambda: False)
    got = launcher.check.hidden_targets()
    canary = home / launcher.check.CANARY_REL
    assert got["present"] == [str(canary)]
    assert canary.is_file()
    assert canary.stat().st_mode & 0o777 == 0o600


def test_canary_must_not_be_readable_inside_the_boundary(tmp_path):
    """目印は read にも write にも載せない (載ると必ず「読める」で止まる)。"""
    base = _generated(tmp_path)["base"]
    opened = [*base["read"], *base["work_read"], *base["write"]]
    assert opened, "許可のリストが空で、検査になっていない"
    canary = str(Path.home() / _launcher().check.CANARY_REL)
    assert not any(canary == p or canary.startswith(p.rstrip("/") + "/") for p in opened)


def test_check_does_not_take_curl_from_the_inherited_path(tmp_path):
    """★検査スクリプトは PATH を固定し、curl を絶対パスで呼ぶ。"""
    launcher = _launcher()
    env = launcher.check.check_environment(
        _check_project(tmp_path, []),
        {"PATH": "/evil:/usr/bin", "BOUNDARY_CURL": "/evil/curl"},
        {"present": [], "absent": []},
    )
    assert "BOUNDARY_CURL" not in env

    lines = [
        line.strip()
        for line in CHECK_SCRIPT.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert lines[1] == "PATH=/usr/bin:/bin", "set -eu の直後で PATH を固定する"
    assert not [line for line in lines if re.search(r"(^|[\s;(])curl\s", line)]


# --- 起動 ---------------------------------------------------------------------


def _launch(
    tmp_path: Path, monkeypatch, env: dict[str, str], argv: list[str] | None = None
) -> dict:
    """``ocs`` を起動し、``execve`` (または境界チェック) に渡る引数と環境を返す。"""
    launcher = _launcher()
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.chdir(ws)
    runtime = tmp_path / "fence"
    runtime.write_text("", "utf-8")
    opencode = tmp_path / "opencode"
    opencode.write_text("", "utf-8")
    sandbox = {
        "runtime_path": str(runtime),
        "config_dir": str(tmp_path / "config"),
        **_base_sandbox(tmp_path, unsafe_workspace=[]),
    }
    monkeypatch.setattr(launcher.boundary, "load_boundary", lambda: sandbox)
    monkeypatch.setattr(launcher.cli, "OPENCODE", opencode)
    monkeypatch.setattr(launcher.cli, "BOUNDARIES", tmp_path / "state" / "boundaries")
    monkeypatch.setattr(launcher.cli, "FENCE_TMP", tmp_path / "state" / "tmp")
    monkeypatch.setattr(launcher.backup, "backup_worktree", lambda *a: None)
    monkeypatch.setattr(launcher.config, "write_isolated_config", lambda *a: None)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    seen: dict = {"opencode": str(opencode), "runtime": str(runtime), "ws": ws}

    def fake_execve(path, argv, env):
        seen.update(
            path=path, argv=argv, env=env, boundary=json.loads(Path(argv[2]).read_text("utf-8"))
        )
        raise SystemExit(0)

    def fake_check(runtime, boundary, project, env, tmpdir):
        seen.update(check=(runtime, boundary, project, env, tmpdir))
        return 3

    monkeypatch.setattr(os, "execve", fake_execve)
    monkeypatch.setattr(launcher.check, "run_check", fake_check)
    with contextlib.suppress(SystemExit):
        seen["returned"] = launcher.cli.main(argv if argv is not None else ["--no-backup"])
    return seen


def test_launch_runs_opencode_inside_fence(tmp_path, monkeypatch):
    """★Fence へは ``--settings`` を必ず渡す (省くとカレントの fence.json を読む)。

    引数は 1 本の文字列にせず並べて渡す。``ocs --continue`` が opencode に届くこと。
    """
    seen = _launch(tmp_path, monkeypatch, {"PATH": "/usr/bin"}, ["--no-backup", "--continue"])
    argv = seen["argv"]
    assert seen["path"] == seen["runtime"]
    assert argv[:2] == [seen["runtime"], "--settings"]
    assert argv[3] == "--"
    assert argv[-3:] == [seen["opencode"], "--standalone", "--continue"]
    assert Path(argv[2]).parent == tmp_path / "state" / "boundaries"


def test_launch_fixes_the_host_path_but_keeps_the_users_path_inside(tmp_path, monkeypatch):
    """★Fence には固定の PATH と状態領域の TMPDIR を、内側の opencode には利用者の PATH と
    ``/tmp`` を渡す。

    Fence は境界を張る前に bwrap / socat / bash を PATH から探す。内側の TMPDIR が
    見えない場所のままだと書けない。
    """
    user_path = f"{tmp_path / 'ws' / 'bin'}:/usr/bin"
    seen = _launch(tmp_path, monkeypatch, {"PATH": user_path, "TMPDIR": "/somewhere"})
    assert seen["env"]["PATH"] == "/usr/bin:/bin", "Fence が利用者の PATH で動く"
    assert seen["env"]["TMPDIR"] == str(tmp_path / "state" / "tmp")
    inner = seen["argv"][4:]
    assert inner[:3] == ["/usr/bin/env", f"PATH={user_path}", "TMPDIR=/tmp"]
    assert inner[4] == seen["opencode"]


def test_inner_state_home_is_writable_scratch(tmp_path, monkeypatch):
    """★``~/.local/state`` は開けない。opencode は起動時にそこへディレクトリを作るので、
    内側の ``XDG_STATE_HOME`` を内側の ``/tmp`` (終了時に消える) へ向ける (実測で EROFS)。

    常駐サービスの接続情報 (``service.json``) は見えないまま。
    """
    seen = _launch(tmp_path, monkeypatch, {"PATH": "/usr/bin"})
    assert "XDG_STATE_HOME=/tmp/xdg-state" in seen["argv"][4:9]
    opened = (
        seen["boundary"]["filesystem"]["allowRead"] + seen["boundary"]["filesystem"]["allowWrite"]
    )
    assert not [p for p in opened if "/.local/state" in p]


def test_launch_shares_the_host_db(tmp_path, monkeypatch):
    """★XDG_DATA_HOME と OPENCODE_DB を上書きしない。利用者の OPENCODE_DB は落とす。

    OPENCODE_DB が残ると常駐サービスと別の DB を使い、履歴が分かれる。
    """
    seen = _launch(tmp_path, monkeypatch, {"PATH": "/usr/bin", "OPENCODE_DB": "/elsewhere/x.db"})
    env = seen["env"]
    assert "OPENCODE_DB" not in env
    assert env["XDG_DATA_HOME"] == str(tmp_path / "share")
    data = tmp_path / "share" / "opencode"
    assert data.is_dir(), "データディレクトリを用意していない"
    assert str(data) in seen["boundary"]["filesystem"]["allowWrite"]
    assert env["OCS_ISOLATED"] == "1"
    assert env["OPENCODE_CONFIG_DIR"] == str(tmp_path / "config")


@pytest.mark.parametrize(
    ("value", "under_home"),
    [
        pytest.param(None, True, id="unset"),
        pytest.param("", True, id="empty"),
        pytest.param("relative/share", True, id="relative"),
        pytest.param("/abs/share", False, id="absolute"),
    ],
)
def test_data_dir_falls_back_like_opencode(tmp_path, monkeypatch, value, under_home):
    """★XDG_DATA_HOME が無い・空・相対なら ``~/.local/share/opencode`` (XDG の規定)。"""
    launcher = _launcher()
    monkeypatch.setattr(launcher.cli, "HOME", tmp_path / "home")
    if value is None:
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    else:
        monkeypatch.setenv("XDG_DATA_HOME", value)
    expected = (tmp_path / "home" / ".local/share") if under_home else Path("/abs/share")
    assert launcher.cli.opencode_data_dir() == expected / "opencode"


def test_launch_without_xdg_data_home_uses_the_standard_data_dir(tmp_path, monkeypatch):
    """★XDG_DATA_HOME が無くても、作る場所・書ける場所・DB が同じ標準領域を指すこと。

    起動ヘルパーは必ず XDG_DATA_HOME を設定するので、ここで別に通す。
    """
    launcher = _launcher()
    home = tmp_path / "home"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.chdir(ws)
    runtime = tmp_path / "fence"
    runtime.write_text("", "utf-8")
    opencode = tmp_path / "opencode"
    opencode.write_text("", "utf-8")
    sandbox = {
        "runtime_path": str(runtime),
        "config_dir": str(tmp_path / "config"),
        **_base_sandbox(tmp_path, unsafe_workspace=[]),
    }
    monkeypatch.setattr(launcher.cli, "HOME", home)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(launcher.boundary, "load_boundary", lambda: sandbox)
    monkeypatch.setattr(launcher.cli, "OPENCODE", opencode)
    monkeypatch.setattr(launcher.cli, "BOUNDARIES", tmp_path / "state" / "boundaries")
    monkeypatch.setattr(launcher.cli, "FENCE_TMP", tmp_path / "state" / "tmp")
    monkeypatch.setattr(launcher.backup, "backup_worktree", lambda *a: None)
    seen: dict = {}

    def fake_config(sandbox_, project):
        seen["project"] = project

    def fake_execve(path, argv, env):
        seen.update(env=env, boundary=json.loads(Path(argv[2]).read_text("utf-8")))
        raise SystemExit(0)

    monkeypatch.setattr(launcher.config, "write_isolated_config", fake_config)
    monkeypatch.setattr(os, "execve", fake_execve)
    with contextlib.suppress(SystemExit):
        launcher.cli.main(["--no-backup"])

    data = home / ".local" / "share" / "opencode"
    assert data.is_dir(), "標準のデータディレクトリを作っていない"
    assert seen["project"]["data_dir"] == str(data)
    assert seen["project"]["db"] == str(data / "opencode.db")
    assert str(data) in seen["boundary"]["filesystem"]["allowWrite"]
    assert "XDG_DATA_HOME" not in seen["env"]


def test_launch_drops_credentials_from_the_environment(tmp_path, monkeypatch):
    seen = _launch(
        tmp_path, monkeypatch, {"PATH": "/usr/bin", "GH_TOKEN": "t", "SSH_AUTH_SOCK": "/s"}
    )
    assert "GH_TOKEN" not in seen["env"] and "SSH_AUTH_SOCK" not in seen["env"]


def test_check_is_manual_and_does_not_launch(tmp_path, monkeypatch):
    """★境界チェックは ``ocs --check`` で手動実行する。起動時には走らせない。"""
    seen = _launch(tmp_path, monkeypatch, {"PATH": "/usr/bin"})
    assert "check" not in seen, "起動時に境界チェックが走った"

    other = tmp_path / "second"
    other.mkdir()
    seen = _launch(other, monkeypatch, {"PATH": "/usr/bin"}, ["--check"])
    assert "argv" not in seen, "--check で opencode を起動した"
    assert seen["returned"] == 3, "検査の終了コードを返していない"
    runtime, _boundary, project, _env, tmpdir = seen["check"]
    assert runtime == Path(seen["runtime"])
    assert project["data_dir"] == str(other / "share" / "opencode")
    assert tmpdir == other / "state" / "tmp", "Fence の TMPDIR を状態領域にしていない"


def _rules_sandbox(tmp_path: Path) -> dict:
    """rules.json の ``sandbox`` 節。隔離版の設定ディレクトリは読み取りに入れ、まだ作らない。"""
    runtime = tmp_path / "fence"
    runtime.write_text("", "utf-8")
    config_dir = tmp_path / "sandbox-config"
    sandbox = {
        "runtime_path": str(runtime),
        "config_dir": str(config_dir),
        "permissions": [],
        **_base_sandbox(tmp_path, unsafe_workspace=[]),
    }
    sandbox["base"]["read"].append(str(config_dir))
    return sandbox


def _main_with_rules(
    tmp_path: Path, monkeypatch, rules: str | bytes | None, argv: list[str]
) -> dict:
    """実物の ``load_boundary`` と設定の書き出しで ``main`` を通す。外部の実行だけ捕まえる。

    ``rules`` は rules.json の中身 (``None`` なら置かない)。
    """
    launcher = _launcher()
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    monkeypatch.chdir(ws)
    rules_file = tmp_path / "rules.json"
    if isinstance(rules, bytes):
        rules_file.write_bytes(rules)
    elif rules is not None:
        rules_file.write_text(rules, encoding="utf-8")
    opencode = tmp_path / "opencode"
    opencode.write_text("", "utf-8")
    monkeypatch.setattr(launcher.boundary, "RULES", rules_file)
    monkeypatch.setattr(launcher.cli, "OPENCODE", opencode)
    monkeypatch.setattr(launcher.cli, "BOUNDARIES", tmp_path / "state" / "boundaries")
    monkeypatch.setattr(launcher.cli, "FENCE_TMP", tmp_path / "state" / "tmp")
    monkeypatch.setattr(launcher.config, "HOST_CONFIG", tmp_path / "host-opencode.json")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    seen: dict = {"calls": []}

    def recorded(name, real):
        def wrapper(*args, **kwargs):
            seen["calls"].append(name)
            return real(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(
        launcher.backup, "backup_worktree", recorded("backup", launcher.backup.backup_worktree)
    )
    monkeypatch.setattr(
        launcher.config,
        "write_isolated_config",
        recorded("config", launcher.config.write_isolated_config),
    )
    monkeypatch.setattr(
        launcher.cli, "write_boundary", recorded("boundary", launcher.cli.write_boundary)
    )
    monkeypatch.setattr(
        launcher.boundary, "build_boundary", recorded("build", launcher.boundary.build_boundary)
    )

    def fake_execve(path, args, env):
        seen["calls"].append("execve")
        seen["boundary"] = json.loads(Path(args[2]).read_text("utf-8"))
        raise SystemExit(0)

    def fake_check(runtime, boundary, project, env, tmpdir):
        seen["calls"].append("check")
        seen["boundary"] = json.loads(Path(boundary).read_text("utf-8"))
        return 0

    monkeypatch.setattr(os, "execve", fake_execve)
    monkeypatch.setattr(launcher.check, "run_check", fake_check)
    try:
        seen["returned"] = launcher.cli.main(argv)
    except SystemExit as exc:
        seen["exit"] = exc.code
    return seen


@pytest.mark.parametrize("argv", [["--no-backup"], ["--check"]])
def test_isolated_config_dir_is_readable_on_first_launch(tmp_path, monkeypatch, argv):
    """★初回 (設定ディレクトリがまだ無い) でも、隔離版の設定を境界の内側から読めること。

    境界は無いパスを落とすので、設定ディレクトリを作る前に組むと allowRead から抜ける。
    書き込みは許さない (内側から緩和を広げられないように)。
    """
    sandbox = _rules_sandbox(tmp_path)
    config_dir = sandbox["config_dir"]
    assert not Path(config_dir).exists()
    seen = _main_with_rules(tmp_path, monkeypatch, json.dumps({"sandbox": sandbox}), argv)
    assert seen["calls"][-1] in ("execve", "check"), seen
    filesystem = seen["boundary"]["filesystem"]
    assert config_dir in filesystem["allowRead"], "初回の起動で設定ディレクトリが読めない"
    writable = [p for p in filesystem["allowWrite"] if Path(config_dir).is_relative_to(p)]
    assert not writable, f"設定ディレクトリへ書ける: {writable}"
    if argv == ["--no-backup"]:
        assert (Path(config_dir) / "opencode.json").is_file()


def _drop(key: str):
    def edit(sandbox: dict) -> dict:
        return {k: v for k, v in sandbox.items() if k != key}

    return edit


@pytest.mark.parametrize(
    "rules",
    [
        pytest.param(None, id="no-rules"),
        pytest.param("{壊れた JSON", id="broken-json"),
        pytest.param(b"\xff\xfe{}", id="not-utf8"),
        pytest.param("[]", id="top-not-object"),
        pytest.param("{}", id="no-sandbox"),
        pytest.param('{"sandbox": null}', id="sandbox-null"),
        pytest.param('{"sandbox": "x"}', id="sandbox-not-object"),
        pytest.param(_drop("runtime_path"), id="no-runtime_path"),
        pytest.param(_drop("base"), id="no-base"),
        pytest.param(_drop("config_dir"), id="no-config_dir"),
        pytest.param(lambda s: {**s, "base": ["x"]}, id="base-not-object"),
        pytest.param(
            lambda s: {**s, "runtime_path": s["runtime_path"] + ".missing"}, id="no-fence"
        ),
    ],
)
@pytest.mark.parametrize("argv", [["--no-backup"], ["--check"]])
def test_launch_is_refused_without_a_usable_boundary(tmp_path, monkeypatch, rules, argv):
    """★境界の素材が使えなければ、設定の書き出し・退避・境界の書き出し・起動に進まない。"""
    if callable(rules):
        rules = json.dumps({"sandbox": rules(_rules_sandbox(tmp_path))})
    seen = _main_with_rules(tmp_path, monkeypatch, rules, argv)
    assert seen.get("exit") == 1, seen
    assert seen["calls"] == [], f"拒否する前に進んだ: {seen['calls']}"
    assert not (tmp_path / "state" / "boundaries").exists()


def _unsafe_here(tmp_path: Path, sandbox: dict) -> None:
    sandbox["base"]["unsafe_workspace"] = [str(tmp_path / "ws")]


def _protected_here(tmp_path: Path, sandbox: dict) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    sandbox["base"]["protected"] = ["ws"]


def _protected_write_here(tmp_path: Path, sandbox: dict) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "guarded").mkdir()
    sandbox["base"]["protected"] = ["guarded"]
    _request(tmp_path / "ws", 'write = ["../guarded/gen.py"]\n')


def _control_here(tmp_path: Path, sandbox: dict) -> None:
    sandbox["base"]["control_dirs"] = [str(tmp_path)]


def _control_write_here(tmp_path: Path, sandbox: dict) -> None:
    (tmp_path / "deployed").mkdir()
    sandbox["base"]["control_dirs"] = [str(tmp_path / "deployed" / "ocs")]
    _request(tmp_path / "ws", 'write = ["../deployed"]\n')


@pytest.mark.parametrize(
    "refuse",
    [_unsafe_here, _protected_here, _protected_write_here, _control_here, _control_write_here],
    ids=[
        "unsafe_workspace",
        "保護対象の中",
        "保護対象の中への write",
        "制御ファイルの置き場の中",
        "制御ファイルの置き場と重なる write",
    ],
)
@pytest.mark.parametrize("argv", [["--no-backup"], ["--check"]])
def test_refused_workspace_stops_main_before_the_boundary(tmp_path, monkeypatch, refuse, argv):
    """★起動を拒否する場所では、境界の組み立て・設定と境界の書き出し・退避・起動に進まない。"""
    sandbox = _rules_sandbox(tmp_path)
    refuse(tmp_path, sandbox)
    seen = _main_with_rules(tmp_path, monkeypatch, json.dumps({"sandbox": sandbox}), argv)
    assert seen.get("exit") == 1, seen
    assert seen["calls"] == [], f"拒否する前に進んだ: {seen['calls']}"
    assert not (tmp_path / "state" / "boundaries").exists()
    assert not (Path(sandbox["config_dir"]) / "opencode.json").exists()


def test_removed_flags_are_gone():
    """承認・自動の境界チェック・隔離用 DB の操作のフラグは無い (CHG-0009)。"""
    body = (LIB / "cli.py").read_text(encoding="utf-8")
    for flag in ("--trust", "--recheck", "--skip-check", "--handoff", "--list-sessions"):
        assert f'"{flag}"' not in body, f"{flag} が残っている"
    assert not (LIB / "session.py").exists(), "隔離用 DB の処理が残っている"


def test_check_invokes_fence_with_settings(tmp_path, monkeypatch):
    """★境界チェックも Fence に ``--settings`` と固定の PATH を渡して走らせる。"""
    launcher = _launcher()
    check = tmp_path / "bin dir" / "ocs-boundary-check"
    check.parent.mkdir()
    check.write_text("", encoding="utf-8")
    monkeypatch.setattr(launcher.check, "CHECK", check)
    monkeypatch.setattr(launcher.check, "hidden_targets", lambda: {"present": [], "absent": []})
    seen: list = []

    def fake_run(cmd, **kw):
        seen.append((cmd, kw["env"]))
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    got = launcher.check.run_check(
        tmp_path / "fence",
        str(tmp_path / "b.json"),
        _check_project(tmp_path, []),
        {"PATH": str(tmp_path / "evil")},
        tmp_path / "tmp",
    )
    cmd, env = seen[0]
    assert got == 1
    assert cmd == [
        str(tmp_path / "fence"),
        "--settings",
        str(tmp_path / "b.json"),
        "--",
        "/bin/sh",
        str(check),
    ]
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["TMPDIR"] == str(tmp_path / "tmp")


def test_missing_check_script_is_refused(tmp_path, monkeypatch):
    launcher = _launcher()
    monkeypatch.setattr(launcher.check, "CHECK", tmp_path / "none")
    with pytest.raises(SystemExit):
        launcher.check.run_check(
            tmp_path / "fence", "b.json", _check_project(tmp_path, []), {}, tmp_path
        )


# --- 本体の読み込み (信頼の鎖) ------------------------------------------------


def _impostor(root: Path) -> Path:
    """sys.path・PYTHONPATH・cwd に置く偽の ``ocs_lib``。読まれたら印を出す。"""
    package = root / "ocs_lib"
    package.mkdir(parents=True)
    for name in ("__init__", *MODULES):
        (package / f"{name}.py").write_text(
            'print("IMPOSTOR")\ndef main():\n    return 0\n', encoding="utf-8"
        )
    return root


def test_library_path_is_absolute_under_home():
    """★本体は配備先の絶対パスから読む。スクリプトの場所や cwd から導かない。"""
    assert _entry()["LIB"] == Path.home() / ".local/share/ocs"


def test_modules_come_only_from_the_given_directory(tmp_path, monkeypatch):
    """★sys.path・cwd・先に居座った ``sys.modules`` の偽物を拾わないこと。"""
    evil = _impostor(tmp_path / "evil")
    monkeypatch.syspath_prepend(str(evil))
    monkeypatch.chdir(evil)
    monkeypatch.setitem(sys.modules, "ocs_lib.common", SimpleNamespace(HOME=tmp_path))

    _launcher()

    loaded = {n: m for n, m in sys.modules.items() if n.split(".")[0] == "ocs_lib"}
    assert set(loaded) == {"ocs_lib", *(f"ocs_lib.{n}" for n in MODULES)}
    for name, module in loaded.items():
        assert Path(module.__file__).parent == LIB, f"{name} を {module.__file__} から読んだ"


def _run_entry(home: Path, cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(LAUNCHER), *args],
        cwd=cwd,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(cwd)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )


def test_entry_ignores_pythonpath_and_cwd(tmp_path):
    """★PYTHONPATH と cwd に偽の本体があっても、配備先の本体だけを動かすこと。"""
    evil = _impostor(tmp_path / "evil")
    home = tmp_path / "home"
    (home / ".local/share").mkdir(parents=True)
    (home / ".local/share/ocs").symlink_to(LIB)

    done = _run_entry(home, evil, "--help")

    assert done.returncode == 0, done.stderr
    assert "IMPOSTOR" not in done.stdout + done.stderr
    assert "OpenCode を OS のアクセス制御で囲って起動する" in done.stdout
    assert not list(LIB.glob("__pycache__")), "配備先へ __pycache__ を作った"


def test_entry_refuses_without_the_library(tmp_path):
    """★本体が無ければ起動しない。PYTHONPATH の偽物へ落ちないこと。"""
    evil = _impostor(tmp_path / "evil")
    home = tmp_path / "home"
    home.mkdir()

    done = _run_entry(home, evil)

    assert done.returncode == 1
    assert "IMPOSTOR" not in done.stdout + done.stderr
    assert "起動しない" in done.stderr


def _covers(entries: list[str], target: str) -> bool:
    target = target.rstrip("/")
    return any(target == e.rstrip("/") or target.startswith(e.rstrip("/") + "/") for e in entries)


@pytest.mark.parametrize("deployed", ["~/.local/bin/ocs", "~/.local/share/ocs"])
def test_launcher_code_is_not_writable_from_agent_sandboxes(deployed):
    """★ocs が読むコードは、どの sandbox の書き込み範囲にも入れない。"""
    sandbox = COMMON["sandbox"]
    boundary = COMMON["opencode"]["sandbox"]
    for key, entries in (
        ("[sandbox] claude_write_allow", sandbox.get("claude_write_allow", [])),
        ("[sandbox] copilot_write_allow", sandbox.get("copilot_write_allow", [])),
        ("[opencode.sandbox] write", boundary.get("write", [])),
    ):
        assert not _covers(entries, deployed), f"{key} が {deployed} を書き込み可能にしている"


STATE_DIR = "~/.local/state/opencode-sandbox"


def test_launcher_state_is_denied_to_agent_sandboxes():
    """★ocs の状態 (退避・境界の定義) は ocs の外の CLI からも書けない。"""
    assert _covers(COMMON["sandbox"]["deny"], STATE_DIR)
    claude = gen.build_claude_sandbox(COMMON)["filesystem"]
    assert _covers(claude["denyWrite"], STATE_DIR)
    copilot = gen.build_copilot_sandbox(None, COMMON)["userPolicy"]["filesystem"]
    assert os.path.expanduser(STATE_DIR) in copilot["deniedPaths"]
    assert f"{STATE_DIR}/**" in COMMON["file"]["write_deny_globs"]


def test_launcher_state_exists_before_agents_start():
    """★Copilot はセッション開始時に無いパスの deny を捨て、途中で作られても効かせない。

    chezmoi が apply で先に作っておく (0700)。
    """
    assert (ROOT / "home/dot_local/state/private_opencode-sandbox/.keep").is_file()


@pytest.mark.parametrize("source", ["home/dot_local/bin", "home/dot_local/share/ocs"])
def test_launcher_source_is_protected_inside_the_boundary(source):
    """★ocs の source state は境界の内側から書き換えられないこと (denyWrite)。"""
    protected = COMMON["opencode"]["sandbox"]["protected"]
    assert _covers(protected, source), f"{source} が protected に無い"

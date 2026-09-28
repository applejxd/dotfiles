"""隔離起動 ``ocs`` のランチャーに関するテスト。

Run with: ``uv run --with pytest --no-project pytest test/agents/`` or
``python3 -m pytest test/agents/``.

see docs/spec/opencode-sandbox.md
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
import subprocess
import sys
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
    return SimpleNamespace(**{name: sys.modules[f"ocs_lib.{name}"] for name in MODULES})


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
    filesystem = launcher.boundary.build_boundary(
        _base_sandbox(tmp_path), tmp_path / "ws"
    )["filesystem"]
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
    filesystem = launcher.boundary.build_boundary(
        _base_sandbox(tmp_path), ws, None, data
    )["filesystem"]
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


def test_generated_unsafe_workspace_covers_home_and_tmp(tmp_path):
    unsafe = _generated(tmp_path)["base"]["unsafe_workspace"]
    for required in (str(Path.home()), "/mnt", "/tmp"):
        assert required in unsafe, f"unsafe_workspace に {required} が無い"


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
    assert extras == [
        str(Path.home() / "datasets"), str(ws / "sub/dir"), str(tmp_path / "other")
    ]


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


def test_protected_paths_are_workspace_relative(tmp_path):
    """保護対象は起動ディレクトリと組み合わせる。"""
    launcher = _launcher()
    where = tmp_path / "gamma"
    where.mkdir()
    deny_write = launcher.boundary.build_boundary(_base_sandbox(tmp_path), where)[
        "filesystem"
    ]["denyWrite"]
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
    )
    config_dir = Path(full["config_dir"])
    target = config_dir / "opencode.json"
    agents = config_dir / "AGENTS.md"

    launcher.config.write_isolated_config(full, project)
    config = json.loads(target.read_text(encoding="utf-8"))
    assert config["plugins"] == ["/opt/plugin.js"]
    assert config["experimental"]["policies"] == [{"statement": "x"}]
    assert agents.is_file()
    config["model"] = "github-copilot/claude-sonnet-5"
    config["username"] = "alice"
    config["experimental"]["other"] = True
    target.write_text(json.dumps(config), encoding="utf-8")

    managed = ("policies", "plugins", "system_prompt")
    if stage == "空":
        sandbox = {**full, "policies": [], "plugins": [], "system_prompt": ""}
    else:
        sandbox = {k: v for k, v in full.items() if k not in managed}
    launcher.config.write_isolated_config(sandbox, project)
    after = json.loads(target.read_text(encoding="utf-8"))
    assert "plugins" not in after, "plugins が残った"
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


# --- git worktree ------------------------------------------------------------


def _worktree(tmp_path: Path) -> tuple[Path, Path]:
    """linked worktree を 1 つ作り、(共有 .git, worktree) を返す。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", "-C", str(repo), *a], check=True, capture_output=True
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
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
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    assert launcher.boundary.git_common_dir(repo) is None


def test_git_common_dir_ignores_git_env(tmp_path, monkeypatch):
    """★GIT_DIR などを利用者の環境から通すと、別のリポジトリが allowWrite に入る。"""
    launcher = _launcher()
    other = tmp_path / "other"
    subprocess.run(["git", "init", "-q", str(other)], check=True, capture_output=True)
    repo = tmp_path / "plain"
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
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
    host.write_text(
        json.dumps({"theme": "dark", "model": "p/host"}), encoding="utf-8"
    )
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
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    for key, value in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(
            ["git", "-C", str(repo), "config", key, value], check=True, capture_output=True
        )
    (repo / "a.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "init"], check=True, capture_output=True
    )
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
    monkeypatch.setattr(launcher.backup, "BACKUP_TOTAL_MAX_BYTES", 1)  # 実質 1 件だけ残る
    for name in ("one", "two", "three"):
        repo = _repo(tmp_path / name)
        (repo / "a.txt").write_text(f"{name}\n", encoding="utf-8")
        launcher.backup.backup_worktree(repo, False)
    assert len(_backups(launcher)) <= 1, "全体の上限が効いていない"


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
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "ignore"], check=True, capture_output=True
    )
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
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

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
    if os.geteuid() != 0:
        assert f"★NG  {data} へ書けない" in done.stdout, done.stdout
        assert done.returncode == 1


def test_check_script_refuses_without_the_path_lists(tmp_path):
    """★ランチャーと検査スクリプトの受け渡しが食い違ったら合格にしない。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    done = subprocess.run(
        ["/bin/sh", str(CHECK_SCRIPT)],
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "BOUNDARY_WORKSPACE": str(ws)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    assert done.returncode != 0
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
    opened = seen["boundary"]["filesystem"]["allowRead"] + seen["boundary"]["filesystem"][
        "allowWrite"
    ]
    assert not [p for p in opened if "/.local/state" in p]


def test_launch_shares_the_host_db(tmp_path, monkeypatch):
    """★XDG_DATA_HOME と OPENCODE_DB を上書きしない。利用者の OPENCODE_DB は落とす。

    OPENCODE_DB が残ると常駐サービスと別の DB を使い、履歴が分かれる。
    """
    seen = _launch(
        tmp_path, monkeypatch, {"PATH": "/usr/bin", "OPENCODE_DB": "/elsewhere/x.db"}
    )
    env = seen["env"]
    assert "OPENCODE_DB" not in env
    assert env["XDG_DATA_HOME"] == str(tmp_path / "share")
    data = tmp_path / "share" / "opencode"
    assert data.is_dir(), "データディレクトリを用意していない"
    assert str(data) in seen["boundary"]["filesystem"]["allowWrite"]
    assert env["OCS_ISOLATED"] == "1"
    assert env["OPENCODE_CONFIG_DIR"] == str(tmp_path / "config")


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
    monkeypatch.setattr(
        launcher.check, "hidden_targets", lambda: {"present": [], "absent": []}
    )
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
    assert cmd == [str(tmp_path / "fence"), "--settings", str(tmp_path / "b.json"), "--",
                   "/bin/sh", str(check)]
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

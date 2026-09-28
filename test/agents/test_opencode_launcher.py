"""ランチャーの設定書き出しに関するテスト。

Run with: ``uv run --with pytest --no-project pytest test/agents/`` or
``python3 -m pytest test/agents/``.

★守りたいのは「緩和に関わるキーは毎回差し替わる」ことと
  「それ以外のキーは残る」ことの両立。
  丸ごと上書きすると、TUI で選んだモデルが毎回消える (実際に出したバグ)。
see docs/change/closed/0004-opencode-sandbox.md
"""

from __future__ import annotations

import json
import os
import re
import shlex
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

# ocs は bwrap で囲うので Ubuntu / WSL 専用 (CHG-0004)。他の OS には配らない
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="ocs は Linux 専用")
from agents_common import load_common  # noqa: E402

LAUNCHER = ROOT / "home" / "dot_local" / "bin" / "executable_ocs"
LIB = ROOT / "home" / "dot_local" / "share" / "ocs"
MODULES = ("common", "boundary", "check", "backup", "session", "config", "cli")
COMMON = load_common()


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
    """境界の設定に、書き出し先だけ差し替えたものを返す。"""
    base = gen.opencode_sandbox(COMMON) or {}
    fallback = [{"action": "shell", "resource": "*", "effect": "allow"}]
    return {
        "config_dir": str(tmp_path / "config"),
        "permissions": base.get("permissions", fallback),
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
        "data_home": str(tmp_path / "ws" / ".opencode-sandbox" / "data"),
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


def _base_sandbox() -> dict:
    return {
        "base": {
            "read": ["/opt/shared"],
            "write": [],
            "deny_read": ["/home/u", "/mnt", "/tmp"],
            "protected": [".opencode"],
            "network": {
                "allowedDomains": ["github.com"],
                "deniedDomains": [],
                "allowLocalBinding": False,
            },
        },
        "paths": {
            "data_home": ".opencode-sandbox/data",
            "db": ".opencode-sandbox/opencode.db",
        },
    }


def _request(workspace: Path, body: str) -> Path:
    path = workspace / ".opencode" / "sandbox.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_launch_directory_is_always_writable(tmp_path):
    """★起動ディレクトリ以下は無条件に許可する。

    どこで起動するかは利用者の責務。要求は追加の許可が要るときだけ。
    """
    launcher = _launcher()
    where = tmp_path / "undeclared" / "deep"
    where.mkdir(parents=True)
    filesystem = launcher.boundary.build_boundary(_base_sandbox(), where)["filesystem"]
    assert str(where) in filesystem["allowWrite"]
    # R1: ワークスペースは allowRead にも完全一致で入れる
    assert str(where) in filesystem["allowRead"]


@pytest.mark.parametrize(
    "where",
    ["/home/u", "/home", "/", "/tmp", "/mnt"],
    ids=["deny_read そのもの", "その祖先", "ルート", "/tmp", "/mnt"],
)
def test_workspace_that_cancels_deny_read_is_rejected(where):
    """★deny_read を打ち消す場所では起動しない。

    R3 で allowRead が denyRead に勝つため、deny_read の項目そのものか
    その祖先で起動すると、その deny が丸ごと無効になる。
    """
    launcher = _launcher()
    with pytest.raises(SystemExit):
        launcher.boundary.reject_unsafe_workspace(_base_sandbox(), Path(where))


@pytest.mark.parametrize(
    "where",
    ["/home/u/work/repo", "/tmp/scratch", "/opt/shared/x"],
    ids=["ホーム配下", "/tmp 配下", "deny_read の外"],
)
def test_workspace_below_deny_read_is_allowed(where):
    """子孫での起動は安全なので通す。/tmp/x は /tmp の deny を壊さない。"""
    launcher = _launcher()
    launcher.boundary.reject_unsafe_workspace(_base_sandbox(), Path(where))


def test_unsafe_workspace_is_rejected_before_boundary_is_built(tmp_path, monkeypatch):
    """★拒否は境界を組み立てる前に起きること。

    順序が逆だと、打ち消された境界を一度作ってから捨てることになる。
    """
    launcher = _launcher()
    built = []
    monkeypatch.setattr(launcher.boundary, "build_boundary", lambda *a: built.append(a))
    with pytest.raises(SystemExit):
        launcher.boundary.reject_unsafe_workspace(_base_sandbox(), Path("/home/u"))
    assert built == []


def test_no_request_means_no_extras(tmp_path):
    """要求が無ければ追加はゼロ。共通分だけで動く。"""
    launcher = _launcher()
    (tmp_path / "gamma").mkdir()
    boundary = launcher.boundary.build_boundary(_base_sandbox(), tmp_path / "gamma")
    assert boundary["filesystem"]["allowRead"] == [
        str(tmp_path / "gamma"),
        "/opt/shared",
    ]
    assert boundary["network"]["allowedDomains"] == ["github.com"]


def test_request_adds_only_to_its_own_workspace(tmp_path):
    """★要求は、それを置いたワークスペースにしか効かない。"""
    launcher = _launcher()
    alpha, beta = tmp_path / "alpha", tmp_path / "beta"
    alpha.mkdir()
    beta.mkdir()
    _request(
        alpha,
        'read = ["/mnt/d/alpha"]\nnetwork_allow = ["api.alpha.test"]\n',
    )

    build, read = launcher.boundary.build_boundary, launcher.boundary.read_request
    got = build(_base_sandbox(), alpha, read(alpha))
    assert "/mnt/d/alpha" in got["filesystem"]["allowRead"]
    assert "api.alpha.test" in got["network"]["allowedDomains"]

    other = build(_base_sandbox(), beta, read(beta))
    assert "/mnt/d/alpha" not in other["filesystem"]["allowRead"]
    assert "api.alpha.test" not in other["network"]["allowedDomains"]


def test_request_is_not_inherited_by_subdirectories(tmp_path):
    """★親の要求で子を動かさない。

    起動ディレクトリが境界なので、要求もその場のものだけを見る。
    """
    launcher = _launcher()
    outer = tmp_path / "repo"
    inner = outer / "pkg"
    inner.mkdir(parents=True)
    _request(outer, 'read = ["/outer"]\n')
    allow_read = launcher.boundary.build_boundary(_base_sandbox(), inner)["filesystem"][
        "allowRead"
    ]
    assert "/outer" not in allow_read


def test_request_paths_are_resolved(tmp_path):
    """``~`` と相対パスは展開してから境界へ渡す。

    人が承認するのは「何が開くか」なので、書かれた文字列のままにしない。
    """
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, 'read = ["~/datasets", "sub/dir"]\n')
    allow_read = launcher.boundary.build_boundary(
        _base_sandbox(), ws, launcher.boundary.read_request(ws)
    )["filesystem"]["allowRead"]
    assert str(Path.home() / "datasets") in allow_read
    assert str(ws / "sub/dir") in allow_read
    assert "~/datasets" not in allow_read


def test_protected_paths_are_workspace_relative(tmp_path):
    """保護対象は起動ディレクトリと組み合わせる。"""
    launcher = _launcher()
    where = tmp_path / "gamma"
    where.mkdir()
    deny_write = launcher.boundary.build_boundary(_base_sandbox(), where)["filesystem"][
        "denyWrite"
    ]
    assert str(where / ".opencode") in deny_write


def test_unapproved_request_refuses_to_start(tmp_path, monkeypatch):
    """★承認していない要求では起動しない。

    リポジトリは「要求」できるが「付与」はできない。
    """
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, 'read = ["/mnt/d/alpha"]\n')
    monkeypatch.setattr(launcher.boundary, "TRUST", tmp_path / "trusted.json")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit):
        launcher.boundary.ensure_trusted(ws, False, launcher.boundary.read_request(ws))


def test_approval_is_recorded_outside_the_workspace(tmp_path, monkeypatch):
    """承認の記録は境界の外に置く。内側から書けると自分で承認できる。"""
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, 'read = ["/mnt/d/alpha"]\n')
    trust = tmp_path / "state" / "trusted.json"
    monkeypatch.setattr(launcher.boundary, "TRUST", trust)

    launcher.boundary.ensure_trusted(ws, True, launcher.boundary.read_request(ws))  # --trust
    assert ws not in trust.parents, "承認の記録がワークスペースの中にある"
    # 2 回目は尋ねずに通る (端末が無くても落ちない)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    launcher.boundary.ensure_trusted(ws, False, launcher.boundary.read_request(ws))


def test_changed_request_needs_reapproval(tmp_path, monkeypatch):
    """★要求が変わったら承認をやり直す。"""
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, 'read = ["/mnt/d/alpha"]\n')
    monkeypatch.setattr(launcher.boundary, "TRUST", tmp_path / "trusted.json")
    launcher.boundary.ensure_trusted(ws, True, launcher.boundary.read_request(ws))

    _request(ws, 'read = ["/mnt/d/alpha", "/home/u/.ssh"]\n')
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit):
        launcher.boundary.ensure_trusted(ws, False, launcher.boundary.read_request(ws))


def test_unknown_keys_in_request_refuse_to_start(tmp_path):
    """知らない項目は黙って無視しない。読み違えたまま承認させない。"""
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, 'read = ["/mnt/d/alpha"]\nallow_all = true\n')
    with pytest.raises(SystemExit):
        launcher.boundary.read_request(ws)


def test_approval_prompt_shows_what_opens(tmp_path):
    """承認画面に、実際に開くものが出ること。"""
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, 'read = ["/mnt/d/alpha"]\nnetwork_allow = ["api.alpha.test"]\n')
    text = launcher.boundary.describe_request(ws, launcher.boundary.read_request(ws))
    assert "/mnt/d/alpha" in text
    assert "api.alpha.test" in text
    assert str(ws / ".opencode" / "sandbox.toml") in text



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


# --- 渡した引数が opencode まで届くこと -------------------------------------


def test_passthrough_reaches_opencode():
    """★srt の -c はコマンド文字列を 1 個しか取らない。

    後ろへ並べた引数は srt の位置引数になり **エラーも出さずに捨てられる**。
    `ocs --continue` が素の起動になっていた回帰。
    """
    launcher = _launcher()
    got = launcher.cli.inner_command(["--continue"], "/usr/bin")
    assert got.endswith("--standalone --continue"), got
    assert "--session ses_x" in launcher.cli.inner_command(["--session", "ses_x"], "/usr/bin")


def test_passthrough_is_quoted():
    """コマンド文字列へ入れる以上、引用符はこちらで付ける。"""
    launcher = _launcher()
    got = launcher.cli.inner_command(["--prompt", "a; rm -rf /"], "/a b:/usr/bin")
    assert "'a; rm -rf /'" in got, got
    assert "'PATH=/a b:/usr/bin'" in got, got


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
    filesystem = launcher.boundary.build_boundary(_base_sandbox(), wt)["filesystem"]
    assert str(common) in filesystem["allowWrite"], "共有 .git が書けない"


def test_worktree_git_hooks_and_config_stay_protected(tmp_path):
    """★共有 .git を開けても hooks と config は閉じたままにする。

    ここへ書けると **ホストで実行されるコード** を仕込める。
    """
    launcher = _launcher()
    common, wt = _worktree(tmp_path)
    deny_write = launcher.boundary.build_boundary(_base_sandbox(), wt)["filesystem"]["denyWrite"]
    assert str(common / "hooks") in deny_write
    assert str(common / "config") in deny_write


def test_plain_repository_adds_nothing(tmp_path):
    """通常のリポジトリでは足すものが無い (起動ディレクトリの中にある)。"""
    launcher = _launcher()
    repo = tmp_path / "plain"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    assert launcher.boundary.git_common_dir(repo) is None


# --- 境界チェックの再利用 ----------------------------------------------------


def test_check_digest_changes_with_the_boundary(tmp_path, monkeypatch):
    """★境界が変われば再検査になること。

    ここに混ぜ忘れた入力は「変わっても古い合格が使われる」ことになる。
    """
    launcher = _launcher()
    sandbox = {"runtime_path": str(tmp_path / "srt.js")}
    one = launcher.check.check_digest(sandbox, {"filesystem": {"allowWrite": ["/a"]}}, [])
    two = launcher.check.check_digest(sandbox, {"filesystem": {"allowWrite": ["/a", "/b"]}}, [])
    assert one != two, "境界を広げても digest が変わっていない"


def test_check_digest_changes_when_a_hidden_target_appears(tmp_path):
    """★後からホストに現れた秘密を、古い合格で素通りさせないこと。"""
    launcher = _launcher()
    sandbox = {"runtime_path": str(tmp_path / "srt.js")}
    boundary = {"filesystem": {"allowWrite": ["/a"]}}
    before = launcher.check.check_digest(sandbox, boundary, [])
    after = launcher.check.check_digest(sandbox, boundary, ["/home/u/.ssh"])
    assert before != after, "検査対象が増えても digest が変わっていない"


def test_handoff_reads_the_isolated_db_and_writes_the_host_db(tmp_path, monkeypatch):
    """★移送は「隔離用 DB から読み、ホストの DB へ書く」こと。

    取り込み側に ``OPENCODE_DB`` が残っていると隔離用 DB へ書き戻すことに
    なり、境界の外から再開できない。``--standalone`` を付けないことで
    常駐サービス（ホスト DB）へ届かせる。
    """
    launcher = _launcher()
    ws = tmp_path / "proj"
    (ws / ".opencode-sandbox").mkdir(parents=True)
    db = ws / ".opencode-sandbox" / "opencode.db"
    db.write_bytes(b"x")
    monkeypatch.setattr(launcher.session, "HOME", tmp_path / "home")

    calls: list[dict] = []

    def fake_run(cmd, **kw):
        calls.append({"cmd": cmd, "env": kw.get("env") or {}})
        if "export" in cmd:
            Path(kw["stdout"].name).write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(launcher.session, "subprocess", subprocess)
    monkeypatch.setattr(subprocess, "run", fake_run)
    launcher.session.handoff_session(ws, "ses_x")

    export, import_ = calls
    assert "export" in export["cmd"] and "--standalone" in export["cmd"]
    assert export["env"]["OPENCODE_DB"] == str(db), "隔離用 DB から読んでいない"

    assert "import" in import_["cmd"]
    assert "OPENCODE_DB" not in import_["env"], "取り込み側に OPENCODE_DB が残っている"
    assert "--standalone" not in import_["cmd"], "常駐サービス(ホスト DB)へ届かない"
    assert str(ws) in import_["cmd"], "--directory にワークスペースを渡していない"


def test_handoff_staging_is_outside_the_workspace(tmp_path, monkeypatch):
    """★書き出す JSON をワークスペース内に置かないこと。

    境界内から書ける場所に置くと、取り込む前に内容を差し替えられる。
    """
    launcher = _launcher()
    ws = tmp_path / "proj"
    (ws / ".opencode-sandbox").mkdir(parents=True)
    (ws / ".opencode-sandbox" / "opencode.db").write_bytes(b"x")
    home = tmp_path / "home"
    monkeypatch.setattr(launcher.session, "HOME", home)

    seen: list[Path] = []

    def fake_run(cmd, **kw):
        if "export" in cmd:
            path = Path(kw["stdout"].name)
            seen.append(path)
            path.write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    launcher.session.handoff_session(ws, "ses_x")

    assert seen, "書き出しが走っていない"
    assert ws not in seen[0].parents, f"ワークスペース内に置いた: {seen[0]}"
    assert str(home) in str(seen[0]), "状態領域の外に置いた"


def test_seed_db_never_copies_host_conversations(tmp_path, monkeypatch):
    """★ホストの会話をワークスペースへ**一度も書かない**こと。

    以前は ``src.backup(dst)`` で丸ごと写してから要らないテーブルを
    削除していた。削除前の全会話がワークスペース内に存在する時間帯があり、
    同じワークスペースで別セッションが動いていれば読めた。
    """
    launcher = _launcher()
    home = tmp_path / "home"
    source = home / ".local/share/opencode/opencode.db"
    source.parent.mkdir(parents=True)
    con = sqlite3.connect(str(source))
    con.execute("create table credential (id text, integration_id text)")
    con.execute("create table migration (id integer)")
    con.execute("create table session_v2 (id text, title text)")
    con.execute("create table session_message (id text, body text)")
    con.execute("insert into credential values ('c1', 'github-copilot')")
    con.execute("insert into migration values (1)")
    con.execute("insert into session_v2 values ('s1', 'ホストの会話')")
    con.execute("insert into session_message values ('m1', '秘密の本文')")
    con.commit()
    con.close()

    monkeypatch.setattr(launcher.session, "HOME", home)
    out = tmp_path / "ws" / ".opencode-sandbox" / "opencode.db"
    launcher.session.seed_db(out)

    got = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    counts = {
        name: got.execute(f'select count(*) from "{name}"').fetchone()[0]
        for (name,) in got.execute(
            "select name from sqlite_master where type='table'"
            " and name not like 'sqlite_%'"
        )
    }
    got.close()

    assert counts["credential"] == 1, "資格情報が引き継がれていない"
    assert counts["migration"] == 1, "migration が無いと OpenCode が壊れる"
    assert counts["session_v2"] == 0, "ホストの会話が入っている"
    assert counts["session_message"] == 0, "ホストのメッセージが入っている"
    # ★スキーマは残す。テーブルごと消すと OpenCode が作り直せない。
    assert "session_v2" in counts, "スキーマまで落としている"
    # 削除済みデータが空きページに残っていないこと (本文が生で出ないこと)
    assert b"\xe7\xa7\x98\xe5\xaf\x86" not in out.read_bytes(), "本文がファイルに残っている"


def test_seed_db_does_not_leave_a_half_built_db(tmp_path, monkeypatch):
    """★書き途中を ``db.exists()`` に拾わせないこと。

    途中で落ちたものが残ると、次回は初期化を飛ばして**不完全な DB を
    恒久的に再利用**する。別名で作ってから rename する。
    """
    launcher = _launcher()
    home = tmp_path / "home"
    source = home / ".local/share/opencode/opencode.db"
    source.parent.mkdir(parents=True)
    con = sqlite3.connect(str(source))
    con.execute("create table credential (id text)")
    con.commit()
    con.close()

    monkeypatch.setattr(launcher.session, "HOME", home)
    out = tmp_path / "ws" / "opencode.db"
    launcher.session.seed_db(out)

    leftovers = list(out.parent.glob("*.building"))
    assert not leftovers, f"作業用ファイルが残っている: {leftovers}"


def test_boundary_check_is_fail_closed():
    """★検査スクリプトが無ければ起動しないこと。

    以前は ``if not args.skip_check and CHECK.is_file():`` で、配備の失敗や
    ファイル消失が「検査を飛ばして起動」に化けていた。保護が消えても
    誰も気づかない形なので、**存在しないときは die** にする。
    """
    body = (LIB / "cli.py").read_text(encoding="utf-8")
    assert "if not args.skip_check and check.CHECK.is_file():" not in body, (
        "fail-open の条件が残っている"
    )
    assert "if not check.CHECK.is_file():" in body, "検査スクリプトの不在を弾いていない"


def test_boundary_file_lives_outside_the_workspace():
    """★境界の定義をワークスペース内に置かないこと。

    tempfile の既定は TMPDIR に従い、このリポジトリでは TMPDIR が
    ワークスペース内を指す。そこは allowWrite 領域なので、srt が読む前に
    **内側から書き換えられる**（同一 UID では 0600 でも別セッションを
    隔離できない）。
    """
    launcher = _launcher()
    boundaries = launcher.cli.BOUNDARIES
    assert ".local/state/opencode-sandbox" in str(boundaries), (
        f"境界の置き場が状態領域の外: {boundaries}"
    )
    assert "/.tmp" not in str(boundaries), "TMPDIR 配下に置いている"


def test_prune_boundaries_drops_only_stale_files(tmp_path, monkeypatch):
    """★残骸だけ捨て、稼働中のものは残すこと。

    execve で finally が走らないため自分では消せない。次の起動が前回の分を
    捨てるが、並行して動いているセッションの分を消してはいけない。
    """
    launcher = _launcher()
    monkeypatch.setattr(launcher.cli, "BOUNDARIES", tmp_path)
    monkeypatch.setattr(launcher.cli, "BOUNDARY_MAX_AGE_SECONDS", 3600)

    stale = tmp_path / "opencode-boundary-old.json"
    fresh = tmp_path / "opencode-boundary-new.json"
    other = tmp_path / "checked.json"
    for p in (stale, fresh, other):
        p.write_text("{}", encoding="utf-8")
    os.utime(stale, (0, time.time() - 7200))

    launcher.cli.prune_boundaries()

    assert not stale.exists(), "古い残骸が残っている"
    assert fresh.exists(), "稼働中のものを消した"
    assert other.exists(), "対象外のファイルを消した"


def test_check_is_reused_only_while_fresh(tmp_path, monkeypatch):
    """同じ入力の合格は使い回すが、期限を過ぎたら再検査する。"""
    launcher = _launcher()
    monkeypatch.setattr(launcher.check, "CHECKED", tmp_path / "checked.json")
    assert launcher.check.check_is_fresh("d1") is False, "記録が無いのに合格にした"

    launcher.check.save_check("d1")
    assert launcher.check.check_is_fresh("d1") is True
    assert launcher.check.check_is_fresh("d2") is False, "別の入力で合格にした"

    monkeypatch.setattr(launcher.check, "CHECK_TTL_SECONDS", 0)
    assert launcher.check.check_is_fresh("d1") is False, "期限を過ぎても合格にした"


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


def test_skill_roots_are_readable_inside_the_boundary():
    """★skill 置き場が read に載っていること。

    deny_read の ~ に埋もれると skill が 1 つも読めなくなる (実測)。
    """
    read = (gen.opencode_sandbox(COMMON) or {}).get("base", {}).get("read", [])
    joined = " ".join(read)
    assert ".claude/skills" in joined, "~/.claude/skills が読めない"
    assert ".agents/skills" in joined, "~/.agents/skills が読めない"


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


# --- 境界チェックへの受け渡し ------------------------------------------------

CHECK_SCRIPT = ROOT / "home" / "dot_local" / "bin" / "executable_ocs-boundary-check"


def _check_project(workspace: Path, protected: list[str]) -> dict:
    return {
        "workspace": str(workspace),
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
    base = {
        "PATH": f"{fakebin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "XDG_DATA_HOME": str(ws / "data"),
    }
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

    以前は空白で連結して未引用で展開していたので、``a b`` は ``a`` と ``b``
    に割れ、``c*`` は作業領域のファイル名へ化けて、本来の対象を検査しなかった。
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
    """★見えてはいけない対象も、空白で割らずに検査すること。"""
    launcher = _launcher()
    visible = tmp_path / "secret dir"
    visible.mkdir()
    gone = tmp_path / "gone dir"
    done = _run_check_script(
        tmp_path, launcher, [], {"present": [str(visible)], "absent": [str(gone)]}
    )
    assert f"★NG  {visible} が見えている\n" in done.stdout, done.stdout
    assert f"SKIP {gone} はホストに無いので検査しない\n" in done.stdout, done.stdout
    assert done.returncode == 1


def test_check_script_reports_every_failure_before_exiting(tmp_path):
    """★``set -eu`` を入れても集計が途中で切れないこと。

    NG が複数あっても全て並び、最後の判定まで届くこと。
    """
    launcher = _launcher()
    visible = tmp_path / "secret"
    visible.mkdir()
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
    assert done.returncode == 0


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
    """★ホストに無いものは「見えない」を合格の根拠にしない。

    在ると分かっているものだけを検査に回し、無いものは SKIP として示す。
    """
    launcher = _launcher()
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    monkeypatch.setattr(launcher.check, "HOME", home)
    monkeypatch.setattr(launcher.check, "_is_wsl", lambda: False)
    got = launcher.check.hidden_targets()
    canary = home / launcher.check.CANARY_REL
    assert got["present"] == [str(canary), str(home / ".ssh")]
    assert str(home / ".git-credentials") in got["absent"]
    assert str(home / ".config/gh") in got["absent"]
    assert not any(p.startswith("/mnt/c") for p in got["present"] + got["absent"])


def test_check_is_invoked_with_absolute_quoted_shell(tmp_path, monkeypatch):
    """★検査は ``/bin/sh`` を絶対パスで呼び、スクリプトのパスは引用する。

    ``srt -c`` は引用しない ``sh -c`` なので、空白入りのパスは割れる。
    """
    launcher = _launcher()
    check = tmp_path / "bin dir" / "ocs-boundary-check"
    monkeypatch.setattr(launcher.check, "CHECK", check)
    seen: list[list[str]] = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    launcher.check.run_check(
        "/usr/bin/node",
        tmp_path / "srt.js",
        str(tmp_path / "b.json"),
        _check_project(tmp_path, []),
        {},
        {"present": [], "absent": []},
    )
    assert seen[0][-1] == f"/bin/sh '{check}'", seen[0]


def test_canary_is_always_checked_even_without_host_secrets(tmp_path, monkeypatch):
    """★~/.ssh などが 1 つも無い機械でも、目印の分だけは本当に検査する。"""
    launcher = _launcher()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(launcher.check, "HOME", home)
    monkeypatch.setattr(launcher.check, "_is_wsl", lambda: False)
    got = launcher.check.hidden_targets()
    canary = home / launcher.check.CANARY_REL
    assert got["present"] == [str(canary)]
    assert canary.is_file()
    assert canary.stat().st_mode & 0o777 == 0o600


def test_canary_must_not_be_readable_inside_the_boundary(tmp_path):
    """目印は read にも write にも載せない (載ると必ず「見えている」で止まる)。

    ★srt の無い機械でも生成結果が空にならないよう、runtime だけダミーに差し替える。
    """
    runtime = tmp_path / "srt"
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
    base = sandbox["base"]
    opened = [*base["read"], *base["write"]]
    assert opened, "許可のリストが空で、検査になっていない"
    canary = str(Path.home() / _launcher().check.CANARY_REL)
    assert not any(canary == p or canary.startswith(p.rstrip("/") + "/") for p in opened)


def test_srt_runs_with_a_fixed_path():
    """★srt は境界の外で PATH から which / bwrap / socat を起動する。

    利用者の PATH のまま渡すと、先頭の書き込める場所の偽物がホストで動く。
    PATH 以外は変えない。
    """
    launcher = _launcher()
    got = launcher.check.srt_env({"PATH": "/evil:/usr/bin", "HOME": "/h"})
    assert got == {"PATH": "/usr/bin:/bin", "HOME": "/h"}


def test_check_runs_srt_with_a_fixed_path(tmp_path, monkeypatch):
    """★境界チェックで srt を起動するときも PATH を固定する。"""
    launcher = _launcher()
    seen: list[dict] = []

    def fake_run(cmd, **kw):
        seen.append(kw["env"])
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    launcher.check.run_check(
        "/usr/bin/node",
        tmp_path / "srt.js",
        str(tmp_path / "b.json"),
        _check_project(tmp_path, []),
        {"PATH": str(tmp_path / "evil")},
        {"present": [], "absent": []},
    )
    assert seen[0]["PATH"] == "/usr/bin:/bin"


def test_launch_fixes_srt_path_but_keeps_the_users_path_inside(tmp_path, monkeypatch):
    """★srt には固定の PATH を、内側の opencode には利用者の PATH を渡す。

    境界の内側で mise の道具を使えるよう、利用者の PATH はコマンド文字列で戻す。
    rg は srt が境界の外で走らせるので、実体の絶対パスを境界の設定に入れる。
    """
    launcher = _launcher()
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.chdir(ws)
    runtime = tmp_path / "srt.js"
    runtime.write_text("", "utf-8")
    opencode = tmp_path / "opencode"
    opencode.write_text("", "utf-8")
    sandbox = {
        "runtime_path": str(runtime),
        "config_dir": str(tmp_path / "config"),
        "base": {
            "read": [],
            "write": [],
            "deny_read": [],
            "protected": [],
            "network": {"allowedDomains": [], "deniedDomains": []},
        },
        "paths": {"data_home": ".d/data", "db": ".d/opencode.db"},
    }
    monkeypatch.setattr(launcher.boundary, "load_boundary", lambda: sandbox)
    monkeypatch.setattr(launcher.cli, "OPENCODE", opencode)
    monkeypatch.setattr(launcher.cli, "resolve_node", lambda: "/usr/bin/node")
    monkeypatch.setattr(launcher.cli, "BOUNDARIES", tmp_path / "boundaries")
    monkeypatch.setattr(launcher.backup, "backup_worktree", lambda *a: None)
    monkeypatch.setattr(launcher.config, "write_isolated_config", lambda *a: None)
    monkeypatch.setattr(launcher.session, "seed_db", lambda *a: None)
    monkeypatch.setattr(launcher.check, "resolve_ripgrep", lambda config: "/opt/rg/rg")
    monkeypatch.setattr(
        launcher.check, "hidden_targets", lambda: {"present": [], "absent": []}
    )
    user_path = f"{ws / 'bin'}:/usr/bin"
    monkeypatch.setenv("PATH", user_path)
    seen: dict = {}

    def fake_execve(path, argv, env):
        seen.update(argv=argv, env=env, boundary=json.loads(Path(argv[3]).read_text("utf-8")))
        raise SystemExit(0)

    monkeypatch.setattr(os, "execve", fake_execve)
    with pytest.raises(SystemExit):
        launcher.cli.main(["--skip-check", "--no-backup"])

    assert seen["env"]["PATH"] == "/usr/bin:/bin", "srt が利用者の PATH で動く"
    inner = shlex.split(seen["argv"][-1])
    assert inner[:3] == ["/usr/bin/env", f"PATH={user_path}", str(opencode)], inner
    assert seen["boundary"]["ripgrep"] == {"command": "/opt/rg/rg"}


def _fake_rg(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_ripgrep_is_taken_from_mise_installs_not_path(tmp_path, monkeypatch):
    """★rg は PATH からも shim からも探さない。新しい版の実体を選ぶ。"""
    launcher = _launcher()
    installs = tmp_path / "installs"
    _fake_rg(installs / "9.0.0" / "rg-9" / "rg")
    newest = _fake_rg(installs / "14.1.1" / "ripgrep-14.1.1" / "rg")
    (installs / "latest").symlink_to("9.0.0")
    monkeypatch.setattr(launcher.check, "RIPGREP_INSTALLS", installs)
    monkeypatch.setattr(launcher.check, "RIPGREP_SYSTEM", tmp_path / "none")
    config = {"filesystem": {"allowWrite": [str(tmp_path / "ws")]}}
    assert launcher.check.resolve_ripgrep(config) == str(newest)


def test_ripgrep_in_a_writable_area_stops_the_launch(tmp_path, monkeypatch):
    """★境界の内側から書き換えられる rg を srt に渡さない (symlink も実体で比べる)。"""
    launcher = _launcher()
    ws = tmp_path / "ws"
    real = _fake_rg(ws / "bin" / "rg")
    system = tmp_path / "usr" / "rg"
    system.parent.mkdir()
    system.symlink_to(real)
    monkeypatch.setattr(launcher.check, "RIPGREP_INSTALLS", tmp_path / "none")
    monkeypatch.setattr(launcher.check, "RIPGREP_SYSTEM", system)
    config = {"filesystem": {"allowWrite": [str(ws)]}}
    with pytest.raises(SystemExit):
        launcher.check.resolve_ripgrep(config)


def test_missing_ripgrep_stops_the_launch(tmp_path, monkeypatch):
    launcher = _launcher()
    monkeypatch.setattr(launcher.check, "RIPGREP_INSTALLS", tmp_path / "none")
    monkeypatch.setattr(launcher.check, "RIPGREP_SYSTEM", tmp_path / "none" / "rg")
    with pytest.raises(SystemExit):
        launcher.check.resolve_ripgrep({"filesystem": {"allowWrite": []}})


def test_inner_env_marks_the_isolated_session(tmp_path):
    """guide plugin はこの印で隔離版を見分け、表示されない説明の生成を止める。"""
    launcher = _launcher()
    env = launcher.cli.inner_env(_sandbox(tmp_path), _project(tmp_path))
    assert env["OCS_ISOLATED"] == "1"


def test_check_does_not_take_curl_from_the_inherited_path(tmp_path):
    """★検査スクリプトは PATH を固定し、curl を絶対パスで呼ぶ。

    作業領域の PATH にある偽の curl で合格を装わせない。試験用の差し替え口
    (BOUNDARY_CURL) は、ランチャーが利用者の環境から通さない。
    """
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
    """★承認 (trusted.json) と合格 (checked.json) の記録は ocs の外の CLI からも書けない。

    ~/.local/state は Claude / Copilot の write 許可に入っているので、名指しの
    deny が無いと、ocs の外で動くエージェントが承認や合格を偽造できる。
    """
    assert _covers(COMMON["sandbox"]["deny"], STATE_DIR)
    claude = gen.build_claude_sandbox(COMMON)["filesystem"]
    assert _covers(claude["denyWrite"], STATE_DIR)
    copilot = gen.build_copilot_sandbox(None, COMMON)["userPolicy"]["filesystem"]
    assert os.path.expanduser(STATE_DIR) in copilot["deniedPaths"]
    assert f"{STATE_DIR}/**" in COMMON["file"]["write_deny_globs"]


def test_launcher_state_exists_before_agents_start():
    """★Copilot はセッション開始時に無いパスの deny を捨て、途中で作られても効かせない。

    ocs を初めて起動する前に Copilot が作ると、そのセッションでは記録を書ける。
    chezmoi が apply で先に作っておく (0700)。
    """
    assert (ROOT / "home/dot_local/state/private_opencode-sandbox/.keep").is_file()


STATE_CLEANUP = ROOT / "home/.chezmoiscripts/100_linux/run_once_after_127_ocs_state.sh"


def test_records_made_before_the_deny_are_discarded(tmp_path):
    """★保護が効く前に作られた承認と合格は信頼せず 1 回だけ捨てる。退避は残す。"""
    state = tmp_path / ".local/state/opencode-sandbox"
    (state / "backups").mkdir(parents=True)
    for name in ("trusted.json", "checked.json", "boundary-canary"):
        (state / name).write_text("{}", encoding="utf-8")
    (state / "boundaries").symlink_to(tmp_path)
    done = subprocess.run(
        ["/bin/sh", str(STATE_CLEANUP)],
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert sorted(p.name for p in state.iterdir()) == ["backups", "boundary-canary"]
    assert "捨てた" in done.stdout


def test_state_cleanup_is_quiet_without_state(tmp_path):
    done = subprocess.run(
        ["/bin/sh", str(STATE_CLEANUP)],
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert (done.returncode, done.stdout) == (0, "")


@pytest.mark.parametrize("source", ["home/dot_local/bin", "home/dot_local/share/ocs"])
def test_launcher_source_is_protected_inside_the_boundary(source):
    """★ocs の source state は境界の内側から書き換えられないこと (denyWrite)。"""
    protected = COMMON["opencode"]["sandbox"]["protected"]
    assert _covers(protected, source), f"{source} が protected に無い"

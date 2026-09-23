"""ランチャーの設定書き出しに関するテスト。

Run with: ``uv run --with pytest --no-project pytest test/agents/`` or
``python3 -m pytest test/agents/``.

★守りたいのは「緩和に関わるキーは毎回差し替わる」ことと
  「それ以外のキーは残る」ことの両立。
  丸ごと上書きすると、TUI で選んだモデルが毎回消える (実際に出したバグ)。
see docs/change/0004-opencode-sandbox.md
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402
from agents_common import load_common  # noqa: E402

LAUNCHER = ROOT / "home" / "dot_local" / "bin" / "executable_opencode-sandboxed"
COMMON = load_common()


def _launcher() -> dict:
    """ランチャーの関数だけ取り出す (main は動かさない)。"""
    namespace: dict = {"__name__": "probe"}
    exec(compile(LAUNCHER.read_text(encoding="utf-8"), "launcher", "exec"), namespace)
    return namespace


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
    launcher["write_isolated_config"](sandbox, project)

    target = Path(sandbox["config_dir"]) / "opencode.json"
    tampered = json.loads(target.read_text(encoding="utf-8"))
    tampered["permissions"] = []  # 緩めた想定
    tampered["snapshots"] = False
    target.write_text(json.dumps(tampered), encoding="utf-8")

    launcher["write_isolated_config"](sandbox, project)
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
    launcher["write_isolated_config"](sandbox, project)

    target = Path(sandbox["config_dir"]) / "opencode.json"
    config = json.loads(target.read_text(encoding="utf-8"))
    config["model"] = "github-copilot/claude-sonnet-5"
    config["username"] = "alice"
    target.write_text(json.dumps(config), encoding="utf-8")

    launcher["write_isolated_config"](sandbox, project)
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

    launcher["write_isolated_config"](sandbox, project)
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

    launcher["write_isolated_config"](sandbox, project)
    assert current_model() == "github-copilot/claude-opus-5"

    config = json.loads(target.read_text(encoding="utf-8"))
    config["model"] = "github-copilot/claude-sonnet-5"
    target.write_text(json.dumps(config), encoding="utf-8")
    launcher["write_isolated_config"](sandbox, project)
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
    assert launcher["pick_model"](sandbox, project) == "github-copilot/claude-opus-5"


def test_model_is_absent_without_credentials(tmp_path):
    """資格情報が無ければ既定を置かない (誤った provider を固定しない)。"""
    launcher = _launcher()
    sandbox = _sandbox(
        tmp_path,
        model_preference=[{"provider": "amazon-bedrock", "model": "sonnet-5"}],
    )
    project = _project(tmp_path)
    _seed_db(Path(project["db"]), integration="github-copilot")
    assert launcher["pick_model"](sandbox, project) is None


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
    filesystem = launcher["build_boundary"](_base_sandbox(), where)["filesystem"]
    assert str(where) in filesystem["allowWrite"]
    # R1: ワークスペースは allowRead にも完全一致で入れる
    assert str(where) in filesystem["allowRead"]


def test_no_request_means_no_extras(tmp_path):
    """要求が無ければ追加はゼロ。共通分だけで動く。"""
    launcher = _launcher()
    (tmp_path / "gamma").mkdir()
    boundary = launcher["build_boundary"](_base_sandbox(), tmp_path / "gamma")
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

    got = launcher["build_boundary"](_base_sandbox(), alpha)
    assert "/mnt/d/alpha" in got["filesystem"]["allowRead"]
    assert "api.alpha.test" in got["network"]["allowedDomains"]

    other = launcher["build_boundary"](_base_sandbox(), beta)
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
    allow_read = launcher["build_boundary"](_base_sandbox(), inner)["filesystem"][
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
    allow_read = launcher["build_boundary"](_base_sandbox(), ws)["filesystem"][
        "allowRead"
    ]
    assert str(Path.home() / "datasets") in allow_read
    assert str(ws / "sub/dir") in allow_read
    assert "~/datasets" not in allow_read


def test_protected_paths_are_workspace_relative(tmp_path):
    """保護対象は起動ディレクトリと組み合わせる。"""
    launcher = _launcher()
    where = tmp_path / "gamma"
    where.mkdir()
    deny_write = launcher["build_boundary"](_base_sandbox(), where)["filesystem"][
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
    monkeypatch.setitem(launcher, "TRUST", tmp_path / "trusted.json")
    monkeypatch.setattr(launcher["sys"].stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit):
        launcher["ensure_trusted"](ws, False)


def test_approval_is_recorded_outside_the_workspace(tmp_path, monkeypatch):
    """承認の記録は境界の外に置く。内側から書けると自分で承認できる。"""
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, 'read = ["/mnt/d/alpha"]\n')
    trust = tmp_path / "state" / "trusted.json"
    monkeypatch.setitem(launcher, "TRUST", trust)

    launcher["ensure_trusted"](ws, True)  # --trust
    assert ws not in trust.parents, "承認の記録がワークスペースの中にある"
    # 2 回目は尋ねずに通る (端末が無くても落ちない)
    monkeypatch.setattr(launcher["sys"].stdin, "isatty", lambda: False)
    launcher["ensure_trusted"](ws, False)


def test_changed_request_needs_reapproval(tmp_path, monkeypatch):
    """★要求が変わったら承認をやり直す。"""
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, 'read = ["/mnt/d/alpha"]\n')
    monkeypatch.setitem(launcher, "TRUST", tmp_path / "trusted.json")
    launcher["ensure_trusted"](ws, True)

    _request(ws, 'read = ["/mnt/d/alpha", "/home/u/.ssh"]\n')
    monkeypatch.setattr(launcher["sys"].stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit):
        launcher["ensure_trusted"](ws, False)


def test_unknown_keys_in_request_refuse_to_start(tmp_path):
    """知らない項目は黙って無視しない。読み違えたまま承認させない。"""
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, 'read = ["/mnt/d/alpha"]\nallow_all = true\n')
    with pytest.raises(SystemExit):
        launcher["read_request"](ws)


def test_approval_prompt_shows_what_opens(tmp_path):
    """承認画面に、実際に開くものが出ること。"""
    launcher = _launcher()
    ws = tmp_path / "proj"
    ws.mkdir()
    _request(ws, 'read = ["/mnt/d/alpha"]\nnetwork_allow = ["api.alpha.test"]\n')
    text = launcher["describe_request"](ws, launcher["read_request"](ws))
    assert "/mnt/d/alpha" in text
    assert "api.alpha.test" in text
    assert str(ws / ".opencode" / "sandbox.toml") in text



def test_system_prompt_is_written(tmp_path):
    launcher = _launcher()
    sandbox = _sandbox(tmp_path)
    project = _project(tmp_path)
    launcher["write_isolated_config"](sandbox, project)
    agents = Path(sandbox["config_dir"]) / "AGENTS.md"
    assert agents.is_file(), "AGENTS.md が書かれていない"
    assert agents.read_text(encoding="utf-8").strip(), "AGENTS.md が空"

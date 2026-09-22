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
        "db": str(tmp_path / "opencode.db"),
        "permissions": base.get("permissions", fallback),
        "policies": base.get("policies", []),
        "plugins": base.get("plugins", []),
        "system_prompt": base.get("system_prompt", "境界の説明"),
        "model_preference": base.get("model_preference", []),
        **overrides,
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
    launcher["write_isolated_config"](sandbox)

    target = Path(sandbox["config_dir"]) / "opencode.json"
    tampered = json.loads(target.read_text(encoding="utf-8"))
    tampered["permissions"] = []  # 緩めた想定
    tampered["snapshots"] = False
    target.write_text(json.dumps(tampered), encoding="utf-8")

    launcher["write_isolated_config"](sandbox)
    after = json.loads(target.read_text(encoding="utf-8"))
    assert after["permissions"] == sandbox["permissions"], "permissions が戻っていない"
    assert after["snapshots"] is True, "snapshots が戻っていない"


def test_unmanaged_keys_survive(tmp_path):
    """★こちらが管理しないキーは残すこと。

    丸ごと上書きすると、TUI で選んだモデルが起動のたびに消える。
    """
    launcher = _launcher()
    sandbox = _sandbox(tmp_path)
    launcher["write_isolated_config"](sandbox)

    target = Path(sandbox["config_dir"]) / "opencode.json"
    config = json.loads(target.read_text(encoding="utf-8"))
    config["model"] = "github-copilot/claude-sonnet-5"
    config["username"] = "alice"
    target.write_text(json.dumps(config), encoding="utf-8")

    launcher["write_isolated_config"](sandbox)
    after = json.loads(target.read_text(encoding="utf-8"))
    assert after.get("model") == "github-copilot/claude-sonnet-5", "model が消えた"
    assert after.get("username") == "alice", "宣言外のキーが消えた"


def test_broken_config_is_rebuilt(tmp_path):
    """壊れた JSON は作り直す。読めないまま残すと起動できない。"""
    launcher = _launcher()
    sandbox = _sandbox(tmp_path)
    config_dir = Path(sandbox["config_dir"])
    config_dir.mkdir(parents=True)
    (config_dir / "opencode.json").write_text("{これは JSON ではない", encoding="utf-8")

    launcher["write_isolated_config"](sandbox)
    after = json.loads((config_dir / "opencode.json").read_text(encoding="utf-8"))
    assert after["permissions"] == sandbox["permissions"]


def test_default_model_only_on_first_write(tmp_path):
    """既定モデルは初回だけ置き、以降は利用者の選択を尊重する。"""
    launcher = _launcher()
    sandbox = _sandbox(
        tmp_path,
        model_preference=[{"provider": "github-copilot", "model": "claude-opus-5"}],
    )
    _seed_db(Path(sandbox["db"]))
    target = Path(sandbox["config_dir"]) / "opencode.json"

    def current_model() -> str:
        return json.loads(target.read_text(encoding="utf-8"))["model"]

    launcher["write_isolated_config"](sandbox)
    assert current_model() == "github-copilot/claude-opus-5"

    config = json.loads(target.read_text(encoding="utf-8"))
    config["model"] = "github-copilot/claude-sonnet-5"
    target.write_text(json.dumps(config), encoding="utf-8")
    launcher["write_isolated_config"](sandbox)
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
    # bedrock の資格情報は無く、copilot だけある状況
    _seed_db(Path(sandbox["db"]), integration="github-copilot")
    assert launcher["pick_model"](sandbox) == "github-copilot/claude-opus-5"


def test_model_is_absent_without_credentials(tmp_path):
    """資格情報が無ければ既定を置かない (誤った provider を固定しない)。"""
    launcher = _launcher()
    sandbox = _sandbox(
        tmp_path,
        model_preference=[{"provider": "amazon-bedrock", "model": "sonnet-5"}],
    )
    _seed_db(Path(sandbox["db"]), integration="github-copilot")
    assert launcher["pick_model"](sandbox) is None


def test_system_prompt_is_written(tmp_path):
    launcher = _launcher()
    sandbox = _sandbox(tmp_path)
    launcher["write_isolated_config"](sandbox)
    agents = Path(sandbox["config_dir"]) / "AGENTS.md"
    assert agents.is_file(), "AGENTS.md が書かれていない"
    assert agents.read_text(encoding="utf-8").strip(), "AGENTS.md が空"

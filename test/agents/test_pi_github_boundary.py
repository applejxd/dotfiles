"""GitHub ブローカー (CHG-0037 段 U8) の、境界まわりの不変条件。"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_pi_boundary import _ocs


def test_make_agent_dir_is_empty_and_private(tmp_path):
    pi = _ocs().pi
    agent = pi.make_agent_dir(tmp_path / "home")
    assert agent.is_dir() and list(agent.iterdir()) == []
    assert stat.S_IMODE(agent.stat().st_mode) == 0o700


def test_gh_config_points_at_the_socket_and_is_private(tmp_path):
    pi = _ocs().pi
    agent = pi.make_agent_dir(tmp_path / "home")
    sock = agent / "gh.sock"
    config_dir = pi.write_gh_config(agent, sock)
    config = config_dir / "config.yml"
    assert config.read_text(encoding="utf-8").strip() == f"http_unix_socket: {sock}"
    assert stat.S_IMODE(config.stat().st_mode) == 0o600


def test_inner_env_gives_gh_only_a_dummy_token_when_enabled(tmp_path, monkeypatch):
    pi = _ocs().pi
    monkeypatch.setattr(pi.check, "ensure_canary", lambda: None)
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN"):
        monkeypatch.setenv(name, "host-real-value")
    agent = tmp_path / "agent"
    on = pi.inner_env(agent, {"filesystem": {}}, github=True)
    assert on["GH_TOKEN"] != "host-real-value" and "host-real" not in on["GH_TOKEN"]
    assert on["GH_CONFIG_DIR"] == str(agent / "gh")
    assert on["GH_NO_UPDATE_NOTIFIER"] == "1" and on["GH_TELEMETRY"] == "false"
    assert on["GH_PROMPT_DISABLED"] == "1"
    assert "GITHUB_TOKEN" not in on and "GH_ENTERPRISE_TOKEN" not in on


def test_inner_env_leaves_gh_alone_when_disabled(tmp_path, monkeypatch):
    pi = _ocs().pi
    monkeypatch.setattr(pi.check, "ensure_canary", lambda: None)
    monkeypatch.setenv("GH_TOKEN", "host-real-value")
    off = pi.inner_env(tmp_path / "agent", {"filesystem": {}})
    assert "GH_TOKEN" not in off and "GH_CONFIG_DIR" not in off
    assert os.environ["GH_TOKEN"] == "host-real-value"  # ホスト側は変えない

"""起動ディレクトリの中の秘密ファイルを、OS の層 (Fence の ``denyRead``) でも隠す試験。

``[file] read_deny_globs`` に当たる実在のファイルを起動時に列挙して ``denyRead`` へ足す
(``boundary.hide_workspace_secrets``)。実機 (Fence) での読み取り拒否は、ここでは見ない
(手で確かめた結果は docs に書く)。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from agents_common import ROOT
from test_broker import _ocs

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="境界は Linux 専用")

COMMON = """\
[file]
read_deny_globs = ["**/.env", "**/.env.*", "**/secrets/**", "**/.ssh/**"]

[[file.deny_exceptions]]
deny = "**/.env.*"
except = ["**/.env.example"]
"""


@pytest.fixture
def boundary():
    _ocs()
    return sys.modules["ocs_lib.boundary"]


@pytest.fixture
def agents(tmp_path):
    directory = tmp_path / "agents"
    directory.mkdir()
    shutil.copy(ROOT / "home/dot_config/agents/command_policy.py", directory)
    (directory / "common.toml").write_text(COMMON, encoding="utf-8")
    return directory


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "ws"
    (ws / "sub" / "secrets").mkdir(parents=True)
    (ws / "sub" / ".ssh").mkdir()
    (ws / "node_modules").mkdir()
    (ws / ".git").mkdir()
    for name in (".env", ".env.example", ".env.local", "sub/.env", "ok.txt", "sub/secrets/k"):
        (ws / name).write_text("x\n", encoding="utf-8")
    (ws / "sub" / ".ssh" / "id").write_text("x\n", encoding="utf-8")
    (ws / "node_modules" / ".env").write_text("x\n", encoding="utf-8")
    (ws / ".git" / ".env").write_text("x\n", encoding="utf-8")
    return ws


def _relative(paths, ws):
    return sorted(str(Path(p).relative_to(ws.resolve())) for p in paths)


def test_workspace_files_matching_read_deny_are_listed(boundary, agents, workspace):
    config = {"filesystem": {"denyRead": ["/already"]}}
    hidden = boundary.hide_workspace_secrets(config, workspace, agents)
    assert _relative(hidden, workspace) == [
        ".env",
        ".env.local",
        "sub/.env",
        "sub/.ssh",
        "sub/secrets",
    ]
    # 既存の項目は残り、足した分が加わる。例外 (.env.example)・無関係なファイルは入らない
    assert config["filesystem"]["denyRead"][0] == "/already"
    assert set(config["filesystem"]["denyRead"][1:]) == set(hidden)


def test_directory_rules_hide_the_directory_not_each_file(boundary, agents, workspace):
    hidden = _relative(
        boundary.hide_workspace_secrets({"filesystem": {}}, workspace, agents), workspace
    )
    assert "sub/secrets" in hidden and "sub/secrets/k" not in hidden


def test_heavy_directories_are_not_entered(boundary, agents, workspace):
    hidden = boundary.hide_workspace_secrets({"filesystem": {}}, workspace, agents)
    assert not any("node_modules" in h or "/.git/" in h for h in hidden)


def test_symlinks_are_not_followed_and_are_listed_by_their_real_path(
    boundary, agents, workspace, tmp_path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / ".env").write_text("x\n", encoding="utf-8")
    (workspace / "link").symlink_to(outside)
    hidden = boundary.hide_workspace_secrets({"filesystem": {}}, workspace, agents)
    assert str(outside.resolve() / ".env") not in hidden  # 中には降りない


def test_missing_policy_stops_the_launch(boundary, workspace, tmp_path):
    with pytest.raises(SystemExit):
        boundary.hide_workspace_secrets({"filesystem": {}}, workspace, tmp_path / "nowhere")


def test_empty_read_deny_stops_the_launch(boundary, agents, workspace):
    (agents / "common.toml").write_text("[file]\nread_deny_globs = []\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        boundary.hide_workspace_secrets({"filesystem": {}}, workspace, agents)


def test_too_many_hits_stops_the_launch(boundary, agents, workspace, monkeypatch):
    monkeypatch.setattr(boundary, "SECRET_SCAN_MAX_DENY", 1)
    with pytest.raises(SystemExit):
        boundary.hide_workspace_secrets({"filesystem": {}}, workspace, agents)


def test_too_large_workspace_stops_the_launch(boundary, agents, workspace, monkeypatch):
    monkeypatch.setattr(boundary, "SECRET_SCAN_MAX_ENTRIES", 3)
    with pytest.raises(SystemExit):
        boundary.hide_workspace_secrets({"filesystem": {}}, workspace, agents)


def test_pis_hides_workspace_secrets_after_building_the_boundary():
    source = (ROOT / "home/dot_local/share/ocs/pi.py").read_text(encoding="utf-8")
    build = source.index("config_ = boundary.build_boundary(")
    assert source.index("boundary.hide_workspace_secrets(config_, workspace)") > build

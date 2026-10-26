"""素の pi の起動時に、フルガードの判定の外で動きうるものを知らせる (``unguarded.ts``) の試験。

``test/agents/pi/unguarded_driver.mjs`` が unguarded.ts を読んで結果を JSON で出す
(node の型除去を使うので、22.18 未満の node では飛ばす)。
see docs/spec/guard/pi-guard.md#判定の外で動くもの
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "unguarded_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


def _run(tmp_path, argv=()):
    proc = subprocess.run(
        [
            _node(),
            str(RUNNER),
            json.dumps(
                {
                    "agentDir": str(tmp_path / "agent"),
                    "cwd": str(tmp_path / "proj"),
                    "argv": list(argv),
                }
            ),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-1500:]
    return json.loads(proc.stdout)


@pytest.fixture
def dirs(tmp_path):
    (tmp_path / "agent").mkdir()
    (tmp_path / "proj" / ".pi").mkdir(parents=True)
    return tmp_path


def test_nothing_to_report_for_a_clean_setup(dirs):
    assert _run(dirs)["found"] == []


def test_project_skills_are_not_reported(dirs):
    (dirs / "proj" / ".agents" / "skills" / "x").mkdir(parents=True)
    (dirs / "proj" / ".pi" / "skills" / "y").mkdir(parents=True)
    assert _run(dirs)["found"] == []


def test_global_mcp_servers_are_reported(dirs):
    (dirs / "agent" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"a": {"command": "x"}}}), encoding="utf-8"
    )
    found = _run(dirs)["found"]
    assert len(found) == 1 and "mcp.json" in found[0]


def test_empty_or_server_less_mcp_json_is_quiet(dirs):
    (dirs / "agent" / "mcp.json").write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    assert _run(dirs)["found"] == []


def test_unreadable_mcp_json_is_reported(dirs):
    (dirs / "agent" / "mcp.json").write_text("{broken", encoding="utf-8")
    assert len(_run(dirs)["found"]) == 1


def test_project_extensions_mcp_and_settings_are_reported(dirs):
    pi = dirs / "proj" / ".pi"
    (pi / "extensions").mkdir()
    (pi / "extensions" / "e.ts").write_text("export default () => {}\n", encoding="utf-8")
    (pi / "mcp.json").write_text(
        json.dumps({"mcpServers": {"b": {"command": "y"}}}), encoding="utf-8"
    )
    (pi / "settings.json").write_text(json.dumps({"defaultTools": ["bash"]}), encoding="utf-8")
    found = _run(dirs)["found"]
    assert len(found) == 3
    assert "判定の外" in _run(dirs)["message"]


def test_unrelated_project_settings_are_quiet(dirs):
    (dirs / "proj" / ".pi" / "settings.json").write_text(
        json.dumps({"theme": "dark"}), encoding="utf-8"
    )
    assert _run(dirs)["found"] == []


@pytest.mark.parametrize("flag", ["--no-approve", "-na"])
def test_project_resources_are_not_reported_when_trust_is_declined(dirs, flag):
    pi = dirs / "proj" / ".pi"
    (pi / "extensions").mkdir()
    (pi / "extensions" / "e.ts").write_text("x\n", encoding="utf-8")
    assert _run(dirs, [flag])["found"] == []

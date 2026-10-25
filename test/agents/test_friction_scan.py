"""friction_scan.py (不満・摩擦の手がかりの集計) の試験。合成のログだけを使う。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts" / "agents"


def _load():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("friction_scan", SCRIPTS / "friction_scan.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _message(role, content, stamp="2026-10-25T01:00:00.000Z", **extra):
    return {
        "type": "message",
        "timestamp": stamp,
        "message": {"role": role, "content": content, **extra},
    }


def _session(tmp_path: Path) -> Path:
    events = [
        _message("system", ""),
        _message(
            "user",
            [
                {
                    "type": "text",
                    "text": "ちょっと待って。token は ghp_" + "a" * 30 + " ではなく別です",
                }
            ],
        ),
        _message(
            "assistant",
            [
                {
                    "type": "toolCall",
                    "id": "1",
                    "name": "ask",
                    "arguments": {"questions": "コミットしてよいですか"},
                }
            ],
        ),
        _message(
            "assistant",
            [
                {
                    "type": "toolCall",
                    "id": "2",
                    "name": "guarded_bash",
                    "arguments": {"command": "git commit -m x"},
                }
            ],
        ),
        _message(
            "toolResult",
            [{"type": "text", "text": "not approved: 拒否された"}],
            toolName="guarded_bash",
            isError=True,
        ),
        _message(
            "toolResult",
            [{"type": "text", "text": "Invalid arguments 12"}],
            toolName="ask",
            isError=True,
        ),
        _message(
            "toolResult",
            [{"type": "text", "text": "Invalid arguments 34"}],
            toolName="ask",
            isError=True,
        ),
        _message(
            "toolResult",
            [{"type": "text", "text": "Invalid arguments 56"}],
            toolName="ask",
            isError=True,
        ),
        _message("user", [{"type": "text", "text": "普通の依頼です"}]),
    ]
    path = tmp_path / "s.jsonl"
    path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", encoding="utf-8"
    )
    return path


def test_metrics_and_excerpts(tmp_path):
    scan = _load()
    result = scan.scan_session(_session(tmp_path), "")
    m = result["metrics"]
    assert m["user_turns"] == 2
    assert m["tool_errors"] == 4
    assert m["not_approved"] == 1
    assert m["error_streaks"] == 1  # ask が 3 回続けて失敗
    assert result["errors_by_tool"] == {"guarded_bash": 1, "ask": 3}
    assert m["routing.publish_calls"] == 1
    assert m["routing.publish_after_ask"] == 1  # 直前の ask のあとの commit は二重承認の候補


def test_excerpt_is_redacted_and_only_cued_turns(tmp_path):
    scan = _load()
    result = scan.scan_session(_session(tmp_path), "")
    (excerpt,) = result["excerpts"]
    assert "ghp_" not in excerpt["text"] and "<token>" in excerpt["text"]
    assert excerpt["text"].startswith("ちょっと待って")


def test_merge_and_render_keep_no_raw_log(tmp_path):
    scan = _load()
    total = scan.merge([scan.scan_session(_session(tmp_path), "")])
    report = scan.render(total, 1, "")
    assert "二重承認の候補" in report and "ghp_" not in report


def test_since_filters_old_events(tmp_path):
    scan = _load()
    result = scan.scan_session(_session(tmp_path), "2026-12-01")
    assert result["metrics"].get("user_turns", 0) == 0

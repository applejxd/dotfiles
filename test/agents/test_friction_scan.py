"""friction_scan.py (不満・摩擦の手がかりの集計) の試験。合成のログだけを使う。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".agents" / "skills" / "friction-review" / "scripts"


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


# --- 承認・拒否・時間切れの集計 (CHG-0054 段 1) ---


def _action_call(call_id, action):
    return _message(
        "assistant",
        [
            {
                "type": "toolCall",
                "id": call_id,
                "name": "guarded_action",
                "arguments": {"action": action, "params": {}},
            }
        ],
    )


def _result(call_id, tool, text, is_error=False, details=None):
    extra = {"toolCallId": call_id, "toolName": tool, "isError": is_error}
    if details is not None:
        extra["details"] = details
    return _message("toolResult", [{"type": "text", "text": text}], **extra)


def _write(tmp_path, events, name="a.jsonl"):
    path = tmp_path / name
    path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", encoding="utf-8"
    )
    return path


def _approval_events():
    return [
        _action_call("1", "git_commit"),
        _result("1", "guarded_action", "ok", details={"action": "git_commit", "auto": False}),
        _action_call("2", "git_commit"),
        _result(
            "2",
            "guarded_action",
            "ok",
            details={"action": "git_commit", "freeZone": {"free": True}},
        ),
        _action_call("3", "gitflow_feature_start"),
        _result(
            "3", "guarded_action", "ok", details={"action": "gitflow_feature_start", "auto": True}
        ),
        _action_call("4", "gitflow_feature_finish"),
        _result(
            "4",
            "guarded_action",
            "not approved: 利用者が拒否した。同じ操作をくり返さない",
            True,
            {},
        ),
        _action_call("5", "gitflow_feature_finish"),
        _result(
            "5",
            "guarded_action",
            "not approved: 確認が時間内に無かったので拒否した。再試行せず待つ",
            True,
            {},
        ),
        _action_call("6", "gitflow_feature_finish"),
        _result(
            "6",
            "guarded_action",
            "not approved: 確認が 5 分の時間切れになった。元の操作は未実行。",
            True,
            {},
        ),
        _action_call("7", "git_commit"),
        _result(
            "7",
            "guarded_action",
            "not approved: 元の操作は未実行。保留 abc に保存した。再試行しない",
            True,
            {},
        ),
        _action_call("8", "git_commit"),
        _result("8", "guarded_action", "ok", details={"action": "git_commit"}),
        _result("9", "guarded_bash", "not approved: 確認が時間内に無かったので拒否した。", True),
        _result("10", "guarded_read", "普通の結果"),
    ]


def test_approvals_categories_and_rule_fallback(tmp_path):
    scan = _load()
    table = scan.scan_approvals(_write(tmp_path, _approval_events()), "")
    assert table["guarded_action:git_commit"] == {
        "承認": 1,
        "確認なしで実行": 1,
        "保留に保存": 1,
        "不明": 1,
    }
    assert table["guarded_action:gitflow_feature_start"] == {"確認なしで実行": 1}
    assert table["guarded_action:gitflow_feature_finish"] == {"拒否": 1, "時間切れ": 2}
    assert table["guarded_bash"] == {"時間切れ": 1}  # 規則名が無い行はツール名で代替
    assert "guarded_read" not in table


def test_approvals_ignore_broken_lines_and_empty_log(tmp_path):
    scan = _load()
    path = tmp_path / "b.jsonl"
    path.write_text("{壊れた\n[]\n" + json.dumps(_message("user", "x")) + "\n", encoding="utf-8")
    assert scan.scan_approvals(path, "") == {}  # 1 行だけ、tool 名の無い結果は数えない
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert scan.scan_approvals(empty, "") == {}
    assert scan.merge_approvals([{}, {}])["rules"] == {}


def test_approvals_floor_marks_rules_below_20(tmp_path):
    scan = _load()
    events = []
    for i in range(20):
        events += [
            _action_call(f"x{i}", "git_commit"),
            _result(
                f"x{i}", "guarded_action", "ok", details={"action": "git_commit", "auto": False}
            ),
        ]
    events += [
        _action_call("y", "gh_issue_edit_body"),
        _result(
            "y", "guarded_action", "ok", details={"action": "gh_issue_edit_body", "auto": False}
        ),
    ]
    path = _write(tmp_path, events)
    total = scan.merge_approvals([scan.scan_approvals(path, ""), scan.scan_approvals(path, "")])
    rules = total["rules"]
    assert rules["guarded_action:git_commit"]["total"] == 40
    assert rules["guarded_action:git_commit"]["enough"] is True
    assert rules["guarded_action:gh_issue_edit_body"]["enough"] is False
    assert total["min_per_rule"] == 20
    text = scan.render_approvals(total)
    assert "下限未満" in text and "代替" in text
    assert "git commit" not in text


def test_approvals_cli_json(tmp_path, capsys):
    scan = _load()
    proj = tmp_path / "proj"
    proj.mkdir()
    _write(proj, _approval_events())
    assert scan.main(["--root", str(tmp_path), "--approvals", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["rules"]["guarded_action:gitflow_feature_finish"]["counts"]["時間切れ"] == 2


def test_report_includes_approvals_section(tmp_path):
    scan = _load()
    result = scan.scan_session(_write(tmp_path, _approval_events()), "")
    assert result["approvals"]["guarded_action:git_commit"]["承認"] == 1
    total = scan.merge([result])
    assert "承認" in scan.render(total, 1, "") and "guarded_action:git_commit" in scan.render(
        total, 1, ""
    )

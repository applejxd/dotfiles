"""自動の通知を畳む表示 (``home/dot_config/pi/harness/quiet-notices.ts``) の純関数の試験。

``test/agents/pi/quiet_notices_driver.mjs`` に入力の配列を渡し、表示行を見る (node の型除去を使うので、22.18 未満の node では飛ばす)。
モデルに渡す本文 (content) は変えない: 純関数は content を入力に取り、書き換えない。

see docs/spec/guard/pi-extensions.md#自動の通知を畳む表示
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "quiet_notices_driver.mjs"
HARNESS = ROOT / "home" / "dot_config" / "pi" / "harness"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


def run(cases):
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        input=json.dumps(cases),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1000:]
    return json.loads(proc.stdout)


def notice(kind, content, details=None, **kw):
    return {
        "fn": "notice",
        "args": {
            "kind": kind,
            "content": content,
            "details": details,
            "width": 80,
            "env": {},
            **kw,
        },
    }


def child(status="done", agent="worker", title="goal-eval の評価を直す", **kw):
    stats = {"durationMs": 211_000, "calls": 9, "tokens": 5000, "cost": 0.58}
    d = {
        "agent": agent,
        "status": status,
        "blocked": 0,
        "errors": 0,
        "stats": stats,
        "id": "j7",
        "title": title,
    }
    d.update(kw)
    return d


FULL = "バックグラウンドの子 j7 (worker) が終わりました\nchild worker: completed [3s]\n\nanswer:\n長い報告\n行2"


def test_child_done_is_one_line_within_46_columns():
    (r,) = run([notice("child-finished", FULL, child())])
    assert r["folded"] is True and len(r["lines"]) == 1
    line = r["lines"][0]
    assert line.startswith("✓ worker") and "3:31" in line and "$0.58" in line and "完了" in line
    assert r["widths"][0] <= 46


@pytest.mark.parametrize(
    ("status", "mark", "word"),
    [
        ("failed", "✗", "失敗"),
        ("limit", "✗", "時間切れ"),
        ("aborted", "✗", "中断"),
        ("blocked", "⚠", "承認待ち"),
    ],
)
def test_problem_statuses_are_never_hidden(status, mark, word):
    (r,) = run([notice("child-finished", FULL, child(status=status, title="とても長い題名" * 10))])
    line = r["lines"][0]
    assert line.startswith(mark) and word in line
    assert r["widths"][0] <= 46


def test_warnings_show_count_on_done():
    content = FULL.replace("answer:", "format check (the answer lacks):\n- missing: x\nanswer:")
    (r,) = run([notice("child-finished", content, child(errors=2))])
    line = r["lines"][0]
    assert line.startswith("⚠") and "要確認" in line and "⚠3件" in line
    assert r["level"] == "warn" and r["widths"][0] <= 46


def test_answer_text_with_warning_words_is_not_counted():
    content = FULL.replace("長い報告", "format check (x\n⚠ foo")
    (r,) = run([notice("child-finished", content, child())])
    assert r["lines"][0].startswith("✓")


def test_wide_title_width_counts_double():
    (r,) = run([notice("child-finished", FULL, child(title="全角" * 40), width=46)])
    assert r["widths"][0] <= 46


def test_narrow_width_is_respected():
    (r,) = run([notice("child-finished", FULL, child(), width=30)])
    assert r["widths"][0] <= 30


def test_batch_children():
    (ok, bad) = run(
        [
            notice("child-finished", "x", {"statuses": ["done", "done"]}),
            notice("child-finished", "x", {"statuses": ["done", "failed", "limit"]}),
        ]
    )
    assert ok["lines"][0].startswith("✓ 並列 2 件")
    assert bad["lines"][0].startswith("✗") and "2/3" in bad["lines"][0]


def test_bg_job():
    ok_text = "バックグラウンドジョブ bg-3 が終わりました (exit 0)\nコマンド: make test\n--- ログ ---\nfoo (exit 9)"
    bad_text = ok_text.replace("(exit 0)", "(exit 2)")
    many = "バックグラウンドジョブ 2 件が終わりました\n- bg-1 (exit 0): a\n    ok\n- bg-2 (exit 1): b\n    ng"
    ok, bad, multi = run(
        [
            notice("bg-job-finished", ok_text, {"id": "bg-3", "exit": 0, "ids": ["bg-3"]}),
            notice("bg-job-finished", bad_text, {"id": "bg-3", "exit": 2, "ids": ["bg-3"]}),
            notice("bg-job-finished", many, {"id": "bg-1", "exit": 0, "ids": ["bg-1", "bg-2"]}),
        ]
    )
    assert ok["lines"][0].startswith("✓ job") and "make test" in ok["lines"][0]
    assert bad["lines"][0].startswith("✗") and "exit 2" in bad["lines"][0]
    assert multi["lines"][0].startswith("✗ job 2 件") and "1/2" in multi["lines"][0]
    assert all(x["widths"][0] <= 46 for x in (ok, bad, multi))


def test_todo_reminder_and_autocheckpoint():
    todo, todo0, save, save0 = run(
        [
            notice("todo-reminder", "作業中のまま終わろうとしています", {"open": 4}),
            notice("todo-reminder", "x"),
            notice("autocheckpoint", "【自動の保存】…", {"percent": 82.4}),
            notice("autocheckpoint", "【自動の保存】…"),
        ]
    )
    assert todo["lines"] == ["📌 続き: 未完了 4 件"]
    assert todo0["lines"] == ["📌 続き: 未完了あり"]
    assert save["lines"] == ["💾 保存を指示（使用率 82%）"]
    assert save0["lines"] == ["💾 保存を指示"]


def test_expanded_and_kill_switch_show_full_content_unchanged():
    for kind in ("child-finished", "bg-job-finished", "todo-reminder", "autocheckpoint"):
        expanded, off, quiet = run(
            [
                notice(kind, FULL, child(), expanded=True),
                notice(kind, FULL, child(), env={"PI_QUIET_NOTICES": "0"}),
                notice(kind, FULL, child()),
            ]
        )
        assert expanded["lines"] == FULL.split("\n") and expanded["folded"] is False
        assert off["lines"] == FULL.split("\n") and off["folded"] is False
        assert quiet["folded"] is True and len(quiet["lines"]) == 1


COMMIT = (
    "[feature/x abc1234] feat: 表示を畳む\n 2 files changed, 3 insertions(+)\n"
    "trailing whitespace......................................................Passed\n"
    "check yaml...........................................(no files to check)Skipped\n"
    "ruff.....................................................................Passed\n\n"
    "確認なしで実行した (自由区: feature/x。実行後の HEAD: abc1234)"
)


def test_action_success_is_folded_and_hooks_summarized():
    (r,) = run(
        [
            {
                "fn": "action",
                "args": {
                    "text": COMMIT,
                    "details": {"action": "git_commit", "repo": "chezmoi"},
                    "width": 100,
                },
            }
        ]
    )
    assert r["folded"] is True
    assert r["lines"][0] == "✓ chezmoi feature/x abc1234 feat: 表示を畳む"
    assert "pre-commit: 全 3 項目 Passed（うち Skipped 1）" in r["lines"]
    assert any(line.startswith("確認なしで実行した") for line in r["lines"])
    assert not any("trailing whitespace" in line for line in r["lines"])


def test_action_failed_hook_is_kept():
    text = COMMIT.replace(
        "ruff.....................................................................Passed",
        "ruff...Failed\n- hook id: ruff\nE501 line too long",
    )
    (r,) = run([{"fn": "action", "args": {"text": text, "details": {"action": "git_commit"}}}])
    assert "ruff...Failed" in r["lines"] and "E501 line too long" in r["lines"]
    assert not any("trailing whitespace" in line for line in r["lines"])


def test_action_without_details_expanded_or_off_shows_full():
    cases = [
        {"fn": "action", "args": {"text": COMMIT, "details": None}},
        {
            "fn": "action",
            "args": {"text": COMMIT, "details": {"action": "git_commit"}, "expanded": True},
        },
        {
            "fn": "action",
            "args": {
                "text": COMMIT,
                "details": {"action": "git_commit"},
                "env": {"PI_QUIET_NOTICES": "0"},
            },
        },
    ]
    for r in run(cases):
        assert r["lines"] == COMMIT.split("\n") and r["folded"] is False


def test_user_markdown_only_resume_is_folded():
    on, other, off = run(
        [
            {"fn": "user", "args": {"markdown": "【自動の再開】圧縮が完了した。…"}},
            {"fn": "user", "args": {"markdown": "こんにちは"}},
            {
                "fn": "user",
                "args": {"markdown": "【自動の再開】x", "env": {"PI_QUIET_NOTICES": "0"}},
            },
        ]
    )
    assert on["text"] == "▶ 再開を指示（自動）"
    assert other["text"] == "こんにちは"
    assert off["text"] == "【自動の再開】x"


def test_width_and_component_wrap():
    w, c = run(
        [
            {"fn": "width", "args": {"text": "ab全角🙂"}},
            {"fn": "component", "args": {"lines": ["全" * 30], "width": 20}},
        ]
    )
    assert w["width"] == 2 + 4 + 2
    assert c["rows"] == ["全" * 10, "全" * 10, "全" * 10]


def test_wiring_in_index_and_autocheckpoint_and_todo():
    index = (HARNESS / "index.ts").read_text(encoding="utf-8")
    assert "registerQuietNotices(pi)" in index and "foldActionResult" in index
    assert "details: { ...detailsOf(job, r, alive), id: job.id" in index
    # 本文 (content) には手を入れない: 通知の content の組み立ては従来のまま
    assert (
        "content: `バックグラウンドの子 ${job.id} (${job.agent}) が終わりました (${stamp})\\n${body}`"
        in index
    )
    assert "details: { percent }" in (HARNESS / "autocheckpoint.ts").read_text(encoding="utf-8")
    todo = (ROOT / "home" / "dot_pi" / "agent" / "extensions" / "todo" / "index.ts").read_text(
        encoding="utf-8"
    )
    assert 'customType: "todo-reminder", content, display: true, details: { open:' in todo

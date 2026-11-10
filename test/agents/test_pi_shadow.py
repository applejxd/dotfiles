"""judge/shadow.ts (観測) と scripts/shadow_stats.py の試験。

- 記録の形式、コマンド全文・引用文字列が記録に入らないこと、would_tighten の条件、cmd 名の上限
- 応答の不変 (baseline と同じ入力集合で、観測の有効 / 無効の応答が一致する。凍結した応答を渡しても変わらない)
- 追記の失敗・上限、PI_SHADOW=0・子・ツールの絞り込み、簡易ブレーカー、analyze の例外
- 集計 (shadow_stats.py)

see docs/spec/guard/pi-decide.md#shadow観測
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

DRIVER = ROOT / "test" / "agents" / "pi" / "shadow_driver.mjs"
sys.path.insert(0, str(ROOT / "scripts"))
import shadow_stats  # noqa: E402


def run_cases(cases: list[dict], timeout: int = 300) -> list:
    node = _node()
    assert node is not None
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "cases.json"
        path.write_text(json.dumps(cases), encoding="utf-8")
        proc = subprocess.run(
            [node, str(DRIVER), str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=ROOT,
            timeout=timeout,
            check=False,
        )
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    return json.loads(proc.stdout)


def rec(cmd: str, decision: str = "allow", **kw) -> dict:
    return run_cases(
        [{"op": "record", "cmd": cmd, "response": {"decision": decision, "source": "rule"}, **kw}]
    )[0]


def observe(tmp_path, cmds, **kw) -> dict:
    return run_cases([{"op": "observe", "dir": str(tmp_path), "cmds": cmds, **kw}])[0]


# --- 記録の形式


def test_record_shape():
    r = rec("git log -1")
    assert set(r) == {
        "t",
        "role",
        "mode",
        "tool",
        "old",
        "len",
        "head",
        "ok",
        "why",
        "sites",
        "cmds",
        "ms",
        "would_tighten",
        "vendor_missing",
        "error",
    }
    assert r["old"] == {"decision": "allow", "source": "rule"}
    assert (r["ok"], r["why"], r["sites"], r["cmds"], r["len"], r["head"]) == (
        True,
        None,
        1,
        ["git"],
        10,
        "git",
    )
    assert r["would_tighten"] is False and r["vendor_missing"] is False and r["error"] is None


_AUTH_HEADER = "Author" + "ization"


@pytest.mark.parametrize(
    "cmd",
    [
        "echo 'sk-SECRETVALUE-123456'",
        # gitleaks の誤検出を避けるため、ヘッダ名は変数で組み立てる
        f'curl -H "{_AUTH_HEADER}: Bearer abcdef123456" https://x',
        "TOKEN=hunter2hunter2 git log",
        'git commit -m "パスワードは zzz-yyy-xxx"',
        'echo "unterminated sk-LEAK-987654',
    ],
)
def test_record_has_no_command_text(cmd):
    text = json.dumps(rec(cmd), ensure_ascii=False)
    for frag in (
        "SECRET",
        "abcdef123456",
        "hunter2",
        "zzz-yyy",
        "LEAK",
        "Bearer",
        "Authorization",
        "https",
    ):
        assert frag not in text, (frag, text)


def test_head_word_is_unsafe_for_assignment_and_quotes():
    assert rec("TOKEN=abc123 git log")["head"] == "?"
    assert rec('"git" log')["head"] == "?"
    assert rec("  git log")["head"] == "git"


def test_cmds_are_capped_at_eight():
    r = rec("; ".join(f"echo {i}" for i in range(12)))
    assert r["ok"] is True and r["sites"] == 12
    assert len(r["cmds"]) == 8


def test_non_literal_cmd_name_is_masked():
    r = rec("$X log")
    assert r["ok"] is True and r["cmds"] == ["?"]


def test_cmd_names_do_not_include_arguments():
    r = rec("git log --grep=secret-pattern /etc/shadow")
    assert r["cmds"] == ["git"]


@pytest.mark.parametrize(
    ("decision", "cmd", "expect"),
    [
        ("allow", 'echo "unterminated', True),
        ("ask", 'echo "unterminated', True),
        ("deny", 'echo "unterminated', False),
        ("allow", "git log", False),
        ("ask", "git log", False),
    ],
)
def test_would_tighten_condition(decision, cmd, expect):
    assert rec(cmd, decision)["would_tighten"] is expect


@pytest.mark.parametrize(
    ("why", "missing"),
    [("load", True), ("sha", True), ("eval", True), ("syntax", False), ("ctl", False)],
)
def test_vendor_missing_flag(why, missing):
    plan = {"ok": False, "source": "x", "why": why, "detail": "d"}
    r = run_cases(
        [
            {
                "op": "record",
                "input": {
                    "role": "r",
                    "mode": "ask",
                    "tool": "bash",
                    "cmd": "x",
                    "response": {"decision": "allow"},
                    "plan": plan,
                    "ms": 1,
                },
            }
        ]
    )[0]
    assert r["vendor_missing"] is missing and r["why"] == why and r["would_tighten"] is True
    assert "detail" not in json.dumps(r)


def test_error_records_only_the_name():
    inp = {
        "role": "r",
        "mode": "ask",
        "tool": "bash",
        "cmd": "x",
        "response": {"decision": "allow"},
        "error": {"name": "TypeError", "message": "sk-LEAK"},
        "ms": 1,
    }
    r = run_cases([{"op": "record", "input": inp}])[0]
    assert r["error"] == "TypeError" and r["ok"] is None and r["would_tighten"] is False
    assert "LEAK" not in json.dumps(r)


@pytest.mark.parametrize(
    ("cmd", "ok", "why"),
    [
        ("git log", True, None),
        ('echo "unterminated', False, "syntax"),
        ("echo a\rb", False, "ctl"),
        ("echo " + "x" * 10001, False, "limit:len"),
    ],
)
def test_record_of_real_analyze(cmd, ok, why):
    r = rec(cmd)
    assert (r["ok"], r["why"]) == (ok, why)


# --- 追記


def test_append_creates_directory_and_lines_are_json(tmp_path):
    f = tmp_path / "a" / "b" / "s.jsonl"
    r = run_cases([{"op": "append", "file": str(f), "n": 3}])[0]
    assert r["ok"] == 3
    assert [json.loads(line)["tool"] for line in f.read_text().splitlines()] == ["bash"] * 3


def test_append_failure_does_not_raise_when_parent_is_a_file(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    r = run_cases([{"op": "append", "file": str(blocker / "sub" / "s.jsonl")}])[0]
    assert r["ok"] == 0


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="読み取り専用が効く環境のみ")
def test_append_failure_does_not_raise_on_readonly_dir(tmp_path):
    d = tmp_path / "ro"
    d.mkdir()
    d.chmod(0o555)
    try:
        r = run_cases([{"op": "append", "file": str(d / "s.jsonl"), "n": 2}])[0]
    finally:
        d.chmod(0o755)
    assert r["ok"] == 0


def test_size_limit_stops_recording(tmp_path):
    f = tmp_path / "s.jsonl"
    r = run_cases([{"op": "append", "file": str(f), "n": 50, "maxBytes": 1000}])[0]
    assert 0 < r["ok"] < 50 and r["size"] <= 1000


def test_default_limit_is_five_megabytes():
    src = (ROOT / "home" / "dot_config" / "pi" / "harness" / "judge" / "shadow.ts").read_text(
        encoding="utf-8"
    )
    assert "MAX_SHADOW_BYTES = 5 * 1024 * 1024" in src and "BUDGET_MS = 200" in src


def test_session_name_is_sanitized(tmp_path):
    out = observe(tmp_path, ["git log"], session="../../evil")
    assert len(out["lines"]) == 1
    assert not (tmp_path.parent / "evil.jsonl").exists()


# --- 有効 / 無効・子・ツール


def test_enabled_by_default(tmp_path):
    out = observe(tmp_path, ["git log", "git status"])
    assert len(out["lines"]) == 2 and out["tripped"] is False


def test_pi_shadow_zero_disables(tmp_path):
    assert observe(tmp_path, ["git log"], env={"PI_SHADOW": "0"})["lines"] == []


def test_pi_shadow_one_stays_enabled(tmp_path):
    assert len(observe(tmp_path, ["git log"], env={"PI_SHADOW": "1"})["lines"]) == 1


def test_child_does_not_record(tmp_path):
    assert observe(tmp_path, ["git log"], env={"PI_HARNESS_CHILD": "1"})["lines"] == []


def test_non_bash_tool_is_ignored(tmp_path):
    assert observe(tmp_path, ["git log"], tool="read")["lines"] == []


def test_bg_run_is_recorded(tmp_path):
    out = observe(tmp_path, ["git log"], tool="bg_run")
    assert [r["tool"] for r in out["lines"]] == ["bg_run"]


def test_non_string_command_is_ignored(tmp_path):
    out = observe(tmp_path, [None, 5, "git log"])
    assert out["threw"] is False and len(out["lines"]) == 1


# --- ブレーカー・例外・応答の不変


def test_breaker_stops_after_slow_call(tmp_path):
    out = observe(tmp_path, ["git log"] * 4, analyze="slow")
    assert out["tripped"] is True
    # 1 回目は vendor 読み込みを含むので対象外。2 回目の遅さで止まり、その 1 件までは記録する
    assert len(out["lines"]) == 2 and out["lines"][-1]["ms"] > 200


def test_breaker_exempts_first_call(tmp_path):
    out = observe(tmp_path, ["git log"], analyze="slow")
    assert out["tripped"] is False and len(out["lines"]) == 1


def test_breaker_not_tripped_when_fast(tmp_path):
    out = observe(tmp_path, ["git log"] * 5, budgetMs=1e9, analyze="slow")
    assert out["tripped"] is False and len(out["lines"]) == 5


def test_analyze_exception_keeps_response_and_records_error(tmp_path):
    resp = {"decision": "ask", "reason": "r", "source": "rule"}
    out = observe(tmp_path, ["git log"], analyze="throw", response=resp)
    assert out["threw"] is False and out["resp"] == resp
    (line,) = out["lines"]
    assert line["error"] == "TypeError" and line["ok"] is None and line["would_tighten"] is False


def test_frozen_response_is_not_mutated(tmp_path):
    resp = {"decision": "allow", "reason": "r", "source": "rule", "mustConfirm": False}
    out = observe(tmp_path, ['echo "x', "git log"], response=resp)
    assert out["resp"] == resp and len(out["lines"]) == 2


def test_responses_are_identical_for_all_baseline_inputs(tmp_path):
    """baseline と同じ入力集合 (decide_golden + 真理値表) で、観測の有効 / 無効の応答が 1 バイトも変わらない。"""
    r = run_cases([{"op": "invariance", "dir": str(tmp_path)}], timeout=900)[0]
    assert r["total"] > 1000 and r["bash"] > 1000
    assert r["diffs"] == 0
    assert r["offExists"] is False
    assert r["onLines"] == r["bash"]
    assert r["leaks"] == 0


# --- 集計 (scripts/shadow_stats.py)


def _row(**kw) -> dict:
    base = {
        "ok": True,
        "why": None,
        "ms": 1.0,
        "would_tighten": False,
        "vendor_missing": False,
        "error": None,
        "head": "git",
    }
    return {**base, **kw}


def test_percentile():
    assert shadow_stats.percentile([], 50) == 0.0
    vals = [float(i) for i in range(1, 101)]
    assert shadow_stats.percentile(vals, 50) == 50.0
    assert shadow_stats.percentile(vals, 90) == 90.0
    assert shadow_stats.percentile(vals, 99) == 99.0


def test_summarize_counts():
    rows = [
        _row(),
        _row(),
        _row(ok=False, why="syntax", would_tighten=True, head="awk"),
        _row(ok=False, why="load", vendor_missing=True, head="awk"),
        _row(error="TypeError", ok=None),
    ]
    s = shadow_stats.summarize(rows)
    assert s["total"] == 5 and s["failed"] == 2 and s["fail_rate"] == pytest.approx(0.4)
    assert s["would_tighten"] == 1 and s["tighten_why"] == [("syntax", 1)]
    assert s["vendor_missing"] == 1 and s["errors"] == 1
    assert s["failed_heads"] == [("awk", 2)]


def test_load_skips_broken_lines_and_reads_directories(tmp_path):
    (tmp_path / "a.jsonl").write_text(
        json.dumps(_row()) + "\nnot json\n[1]\n" + json.dumps(_row(ok=False)) + "\n"
    )
    (tmp_path / "b.jsonl").write_text(json.dumps(_row()) + "\n")
    assert len(shadow_stats.load([tmp_path])) == 3
    assert len(shadow_stats.load([tmp_path / "a.jsonl"])) == 2
    assert shadow_stats.load([tmp_path / "none.jsonl"]) == []


def test_main_prints_report(tmp_path, capsys):
    (tmp_path / "a.jsonl").write_text(
        json.dumps(_row(ok=False, why="syntax", would_tighten=True, head="awk")) + "\n"
    )
    assert shadow_stats.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "would_tighten" in out and "p99" in out and "awk=1" in out and "syntax=1" in out


def test_main_without_records_returns_one(tmp_path, capsys):
    assert shadow_stats.main([str(tmp_path)]) == 1
    assert "記録がない" in capsys.readouterr().out


def test_stats_reads_what_shadow_writes(tmp_path):
    out = observe(tmp_path, ["git log", 'echo "x'])
    s = shadow_stats.summarize(out["lines"])
    assert s["total"] == 2 and s["failed"] == 1 and s["would_tighten"] == 1

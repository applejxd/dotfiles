"""away-shift skill の停止ガード (away_guard.py) の挙動を確認する。

無人実行では「止まるべきときに止まる」ことが最優先なので、停止条件の判定を
ここで押さえる。exit code の意味は継続 0 / 停止 3 / 誤用 2。

Run with: ``uv run --with pytest --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = (
    ROOT
    / "home"
    / "dot_claude"
    / "skills"
    / "away-shift"
    / "scripts"
    / "executable_away_guard.py"
)


def load_guard():
    spec = importlib.util.spec_from_file_location("away_guard", GUARD_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["away_guard"] = module
    spec.loader.exec_module(module)
    return module


guard = load_guard()


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def init_run(run_id: str, deadline: str = "8h", max_cycles: int = 20) -> int:
    return guard.main(
        [
            "init",
            "--goal",
            "テスト目標",
            "--deadline",
            deadline,
            "--run-id",
            run_id,
            "--max-cycles",
            str(max_cycles),
        ]
    )


# ---------------------------------------------------------------------------
# 期限のパース
# ---------------------------------------------------------------------------

def test_clock_deadline_in_the_future_stays_today():
    base = dt.datetime(2026, 9, 9, 22, 0)
    assert guard.parse_deadline("23:30", base) == dt.datetime(2026, 9, 9, 23, 30)


def test_clock_deadline_already_passed_rolls_to_tomorrow():
    """離席時の指定。過ぎた時刻は翌日とみなす（夜→翌朝、昼→翌昼）."""
    base = dt.datetime(2026, 9, 9, 22, 0)
    assert guard.parse_deadline("07:30", base) == dt.datetime(2026, 9, 10, 7, 30)


def test_absolute_datetime_deadline():
    base = dt.datetime(2026, 9, 9, 22, 0)
    assert guard.parse_deadline("2026-09-11 06:00", base) == dt.datetime(
        2026, 9, 11, 6, 0
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [("8h", dt.timedelta(hours=8)), ("90m", dt.timedelta(minutes=90))],
)
def test_duration_deadline(text, expected):
    base = dt.datetime(2026, 9, 9, 22, 0)
    assert guard.parse_deadline(text, base) == base + expected


@pytest.mark.parametrize("text", ["bogus", "25:99:00", "", "8d", "7:5"])
def test_invalid_deadline_is_rejected(text):
    with pytest.raises(ValueError):
        guard.parse_deadline(text, dt.datetime(2026, 9, 9, 22, 0))


def test_init_rejects_a_deadline_in_the_past(workspace):
    assert init_run("past", deadline="2020-01-01 00:00") == guard.EXIT_USAGE
    assert not (workspace / ".tmp" / "away-shift" / "past").exists()


def test_init_rejects_an_unparsable_deadline(workspace):
    assert init_run("bad", deadline="bogus") == guard.EXIT_USAGE


# ---------------------------------------------------------------------------
# run の作成
# ---------------------------------------------------------------------------

def test_init_creates_the_evidence_and_work_directories(workspace):
    assert init_run("r1") == guard.EXIT_CONTINUE
    run = workspace / ".tmp" / "away-shift" / "r1"
    assert (run / "state.json").exists()
    assert (run / "cycles").is_dir()
    assert (run / "work").is_dir()


def test_init_reuses_an_existing_run(workspace):
    init_run("r1", max_cycles=3)
    guard.main(["check", "r1"])
    init_run("r1", max_cycles=99)
    state = json.loads((workspace / ".tmp/away-shift/r1/state.json").read_text())
    # 再利用なので cycle も max_cycles も引き継がれる
    assert state["cycle"] == 1
    assert state["max_cycles"] == 3


# ---------------------------------------------------------------------------
# 停止条件
# ---------------------------------------------------------------------------

def test_check_continues_and_counts_cycles(workspace):
    init_run("r1")
    assert guard.main(["check", "r1"]) == guard.EXIT_CONTINUE
    assert guard.main(["check", "r1"]) == guard.EXIT_CONTINUE
    state = json.loads((workspace / ".tmp/away-shift/r1/state.json").read_text())
    assert state["cycle"] == 2


def test_check_stops_at_the_deadline(workspace, monkeypatch):
    init_run("r1", deadline="90m")
    later = dt.datetime.now() + dt.timedelta(hours=2)
    monkeypatch.setattr(guard, "now", lambda: later)
    assert guard.main(["check", "r1"]) == guard.EXIT_STOP
    state = json.loads((workspace / ".tmp/away-shift/r1/state.json").read_text())
    assert state["stopped"] == "deadline"


def test_check_reserves_time_for_the_report(workspace):
    """残りが予備時間を下回ったら、期限前でも新しいサイクルを始めない."""
    init_run("r1", deadline="10m")
    assert guard.main(["check", "r1"]) == guard.EXIT_STOP


def test_reserve_minutes_is_configurable(workspace):
    init_run("r1", deadline="10m")
    assert (
        guard.main(["check", "r1", "--reserve-minutes", "1"]) == guard.EXIT_CONTINUE
    )


def test_check_stops_at_max_cycles(workspace):
    init_run("r1", max_cycles=1)
    assert guard.main(["check", "r1"]) == guard.EXIT_CONTINUE
    assert guard.main(["check", "r1"]) == guard.EXIT_STOP


@pytest.mark.parametrize(
    "stop_path",
    [".tmp/away-shift/r1/STOP", ".tmp/away-shift/r1/stop", "STOP", "stop"],
)
def test_check_stops_on_a_stop_file(workspace, stop_path):
    """ユーザは run_id を知らなくてもリポジトリ直下の STOP で止められる."""
    init_run("r1")
    path = workspace / stop_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    assert guard.main(["check", "r1"]) == guard.EXIT_STOP


def test_stop_file_wins_over_a_remaining_deadline(workspace):
    init_run("r1", deadline="8h")
    (workspace / "STOP").touch()
    assert guard.main(["check", "r1"]) == guard.EXIT_STOP


def test_check_on_an_unknown_run_is_a_usage_error(workspace):
    assert guard.main(["check", "missing"]) == guard.EXIT_USAGE


# ---------------------------------------------------------------------------
# ペース配分 (離席時間いっぱい使う)
# ---------------------------------------------------------------------------

def wake_seconds(capsys) -> int:
    for line in capsys.readouterr().out.splitlines():
        if line.startswith("NEXT_WAKE_SECONDS:"):
            return int(line.split(":", 1)[1])
    raise AssertionError("NEXT_WAKE_SECONDS が出力されていない")


def test_check_spreads_cycles_over_the_remaining_time(workspace, capsys):
    """8 時間 / 20 サイクルなら 1 サイクルあたり 20 分強になる."""
    init_run("r1", deadline="8h", max_cycles=20)
    assert guard.main(["check", "r1"]) == guard.EXIT_CONTINUE
    seconds = wake_seconds(capsys)
    # (480 - 15) / 19 = 24.4 分。境界の丸めを許容して幅で見る
    assert 20 * 60 <= seconds <= 26 * 60


def test_wake_interval_is_capped_for_manage_schedule(workspace, capsys):
    """manage_schedule の wakeup は 1 時間で頭打ちなので超えない."""
    init_run("r1", deadline="12h", max_cycles=2)
    assert guard.main(["check", "r1"]) == guard.EXIT_CONTINUE
    assert wake_seconds(capsys) == 60 * 60


def test_wake_interval_has_a_floor(workspace, capsys):
    """残りが少なくても 0 秒にはしない (即時再開の暴走を防ぐ)."""
    init_run("r1", deadline="30m", max_cycles=20)
    assert (
        guard.main(["check", "r1", "--reserve-minutes", "1"]) == guard.EXIT_CONTINUE
    )
    assert wake_seconds(capsys) == 60


def test_stop_output_has_no_wake_hint(workspace, capsys):
    init_run("r1", max_cycles=1)
    guard.main(["check", "r1"])
    capsys.readouterr()
    assert guard.main(["check", "r1"]) == guard.EXIT_STOP
    assert "NEXT_WAKE_SECONDS" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 記録
# ---------------------------------------------------------------------------

def test_log_appends_to_the_current_cycle(workspace):
    init_run("r1")
    guard.main(["check", "r1"])
    guard.main(["log", "r1", "--text", "一回目"])
    guard.main(["log", "r1", "--text", "二回目"])
    body = (workspace / ".tmp/away-shift/r1/cycles/cycle-001.md").read_text(
        encoding="utf-8"
    )
    assert "一回目" in body
    assert "二回目" in body


def test_log_follows_the_cycle_counter(workspace):
    init_run("r1")
    guard.main(["check", "r1"])
    guard.main(["log", "r1", "--text", "c1"])
    guard.main(["check", "r1"])
    guard.main(["log", "r1", "--text", "c2"])
    cycles = sorted((workspace / ".tmp/away-shift/r1/cycles").iterdir())
    assert [p.name for p in cycles] == ["cycle-001.md", "cycle-002.md"]

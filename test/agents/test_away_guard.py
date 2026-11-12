"""away-shift skill の停止ガード (away_guard.py) の挙動を確認する。

無人実行では「止まるべきときに止まる」ことが最優先なので、停止条件の判定を
ここで押さえる。exit code の意味は継続 0 / 停止 3 / 誤用 2。

Run with: ``uv run --with pytest --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = (
    ROOT / "home" / "dot_agents" / "skills" / "away-shift" / "scripts" / "executable_away_guard.py"
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
    assert guard.parse_deadline("2026-09-11 06:00", base) == dt.datetime(2026, 9, 11, 6, 0)


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
    assert guard.main(["check", "r1", "--reserve-minutes", "1"]) == guard.EXIT_CONTINUE


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
    assert guard.main(["check", "r1", "--reserve-minutes", "1"]) == guard.EXIT_CONTINUE
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
    body = (workspace / ".tmp/away-shift/r1/cycles/cycle-001.md").read_text(encoding="utf-8")
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


# ---------------------------------------------------------------------------
# 閉じ込め (書き込み先・読み取り先が .tmp/away-shift/ の外へ出ない)
# ---------------------------------------------------------------------------

BAD_RUN_IDS = ["/abs/path", "../x", "a/b", "", ".", "..", "a..b", "x" * 65, ".hid"]


def symlink_or_skip(link: Path, target: Path, is_dir: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=is_dir)
    except (OSError, NotImplementedError):
        pytest.skip("シンボリックリンクを作れない環境")


def hardlink_or_skip(link: Path, target: Path) -> None:
    try:
        os.link(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("ハードリンクを作れない環境")


def snapshot(base: Path) -> set[str]:
    return {str(p.relative_to(base)) for p in base.rglob("*")}


@pytest.mark.parametrize("run_id", BAD_RUN_IDS)
def test_invalid_run_id_is_refused_by_every_subcommand(workspace, run_id):
    before = snapshot(workspace)
    assert init_run(run_id) == guard.EXIT_USAGE
    assert guard.main(["check", run_id]) == guard.EXIT_USAGE
    assert guard.main(["log", run_id, "--text", "x"]) == guard.EXIT_USAGE
    assert guard.main(["status", run_id]) == guard.EXIT_USAGE
    assert snapshot(workspace) == before


def test_run_id_with_a_trailing_newline_is_refused(workspace):
    before = snapshot(workspace)
    assert init_run("r1\n") == guard.EXIT_USAGE
    assert guard.main(["check", "r1\n"]) == guard.EXIT_USAGE
    assert snapshot(workspace) == before


def test_auto_generated_run_id_is_valid(workspace):
    assert guard.main(["init", "--goal", "g", "--deadline", "8h"]) == guard.EXIT_CONTINUE
    runs = list((workspace / ".tmp/away-shift").iterdir())
    assert len(runs) == 1
    assert guard._RUN_ID_RE.match(runs[0].name)


def test_away_shift_root_env_does_not_move_the_root(workspace, monkeypatch):
    elsewhere = workspace / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("AWAY_SHIFT_ROOT", str(elsewhere))
    assert init_run("r1") == guard.EXIT_CONTINUE
    assert (workspace / ".tmp/away-shift/r1/state.json").exists()
    assert not any(elsewhere.iterdir())


def test_script_as_subprocess_uses_the_cwd_root(workspace):
    env = {**os.environ, "AWAY_SHIFT_ROOT": "/nonexistent"}
    result = subprocess.run(
        [
            sys.executable,
            str(GUARD_PATH),
            "init",
            "--goal",
            "g",
            "--deadline",
            "8h",
            "--run-id",
            "r1",
        ],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert (workspace / ".tmp/away-shift/r1/state.json").exists()


def test_symlinked_dot_tmp_is_refused(workspace):
    target = workspace / "real"
    target.mkdir()
    symlink_or_skip(workspace / ".tmp", target, is_dir=True)
    assert init_run("r1") == guard.EXIT_USAGE
    assert not any(target.iterdir())


def test_symlinked_root_is_refused(workspace):
    target = workspace / "real"
    target.mkdir()
    (workspace / ".tmp").mkdir()
    symlink_or_skip(workspace / ".tmp/away-shift", target, is_dir=True)
    assert init_run("r1") == guard.EXIT_USAGE
    assert not any(target.iterdir())


def test_symlinked_run_directory_is_refused(workspace):
    init_run("r1")
    target = workspace / "real"
    target.mkdir()
    symlink_or_skip(workspace / ".tmp/away-shift/r2", target, is_dir=True)
    assert init_run("r2") == guard.EXIT_USAGE
    assert guard.main(["check", "r2"]) == guard.EXIT_USAGE
    assert guard.main(["log", "r2", "--text", "x"]) == guard.EXIT_USAGE
    assert not any(target.iterdir())


def test_symlinked_state_json_is_refused_and_target_untouched(workspace):
    init_run("r1")
    victim = workspace / "victim.json"
    victim.write_text("{}", encoding="utf-8")
    state = workspace / ".tmp/away-shift/r1/state.json"
    state.unlink()
    symlink_or_skip(state, victim)
    assert guard.main(["check", "r1"]) == guard.EXIT_USAGE
    assert init_run("r1") == guard.EXIT_USAGE
    assert victim.read_text(encoding="utf-8") == "{}"


def test_symlinked_cycles_directory_is_refused(workspace):
    init_run("r1")
    target = workspace / "real"
    target.mkdir()
    cycles = workspace / ".tmp/away-shift/r1/cycles"
    cycles.rmdir()
    symlink_or_skip(cycles, target, is_dir=True)
    assert guard.main(["log", "r1", "--text", "x"]) == guard.EXIT_USAGE
    assert not any(target.iterdir())


def test_symlinked_cycle_log_is_refused(workspace):
    init_run("r1")
    victim = workspace / "victim.md"
    victim.write_text("orig", encoding="utf-8")
    symlink_or_skip(workspace / ".tmp/away-shift/r1/cycles/cycle-000.md", victim)
    assert guard.main(["log", "r1", "--text", "x"]) == guard.EXIT_USAGE
    assert victim.read_text(encoding="utf-8") == "orig"


def test_hardlinked_state_json_is_refused(workspace):
    init_run("r1")
    state = workspace / ".tmp/away-shift/r1/state.json"
    hardlink_or_skip(workspace / "alias.json", state)
    before = state.read_text(encoding="utf-8")
    assert guard.main(["check", "r1"]) == guard.EXIT_USAGE
    assert guard.main(["status", "r1"]) == guard.EXIT_USAGE
    assert state.read_text(encoding="utf-8") == before


def test_hardlinked_cycle_log_is_refused(workspace):
    init_run("r1")
    log = workspace / ".tmp/away-shift/r1/cycles/cycle-000.md"
    log.write_text("orig", encoding="utf-8")
    hardlink_or_skip(workspace / "alias.md", log)
    assert guard.main(["log", "r1", "--text", "x"]) == guard.EXIT_USAGE
    assert (workspace / "alias.md").read_text(encoding="utf-8") == "orig"


def test_state_is_replaced_without_leaving_a_temp_file(workspace):
    init_run("r1")
    guard.main(["check", "r1"])
    run = workspace / ".tmp/away-shift/r1"
    assert sorted(p.name for p in run.iterdir()) == ["cycles", "state.json", "work"]


# ---------------------------------------------------------------------------
# 停止の確定 / 引数の範囲
# ---------------------------------------------------------------------------


def test_force_is_an_unknown_argument(workspace):
    argv = ["init", "--goal", "g", "--deadline", "8h", "--run-id", "r1", "--force"]
    with pytest.raises(SystemExit) as exc:
        guard.main(argv)
    assert exc.value.code == guard.EXIT_USAGE
    assert not (workspace / ".tmp").exists()


def test_check_on_a_stopped_run_is_final_and_changes_nothing(workspace, capsys):
    init_run("r1", max_cycles=1)
    guard.main(["check", "r1"])
    assert guard.main(["check", "r1"]) == guard.EXIT_STOP
    state_file = workspace / ".tmp/away-shift/r1/state.json"
    before = state_file.read_text(encoding="utf-8")
    capsys.readouterr()
    assert guard.main(["check", "r1"]) == guard.EXIT_STOP
    out = capsys.readouterr().out
    assert "max-cycles" in out
    assert state_file.read_text(encoding="utf-8") == before
    assert json.loads(before)["cycle"] == 1
    # 停止済みでも log / status はレポート用に使える
    assert guard.main(["log", "r1", "--text", "x"]) == guard.EXIT_CONTINUE
    assert guard.main(["status", "r1"]) == guard.EXIT_CONTINUE


@pytest.mark.parametrize("minutes", ["0", "121", "-1"])
def test_max_wake_minutes_out_of_range_is_a_usage_error(workspace, minutes):
    init_run("r1")
    with pytest.raises(SystemExit) as exc:
        guard.main(["check", "r1", "--max-wake-minutes", minutes])
    assert exc.value.code == guard.EXIT_USAGE
    state = json.loads((workspace / ".tmp/away-shift/r1/state.json").read_text())
    assert state["cycle"] == 0


# ---------------------------------------------------------------------------
# log --note-file
# ---------------------------------------------------------------------------


def note_run(workspace) -> Path:
    init_run("r1")
    return workspace / ".tmp/away-shift/r1/work"


def log_note(name: str) -> int:
    return guard.main(["log", "r1", "--note-file", name])


def test_note_file_is_appended_like_text(workspace):
    work = note_run(workspace)
    (work / "note.md").write_text("本文\n$(not run)\n", encoding="utf-8")
    assert log_note("note.md") == guard.EXIT_CONTINUE
    body = (workspace / ".tmp/away-shift/r1/cycles/cycle-000.md").read_text(encoding="utf-8")
    assert "\n## " in body
    assert body.rstrip().endswith("本文\n$(not run)")


def test_note_file_and_text_are_exclusive(workspace):
    work = note_run(workspace)
    (work / "n.md").write_text("x", encoding="utf-8")
    code = guard.main(["log", "r1", "--text", "a", "--note-file", "n.md"])
    assert code == guard.EXIT_USAGE
    assert not (workspace / ".tmp/away-shift/r1/cycles/cycle-000.md").exists()


@pytest.mark.parametrize(
    "name",
    ["../x", "../../etc/passwd", "sub/n.md", "/etc/passwd", ".hidden", "..", "", "a\\b"],
)
def test_note_file_rejects_bad_names(workspace, name):
    note_run(workspace)
    (workspace / "x").write_text("secret", encoding="utf-8")
    assert log_note(name) == guard.EXIT_USAGE
    assert not (workspace / ".tmp/away-shift/r1/cycles/cycle-000.md").exists()


def test_note_file_missing_is_refused(workspace):
    note_run(workspace)
    assert log_note("nope.md") == guard.EXIT_USAGE


def test_note_file_directory_is_refused(workspace):
    work = note_run(workspace)
    (work / "d").mkdir()
    assert log_note("d") == guard.EXIT_USAGE


def test_note_file_symlink_is_refused(workspace):
    work = note_run(workspace)
    secret = workspace / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    symlink_or_skip(work / "n.md", secret)
    assert log_note("n.md") == guard.EXIT_USAGE
    assert not (workspace / ".tmp/away-shift/r1/cycles/cycle-000.md").exists()


def test_note_file_hardlink_is_refused(workspace):
    work = note_run(workspace)
    secret = workspace / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    hardlink_or_skip(work / "n.md", secret)
    assert log_note("n.md") == guard.EXIT_USAGE


def test_note_file_over_64_kib_is_refused(workspace):
    work = note_run(workspace)
    (work / "big.md").write_bytes(b"a" * (64 * 1024 + 1))
    assert log_note("big.md") == guard.EXIT_USAGE
    (work / "ok.md").write_bytes(b"a" * (64 * 1024))
    assert log_note("ok.md") == guard.EXIT_CONTINUE


def test_note_file_non_utf8_is_refused(workspace):
    work = note_run(workspace)
    (work / "bin.md").write_bytes(b"\xff\xfe\x00bad")
    assert log_note("bin.md") == guard.EXIT_USAGE


# ---------------------------------------------------------------------------
# sleep
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["0", "7201", "-1", "abc", "1.5", ""])
def test_sleep_rejects_out_of_range_or_non_integer(workspace, value):
    with pytest.raises(SystemExit) as exc:
        guard.main(["sleep", value])
    assert exc.value.code == guard.EXIT_USAGE


def test_sleep_waits_and_touches_nothing(workspace):
    assert guard.main(["sleep", "1"]) == guard.EXIT_CONTINUE
    assert not (workspace / ".tmp").exists()


def test_sleep_prints_the_note_as_one_bounded_line(workspace, capsys):
    """bg_run の完了通知に run_id と再開手順を載せる。改行は空白にし、長さに上限を付ける。"""
    assert guard.main(["sleep", "1", "--note", "away-shift r1 cycle 3:\n手順 3 から再開"]) == guard.EXIT_CONTINUE
    out = capsys.readouterr().out
    assert out == "away-shift r1 cycle 3: 手順 3 から再開\n"
    assert not (workspace / ".tmp").exists()
    assert guard.main(["sleep", "1", "--note", "x" * 1000]) == guard.EXIT_CONTINUE
    assert capsys.readouterr().out == "x" * guard.NOTE_MAX_CHARS + "\n"


def test_sleep_without_a_note_prints_nothing(workspace, capsys):
    assert guard.main(["sleep", "1"]) == guard.EXIT_CONTINUE
    assert capsys.readouterr().out == ""


def test_sleep_limit_covers_the_default_wake_interval():
    assert guard.SLEEP_MAX_SECONDS >= 60 * 60


# ---------------------------------------------------------------------------
# snapshot: 作業用コピー (隔離ではない)
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture()
def repo(workspace, monkeypatch):
    _git(workspace, "init", "-q")
    (workspace / ".gitignore").write_text(".tmp/\nbuild/\n")
    (workspace / "a.py").write_text("print('a')\n")
    (workspace / "sub").mkdir()
    (workspace / "sub" / "b.py").write_text("print('b')\n")
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-q", "-m", "init")
    assert init_run("r1") == 0
    return workspace


def _src(repo: Path) -> Path:
    return repo / ".tmp" / "away-shift" / "r1" / "work" / "src"


def test_snapshot_copies_tracked_modified_and_untracked_but_not_ignored(repo, capsys):
    (repo / "a.py").write_text("print('changed')\n")  # 未コミットの変更
    (repo / "new.py").write_text("print('new')\n")  # 未追跡
    (repo / "build").mkdir()
    (repo / "build" / "out.bin").write_text("generated")  # ignored

    assert guard.main(["snapshot", "r1"]) == 0

    src = _src(repo)
    assert (src / "a.py").read_text() == "print('changed')\n"
    assert (src / "new.py").exists()
    assert (src / "sub" / "b.py").exists()
    assert not (src / "build").exists()
    assert not (src / ".git").exists()  # コピーは Git リポジトリではない
    out = capsys.readouterr().out
    assert "隔離ではない" in out
    assert "git diff --no-index" in out


def test_snapshot_leaves_the_original_untouched(repo):
    before = (repo / "a.py").read_text()
    assert guard.main(["snapshot", "r1"]) == 0
    (_src(repo) / "a.py").write_text("edited in the copy\n")
    assert (repo / "a.py").read_text() == before


def test_snapshot_skips_secrets_symlinks_and_reports_them(repo, capsys):
    (repo / ".env").write_text("TOKEN=x\n")
    (repo / ".env.example").write_text("TOKEN=\n")
    (repo / "id_rsa").write_text("key\n")
    (repo / "my_secret_notes.txt").write_text("s\n")  # 部分一致の glob (*secret*)
    (repo / ".ssh").mkdir()
    (repo / ".ssh" / "config").write_text("Host x\n")
    (repo / "link.py").symlink_to("a.py")
    outside = repo.parent / f"{repo.name}-outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("s")
    (repo / "dirlink").symlink_to(outside)

    assert guard.main(["snapshot", "r1"]) == 0

    src = _src(repo)
    assert not (src / ".env").exists()
    assert (src / ".env.example").exists()
    assert not (src / "id_rsa").exists()
    assert not (src / "my_secret_notes.txt").exists()
    assert not (src / ".ssh").exists()
    assert not (src / "link.py").exists()
    assert not (src / "dirlink").exists()
    out = capsys.readouterr().out
    assert "除外 (protected)" in out
    assert "除外 (symlink)" in out


def test_snapshot_refuses_existing_copy_unless_replace(repo):
    assert guard.main(["snapshot", "r1"]) == 0
    (_src(repo) / "scratch.txt").write_text("x")
    assert guard.main(["snapshot", "r1"]) == guard.EXIT_USAGE
    assert (_src(repo) / "scratch.txt").exists()
    assert guard.main(["snapshot", "r1", "--replace"]) == 0
    assert not (_src(repo) / "scratch.txt").exists()


def test_snapshot_refuses_over_the_limits_and_copies_nothing(repo):
    assert guard.main(["snapshot", "r1", "--max-files", "1"]) == guard.EXIT_USAGE
    assert not _src(repo).exists()
    (repo / "big.bin").write_bytes(b"x" * (2 * 1024 * 1024))
    assert guard.main(["snapshot", "r1", "--max-mb", "1"]) == guard.EXIT_USAGE
    assert not _src(repo).exists()


def test_snapshot_skips_a_file_over_the_per_file_limit(repo, capsys):
    (repo / "big.bin").write_bytes(b"x" * (2 * 1024 * 1024))
    assert guard.main(["snapshot", "r1", "--max-file-mb", "1"]) == 0
    assert not (_src(repo) / "big.bin").exists()
    assert "除外 (too-large)" in capsys.readouterr().out


def test_snapshot_needs_the_repository_root(repo):
    os.chdir(repo / "sub")
    assert init_run("r2") == 0
    assert guard.main(["snapshot", "r2"]) == guard.EXIT_USAGE


def test_snapshot_of_an_unknown_run_is_a_usage_error(repo):
    assert guard.main(["snapshot", "nope"]) == guard.EXIT_USAGE


# ---------------------------------------------------------------------------
# prepare / check / audit: 専用 worktree を使う run
# ---------------------------------------------------------------------------

linux_only = pytest.mark.skipif(not os.path.isdir("/proc/self"), reason="/proc がある環境だけ")


@pytest.fixture()
def gitrepo(workspace):
    """コミットが 1 つある git リポジトリ。.tmp/ は無視する (本体の status を汚さない)。"""
    _git(workspace, "init", "-q")
    (workspace / ".gitignore").write_text(".tmp/\n")
    (workspace / "a.py").write_text("print('a')\n")
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-q", "-m", "init")
    return workspace


def prepare_run(deadline: str = "8h", max_cycles: int = 20) -> str:
    before = set(os.listdir(".tmp/away-shift")) if os.path.isdir(".tmp/away-shift") else set()
    code = guard.main(["prepare", "--goal", "目標 G", "--deadline", deadline, "--max-cycles", str(max_cycles)])
    assert code == guard.EXIT_CONTINUE
    (run_id,) = set(os.listdir(".tmp/away-shift")) - before
    return run_id


def load_state_of(repo: Path, run_id: str) -> dict:
    return json.loads((repo / ".tmp" / "away-shift" / run_id / "state.json").read_text(encoding="utf-8"))


def test_prepare_creates_worktree_branch_state_and_brief(gitrepo, capsys):
    run_id = prepare_run()
    out = capsys.readouterr().out
    state = load_state_of(gitrepo, run_id)
    worktree = gitrepo / ".tmp" / "worktrees" / f"away-{run_id}"
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=gitrepo, capture_output=True, encoding="utf-8", check=True
    ).stdout.strip()

    assert state["worktree"] == str(worktree)
    assert state["branch"] == f"feature/away-{run_id}"
    assert state["base"] == head
    assert state["repo"] == str(gitrepo.resolve())
    assert worktree.is_dir()
    branches = subprocess.run(
        ["git", "branch", "--list", state["branch"]], cwd=gitrepo, capture_output=True, encoding="utf-8", check=True
    ).stdout
    assert state["branch"] in branches

    brief = (worktree / ".tmp" / "away" / "brief-common.md").read_text(encoding="utf-8")
    assert "目標 G" in brief
    assert str(worktree) in brief
    assert run_id in brief
    assert not brief.lstrip().startswith("<!--")
    assert "-->" not in brief
    assert re.search(r"\{[a-z_]+\}", brief) is None

    for label in ("run_id:", "worktree:", "branch:", "base:", "期限:", "引き継ぎ:"):
        assert any(line.startswith(label) for line in out.splitlines()), label
    assert f"base: {head[:8]}\n" in out
    assert "警告" not in out


def test_prepare_warns_about_uncommitted_changes_in_the_main_tree(gitrepo, capsys):
    (gitrepo / "a.py").write_text("print('changed')\n")
    prepare_run()
    assert "worktree には含まれない" in capsys.readouterr().out


def test_prepare_outside_a_git_root_is_a_usage_error(workspace, capsys):
    code = guard.main(["prepare", "--goal", "G", "--deadline", "8h"])
    assert code == guard.EXIT_USAGE
    assert not (workspace / ".tmp").exists()


def test_prepare_from_a_subdirectory_is_a_usage_error(gitrepo, monkeypatch):
    (gitrepo / "sub").mkdir()
    monkeypatch.chdir(gitrepo / "sub")
    assert guard.main(["prepare", "--goal", "G", "--deadline", "8h"]) == guard.EXIT_USAGE


def test_prepare_with_a_missing_brief_template_keeps_the_worktree(gitrepo, monkeypatch, capsys):
    monkeypatch.setattr(guard, "child_brief_path", lambda: gitrepo / "no-such-brief.md")
    code = guard.main(["prepare", "--goal", "G", "--deadline", "8h"])
    assert code == guard.EXIT_USAGE
    assert "消していません" in capsys.readouterr().err
    assert len(list((gitrepo / ".tmp" / "worktrees").iterdir())) == 1


def test_prepare_rejects_a_past_deadline_before_creating_anything(gitrepo):
    assert guard.main(["prepare", "--goal", "G", "--deadline", "2020-01-01 00:00"]) == guard.EXIT_USAGE
    assert not (gitrepo / ".tmp").exists()


def test_check_prints_worktree_timeouts_for_a_worktree_run(gitrepo, capsys):
    run_id = prepare_run()
    capsys.readouterr()
    assert guard.main(["check", run_id]) == guard.EXIT_CONTINUE
    lines = capsys.readouterr().out.splitlines()
    values = dict(line.split(": ", 1) for line in lines if line.startswith(("WORKTREE", "CHILD_")))
    assert values["WORKTREE"] == str(gitrepo / ".tmp" / "worktrees" / f"away-{run_id}")
    assert values["CHILD_TIMEOUT_MS"] == "1800000"
    assert values["CHILD_CHECKPOINT_MS"] == "180000"
    # 既存の出力の後ろに足される
    assert lines.index(next(x for x in lines if x.startswith("NEXT_WAKE_SECONDS"))) < lines.index(
        next(x for x in lines if x.startswith("WORKTREE"))
    )


def test_check_child_timeout_is_limited_by_the_remaining_time(gitrepo, capsys):
    run_id = prepare_run(deadline="25m")
    capsys.readouterr()
    assert guard.main(["check", run_id]) == guard.EXIT_CONTINUE
    out = capsys.readouterr().out
    # 残り 24 分 - 予備 15 分 = 9 分
    assert "CHILD_TIMEOUT_MS: 540000" in out
    assert "CHILD_CHECKPOINT_MS: 180000" in out


def test_check_checkpoint_is_a_third_of_a_short_timeout(gitrepo, capsys):
    run_id = prepare_run(deadline="22m")
    capsys.readouterr()
    assert guard.main(["check", run_id]) == guard.EXIT_CONTINUE
    out = capsys.readouterr().out
    # 残り 21 分 - 予備 15 分 = 6 分 = 360000 ms、その 3 分の 1 は 120000
    assert "CHILD_TIMEOUT_MS: 360000" in out
    assert "CHILD_CHECKPOINT_MS: 120000" in out


def test_check_output_of_an_init_run_has_no_worktree_lines(workspace, capsys):
    init_run("r1")
    capsys.readouterr()
    assert guard.main(["check", "r1"]) == guard.EXIT_CONTINUE
    out = capsys.readouterr().out
    assert "WORKTREE" not in out
    assert "CHILD_" not in out
    assert "NEXT_WAKE_SECONDS" in out


def test_check_stops_when_the_child_time_is_under_three_minutes(gitrepo, capsys):
    run_id = prepare_run(deadline="17m")  # 残り 16 分 - 予備 15 分 = 1 分
    capsys.readouterr()
    assert guard.main(["check", run_id]) == guard.EXIT_STOP
    assert "子に割り当てられる時間" in capsys.readouterr().out
    assert load_state_of(gitrepo, run_id)["cycle"] == 0


def test_child_time_stop_does_not_apply_to_an_init_run(workspace):
    init_run("r1", deadline="17m")
    assert guard.main(["check", "r1"]) == guard.EXIT_CONTINUE


def test_existing_stop_reasons_win_over_the_child_time_stop(gitrepo, capsys):
    run_id = prepare_run(deadline="10m")  # 予備時間未満でもある
    capsys.readouterr()
    assert guard.main(["check", run_id]) == guard.EXIT_STOP
    assert "予備" in capsys.readouterr().out
    assert load_state_of(gitrepo, run_id)["stopped"] == "reserve"


def test_max_cycles_stop_wins_over_the_child_time_stop(gitrepo, capsys):
    run_id = prepare_run(deadline="17m", max_cycles=0)  # 子の時間も足りないが、最大サイクル数が先
    capsys.readouterr()
    assert guard.main(["check", run_id]) == guard.EXIT_STOP
    assert load_state_of(gitrepo, run_id)["stopped"] == "max-cycles"


def audit_exit(run_id: str, *extra: str) -> int:
    return guard.main(["audit", run_id, *extra])


def test_audit_passes_on_an_untouched_main_tree(gitrepo, capsys):
    run_id = prepare_run()
    capsys.readouterr()
    assert audit_exit(run_id) == guard.EXIT_CONTINUE
    out = capsys.readouterr().out
    assert "同じ" in out
    assert "本体 git status: 0 件" in out
    assert "コミット: 0 件" in out
    assert "差分: なし" in out


def test_audit_reports_commits_made_in_the_worktree(gitrepo, capsys):
    run_id = prepare_run()
    worktree = gitrepo / ".tmp" / "worktrees" / f"away-{run_id}"
    (worktree / "b.py").write_text("print('b')\n")
    _git(worktree, "add", "b.py")
    _git(worktree, "commit", "-q", "-m", "worktree commit")
    (worktree / "a.py").write_text("print('dirty')\n")
    capsys.readouterr()

    assert audit_exit(run_id) == guard.EXIT_CONTINUE
    out = capsys.readouterr().out
    assert "コミット: 1 件" in out
    assert "worktree commit" in out
    assert "1 file changed" in out
    assert "worktree の未コミット: 1 件" in out


def test_audit_fails_when_a_tracked_file_in_the_main_tree_changed(gitrepo, capsys):
    run_id = prepare_run()
    (gitrepo / "a.py").write_text("print('changed')\n")
    capsys.readouterr()
    assert audit_exit(run_id) == guard.EXIT_AUDIT_VIOLATION
    assert "本体 git status: 1 件" in capsys.readouterr().out


def test_audit_fails_when_the_main_head_moved(gitrepo, capsys):
    run_id = prepare_run()
    _git(gitrepo, "commit", "-q", "--allow-empty", "-m", "moved")
    capsys.readouterr()
    assert audit_exit(run_id) == guard.EXIT_AUDIT_VIOLATION
    assert "違う" in capsys.readouterr().out


def test_audit_write_creates_audit_md_in_the_run_directory(gitrepo):
    run_id = prepare_run()
    assert audit_exit(run_id, "--write") == guard.EXIT_CONTINUE
    audit_md = gitrepo / ".tmp" / "away-shift" / run_id / "audit.md"
    assert "本体 HEAD:" in audit_md.read_text(encoding="utf-8")


def test_audit_does_not_write_without_the_write_flag(gitrepo):
    run_id = prepare_run()
    assert audit_exit(run_id) == guard.EXIT_CONTINUE
    assert not (gitrepo / ".tmp" / "away-shift" / run_id / "audit.md").exists()


def test_audit_on_an_init_run_is_a_usage_error(workspace):
    init_run("r1")
    assert audit_exit("r1") == guard.EXIT_USAGE


def test_audit_on_an_unknown_run_is_a_usage_error(workspace):
    assert audit_exit("missing") == guard.EXIT_USAGE


@pytest.fixture()
def sleepers(gitrepo):
    """(worktree の run_id, 別ディレクトリの sleep を起動する関数)。終了時に残った sleep を片づける。"""
    procs: list[subprocess.Popen] = []

    def start(cwd: Path) -> subprocess.Popen:
        proc = subprocess.Popen(["sleep", "60"], cwd=cwd, start_new_session=True)
        procs.append(proc)
        return proc

    yield start
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
        proc.wait()


@linux_only
def test_audit_lists_processes_in_the_worktree_without_killing(gitrepo, sleepers, capsys):
    run_id = prepare_run()
    inside = sleepers(gitrepo / ".tmp" / "worktrees" / f"away-{run_id}")
    capsys.readouterr()
    assert audit_exit(run_id) == guard.EXIT_CONTINUE
    out = capsys.readouterr().out
    assert f"{inside.pid} sleep 60" in out
    assert inside.poll() is None


@linux_only
def test_audit_kill_stops_only_processes_whose_cwd_is_in_the_worktree(gitrepo, sleepers, capsys):
    run_id = prepare_run()
    worktree = gitrepo / ".tmp" / "worktrees" / f"away-{run_id}"
    (worktree / "deep").mkdir()
    other_dir = gitrepo / "other"
    other_dir.mkdir()
    inside = sleepers(worktree / "deep")
    outside = sleepers(other_dir)
    capsys.readouterr()

    assert audit_exit(run_id, "--kill") == guard.EXIT_CONTINUE
    out = capsys.readouterr().out
    assert inside.wait(timeout=5) is not None
    assert str(inside.pid) in out.split("止めた pid:")[1]
    assert outside.poll() is None


@linux_only
def test_audit_kill_spares_processes_with_a_controlling_tty(gitrepo, sleepers, capsys, monkeypatch):
    """worktree で利用者が動かしているシェル・コマンド (端末つき) は、一覧には出すが止めない。"""
    run_id = prepare_run()
    inside = sleepers(gitrepo / ".tmp" / "worktrees" / f"away-{run_id}")
    monkeypatch.setattr(guard, "_has_controlling_tty", lambda pid: pid == inside.pid)
    capsys.readouterr()

    assert audit_exit(run_id, "--kill") == guard.EXIT_CONTINUE
    out = capsys.readouterr().out
    assert f"{inside.pid} sleep 60 [止めない: 端末つき]" in out
    assert "止めた pid:" not in out
    assert inside.poll() is None


@linux_only
def test_audit_kill_spares_processes_started_before_the_run(gitrepo, sleepers, capsys, monkeypatch):
    """run より前に起動したプロセスは、利用者の既存のプロセスなので止めない。"""
    run_id = prepare_run()
    inside = sleepers(gitrepo / ".tmp" / "worktrees" / f"away-{run_id}")
    monkeypatch.setattr(guard, "_process_started_at", lambda pid: 0.0)
    capsys.readouterr()

    assert audit_exit(run_id, "--kill") == guard.EXIT_CONTINUE
    out = capsys.readouterr().out
    assert f"{inside.pid} sleep 60 [止めない: run より前に起動]" in out
    assert inside.poll() is None

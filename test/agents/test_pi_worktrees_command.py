"""``/worktrees`` の本体 (``worktrees-command.ts``) と、起動時の取り残しの照合 (``index.ts`` の ``session_start``) の試験。

コマンドの本体は ``test/agents/pi/worktrees_command_driver.mjs`` が直接呼ぶ (スラッシュコマンドは対話専用で、print モードでは
呼べないため)。起動時の照合は、``pi`` を print モードで起動して標準エラーを見る。記録と worktree は
``worktree_driver.mjs`` (``test_pi_worktree.Env``) で手で作り、子は起動しない。node の型除去 (22.18 以上) と /usr/bin/git が要る。
see docs/change/0029-worktree-isolation.md#w1-の実装計画
"""

# ruff: noqa: F811  (env はインポートしたフィクスチャ。引数名で使うので再定義に見える)
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_harness import PI, env, run_pi  # noqa: F401  (env はフィクスチャ。使い回す)
from test_pi_judge_ts import _node
from test_pi_worktree import Env, build_repo, child_edit, jid

DRIVER = ROOT / "test" / "agents" / "pi" / "worktrees_command_driver.mjs"

pytestmark = pytest.mark.skipif(
    _node() is None or not Path("/usr/bin/git").exists(),
    reason="型除去に対応した node (22.18 以上) か /usr/bin/git が無い",
)
needs_pi = pytest.mark.skipif(PI is None, reason="pi is not installed")

DEAD_PID = "2147483646\n"


def drive(e: Env, **kw) -> dict:
    proc = subprocess.run(
        [_node(), str(DRIVER), json.dumps(kw)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=e.node_env,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    return json.loads(proc.stdout)


def cmd(e: Env, args: str, **kw) -> dict:
    kw.setdefault("repo", str(e.repo))
    return drive(e, op="run", args=args, **kw)


def records_dir(e: Env) -> Path:
    return e.repo / ".tmp" / "subagents" / "worktrees"


def state_of(e: Env, n: int) -> str | None:
    f = records_dir(e) / f"{jid(n)}.json"
    return json.loads(f.read_text(encoding="utf-8"))["state"] if f.exists() else None


def keep(e: Env, n: int, note: str = "test note") -> None:
    e.op(op="mark_kept", repo=str(e.repo), jobId=jid(n), note=note)


def ref_exists(e: Env, n: int) -> bool:
    r = e.git("rev-parse", "--verify", "-q", f"refs/pi-agent/{jid(n)}", check=False)
    return r.returncode == 0


# ─── /worktrees: 一覧・詳細・使い方 ─────────────────────────────────


def test_list_shows_records_and_mismatches(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    e.create(1)
    e.create(2)
    keep(e, 2, "pending review")
    (records_dir(e) / "junk.json").write_text("{not json", encoding="utf-8")
    res = cmd(e, "")
    text = res["text"]
    assert res["level"] == "info"
    assert "job id | 状態 | 作成 | worktree | ref | patch | note" in text, text
    assert f"{jid(1)} | running |" in text and f"{jid(2)} | kept |" in text, text
    assert "pending review" in text and "(壊れた記録) junk.json" in text, text
    assert f"{jid(1)} stuck_running" in text, text
    # 子が生きている job は stuck_running にならない
    live = cmd(e, "", live=[jid(1)])["text"]
    assert f"{jid(1)} stuck_running" not in live and f"{jid(2)} | kept |" in live, live


def test_list_without_records_says_so(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    assert "記録はありません" in cmd(e, "")["text"]
    assert not (e.repo / ".tmp").exists()  # 一覧は何も作らない


def test_show_prints_the_record_without_touching_it(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    before = (records_dir(e) / f"{jid(1)}.json").read_bytes()
    text = cmd(e, f"show {jid(1)}")["text"]
    for needle in (
        rec["startCommit"],
        rec["snapshotCommit"],
        "状態: running",
        "patch: -",
        "ref: -",
    ):
        assert needle in text, text
    assert (records_dir(e) / f"{jid(1)}.json").read_bytes() == before
    assert "記録がありません" in cmd(e, f"show {jid(9)}")["text"]


@pytest.mark.parametrize(
    "args",
    [
        "show",
        "show ../x",
        "show job-zz",
        "collect",
        "collect ../../etc",
        "discard a b",
        "discard job-00000001/../x",
        "frobnicate",
        "unlock now",
        "show job-00000001 extra",
    ],
)
def test_bad_arguments_print_usage_and_never_use_the_id_as_a_path(tmp_path, args):
    e = Env(tmp_path)
    build_repo(e)
    e.create(1)
    res = cmd(e, args, confirm=True)
    assert res["level"] == "warning" and res["text"].startswith("使い方:"), res
    assert res["confirmCalls"] == []
    assert state_of(e, 1) == "running"
    assert (e.repo / ".tmp" / "worktrees" / f"pi-agent-{jid(1)}").is_dir()


def test_not_a_repository(tmp_path):
    e = Env(tmp_path)
    res = drive(e, op="run", args="", repo=None)
    assert res["level"] == "warning" and "git リポジトリではない" in res["text"]


# ─── collect ────────────────────────────────────────────────────────


def test_collect_redoes_a_kept_job_when_confirmed_and_a_second_collect_is_refused(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    child_edit(Path(rec["worktree"]))
    keep(e, 1)
    res = cmd(e, f"collect {jid(1)}", confirm=True)
    text = res["text"]
    assert res["level"] == "info" and text.startswith("collected:"), text
    assert f"ref refs/pi-agent/{jid(1)}" in text, text
    assert f"apply: git apply .tmp/subagents/{jid(1)}.patch" in text, text
    assert (e.repo / ".tmp" / "subagents" / f"{jid(1)}.patch").is_file()
    assert state_of(e, 1) == "collected" and ref_exists(e, 1)
    assert len(res["confirmCalls"]) == 1  # kept も確認を取る
    again = cmd(e, f"collect {jid(1)}", confirm=True)
    assert again["level"] == "warning" and "回収済み" in again["text"], again
    assert again["confirmCalls"] == []


def test_collect_of_a_kept_job_declined_changes_nothing(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    child_edit(Path(rec["worktree"]))
    keep(e, 1)
    res = cmd(e, f"collect {jid(1)}", confirm=False)
    assert res["level"] == "warning" and "中止した" in res["text"], res
    assert len(res["confirmCalls"]) == 1
    assert state_of(e, 1) == "kept" and not ref_exists(e, 1) and Path(rec["worktree"]).is_dir()
    assert not (e.repo / ".tmp" / "subagents" / f"{jid(1)}.patch").exists()


def test_collect_of_a_kept_job_without_ui_is_refused(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    child_edit(Path(rec["worktree"]))
    keep(e, 1)
    res = cmd(e, f"collect {jid(1)}")
    assert res["level"] == "warning" and "確認できない" in res["text"], res
    assert state_of(e, 1) == "kept" and not ref_exists(e, 1) and Path(rec["worktree"]).is_dir()


def test_collect_confirmation_warns_strongly_when_the_stop_was_not_confirmed(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    e.create(1)
    e.create(2)
    keep(e, 1, "child process group not confirmed stopped")
    keep(e, 2, "子の終了を確認できない")
    strong = "停止を確認できていません。作業中の worktree を回収すると、子の変更が失われるおそれがあります"
    for n in (1, 2):
        body = cmd(e, f"collect {jid(n)}", confirm=False)["confirmCalls"][0]["body"]
        assert strong in body and "別の pi プロセスの子" in body, body
    keep(e, 1, "pending review")
    body = cmd(e, f"collect {jid(1)}", confirm=False)["confirmCalls"][0]["body"]
    assert "pending review" in body and strong not in body, body


def test_collect_of_an_unchanged_kept_job_removes_worktree_and_record(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    keep(e, 1)
    res = cmd(e, f"collect {jid(1)}", confirm=True)
    assert res["text"].startswith("unchanged:"), res
    assert not Path(rec["worktree"]).exists() and state_of(e, 1) is None


def test_collect_is_refused_for_a_job_whose_child_is_alive(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    child_edit(Path(rec["worktree"]))
    keep(e, 1)
    res = cmd(e, f"collect {jid(1)}", live=[jid(1)], confirm=True)
    assert res["level"] == "warning" and "子が動いている" in res["text"], res
    assert state_of(e, 1) == "kept" and Path(rec["worktree"]).is_dir() and not ref_exists(e, 1)
    assert res["confirmCalls"] == []


def test_collect_of_a_running_job_needs_a_confirmation(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    child_edit(Path(rec["worktree"]))
    no_ui = cmd(e, f"collect {jid(1)}")
    assert no_ui["level"] == "warning" and "確認できない" in no_ui["text"], no_ui
    declined = cmd(e, f"collect {jid(1)}", confirm=False)
    assert "中止した" in declined["text"] and len(declined["confirmCalls"]) == 1
    assert state_of(e, 1) == "running" and not ref_exists(e, 1)
    ok = cmd(e, f"collect {jid(1)}", confirm=True)
    assert ok["text"].startswith("collected:") and state_of(e, 1) == "collected"


def test_collect_failure_is_reported_without_file_contents(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    (Path(rec["worktree"]) / ".env").write_text("TOKEN=secret-value\n", encoding="utf-8")
    keep(e, 1)
    res = cmd(e, f"collect {jid(1)}", confirm=True)
    assert res["level"] == "warning" and res["text"].startswith("failed:"), res
    assert "secret-value" not in json.dumps(res)
    assert state_of(e, 1) == "kept" and not ref_exists(e, 1)
    assert not (e.repo / ".tmp" / "subagents" / f"{jid(1)}.patch").exists()


def test_collect_without_read_deny_rules_is_refused(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    e.create(1)
    keep(e, 1)
    res = cmd(e, f"collect {jid(1)}", confirm=True, readDeny={"globs": [], "exceptions": []})
    assert res["level"] == "warning" and "no_read_deny_rules" in res["text"], res
    assert state_of(e, 1) == "kept"


# ─── discard ────────────────────────────────────────────────────────


def test_discard_asks_first_and_removes_only_when_confirmed(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    child_edit(Path(rec["worktree"]))
    assert e.collect(1)["changed"] is True
    wt = Path(rec["worktree"])
    patch = e.repo / ".tmp" / "subagents" / f"{jid(1)}.patch"

    # UI が無い・偽・子が生きている・記録が無い: 何も消さない
    no_ui = cmd(e, f"discard {jid(1)}")
    assert no_ui["level"] == "warning" and "破棄しない" in no_ui["text"], no_ui
    no = cmd(e, f"discard {jid(1)}", confirm=False)
    assert "中止した" in no["text"] and len(no["confirmCalls"]) == 1
    live = cmd(e, f"discard {jid(1)}", live=[jid(1)], confirm=True)
    assert "子が動いている" in live["text"] and live["confirmCalls"] == []
    missing = cmd(e, f"discard {jid(9)}", confirm=True)
    assert "記録がありません" in missing["text"] and missing["confirmCalls"] == []
    assert wt.is_dir() and patch.is_file() and ref_exists(e, 1) and state_of(e, 1) == "collected"

    yes = cmd(e, f"discard {jid(1)}", confirm=True)
    assert len(yes["confirmCalls"]) == 1 and "kept" not in yes["text"], yes
    assert not wt.exists() and not patch.exists() and not ref_exists(e, 1)
    assert state_of(e, 1) is None
    assert "pi-agent" not in e.git("worktree", "list")


def test_discard_keeps_what_does_not_match_the_record_and_shows_the_notes(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    child_edit(Path(rec["worktree"]))
    assert e.collect(1)["changed"] is True
    e.git("update-ref", f"refs/pi-agent/{jid(1)}", "HEAD")  # 記録の結果と違う値にする
    res = cmd(e, f"discard {jid(1)}", confirm=True)
    assert res["level"] == "warning" and "ref kept" in res["text"], res
    assert ref_exists(e, 1) and state_of(e, 1) == "kept"


# ─── unlock ─────────────────────────────────────────────────────────


def test_unlock_only_removes_a_stale_lock(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    assert "ロックはない" in cmd(e, "unlock")["text"]
    lock = records_dir(e) / ".lock"
    lock.mkdir(parents=True)
    pid_file = lock / "pid"
    pid_file.write_text(DEAD_PID, encoding="utf-8")
    fresh = cmd(e, "unlock")
    assert fresh["level"] == "warning" and "古くない" in fresh["text"] and lock.is_dir()
    old = time.time() - 3600
    pid_file.write_text(f"{os.getpid()}\n", encoding="utf-8")
    os.utime(lock, (old, old))
    alive = cmd(e, "unlock")
    assert alive["level"] == "warning" and "生きている" in alive["text"] and lock.is_dir()
    pid_file.write_text(DEAD_PID, encoding="utf-8")
    os.utime(lock, (old, old))
    cleared = cmd(e, "unlock")
    assert cleared["level"] == "info" and "解除した" in cleared["text"]
    assert not lock.exists()


# ─── 起動時の照合の関数 ─────────────────────────────────────────────


def test_trace_root_is_found_without_git_and_only_for_a_primary_checkout(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    root = lambda cwd: drive(e, op="trace_root", cwd=str(cwd))["root"]  # noqa: E731
    assert root(e.repo) is None  # 置き場が無いリポジトリ
    rec = e.create(1)
    assert root(e.repo) == str(e.repo)
    assert root(e.repo / "dir") == str(e.repo)  # サブディレクトリからも根が分かる
    assert root(rec["worktree"]) is None  # 子の worktree (.git がファイル) は対象にしない
    plain = Path(
        tempfile.mkdtemp(prefix="wtc-plain-", dir="/tmp")
    )  # TMPDIR はリポジトリの中のことがある
    try:
        assert root(plain) is None
    finally:
        shutil.rmtree(plain, ignore_errors=True)


def test_startup_reconcile_says_when_it_cleared_a_stale_lock(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    e.create(1)
    lock = records_dir(e) / ".lock"
    lock.mkdir()
    (lock / "pid").write_text(DEAD_PID, encoding="utf-8")
    old = time.time() - 3600
    os.utime(lock, (old, old))
    msg = drive(e, op="startup", repo=str(e.repo))["msg"]
    lines = msg.split("\n")
    assert lines[0].startswith("隔離 (worktree) の取り残しが 1 件ある"), msg
    assert (
        "古いロック (死んだ pid・60 秒以上前) を 1 つ解除した (worktree・ref・記録は消していない)"
        in lines
    ), msg
    assert not lock.exists() and state_of(e, 1) == "running"


def test_find_repo_root_accepts_a_short_git_limit(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    root = lambda **kw: drive(e, op="find_root", cwd=str(e.repo / "dir"), **kw)["root"]  # noqa: E731
    assert root() == str(e.repo.resolve())
    assert root(limits={"gitTimeoutMs": 3000, "totalMs": 5000}) == str(e.repo.resolve())
    # 時間切れで起動を止めず 1 行の警告にする経路は未試験 (再現が難しい)


def test_startup_reconcile_message_lists_issues_without_changing_anything(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    e.create(1)
    (records_dir(e) / "junk.json").write_text("{secret-value", encoding="utf-8")
    before = sorted(p.name for p in records_dir(e).iterdir())
    msg = drive(e, op="startup", repo=str(e.repo))["msg"]
    assert msg.startswith(
        "隔離 (worktree) の取り残しが 2 件ある (自動では worktree・ref・記録を消していない)"
    ), msg
    assert "古いロック" not in msg
    assert (
        f"- {jid(1)} stuck_running:" in msg
        and "壊れた記録: .tmp/subagents/worktrees/junk.json" in msg
    )
    assert "/worktrees" in msg and "secret-value" not in msg
    assert sorted(p.name for p in records_dir(e).iterdir()) == before
    assert drive(e, op="startup", repo=str(e.repo), live=[jid(1)])["msg"].startswith(
        "隔離 (worktree) の取り残しが 1 件"
    )


# ─── pi の起動 (session_start) ──────────────────────────────────────


def pi_in(env, e: Env, **env_extra):
    """e.repo を cwd にして pi を print モードで起動する (UI が無いので警告は標準エラー)。"""
    return run_pi({**env, "proj": e.repo}, [], **env_extra)


@needs_pi
def test_startup_warns_about_a_record_without_worktree(env):
    e = Env(env["tmp"])
    build_repo(e)
    rec = e.create(1)
    e.git("worktree", "unlock", rec["worktree"])
    shutil.rmtree(rec["worktree"])
    e.git("worktree", "prune")
    proc = pi_in(env, e)
    assert proc.returncode == 0, proc.stderr
    assert "[harness] 隔離 (worktree) の取り残しが 1 件ある" in proc.stderr, proc.stderr
    assert f"{jid(1)} record_only" in proc.stderr and "/worktrees" in proc.stderr
    assert state_of(e, 1) == "running"  # 自動では何も直さない


@needs_pi
def test_startup_warns_about_a_job_left_running(env):
    e = Env(env["tmp"])
    build_repo(e)
    rec = e.create(1)
    proc = pi_in(env, e)
    assert proc.returncode == 0, proc.stderr
    assert f"{jid(1)} stuck_running" in proc.stderr, proc.stderr
    assert Path(rec["worktree"]).is_dir() and state_of(e, 1) == "running"


@needs_pi
def test_startup_is_quiet_when_nothing_is_left_behind(env):
    e = Env(env["tmp"])
    build_repo(e)
    rec = e.create(1)
    child_edit(Path(rec["worktree"]))
    assert e.collect(1)["changed"] is True  # 回収済み (worktree・ref・patch が揃っている)
    e.create(2)
    e.op(op="discard", repo=str(e.repo), jobId=jid(2))  # 破棄済み
    proc = pi_in(env, e)
    assert proc.returncode == 0, proc.stderr
    assert "取り残し" not in proc.stderr and "照合" not in proc.stderr, proc.stderr


@needs_pi
def test_startup_does_not_reconcile_in_a_child_process(env):
    e = Env(env["tmp"])
    build_repo(e)
    e.create(1)
    proc = pi_in(env, e, PI_HARNESS_CHILD="1")
    assert proc.returncode == 0, proc.stderr
    assert "取り残し" not in proc.stderr and "照合" not in proc.stderr, proc.stderr
    assert state_of(e, 1) == "running"


@needs_pi
def test_startup_without_any_trace_does_nothing(env):
    e = Env(env["tmp"])
    build_repo(e)
    proc = pi_in(env, e)
    assert proc.returncode == 0, proc.stderr
    assert "取り残し" not in proc.stderr and "照合" not in proc.stderr, proc.stderr
    assert not (e.repo / ".tmp" / "subagents").exists()


@needs_pi
def test_startup_outside_a_git_repository_does_not_fail(env):
    plain = Path(
        tempfile.mkdtemp(prefix="wtc-plain-", dir="/tmp")
    )  # TMPDIR はリポジトリの中のことがある
    try:
        proc = run_pi({**env, "proj": plain}, [])
    finally:
        shutil.rmtree(plain, ignore_errors=True)
    assert proc.returncode == 0, proc.stderr
    assert "取り残し" not in proc.stderr and "照合" not in proc.stderr, proc.stderr


@needs_pi
def test_startup_survives_broken_records_and_a_failing_reconcile(env):
    e = Env(env["tmp"])
    build_repo(e)
    e.create(1)
    (records_dir(e) / f"{jid(3)}.json").write_text("{secret-value", encoding="utf-8")
    proc = pi_in(env, e)
    assert proc.returncode == 0, proc.stderr
    assert "壊れた記録" in proc.stderr and "secret-value" not in proc.stderr, proc.stderr

    # 記録の置き場が通常のファイルだと照合が例外になる。起動は止まらず、失敗の警告が 1 行出る
    shutil.rmtree(records_dir(e))
    records_dir(e).write_text("x", encoding="utf-8")
    proc = pi_in(env, e)
    assert proc.returncode == 0, proc.stderr
    assert "隔離の取り残しの照合に失敗した" in proc.stderr, proc.stderr

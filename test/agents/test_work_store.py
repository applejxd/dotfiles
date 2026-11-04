"""work/store.ts・work/root.ts (作業台帳の永続) の試験。実 fs を tmp_path で使い、障害を注入する。

``test/agents/pi/work_store_driver.mjs`` が node 側の操作を受け持つ。親 (この試験) はファイルを直接壊し、子の node を SIGKILL で殺す。
公開実装の欠陥の回帰名: kill9_mid_turn_loses_zero_acked_events・second_writer_rejected_not_discarded・corrupt_midfile_quarantined_visible。
node の型除去を使うので、22.18 未満の node では飛ばす。
see docs/spec/work/store.md
"""

from __future__ import annotations

import json
import os
import random
import signal
import subprocess
import time
import zlib
from pathlib import Path

import pytest
from test_pi_judge_ts import _node

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
DRIVER = HERE / "pi" / "work_store_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


def run(ops: list[dict]) -> list[dict]:
    proc = subprocess.run(
        [_node(), str(DRIVER), "run"],
        input=json.dumps(ops),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1500:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def opened(root: Path, name: str = "a", pid: int = 111, **kw) -> list[dict]:
    return [{"op": "open", "name": name, "root": str(root), "pid": pid, **kw}]


def acquire(name: str = "a", holder: str = "h") -> dict:
    return {"op": "acquire", "name": name, "holder": holder}


def append(name: str = "a", **kw) -> dict:
    return {"op": "append", "name": name, **kw}


def writer(root: Path, n: int, **kw) -> list[dict]:
    """lease を取って n 件追記するところまでの操作列"""
    return [*opened(root, **kw), acquire(), {"op": "appendN", "name": "a", "n": n}]


def log_files(root: Path) -> list[Path]:
    return sorted((root / "log").glob("*.jsonl"))


def fresh(tmp_path: Path, n: int = 10, **kw) -> Path:
    root = tmp_path / "w"
    res = run(writer(root, n, **kw))
    assert all(r["ok"] for r in res), res
    return root


def flip_byte(path: Path, offset: int) -> None:
    b = bytearray(path.read_bytes())
    b[offset] ^= 0x01
    path.write_bytes(bytes(b))


def line_start(path: Path, k: int) -> int:
    """k 行目 (0 始まり) の先頭のバイト位置"""
    data = path.read_bytes()
    pos = 0
    for _ in range(k):
        pos = data.index(b"\n", pos) + 1
    return pos


def load_as_writer(root: Path, pid: int = 222, **kw) -> list[dict]:
    """別の書き手 (前の書き手の pid は死亡扱い) として開いて load する"""
    return run(
        [
            {"op": "deadpids", "pids": [111]},
            *opened(root, "b", pid, **kw),
            acquire("b"),
            {"op": "load", "name": "b"},
        ]
    )


# ── 基本: 追記・形式・読み出し ───────────────────────────────────


def test_crc32_matches_ieee_check_value() -> None:
    assert run([{"op": "crc32", "text": "123456789"}])[0]["value"] == 0xCBF43926


def test_append_assigns_contiguous_seq_and_store_ts(tmp_path: Path) -> None:
    res = run(
        [
            *opened(tmp_path / "w"),
            acquire(),
            append(type="goal.created"),
            {"op": "clock", "t": 5000},
            append(type="node.added", node="t1"),
        ]
    )
    assert [r["ok"] for r in res] == [True] * 5
    assert (res[2]["value"]["seq"], res[2]["value"]["ts"]) == (1, 1_000_000)
    assert (res[4]["value"]["seq"], res[4]["value"]["ts"]) == (2, 5000)


def test_load_returns_what_was_appended_in_order(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *opened(root),
            acquire(),
            append(type="goal.created", data={"t": "あ"}),
            append(type="node.added", node="t1", aux=True),
            {"op": "load", "name": "a"},
        ]
    )
    ev = res[-1]["value"]["events"]
    assert [e["seq"] for e in ev] == [1, 2]
    assert ev[0]["data"] == {"t": "あ"}
    assert (ev[1]["node"], ev[1]["aux"]) == ("t1", True)
    assert "recovered" not in res[-1]["value"] and "degraded" not in res[-1]["value"]


def test_load_of_empty_root_is_empty(tmp_path: Path) -> None:
    res = run([*opened(tmp_path / "none"), {"op": "load", "name": "a"}])
    assert res[-1]["value"] == {"events": []}


def test_line_format_is_json_tab_crc32_hex(tmp_path: Path) -> None:
    root = fresh(tmp_path, 3)
    for line in log_files(root)[0].read_bytes().split(b"\n")[:-1]:
        body, _, crc = line.rpartition(b"\t")
        assert len(crc) == 8
        assert int(crc, 16) == zlib.crc32(body)
        assert json.loads(body)["type"] == "notice"


def test_log_is_one_event_per_line_and_ends_with_newline(tmp_path: Path) -> None:
    root = fresh(tmp_path, 4)
    data = log_files(root)[0].read_bytes()
    assert data.endswith(b"\n") and data.count(b"\n") == 4


def test_segment_rotates_by_size(tmp_path: Path) -> None:
    root = fresh(tmp_path, 12, segmentSize=5)
    assert [p.name for p in log_files(root)] == ["0001.jsonl", "0002.jsonl", "0003.jsonl"]
    assert [p.read_bytes().count(b"\n") for p in log_files(root)] == [5, 5, 2]


def test_default_segment_is_1000_events(tmp_path: Path) -> None:
    root = fresh(tmp_path, 1001)
    assert [p.name for p in log_files(root)] == ["0001.jsonl", "0002.jsonl"]
    res = run([*opened(root, "b", 222), {"op": "load", "name": "b"}])
    assert [e["seq"] for e in res[-1]["value"]["events"]] == list(range(1, 1002))


def test_load_across_segments_is_contiguous(tmp_path: Path) -> None:
    root = fresh(tmp_path, 12, segmentSize=5)
    res = run([*opened(root, "b", 222, segmentSize=5), {"op": "load", "name": "b"}])
    assert [e["seq"] for e in res[-1]["value"]["events"]] == list(range(1, 13))


def test_restart_continues_seq(tmp_path: Path) -> None:
    root = fresh(tmp_path, 3)
    res = run(
        [
            {"op": "deadpids", "pids": [111]},
            *opened(root, "b", 222),
            acquire("b"),
            append("b"),
            {"op": "load", "name": "b"},
        ]
    )
    assert res[3]["value"]["seq"] == 4
    assert [e["seq"] for e in res[-1]["value"]["events"]] == [1, 2, 3, 4]


def test_reader_without_lease_can_load(tmp_path: Path) -> None:
    root = fresh(tmp_path, 3)
    res = run([*opened(root, "r", 333), {"op": "load", "name": "r"}])
    assert len(res[-1]["value"]["events"]) == 3


def test_determinism_same_events_same_bytes_and_same_load(tmp_path: Path) -> None:
    outs = []
    for i in range(3):
        root = tmp_path / f"w{i}"
        res = run(
            [
                *writer(root, 30, segmentSize=7),
                {"op": "load", "name": "a"},
                {"op": "load", "name": "a"},
            ]
        )
        assert res[-1]["value"] == res[-2]["value"]
        outs.append((res[-1]["value"], [p.read_bytes() for p in log_files(root)]))
    assert outs[0] == outs[1] == outs[2]


# ── lease ────────────────────────────────────────────────────────


def test_append_without_lease_is_rejected(tmp_path: Path) -> None:
    res = run([*opened(tmp_path / "w"), append()])
    assert (res[1]["ok"], res[1]["code"]) == (False, "NO_LEASE")


def test_acquire_writes_owner_json(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run([*opened(root), acquire(holder="session-1")])
    owner = json.loads((root / "lease" / "owner.json").read_text())
    assert (owner["holder"], owner["pid"], owner["startedAt"], owner["heartbeat"]) == (
        "session-1",
        111,
        1_000_000,
        1_000_000,
    )
    assert res[1]["value"] == {
        "holder": "session-1",
        "pid": 111,
        "startedAt": 1_000_000,
        "heartbeat": 1_000_000,
    }


def test_second_store_cannot_acquire_a_live_lease(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run([*opened(root), *opened(root, "b", 222), acquire(), acquire("b", "other")])
    assert res[-1]["value"] is None


def test_second_writer_rejected_not_discarded(tmp_path: Path) -> None:
    """公開実装の欠陥: 2 人目の書き手の変更が捨てられる。こちらは 2 人目が書けず、拒否が明示され、1 人目の変更は残る"""
    root = tmp_path / "w"
    holder = subprocess.Popen(
        [_node(), str(DRIVER), "child-hold", str(root), "3000"],
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "ready"
        proc = subprocess.run(
            [_node(), str(DRIVER), "child-try", str(root), "second"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=ROOT,
            timeout=60,
            check=False,
        )
        got = json.loads(proc.stdout.strip().splitlines()[-1])
    finally:
        holder.kill()
        holder.wait()
    assert got["lease"] is False
    assert (got["append"]["ok"], got["append"]["code"]) == (False, "NO_LEASE")
    res = run([*opened(root, "r", 333), {"op": "load", "name": "r"}])
    ev = res[-1]["value"]["events"]
    assert [(e["seq"], e["data"]) for e in ev] == [(1, {"who": "holder"})]


def test_heartbeat_updates_owner_json(tmp_path: Path) -> None:
    root = tmp_path / "w"
    run(
        [
            *opened(root),
            acquire(),
            {"op": "clock", "t": 1_030_000},
            {"op": "heartbeat", "name": "a"},
        ]
    )
    assert json.loads((root / "lease" / "owner.json").read_text())["heartbeat"] == 1_030_000


def test_heartbeat_without_lease_raises(tmp_path: Path) -> None:
    res = run([*opened(tmp_path / "w"), {"op": "heartbeat", "name": "a"}])
    assert res[1]["code"] == "NO_LEASE"


def test_takeover_after_heartbeat_timeout_even_if_pid_alive(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *opened(root),
            *opened(root, "b", 222),
            acquire(),
            {"op": "clock", "t": 1_000_000 + 91_000},
            acquire("b", "new"),
        ]
    )
    assert res[-1]["value"]["holder"] == "new"


def test_no_takeover_just_inside_heartbeat_timeout(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *opened(root),
            *opened(root, "b", 222),
            acquire(),
            {"op": "clock", "t": 1_000_000 + 89_000},
            acquire("b", "new"),
        ]
    )
    assert res[-1]["value"] is None


def test_heartbeat_keeps_the_lease_alive(tmp_path: Path) -> None:
    root = tmp_path / "w"
    ops = [*opened(root), *opened(root, "b", 222), acquire()]
    for t in (60_000, 120_000, 180_000):
        ops += [{"op": "clock", "t": 1_000_000 + t}, {"op": "heartbeat", "name": "a"}]
    res = run([*ops, acquire("b", "new")])
    assert res[-1]["value"] is None


def test_takeover_when_holder_pid_is_dead(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *opened(root),
            *opened(root, "b", 222),
            acquire(),
            {"op": "deadpids", "pids": [111]},
            acquire("b", "new"),
        ]
    )
    assert res[-1]["value"]["holder"] == "new"
    assert json.loads((root / "lease" / "owner.json").read_text())["pid"] == 222


def test_old_holder_rejected_after_takeover(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *opened(root),
            *opened(root, "b", 222),
            acquire(),
            append(),
            {"op": "deadpids", "pids": [111]},
            acquire("b", "new"),
            append("a"),
            {"op": "heartbeat", "name": "a"},
            append("b"),
            {"op": "load", "name": "b"},
        ]
    )
    assert res[6]["code"] == "NO_LEASE" and res[7]["code"] == "NO_LEASE"
    assert [e["seq"] for e in res[-1]["value"]["events"]] == [1, 2]


def test_release_frees_the_lease(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *opened(root),
            *opened(root, "b", 222),
            acquire(),
            {"op": "release", "name": "a"},
            append("a"),
            acquire("b", "new"),
        ]
    )
    assert res[4]["code"] == "NO_LEASE"
    assert res[5]["value"]["holder"] == "new"


def test_same_pid_same_holder_may_reacquire_but_old_instance_is_cut_off(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [*opened(root), *opened(root, "b", 111), acquire(), acquire("b"), append("a"), append("b")]
    )
    assert res[3]["value"] is not None
    assert res[4]["code"] == "NO_LEASE" and res[5]["ok"]


def test_same_pid_different_holder_cannot_take_a_live_lease(tmp_path: Path) -> None:
    res = run(
        [
            *opened(tmp_path / "w"),
            *opened(tmp_path / "w", "b", 111),
            acquire(),
            acquire("b", "other"),
        ]
    )
    assert res[-1]["value"] is None


def test_lease_dir_without_owner_is_held_while_fresh_and_stale_when_old(tmp_path: Path) -> None:
    root = tmp_path / "w"
    (root / "lease").mkdir(parents=True)
    assert run([*opened(root), acquire()])[-1]["value"] is None
    old = time.time() - 120
    os.utime(root / "lease", (old, old))
    assert run([*opened(root), acquire()])[-1]["value"] is not None


def test_takeover_with_a_really_dead_pid(tmp_path: Path) -> None:
    root = tmp_path / "w"
    p = subprocess.Popen(["true"])
    p.wait()
    run([*opened(root, pid=p.pid, realPids=True), acquire()])
    res = run([*opened(root, "b", os.getpid(), realPids=True), acquire("b", "new")])
    assert res[-1]["value"]["holder"] == "new"


def test_simultaneous_takeover_exactly_one_wins(tmp_path: Path) -> None:
    for i in range(8):
        root = tmp_path / f"w{i}"
        p = subprocess.Popen(["true"])
        p.wait()
        run([*opened(root, pid=p.pid, realPids=True), acquire()])
        start = int(time.time() * 1000) + 400
        procs = [
            subprocess.Popen(
                [_node(), str(DRIVER), "child-race", str(root), f"c{k}", str(start)],
                stdout=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                cwd=ROOT,
            )
            for k in range(3)
        ]
        got = [
            json.loads(q.communicate(timeout=60)[0].strip().splitlines()[-1])["got"] for q in procs
        ]
        assert sorted(got) == [False, False, True], (i, got)
        owner = json.loads((root / "lease" / "owner.json").read_text())
        assert owner["holder"].startswith("c")
        assert not list(root.glob("lease.old-*")) and not (root / "lease.lock").exists()


# ── 障害注入: kill -9 ────────────────────────────────────────────


@pytest.mark.parametrize("seed", range(24))
def test_kill9_mid_turn_loses_zero_acked_events(tmp_path: Path, seed: int) -> None:
    rng = random.Random(seed)
    root = tmp_path / "w"
    child = subprocess.Popen(
        [_node(), str(DRIVER), "child-append", str(root), "100000", str(seed)],
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    acks: list[int] = []
    target = 3 + rng.randrange(150)
    delay = rng.random() * 0.004
    assert child.stdout is not None
    try:
        assert child.stdout.readline().strip() == "ready"
        while len(acks) < target:
            line = child.stdout.readline()
            assert line, "子が途中で終わった"
            acks.append(int(line.split()[1]))
        time.sleep(delay)
    finally:
        os.kill(child.pid, signal.SIGKILL)
        for line in child.stdout:  # kill までにパイプへ出た ack も数える (ack は fsync の後に出る)
            if line.startswith("ack "):
                acks.append(int(line.split()[1]))
        child.wait()
    assert acks == list(range(1, len(acks) + 1))
    res = load_as_writer(root, 4_194_000, realPids=True)[-1]["value"]
    seqs = [e["seq"] for e in res["events"]]
    assert seqs == list(range(1, len(seqs) + 1)), "seq に欠番がある"
    assert len(seqs) >= len(acks), "ack 済みのイベントが消えた"
    assert "degraded" not in res
    # 回復後も追記を続けられ、ログ全体の crc が通る
    after = run(
        [
            *opened(root, "c", 4_194_001, realPids=True),
            acquire("c"),
            append("c"),
            {"op": "load", "name": "c"},
        ]
    )
    assert after[2]["value"]["seq"] == len(seqs) + 1
    assert "degraded" not in after[-1]["value"] and "recovered" not in after[-1]["value"]


# ── 障害注入: 破損・torn ─────────────────────────────────────────


def test_corrupt_midfile_quarantined_visible(tmp_path: Path) -> None:
    """公開実装の欠陥: 壊れた行を黙って捨てる。こちらは隔離して degraded を返し、書き込みを拒否する"""
    root = fresh(tmp_path, 10)
    f = log_files(root)[0]
    raw_tail = f.read_bytes()[line_start(f, 4) :]
    flip_byte(f, line_start(f, 4) + 10)
    res = load_as_writer(root)
    val = res[-1]["value"]
    assert [e["seq"] for e in val["events"]] == [1, 2, 3, 4]
    assert "crc" in val["degraded"]["reason"]
    q = Path(val["degraded"]["quarantined"])
    assert q.parent == root / "quarantine" and q.exists()
    qb = q.read_bytes()
    assert (
        len(qb) == len(raw_tail) and sum(x != y for x, y in zip(qb, raw_tail, strict=True)) == 1
    )  # 逐語で保存
    assert f.read_bytes().count(b"\n") == 4
    # 書き込みは拒否され、理由が見える。再起動しても degraded のまま
    again = run(
        [
            {"op": "deadpids", "pids": [111, 222]},
            *opened(root, "c", 333),
            acquire("c"),
            append("c"),
            {"op": "readonlyReason", "name": "c"},
            {"op": "load", "name": "c"},
        ]
    )
    assert again[3]["code"] == "DEGRADED"
    assert "degraded" in again[4]["value"]
    assert "degraded" in again[5]["value"]


def test_degraded_is_reported_without_touching_files_for_a_reader(tmp_path: Path) -> None:
    root = fresh(tmp_path, 10)
    f = log_files(root)[0]
    flip_byte(f, line_start(f, 6) + 10)
    before = f.read_bytes()
    res = run([*opened(root, "r", 333), {"op": "load", "name": "r"}])
    assert [e["seq"] for e in res[-1]["value"]["events"]] == [1, 2, 3, 4, 5, 6]
    assert "degraded" in res[-1]["value"]
    assert f.read_bytes() == before and not (root / "quarantine").exists()


def _crc_hex_flip(f: Path) -> None:
    flip_byte(f, line_start(f, 2) + f.read_bytes()[line_start(f, 2) :].index(b"\n") - 1)


def _json_garbage_with_valid_crc(f: Path) -> None:
    lines = f.read_bytes().split(b"\n")
    body = b"{not json"
    lines[2] = body + b"\t" + f"{zlib.crc32(body):08x}".encode()
    f.write_bytes(b"\n".join(lines))


def _drop_line(f: Path) -> None:
    lines = f.read_bytes().split(b"\n")
    del lines[2]
    f.write_bytes(b"\n".join(lines))


def _line_without_crc(f: Path) -> None:
    lines = f.read_bytes().split(b"\n")
    lines[2] = lines[2].rpartition(b"\t")[0]
    f.write_bytes(b"\n".join(lines))


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (_crc_hex_flip, "crc"),
        (_json_garbage_with_valid_crc, "JSON"),
        (_drop_line, "欠番"),
        (_line_without_crc, "crc"),
    ],
)
def test_midfile_damage_kinds_are_all_quarantined(tmp_path: Path, mutate, reason: str) -> None:
    root = fresh(tmp_path, 8)
    mutate(log_files(root)[0])
    val = load_as_writer(root)[-1]["value"]
    assert [e["seq"] for e in val["events"]] == [1, 2]
    assert reason in val["degraded"]["reason"]
    assert Path(val["degraded"]["quarantined"]).exists()


def test_missing_middle_segment_is_a_gap_and_later_segments_are_quarantined(tmp_path: Path) -> None:
    root = fresh(tmp_path, 12, segmentSize=5)
    log_files(root)[1].unlink()
    val = load_as_writer(root, segmentSize=5)[-1]["value"]
    assert [e["seq"] for e in val["events"]] == [1, 2, 3, 4, 5]
    assert "欠番" in val["degraded"]["reason"]
    assert [p.name for p in log_files(root)] == ["0001.jsonl"]
    assert Path(val["degraded"]["quarantined"]).read_bytes().count(b"\n") == 2


def test_corruption_in_first_segment_quarantines_later_segments_too(tmp_path: Path) -> None:
    root = fresh(tmp_path, 12, segmentSize=5)
    f = log_files(root)[0]
    flip_byte(f, line_start(f, 3) + 10)
    val = load_as_writer(root, segmentSize=5)[-1]["value"]
    assert [e["seq"] for e in val["events"]] == [1, 2, 3]
    assert [p.name for p in log_files(root)] == ["0001.jsonl"]
    assert Path(val["degraded"]["quarantined"]).read_bytes().count(b"\n") == 9


def test_append_after_midfile_corruption_is_refused_at_first_call(tmp_path: Path) -> None:
    root = fresh(tmp_path, 6)
    f = log_files(root)[0]
    flip_byte(f, line_start(f, 2) + 10)
    res = run(
        [{"op": "deadpids", "pids": [111]}, *opened(root, "b", 222), acquire("b"), append("b")]
    )
    assert res[3]["code"] == "DEGRADED"
    assert f.read_bytes().count(b"\n") == 2


@pytest.mark.parametrize("cut", [1, 7, 40])
def test_torn_tail_is_truncated_and_recovered(tmp_path: Path, cut: int) -> None:
    root = fresh(tmp_path, 5)
    f = log_files(root)[0]
    f.write_bytes(f.read_bytes()[:-cut])
    val = load_as_writer(root)[-1]["value"]
    assert val["recovered"] is True and "degraded" not in val
    assert [e["seq"] for e in val["events"]] == [1, 2, 3, 4]
    assert f.read_bytes().endswith(b"\n") and f.read_bytes().count(b"\n") == 4


def test_torn_tail_then_append_continues_without_gap(tmp_path: Path) -> None:
    root = fresh(tmp_path, 5)
    f = log_files(root)[0]
    f.write_bytes(f.read_bytes()[:-9])
    res = run(
        [
            {"op": "deadpids", "pids": [111]},
            *opened(root, "b", 222),
            acquire("b"),
            append("b"),
            {"op": "load", "name": "b"},
        ]
    )
    assert res[3]["value"]["seq"] == 5
    assert [e["seq"] for e in res[-1]["value"]["events"]] == [1, 2, 3, 4, 5]
    assert "recovered" not in res[-1]["value"]


def test_torn_tail_seen_by_a_reader_is_reported_but_not_modified(tmp_path: Path) -> None:
    root = fresh(tmp_path, 5)
    f = log_files(root)[0]
    f.write_bytes(f.read_bytes()[:-9])
    before = f.read_bytes()
    res = run([*opened(root, "r", 333), {"op": "load", "name": "r"}])
    assert res[-1]["value"]["recovered"] is True and len(res[-1]["value"]["events"]) == 4
    assert f.read_bytes() == before


def test_torn_tail_in_a_rotated_segment(tmp_path: Path) -> None:
    root = fresh(tmp_path, 12, segmentSize=5)
    f = log_files(root)[-1]
    f.write_bytes(f.read_bytes()[:-5])
    val = load_as_writer(root, segmentSize=5)[-1]["value"]
    assert val["recovered"] is True and [e["seq"] for e in val["events"]] == list(range(1, 12))


def test_partial_line_at_the_end_of_a_non_last_segment_is_damage(tmp_path: Path) -> None:
    root = fresh(tmp_path, 12, segmentSize=5)
    f = log_files(root)[0]
    f.write_bytes(f.read_bytes()[:-5])
    val = load_as_writer(root, segmentSize=5)[-1]["value"]
    assert "degraded" in val and [e["seq"] for e in val["events"]] == [1, 2, 3, 4]


# ── スナップショット ─────────────────────────────────────────────


def test_snapshot_roundtrip_and_no_tmp_left(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *opened(root),
            acquire(),
            {"op": "saveSnapshot", "name": "a", "seq": 200, "json": '{"x":"あ"}'},
            {"op": "loadSnapshot", "name": "a"},
        ]
    )
    assert res[-1]["value"] == {"seq": 200, "json": '{"x":"あ"}'}
    assert sorted(p.name for p in root.iterdir() if p.name.startswith(("snapshot", "."))) == [
        "snapshot-0000000200.json"
    ]


def test_snapshot_requires_the_lease(tmp_path: Path) -> None:
    res = run(
        [*opened(tmp_path / "w"), {"op": "saveSnapshot", "name": "a", "seq": 1, "json": "{}"}]
    )
    assert res[1]["code"] == "NO_LEASE"


def test_snapshot_keeps_only_the_newest_two(tmp_path: Path) -> None:
    root = tmp_path / "w"
    ops = [*opened(root), acquire()]
    for s in (200, 400, 600, 800):
        ops.append({"op": "saveSnapshot", "name": "a", "seq": s, "json": "{}"})
    run(ops)
    assert sorted(p.name for p in root.glob("snapshot-*.json")) == [
        "snapshot-0000000600.json",
        "snapshot-0000000800.json",
    ]


def test_snapshot_due_every_200_events(tmp_path: Path) -> None:
    res = run(
        [
            *opened(tmp_path / "w"),
            acquire(),
            {"op": "snapshotDue", "name": "a", "seq": 199},
            {"op": "snapshotDue", "name": "a", "seq": 200},
            {"op": "saveSnapshot", "name": "a", "seq": 200, "json": "{}"},
            {"op": "snapshotDue", "name": "a", "seq": 399},
            {"op": "snapshotDue", "name": "a", "seq": 400},
        ]
    )
    assert [r["value"] for r in res if "value" in r and isinstance(r["value"], bool)] == [
        False,
        True,
        False,
        True,
    ]


def test_corrupt_snapshot_is_skipped_and_full_log_reconstructs(tmp_path: Path) -> None:
    root = tmp_path / "w"
    run([*writer(root, 30), {"op": "saveSnapshot", "name": "a", "seq": 30, "json": '{"n":30}'}])
    snap = next(root.glob("snapshot-*.json"))
    flip_byte(snap, 30)
    res = run(
        [*opened(root, "b", 222), {"op": "loadSnapshot", "name": "b"}, {"op": "load", "name": "b"}]
    )
    assert res[1]["value"] is None
    assert [e["seq"] for e in res[2]["value"]["events"]] == list(range(1, 31))


def test_corrupt_newest_snapshot_falls_back_to_the_older_one(tmp_path: Path) -> None:
    root = tmp_path / "w"
    run(
        [
            *opened(root),
            acquire(),
            {"op": "saveSnapshot", "name": "a", "seq": 200, "json": '{"n":1}'},
            {"op": "saveSnapshot", "name": "a", "seq": 400, "json": '{"n":2}'},
        ]
    )
    flip_byte(root / "snapshot-0000000400.json", 30)
    res = run([*opened(root, "b", 222), {"op": "loadSnapshot", "name": "b"}])
    assert res[1]["value"] == {"seq": 200, "json": '{"n":1}'}


def test_truncated_snapshot_file_is_ignored(tmp_path: Path) -> None:
    root = tmp_path / "w"
    run([*opened(root), acquire(), {"op": "saveSnapshot", "name": "a", "seq": 10, "json": "{}"}])
    snap = root / "snapshot-0000000010.json"
    snap.write_bytes(snap.read_bytes()[:10])
    assert run([*opened(root, "b", 222), {"op": "loadSnapshot", "name": "b"}])[1]["value"] is None


def test_load_since_reads_only_the_tail(tmp_path: Path) -> None:
    root = fresh(tmp_path, 12, segmentSize=5)
    res = run([*opened(root, "b", 222, segmentSize=5), {"op": "loadSince", "name": "b", "seq": 7}])
    assert [e["seq"] for e in res[1]["value"]["events"]] == [8, 9, 10, 11, 12]


def test_load_since_at_the_end_is_empty_and_ignores_older_damage(tmp_path: Path) -> None:
    root = fresh(tmp_path, 12, segmentSize=5)
    f = log_files(root)[0]
    flip_byte(f, line_start(f, 1) + 10)
    res = run(
        [
            *opened(root, "b", 222, segmentSize=5),
            {"op": "loadSince", "name": "b", "seq": 12},
            {"op": "loadSince", "name": "b", "seq": 5},
        ]
    )
    assert res[1]["value"]["events"] == []
    assert [e["seq"] for e in res[2]["value"]["events"]] == list(range(6, 13))


# ── 失敗 (ENOSPC / EROFS / EACCES) ───────────────────────────────


@pytest.mark.parametrize("code", ["ENOSPC", "EROFS", "EACCES"])
def test_write_failure_drops_to_readonly_with_reason_and_keeps_acked_events(
    tmp_path: Path, code: str
) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *opened(root),
            acquire(),
            append(),
            {"op": "fault", "name": "a", "code": code},
            append(),
            {"op": "fault", "name": "a", "code": None},
            append(),
            {"op": "readonlyReason", "name": "a"},
            {"op": "load", "name": "a"},
        ]
    )
    assert (res[4]["ok"], res[4]["code"]) == (False, "IO")
    assert code in res[4]["message"]
    assert res[6]["code"] == "READONLY"
    assert code in res[7]["value"]
    assert [e["seq"] for e in res[8]["value"]["events"]] == [1]


def test_failed_append_does_not_consume_a_seq_after_restart(tmp_path: Path) -> None:
    root = tmp_path / "w"
    run(
        [
            *opened(root),
            acquire(),
            append(),
            {"op": "fault", "name": "a", "code": "ENOSPC"},
            append(),
        ]
    )
    res = run(
        [{"op": "deadpids", "pids": [111]}, *opened(root, "b", 222), acquire("b"), append("b")]
    )
    assert res[3]["value"]["seq"] == 2


def test_snapshot_write_failure_is_visible_too(tmp_path: Path) -> None:
    res = run(
        [
            *opened(tmp_path / "w"),
            acquire(),
            {"op": "fault", "name": "a", "code": "ENOSPC"},
            {"op": "saveSnapshot", "name": "a", "seq": 1, "json": "{}"},
            {"op": "readonlyReason", "name": "a"},
        ]
    )
    assert res[3]["code"] == "IO" and "ENOSPC" in res[4]["value"]


def test_heartbeat_write_failure_is_visible(tmp_path: Path) -> None:
    res = run(
        [
            *opened(tmp_path / "w"),
            acquire(),
            {"op": "fault", "name": "a", "code": "EROFS"},
            {"op": "heartbeat", "name": "a"},
            {"op": "readonlyReason", "name": "a"},
        ]
    )
    assert res[3]["code"] == "IO" and "EROFS" in res[4]["value"]


@pytest.mark.skipif(IS_ROOT, reason="root は権限で書き込みが拒否されない")
def test_readonly_root_directory_cannot_acquire_and_reports_reason(tmp_path: Path) -> None:
    root = tmp_path / "ro"
    root.mkdir()
    root.chmod(0o555)
    try:
        res = run([*opened(root / "w"), acquire(), {"op": "readonlyReason", "name": "a"}, append()])
    finally:
        root.chmod(0o755)
    assert res[1]["value"] is None
    assert "EACCES" in res[2]["value"]
    assert res[3]["code"] == "NO_LEASE"


@pytest.mark.skipif(IS_ROOT, reason="root は権限で書き込みが拒否されない")
def test_readonly_log_directory_makes_append_fail_with_eacces(tmp_path: Path) -> None:
    root = tmp_path / "w"
    (root / "log").mkdir(parents=True)
    (root / "log").chmod(0o555)
    try:
        res = run(
            [*opened(root), acquire(), append(), {"op": "readonlyReason", "name": "a"}, append()]
        )
    finally:
        (root / "log").chmod(0o755)
    assert (res[2]["code"], res[4]["code"]) == ("IO", "READONLY")
    assert "EACCES" in res[3]["value"]


# ── resolveStoreRoot ─────────────────────────────────────────────


def _resolve(**kw) -> dict:
    return run([{"op": "resolveRoot", **kw}])[0]["value"]


def test_resolve_root_prefers_git_common_dir() -> None:
    got = _resolve(
        gitCommonDir="/r/.git", cwd="/r/wt", writable=["/r/.git/pi-work", "/r/wt/.tmp/work"]
    )
    assert got == {"root": "/r/.git/pi-work", "source": "git-common-dir", "writable": True}


def test_resolve_root_falls_back_when_git_dir_is_not_writable() -> None:
    got = _resolve(gitCommonDir="/r/.git", cwd="/r/wt", writable=["/r/wt/.tmp/work"])
    assert got == {"root": "/r/wt/.tmp/work", "source": "cwd-tmp", "writable": True}


def test_resolve_root_without_git_dir_uses_cwd() -> None:
    got = _resolve(cwd="/x", writable=["/x/.tmp/work"])
    assert (got["root"], got["source"]) == ("/x/.tmp/work", "cwd-tmp")


def test_resolve_root_reports_unwritable_fallback() -> None:
    got = _resolve(gitCommonDir="/r/.git", cwd="/r/wt", writable=[])
    assert (got["root"], got["source"], got["writable"]) == ("/r/wt/.tmp/work", "cwd-tmp", False)

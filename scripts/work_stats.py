#!/usr/bin/env python3
"""作業台帳の観測ログ (journal) を集計する。標準ライブラリのみ。

使い方: python3 scripts/work_stats.py [journal の .jsonl か、それを置いたディレクトリ ...] [--json]
既定は ./.tmp/work/journal。指標の定義と限界は docs/spec/work/journal.md。
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path

CONTACT_NOTICES = ("child-finished", "bg-job-finished")


def load(paths: list[Path]) -> list[dict]:
    """journal を読む。壊れた行は捨てる (観測用なので止めない)。"""
    files: list[Path] = []
    for p in paths:
        files.extend(sorted(p.glob("*.jsonl")) if p.is_dir() else [p])
    events: list[dict] = []
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if (
                isinstance(ev, dict)
                and isinstance(ev.get("ts"), (int, float))
                and isinstance(ev.get("type"), str)
            ):
                events.append(ev)
    events.sort(key=lambda e: (e["ts"], e.get("seq", 0)))
    return events


def percentile(values: list[float], p: float) -> float | None:
    """最近順位法 (nearest-rank)。空なら None。"""
    if not values:
        return None
    s = sorted(values)
    return s[max(1, math.ceil(p * len(s))) - 1]


def _count(ev: dict, key: str = "n") -> int:
    n = (ev.get("data") or {}).get(key)
    return int(n) if isinstance(n, (int, float)) and n > 0 else 1


def concurrency(events: list[dict]) -> tuple[float, int]:
    """子の同時数 (時間加重の平均, 最大)。run.started で +1、run.ended で -n (0 未満にしない)。"""
    marks = []
    for e in events:
        if e["type"] == "run.started":
            marks.append((e["ts"], 1))
        elif e["type"] == "run.ended":
            marks.append((e["ts"], -_count(e)))
    if not marks:
        return 0.0, 0
    cur = peak = 0
    area = 0.0
    last = marks[0][0]
    for ts, d in marks:
        area += cur * (ts - last)
        last = ts
        cur = max(0, cur + d)
        peak = max(peak, cur)
    span = marks[-1][0] - marks[0][0]
    return (area / span if span > 0 else float(peak)), peak


def restart_delays(events: list[dict]) -> list[float]:
    """子の完了から、次の起動までの遅延 (秒)。完了のあとに起動が無ければ数えない。"""
    starts = [e["ts"] for e in events if e["type"] == "run.started"]
    out = []
    for e in events:
        if e["type"] != "run.ended":
            continue
        nxt = next((t for t in starts if t >= e["ts"]), None)
        if nxt is not None:
            out.append((nxt - e["ts"]) / 1000)
    return out


def _data(e: dict) -> dict:
    d = e.get("data")
    return d if isinstance(d, dict) else {}


def compute(events: list[dict]) -> dict:
    tools = [e for e in events if e["type"] == "tool.call" and not _data(e).get("nested")]
    notices = [e for e in events if e["type"] == "notice"]
    wakes = [e for e in notices if _data(e).get("kind") in CONTACT_NOTICES]
    started = sum(1 for e in events if e["type"] == "run.started")
    contacts = len(tools) + len(wakes)
    avg_c, max_c = concurrency(events)
    delays = restart_delays(events)
    waits = [e for e in events if e["type"] == "wait.resolved" and _data(e).get("on") == "user"]
    wait_ms = [float(_data(e)["ms"]) for e in waits if isinstance(_data(e).get("ms"), (int, float))]
    per_day: dict[str, int] = {}
    for e in notices:
        lines = _data(e).get("lines_shown")
        if isinstance(lines, (int, float)) and lines > 0:
            day = datetime.fromtimestamp(e["ts"] / 1000).strftime("%Y-%m-%d")
            per_day[day] = per_day.get(day, 0) + int(lines)
    to_model = [
        float(_data(e)["chars_to_model"])
        for e in notices
        if isinstance(_data(e).get("chars_to_model"), (int, float))
    ]
    return {
        "events": len(events),
        "m1_contacts": contacts,
        "m1_tool_calls": len(tools),
        "m1_wakes": len(wakes),
        "m1_runs_started": started,
        "m1_contacts_per_run": (contacts / started) if started else None,
        "m2_concurrency_avg": avg_c,
        "m2_concurrency_max": max_c,
        "m4_restart_delay_p50_s": percentile(delays, 0.5),
        "m4_restart_delay_p90_s": percentile(delays, 0.9),
        "m4_restart_samples": len(delays),
        "user_waits": len(waits),
        "user_wait_total_s": sum(wait_ms) / 1000,
        "m5_visible_lines_total": sum(per_day.values()),
        "m5_visible_lines_per_day": (sum(per_day.values()) / len(per_day)) if per_day else 0.0,
        "m6_notices": len(to_model),
        "m6_chars_to_model_p90": percentile(to_model, 0.9),
    }


def fmt(v: object) -> str:
    if v is None:
        return "-"
    return f"{v:.1f}" if isinstance(v, float) else str(v)


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    args = [a for a in argv if a != "--json"]
    paths = [Path(a) for a in args] or [Path(".tmp/work/journal")]
    stats = compute(load(paths))
    if as_json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0
    for k, v in stats.items():
        print(f"{k:28} {fmt(v)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""shadow (観測) の jsonl を集計する。標準ライブラリのみ。

使い方:
    python3 scripts/shadow_stats.py [ファイルまたはディレクトリ ...]   (既定: .tmp/work/shadow)

出すもの: plan.ok の失敗率、would_tighten (旧が allow/ask なのに新が ok:false) の件数と上位の理由、
analyze の ms の p50 / p90 / p99、失敗した入力の先頭の語の上位。
記録の形式は home/dot_config/pi/harness/judge/shadow.ts。
see docs/spec/guard/pi-decide.md#shadow観測
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

DEFAULT_DIR = Path(".tmp/work/shadow")


def load(paths: list[Path]) -> list[dict]:
    """jsonl (または jsonl を含むディレクトリ) から記録を読む。壊れた行は飛ばす。"""
    files: list[Path] = []
    for p in paths:
        files.extend(sorted(p.glob("*.jsonl")) if p.is_dir() else [p])
    rows: list[dict] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def percentile(values: list[float], q: float) -> float:
    """最近傍順位法の百分位 (空なら 0)。"""
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, -(-len(s) * q // 100) - 1))
    return float(s[int(k)])


def summarize(rows: list[dict], top: int = 10) -> dict:
    """集計の結果 (辞書)。"""
    n = len(rows)
    failed = [r for r in rows if r.get("ok") is False]
    tight = [r for r in rows if r.get("would_tighten") is True]
    ms = [float(r["ms"]) for r in rows if isinstance(r.get("ms"), int | float)]
    return {
        "total": n,
        "failed": len(failed),
        "fail_rate": (len(failed) / n) if n else 0.0,
        "errors": sum(1 for r in rows if r.get("error")),
        "would_tighten": len(tight),
        "would_tighten_rate": (len(tight) / n) if n else 0.0,
        "tighten_why": Counter(str(r.get("why")) for r in tight).most_common(top),
        "vendor_missing": sum(1 for r in rows if r.get("vendor_missing")),
        "ms": {"p50": percentile(ms, 50), "p90": percentile(ms, 90), "p99": percentile(ms, 99)},
        "failed_heads": Counter(str(r.get("head", "?")) for r in failed).most_common(top),
    }


def render(s: dict) -> str:
    lines = [
        f"記録 {s['total']} 件 / plan 失敗 {s['failed']} 件 ({s['fail_rate']:.1%}) / analyze の例外 {s['errors']} 件",
        f"would_tighten (旧が allow/ask で新が ok:false): {s['would_tighten']} 件 ({s['would_tighten_rate']:.1%})",
        "  理由の上位: " + (", ".join(f"{w}={c}" for w, c in s["tighten_why"]) or "なし"),
        f"vendor 欠損: {s['vendor_missing']} 件",
        f"analyze の ms: p50={s['ms']['p50']:.2f} p90={s['ms']['p90']:.2f} p99={s['ms']['p99']:.2f}",
        "失敗した入力の先頭の語の上位: "
        + (", ".join(f"{h}={c}" for h, c in s["failed_heads"]) or "なし"),
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv] or [DEFAULT_DIR]
    rows = load(paths)
    if not rows:
        print("記録がない: " + " ".join(str(p) for p in paths))
        return 1
    print(render(summarize(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

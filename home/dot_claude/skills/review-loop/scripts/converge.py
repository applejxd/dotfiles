#!/usr/bin/env python3
"""review-loop の収束・step back 判定（決定的。標準ライブラリのみ）。

入力は rounds.jsonl（1 行 1 ラウンド）。形式は references/convergence.md を参照。

    {"round": 1, "cost_usd": 0.8, "findings": [
        {"id": "R1-1", "severity": "BLOCKER", "cause_class": "impl",
         "fingerprint": "gate:bypass", "status": "open", "introduced_by_fix": false}]}
    {"stepback": {"at": "2026-11-06 10:00", "decision": "範囲を狭める"}}

使い方:
    python3 converge.py check <rounds.jsonl> [--max-rounds 5 ...]
    python3 converge.py explain

判定は最後の step back 行より後のラウンド（区間）だけで行う。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SEVERITIES = ("BLOCKER", "MAJOR", "MINOR", "NIT")
STATUSES = ("open", "fixed", "verified", "accepted")
CAUSE_CLASSES = ("spec", "principle", "scope", "premise", "impl", "surface-open")

# 未解決とみなす状態（fixed は「直したが独立レビュー前」なので未解決に数える）
UNRESOLVED = ("open", "fixed")


class InputError(ValueError):
    """rounds.jsonl の形式エラー。"""


@dataclass(frozen=True)
class Config:
    """トリガーの閾値（既定値。コマンドラインで変えられる）。"""

    max_rounds: int = 5  # ラウンド数の上限
    max_stepbacks: int = 2  # step back をこの回数行っても収束しなければ stop
    recur: int = 2  # T1: 同じ原因クラスの BLOCKER の再発回数（出現はこの値 + 1 ラウンド）
    streak: int = 3  # T2: 異なる原因クラスの BLOCKER が続くラウンド数
    fix_streak: int = 2  # T3: introduced_by_fix の BLOCKER が続くラウンド数
    fp_streak: int = 2  # T4: 同じ fingerprint が open で続くラウンド数
    bm_total: int = 15  # T5: BLOCKER+MAJOR の累計件数
    cost: float = 6.0  # T5: 累計費用（USD）
    t6_round: int = 3  # T6: このラウンド以降で
    t6_blockers: int = 2  # T6: 未解決の BLOCKER がこの件数以上


EXPLAIN = {
    "T1": "同じ原因クラスの BLOCKER が累計 2 回再発（3 ラウンドで出現）。実例: フルガード再設計の『緩和』クラスが 3 回。原理を疑う。",
    "T2": "異なる原因クラスの BLOCKER が 3 ラウンド連続で出る。実例: git_push の 5 回の review。穴を塞ぐ段でなく範囲・責任を疑う。",
    "T3": "直した結果の新しい BLOCKER（introduced_by_fix）が 2 ラウンド続く。実例: git_push の v3→v3.1→v3.2。修正が範囲を広げている。",
    "T4": "同じ fingerprint の BLOCKER/MAJOR が 2 ラウンド連続で open（従来の停滞）。修正方針かレビューの文脈を疑う。",
    "T5": "BLOCKER+MAJOR の累計が約 15 件、または累計費用が $6 超。実例: 非同期承認系の指摘 43 件、git_push の約 $8.4。",
    "T6": "ラウンド 3 以降で未解決の BLOCKER が 2 件以上残る（利用者の指定）。パッチを当て続けない。",
    "T7": "surface-open（保証したい面が閉じていない）が 1 件でも出る。実例: git_push の config・hook・ref。範囲の縮小か撤去を先に検討。",
}


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise InputError(msg)


def _parse_finding(raw: Any, where: str) -> dict[str, Any]:
    _require(isinstance(raw, dict), f"{where}: 指摘はオブジェクトでなければならない")
    for key in ("id", "severity", "cause_class", "fingerprint", "status"):
        _require(key in raw, f"{where}: 必須キー {key} が無い")
    for key in ("id", "fingerprint"):
        _require(isinstance(raw[key], str) and raw[key] != "", f"{where}: {key} は空でない文字列")
    _require(raw["severity"] in SEVERITIES, f"{where}: 未知の severity {raw['severity']!r}")
    _require(
        raw["cause_class"] in CAUSE_CLASSES, f"{where}: 未知の cause_class {raw['cause_class']!r}"
    )
    _require(raw["status"] in STATUSES, f"{where}: 未知の status {raw['status']!r}")
    fixed_flag = raw.get("introduced_by_fix", False)
    _require(isinstance(fixed_flag, bool), f"{where}: introduced_by_fix は真偽値")
    return {**raw, "introduced_by_fix": fixed_flag}


def parse_records(text: str) -> tuple[list[dict[str, Any]], int]:
    """JSONL を読み、(最後の step back 後のラウンド一覧, step back の回数) を返す。"""
    segment: list[dict[str, Any]] = []
    stepbacks = 0
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        where = f"{lineno} 行目"
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise InputError(f"{where}: JSON として読めない ({e.msg})") from e
        _require(isinstance(obj, dict), f"{where}: オブジェクトでなければならない")
        if "stepback" in obj:
            _require(isinstance(obj["stepback"], dict), f"{where}: stepback はオブジェクト")
            stepbacks += 1
            segment = []
            continue
        _require("round" in obj, f"{where}: 必須キー round が無い")
        rnd = obj["round"]
        _require(
            isinstance(rnd, int) and not isinstance(rnd, bool) and rnd >= 1,
            f"{where}: round は 1 以上の整数",
        )
        _require(
            not segment or rnd > segment[-1]["round"],
            f"{where}: round は増加していなければならない",
        )
        cost = obj.get("cost_usd", 0)
        _require(
            isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0,
            f"{where}: cost_usd は 0 以上の数",
        )
        findings_raw = obj.get("findings")
        _require(isinstance(findings_raw, list), f"{where}: findings は配列")
        findings = [_parse_finding(f, f"{where} findings[{i}]") for i, f in enumerate(findings_raw)]
        ids = [f["id"] for f in findings]
        _require(len(ids) == len(set(ids)), f"{where}: 同じ round に重複した id がある")
        segment.append({"round": rnd, "cost_usd": float(cost), "findings": findings})
    return segment, stepbacks


def _latest_state(rounds: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """id ごとの最新の記録（台帳の現在の状態）。"""
    state: dict[str, dict[str, Any]] = {}
    for r in rounds:
        for f in r["findings"]:
            state[f["id"]] = f
    return state


def _new_findings(rounds: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """ラウンドごとの、その区間で初めて出た id の指摘。"""
    seen: set[str] = set()
    out: list[list[dict[str, Any]]] = []
    for r in rounds:
        fresh = [f for f in r["findings"] if f["id"] not in seen]
        seen.update(f["id"] for f in r["findings"])
        out.append(fresh)
    return out


def _longest_run(flags: list[bool]) -> int:
    best = cur = 0
    for flag in flags:
        cur = cur + 1 if flag else 0
        best = max(best, cur)
    return best


def evaluate(rounds: list[dict[str, Any]], stepbacks: int, cfg: Config) -> dict[str, Any]:
    state = _latest_state(rounds)
    fresh = _new_findings(rounds)
    triggers: list[str] = []
    reasons: list[str] = []

    def fire(name: str, why: str) -> None:
        triggers.append(name)
        reasons.append(f"{name}: {why}")

    # T1 同じ原因クラスの BLOCKER が出たラウンド数（再発 = 出現 - 1）
    by_class: dict[str, int] = {}
    for fs in fresh:
        for cls in {f["cause_class"] for f in fs if f["severity"] == "BLOCKER"}:
            by_class[cls] = by_class.get(cls, 0) + 1
    for cls, n in sorted(by_class.items()):
        if n - 1 >= cfg.recur:
            fire("T1", f"原因クラス {cls} の BLOCKER が {n} ラウンドで出現（再発 {n - 1} 回）")

    # T2 新しい BLOCKER が連続するラウンドで出て、原因クラスが 2 種類以上
    blocker_rounds = [[f for f in fs if f["severity"] == "BLOCKER"] for fs in fresh]
    run: list[set[str]] = []
    t2_hit = False
    for bs in [*blocker_rounds, []]:
        if bs:
            run.append({f["cause_class"] for f in bs})
            continue
        if len(run) >= cfg.streak and len(set().union(*run)) >= 2:
            t2_hit = True
        run = []
    if t2_hit:
        fire("T2", f"異なる原因クラスの BLOCKER が {cfg.streak} ラウンド以上連続で出ている")

    # T3 直した結果の新しい BLOCKER が連続
    fix_flags = [any(f["introduced_by_fix"] for f in bs) for bs in blocker_rounds]
    if _longest_run(fix_flags) >= cfg.fix_streak:
        fire("T3", f"直した結果の新しい BLOCKER が {cfg.fix_streak} ラウンド続いている")

    # T4 同じ fingerprint が連続するラウンドで open（BLOCKER / MAJOR のみ）
    open_fps = [
        {
            f["fingerprint"]
            for f in r["findings"]
            if f["status"] == "open" and f["severity"] in SEVERITIES[:2]
        }
        for r in rounds
    ]
    for fp in sorted(set().union(*open_fps) if open_fps else set()):
        if _longest_run([fp in s for s in open_fps]) >= cfg.fp_streak:
            fire("T4", f"fingerprint {fp} が {cfg.fp_streak} ラウンド連続で open")

    # T5 BLOCKER+MAJOR の累計件数・累計費用
    bm_ids = {f["id"] for r in rounds for f in r["findings"] if f["severity"] in SEVERITIES[:2]}
    cost = sum(r["cost_usd"] for r in rounds)
    if len(bm_ids) >= cfg.bm_total:
        fire("T5", f"BLOCKER+MAJOR の累計が {len(bm_ids)} 件（基準 {cfg.bm_total}）")
    if cost > cfg.cost:
        fire("T5", f"累計費用が ${cost:.2f}（基準 ${cfg.cost:.2f}）")

    # T6 ラウンド 3 以降で未解決の BLOCKER が複数
    unresolved_blockers = [
        f for f in state.values() if f["severity"] == "BLOCKER" and f["status"] in UNRESOLVED
    ]
    if len(rounds) >= cfg.t6_round and len(unresolved_blockers) >= cfg.t6_blockers:
        fire("T6", f"ラウンド {len(rounds)} で未解決の BLOCKER が {len(unresolved_blockers)} 件")

    # T7 保証したい面が閉じていない
    surface = sorted(
        {f["id"] for r in rounds for f in r["findings"] if f["cause_class"] == "surface-open"}
    )
    if surface:
        fire("T7", f"surface-open の指摘がある（{', '.join(surface)}）")

    unresolved_bm = [
        f for f in state.values() if f["severity"] in SEVERITIES[:2] and f["status"] in UNRESOLVED
    ]
    accepted_bm = [
        f for f in state.values() if f["severity"] in SEVERITIES[:2] and f["status"] == "accepted"
    ]
    last_fixed = bool(rounds) and any(f["status"] == "fixed" for f in rounds[-1]["findings"])

    metrics = {
        "rounds": len(rounds),
        "stepbacks": stepbacks,
        "cost_usd": round(cost, 4),
        "bm_total": len(bm_ids),
        "unresolved_blocker": len(unresolved_blockers),
        "unresolved_major": sum(1 for f in unresolved_bm if f["severity"] == "MAJOR"),
        "accepted_bm": len(accepted_bm),
        "new_blocker_rounds_by_class": dict(sorted(by_class.items())),
    }

    if not rounds:
        verdict = "continue"
        reasons.append("ラウンド記録がまだ無い")
    elif not unresolved_bm and not accepted_bm and not last_fixed:
        verdict = "converged"
        reasons.insert(
            0,
            "未解決の BLOCKER・MAJOR が 0 で、直した指摘は独立レビューで verified 済み（triggers は参考情報）",
        )
    elif not unresolved_bm and accepted_bm and not last_fixed:
        verdict = "stop"
        reasons.append("リスク受容の BLOCKER・MAJOR が残る（収束とは呼ばない。利用者の承認が要る）")
    elif triggers:
        if stepbacks >= cfg.max_stepbacks:
            verdict = "stop"
            reasons.append(
                f"step back を {stepbacks} 回行っても収束しない。撤退・縮小・撤去を利用者に提案する"
            )
        else:
            verdict = "stepback"
    elif len(rounds) >= cfg.max_rounds:
        verdict = "stop"
        reasons.append(f"ラウンドの上限 {cfg.max_rounds} に達した")
    else:
        verdict = "continue"
        reasons.append("トリガーなし。次のラウンドへ")

    return {
        "verdict": verdict,
        "triggers": sorted(set(triggers)),
        "reasons": reasons,
        "metrics": metrics,
    }


def check(path: Path, cfg: Config) -> dict[str, Any]:
    rounds, stepbacks = parse_records(path.read_text(encoding="utf-8"))
    return evaluate(rounds, stepbacks, cfg)


def build_parser() -> argparse.ArgumentParser:
    d = Config()
    p = argparse.ArgumentParser(description="review-loop の収束・step back 判定")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="rounds.jsonl を判定して JSON を出す")
    c.add_argument("rounds", type=Path)
    c.add_argument("--max-rounds", type=int, default=d.max_rounds)
    c.add_argument("--max-stepbacks", type=int, default=d.max_stepbacks)
    c.add_argument("--recur", type=int, default=d.recur, help="T1: 同じクラスの再発回数")
    c.add_argument("--streak", type=int, default=d.streak, help="T2: 連続ラウンド数")
    c.add_argument("--fix-streak", type=int, default=d.fix_streak, help="T3: 連続ラウンド数")
    c.add_argument("--fp-streak", type=int, default=d.fp_streak, help="T4: 連続ラウンド数")
    c.add_argument("--bm-total", type=int, default=d.bm_total, help="T5: BLOCKER+MAJOR の累計")
    c.add_argument("--cost", type=float, default=d.cost, help="T5: 累計費用 (USD)")
    c.add_argument("--t6-round", type=int, default=d.t6_round)
    c.add_argument("--t6-blockers", type=int, default=d.t6_blockers)
    sub.add_parser("explain", help="各トリガーの意味と実例を表示する")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "explain":
        for name, text in EXPLAIN.items():
            print(f"{name}: {text}")
        return 0
    cfg = Config(
        max_rounds=args.max_rounds,
        max_stepbacks=args.max_stepbacks,
        recur=args.recur,
        streak=args.streak,
        fix_streak=args.fix_streak,
        fp_streak=args.fp_streak,
        bm_total=args.bm_total,
        cost=args.cost,
        t6_round=args.t6_round,
        t6_blockers=args.t6_blockers,
    )
    try:
        result = check(args.rounds, cfg)
    except (InputError, OSError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

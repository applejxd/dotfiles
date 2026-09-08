#!/usr/bin/env python3
"""away-shift skill の停止判定と実行記録を扱うガード。

無人実行では「止まるべきときに止まる」ことが最優先になる。停止条件の判定を
エージェントの記憶に任せると、サイクルが長引いたときに期限を跨いでしまう。
判定をこのスクリプトに寄せて、サイクルの先頭で必ず呼ぶ運用にする。

サブコマンド:

    init   実行ディレクトリと期限を作る。既存の run があれば再利用する
    check  停止条件を判定する。継続なら exit 0、停止なら exit 3
    log    サイクルの記録を追記する
    status 現在の run の要約を出す

exit code:

    0  継続してよい
    3  停止条件に当たった (stdout に理由)
    2  引数や状態の誤り

依存は標準ライブラリのみ。``uv run --no-project python`` で動く。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

# 実行記録の置き場。リポジトリ直下の使い捨てディレクトリに置く
RUN_ROOT = Path(".tmp/away-shift")
STATE_NAME = "state.json"
# ユーザが手で置いて止めるためのファイル。run 側とリポジトリ直下の両方を見る
STOP_NAMES = ("STOP", "stop")

EXIT_CONTINUE = 0
EXIT_STOP = 3
EXIT_USAGE = 2

# "07:30" / "2026-09-10 07:30" / "8h" / "90m" を受け付ける
_CLOCK_RE = re.compile(r"^(?P<h>\d{1,2}):(?P<m>\d{2})$")
_DATETIME_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})[ T](?P<h>\d{1,2}):(?P<m>\d{2})$")
_DURATION_RE = re.compile(r"^(?P<value>\d+(?:\.\d+)?)(?P<unit>[hm])$")


def now() -> dt.datetime:
    return dt.datetime.now()


def parse_deadline(value: str, base: dt.datetime) -> dt.datetime:
    """期限の指定を絶対時刻へ直す。

    ``07:30`` のような時刻だけの指定は「次にその時刻になる瞬間」と解釈する。
    夜に離席して翌朝で止める、昼に離席して夕方で止める、どちらも同じ書き方で
    済ませたいので、過ぎている時刻は翌日とみなす。
    """
    text = value.strip()

    match = _DATETIME_RE.match(text)
    if match:
        date = dt.date.fromisoformat(match.group("date"))
        return dt.datetime.combine(
            date, dt.time(int(match.group("h")), int(match.group("m")))
        )

    match = _CLOCK_RE.match(text)
    if match:
        target = dt.time(int(match.group("h")), int(match.group("m")))
        candidate = dt.datetime.combine(base.date(), target)
        if candidate <= base:
            candidate += dt.timedelta(days=1)
        return candidate

    match = _DURATION_RE.match(text)
    if match:
        amount = float(match.group("value"))
        delta = (
            dt.timedelta(hours=amount)
            if match.group("unit") == "h"
            else dt.timedelta(minutes=amount)
        )
        return base + delta

    raise ValueError(
        f"期限の書式が読めません: {value!r} "
        "(HH:MM / YYYY-MM-DD HH:MM / 8h / 90m のいずれか)"
    )


def run_dir(run_id: str) -> Path:
    return RUN_ROOT / run_id


def state_path(run_id: str) -> Path:
    return run_dir(run_id) / STATE_NAME


def load_state(run_id: str) -> dict:
    path = state_path(run_id)
    if not path.exists():
        raise FileNotFoundError(f"run が見つかりません: {path} (先に init を実行)")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_state(run_id: str, state: dict) -> None:
    path = state_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def find_stop_file(run_id: str) -> Path | None:
    """STOP ファイルを探す。run 配下とリポジトリ直下の両方を見る。

    リポジトリ直下も見るのは、ユーザが run_id を知らなくても
    ``touch STOP`` だけで止められるようにするため。
    """
    candidates = [run_dir(run_id) / name for name in STOP_NAMES]
    candidates += [Path(name) for name in STOP_NAMES]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def cmd_init(args: argparse.Namespace) -> int:
    base = now()
    run_id = args.run_id or base.strftime("%Y%m%d-%H%M%S")
    path = state_path(run_id)
    if path.exists() and not args.force:
        state = load_state(run_id)
        print(f"既存の run を再利用します: {run_id}")
        print(f"  期限: {state['deadline']}")
        print(f"  目標: {state['goal']}")
        return EXIT_CONTINUE

    try:
        deadline = parse_deadline(args.deadline, base)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    if deadline <= base:
        print(f"期限が現在時刻より前です: {deadline.isoformat()}", file=sys.stderr)
        return EXIT_USAGE

    state = {
        "run_id": run_id,
        "goal": args.goal,
        "started_at": base.isoformat(timespec="seconds"),
        "deadline": deadline.isoformat(timespec="seconds"),
        "max_cycles": args.max_cycles,
        "cycle": 0,
        "stopped": None,
    }
    save_state(run_id, state)
    (run_dir(run_id) / "cycles").mkdir(parents=True, exist_ok=True)
    # 試行錯誤の作業場。ここだけは消してよい。cycles/ と state.json、
    # report.md は証跡なので消さない
    (run_dir(run_id) / "work").mkdir(parents=True, exist_ok=True)
    print(f"run_id: {run_id}")
    print(f"作業ディレクトリ: {run_dir(run_id) / 'work'}")
    print(f"証跡ディレクトリ: {run_dir(run_id)} (消さない)")
    print(f"期限: {deadline.isoformat(timespec='seconds')}")
    print(f"最大サイクル: {args.max_cycles}")
    print(f"停止するには: touch {run_dir(run_id) / 'STOP'}  または  touch STOP")
    return EXIT_CONTINUE


def cmd_check(args: argparse.Namespace) -> int:
    try:
        state = load_state(args.run_id)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE

    current = now()
    deadline = dt.datetime.fromisoformat(state["deadline"])

    stop_file = find_stop_file(args.run_id)
    if stop_file is not None:
        state["stopped"] = f"stop-file:{stop_file}"
        save_state(args.run_id, state)
        print(f"STOP: 停止ファイルがあります ({stop_file})")
        return EXIT_STOP

    if current >= deadline:
        state["stopped"] = "deadline"
        save_state(args.run_id, state)
        print(f"STOP: 期限に達しました ({state['deadline']})")
        return EXIT_STOP

    remaining = deadline - current
    remaining_min = int(remaining.total_seconds() // 60)
    if remaining_min < args.reserve_minutes:
        state["stopped"] = "reserve"
        save_state(args.run_id, state)
        print(
            f"STOP: 残り {remaining_min} 分で、レポート用の予備 "
            f"{args.reserve_minutes} 分を下回りました"
        )
        return EXIT_STOP

    if state["cycle"] >= state["max_cycles"]:
        state["stopped"] = "max-cycles"
        save_state(args.run_id, state)
        print(f"STOP: 最大サイクル数に達しました ({state['max_cycles']})")
        return EXIT_STOP

    state["cycle"] += 1
    save_state(args.run_id, state)
    remaining_cycles = max(1, state["max_cycles"] - state["cycle"])
    # 次のサイクルまでどれだけ空けるか。無人実行では 1 サイクルが数分で
    # 終わってしまい、離席時間を使い切れずに手が空く。残り時間を残り
    # サイクル数で割って、復帰時刻まで均等に配分する
    usable_min = max(0, remaining_min - args.reserve_minutes)
    pace_min = min(usable_min // remaining_cycles, args.max_wake_minutes)
    print(f"CONTINUE: cycle {state['cycle']}/{state['max_cycles']}")
    print(f"  残り: {remaining_min} 分 (期限 {state['deadline']})")
    print(f"  目標: {state['goal']}")
    print(f"NEXT_WAKE_SECONDS: {max(60, pace_min * 60)}")
    return EXIT_CONTINUE


def cmd_log(args: argparse.Namespace) -> int:
    try:
        state = load_state(args.run_id)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE

    cycle = args.cycle if args.cycle is not None else state["cycle"]
    path = run_dir(args.run_id) / "cycles" / f"cycle-{cycle:03d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = args.text if args.text is not None else sys.stdin.read()
    stamp = now().isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n## {stamp}\n\n{body.rstrip()}\n")
    print(f"追記しました: {path}")
    return EXIT_CONTINUE


def cmd_status(args: argparse.Namespace) -> int:
    try:
        state = load_state(args.run_id)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    deadline = dt.datetime.fromisoformat(state["deadline"])
    remaining = int((deadline - now()).total_seconds() // 60)
    print(json.dumps({**state, "remaining_minutes": remaining}, ensure_ascii=False, indent=2))
    return EXIT_CONTINUE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="run を作る")
    p_init.add_argument("--goal", required=True, help="達成したいこと (1 行)")
    p_init.add_argument(
        "--deadline",
        required=True,
        help="停止時刻。HH:MM / YYYY-MM-DD HH:MM / 8h / 90m",
    )
    p_init.add_argument("--run-id", help="省略時は開始時刻から作る")
    p_init.add_argument("--max-cycles", type=int, default=20)
    p_init.add_argument("--force", action="store_true", help="既存 run を上書きする")
    p_init.set_defaults(func=cmd_init)

    p_check = sub.add_parser("check", help="停止条件を判定する (継続 0 / 停止 3)")
    p_check.add_argument("run_id")
    p_check.add_argument(
        "--reserve-minutes",
        type=int,
        default=15,
        help="レポート作成用に残す時間。既定 15 分",
    )
    p_check.add_argument(
        "--max-wake-minutes",
        type=int,
        default=60,
        help=(
            "NEXT_WAKE_SECONDS の上限 (分)。"
            "manage_schedule の wakeup は 1 時間で頭打ちになる"
        ),
    )
    p_check.set_defaults(func=cmd_check)

    p_log = sub.add_parser("log", help="サイクルの記録を追記する")
    p_log.add_argument("run_id")
    p_log.add_argument("--cycle", type=int)
    p_log.add_argument("--text", help="省略時は標準入力から読む")
    p_log.set_defaults(func=cmd_log)

    p_status = sub.add_parser("status", help="現在の状態を出す")
    p_status.add_argument("run_id")
    p_status.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = os.environ.get("AWAY_SHIFT_ROOT")
    if root:
        os.chdir(root)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""聞き取り用の確認シート(review.csv)を作る・指摘(notes.json)を読む。

指摘の正本は `notes.json`(キーは行番号、値は {note, text(指摘したときの本文), at})。確認サーバの画面が
書き、窓口(state_store)だけが書く(ADR-0003)。`review.csv` は、timestamps.json と notes.json から作る
**書き出し専用**の表(Excel などで見る)で、手で書き込んでも取り込まない(作り直すと上書きされる)。

列: 行, 開始(分:秒), 本文, 読み(アクセント句を | で区切った仮名), 指摘。
`--notes` で、指摘の一覧を出す(エージェントが直す対象を読むため)。指摘をしたときの本文と、いまの
台本の本文が違う指摘は「古い」と示す(別の行へ付け直さない)。

終了コード: 0 = 成功、2 = 入力が無い・指摘が壊れている。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import narration_check  # noqa: E402
import state_store  # noqa: E402

HEADER = ["行", "開始", "本文", "読み", "指摘"]
NOTES_FILE = "notes.json"


def mmss(sec: float) -> str:
    s = int(sec)
    return f"{s // 60}:{s % 60:02d}"


# ───────────── 指摘(notes.json) ─────────────


def validate_entry(key: str, e) -> None:
    """1 件の検証(state_store の validate に渡す)。不正なら ValueError。"""
    if not key.isdigit() or int(key) < 1:
        raise ValueError("キーは 1 以上の行番号")
    if not isinstance(e, dict) or not all(
        isinstance(e.get(k), str) for k in ("note", "text", "at")
    ):
        raise ValueError("note・text・at(文字列)が要る")
    if not e["note"].strip():
        raise ValueError("note が空(消すときは項目を消す)")


def notes_store(workdir: Path | str) -> state_store.Store:
    return state_store.Store(Path(workdir) / NOTES_FILE, validate=validate_entry)


def read_notes(
    workdir: Path | str, current_lines: list[str] | None = None
) -> list[dict]:
    """指摘を行番号順に返す。current_lines(いまの台本の各行の本文)を渡すと、
    本文が違う・行が無い指摘に stale=True を付ける。壊れていれば ValueError。"""
    try:
        entries = notes_store(workdir).read().entries
    except state_store.Corrupt as e:
        raise ValueError(str(e)) from e
    out = []
    for key in sorted(entries, key=int):
        e = entries[key]
        line = int(key)
        stale = False
        if current_lines is not None:
            stale = not (
                line <= len(current_lines) and current_lines[line - 1] == e["text"]
            )
        out.append(
            {
                "line": line,
                "note": e["note"],
                "text": e["text"],
                "at": e["at"],
                "stale": stale,
                "entry": e,  # 画面が「見た記録」として更新に添える(比較交換)
            }
        )
    return out


# ───────────── 書き出し ─────────────


def build_rows(ts: dict, notes: dict[int, str] | None = None) -> list[list[str]]:
    rows = []
    for i, s in enumerate(ts["subtitles"], 1):
        reading = "|".join(p["text"] for p in s.get("phrases", []))
        rows.append(
            [str(i), mmss(s["start_s"]), s["text"], reading, (notes or {}).get(i, "")]
        )
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--workdir", default=".")
    ap.add_argument("--timestamps", default="timestamps.json")
    ap.add_argument("--out", default="review.csv")
    ap.add_argument(
        "--notes", action="store_true", help="指摘の一覧を表示する(notes.json)"
    )
    a = ap.parse_args(argv)

    w = Path(a.workdir)
    tsp = w / a.timestamps
    ts = None
    if tsp.is_file():
        ts = json.loads(tsp.read_text(encoding="utf-8"))
    current = [s["text"] for s in ts["subtitles"]] if ts else None
    narr = w / "narration.txt"
    if (
        narr.is_file()
    ):  # 「古い」の基準はいまの台本(再合成前でも、timestamps.json より新しい)
        try:
            current = narration_check.parse_subtitles(narr)
        except (ValueError, OSError):
            pass  # 台本が読めないときは timestamps.json を基準にする
    try:
        notes = read_notes(w, current)
    except ValueError as e:
        print(f"エラー: {e}")
        return 2

    if a.notes:
        starts = (
            {i: mmss(s["start_s"]) for i, s in enumerate(ts["subtitles"], 1)}
            if ts
            else {}
        )
        for n in notes:
            mark = "(古い: 台本が変わった)" if n["stale"] else ""
            when = f"({starts[n['line']]})" if n["line"] in starts else ""
            print(f"{n['line']}行目{when} {n['text']}{mark}\n   指摘: {n['note']}")
        print(f"指摘 {len(notes)} 件")
        return 0

    if ts is None:
        print(f"エラー: {tsp.name} が無い(先に tts_generate.py を実行する)")
        return 2
    out = w / a.out
    by_line = {n["line"]: ("【古い】" if n["stale"] else "") + n["note"] for n in notes}
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(HEADER)
        wr.writerows(build_rows(ts, by_line))
    print(
        f"書き出し: {out.resolve()}({len(ts['subtitles'])} 行。Excel 用。取り込みはしない。指摘は画面で書く)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

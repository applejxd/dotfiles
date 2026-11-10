#!/usr/bin/env python3
"""聞き取り用の確認シート(review.csv)を作る・指摘(notes.json)を読み書きする。

指摘の正本は `notes.json`。確認サーバの画面と、この CLI が窓口(state_store)経由で書く(ADR-0003)。
キーは**指摘した行の本文から作った ID**(`n` + 16 進 10 桁)で、値は
{line(最後に分かっていた行), text(指摘した行の本文), note, status(open / fixed), at, fixed_at}。
行番号をキーにしないので、行が挿入・削除されても指摘は同じ本文の行へついていく。
本文が変わると、指摘は付け直さず「古い」と示す(自動では閉じない)。
同じ本文の行が複数あるときは、1 つの指摘を共有して最初の行に出す。

`review.csv` は、timestamps.json と notes.json から作る**書き出し専用**の表(Excel などで見る)で、
手で書き込んでも取り込まない。列: 行, 開始(分:秒), 本文, 読み(アクセント句を | で区切った仮名), 指摘。

使い方:
  review_sheet.py --workdir DIR                 review.csv を作る
  review_sheet.py --workdir DIR --notes [--all]  指摘の一覧(既定は未対応だけ。ID つき)
  review_sheet.py --workdir DIR --fix ID...      直した指摘を「対応済み」にする(画面に残る確認待ち)
  review_sheet.py --workdir DIR --reopen ID...   「対応済み」を未対応へ戻す
  review_sheet.py --workdir DIR --remove ID...   指摘を消す

終了コード: 0 = 成功、2 = 入力が無い・指摘が壊れている・ID が無い。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import narration_check  # noqa: E402
import state_store  # noqa: E402

HEADER = ["行", "開始", "本文", "読み", "指摘"]
NOTES_FILE = "notes.json"
OPEN, FIXED = "open", "fixed"
STATUSES = (OPEN, FIXED)
FIELDS = {"line", "text", "note", "status", "at", "fixed_at"}
KEY_RE = re.compile(r"^n[0-9a-f]{10}$")


def mmss(sec: float) -> str:
    s = int(sec)
    return f"{s // 60}:{s % 60:02d}"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ───────────── 指摘(notes.json) ─────────────


def note_key(text: str) -> str:
    """指摘した行の本文から作る ID。行が動いても同じ本文の行へついていく。"""
    return "n" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def make_entry(
    line: int,
    text: str,
    note: str,
    status: str = OPEN,
    at: str | None = None,
    fixed_at: str | None = None,
) -> dict:
    e = {
        "line": line,
        "text": text,
        "note": note,
        "status": status,
        "at": at or now_iso(),
    }
    if status == FIXED:
        e["fixed_at"] = fixed_at or now_iso()
    return e


def validate_entry(key: str, e) -> None:
    """1 件の検証(state_store の validate に渡す)。不正なら ValueError。"""
    if not isinstance(key, str) or not KEY_RE.match(key):
        raise ValueError("キーは行の本文から作った ID(n + 16 進 10 桁)")
    if not isinstance(e, dict) or set(e) - FIELDS:
        raise ValueError("項目は line・text・note・status・at・fixed_at だけ")
    line = e.get("line")
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        raise ValueError("line は 1 以上の整数")
    for k in ("text", "note", "at"):
        if not isinstance(e.get(k), str):
            raise ValueError(f"{k} は文字列")
    if not e["text"]:
        raise ValueError("text が空")
    if key != note_key(e["text"]):
        raise ValueError("キーが本文と合わない")
    if not e["note"].strip():
        raise ValueError("note が空(消すときは項目を消す)")
    if e.get("status") not in STATUSES:
        raise ValueError("status は open か fixed")
    if "fixed_at" in e and (e["status"] != FIXED or not isinstance(e["fixed_at"], str)):
        raise ValueError("fixed_at は対応済みのときだけ(文字列)")


def notes_store(workdir: Path | str) -> state_store.Store:
    return state_store.Store(Path(workdir) / NOTES_FILE, validate=validate_entry)


def read_notes(
    workdir: Path | str, current_lines: list[str] | None = None
) -> list[dict]:
    """指摘を行の順に返す。current_lines(いまの台本の各行の本文)を渡すと、
    同じ本文の行へ追従した位置(line)と moved を付け、本文が無い指摘に stale=True を付ける。
    壊れていれば ValueError。"""
    try:
        entries = notes_store(workdir).read().entries
    except state_store.Corrupt as e:
        raise ValueError(str(e)) from e
    out = []
    for key, e in entries.items():
        line, stale, moved = e["line"], False, False
        if current_lines is not None:
            at = [i + 1 for i, t in enumerate(current_lines) if t == e["text"]]
            if at:
                line = e["line"] if e["line"] in at else at[0]
                moved = line != e["line"]
            else:
                stale = True
        out.append(
            {
                "id": key,
                "line": line,
                "text": e["text"],
                "note": e["note"],
                "status": e["status"],
                "at": e["at"],
                "fixed_at": e.get("fixed_at", ""),
                "stale": stale,
                "moved": moved,
                "entry": e,  # 画面が「見た記録」として更新に添える(比較交換)
            }
        )
    out.sort(key=lambda n: (n["line"], n["at"], n["id"]))
    return out


def change_status(workdir: Path | str, ids: list[str], status: str | None) -> list[str]:
    """指定した指摘の状態を変える(status が None なら消す)。無い ID があれば何も変えず ValueError。"""
    store = notes_store(workdir)
    entries = store.read().entries
    missing = [i for i in ids if i not in entries]
    if missing:
        raise ValueError("指摘が無い: " + " ".join(missing))
    for i in ids:
        cur = entries[i]
        if status is None:
            new = None
        else:
            new = {k: v for k, v in cur.items() if k != "fixed_at"}
            new["status"] = status
            if status == FIXED:
                new["fixed_at"] = now_iso()
        try:
            store.update(i, cur, new)
        except state_store.Conflict as e:
            raise ValueError(f"{i} は別の更新と重なった。もう一度試す") from e
    return ids


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
        "--notes",
        action="store_true",
        help="指摘の一覧を表示する(既定は未対応だけ。ID つき)",
    )
    ap.add_argument("--all", action="store_true", help="--notes で対応済みも表示する")
    ap.add_argument("--fix", nargs="+", metavar="ID", help="指摘を対応済みにする")
    ap.add_argument("--reopen", nargs="+", metavar="ID", help="対応済みを未対応へ戻す")
    ap.add_argument("--remove", nargs="+", metavar="ID", help="指摘を消す")
    a = ap.parse_args(argv)

    w = Path(a.workdir)
    for flag, ids, status in (
        ("--fix", a.fix, FIXED),
        ("--reopen", a.reopen, OPEN),
        ("--remove", a.remove, None),
    ):
        if ids:
            try:
                change_status(w, ids, status)
            except (ValueError, state_store.StoreError) as e:
                print(f"エラー: {e}")
                return 2
            print(f"{flag}: {len(ids)} 件")
            return 0

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
        shown = [n for n in notes if a.all or n["status"] == OPEN]
        for n in shown:
            marks = []
            if n["stale"]:
                marks.append("古い: 台本が変わった")
            if n["status"] == FIXED:
                marks.append("対応済み")
            mark = f"({'・'.join(marks)})" if marks else ""
            when = f"({starts[n['line']]})" if n["line"] in starts else ""
            print(
                f"[{n['id']}] {n['line']}行目{when} {n['text']}{mark}\n   指摘: {n['note']}"
            )
        fixed = sum(1 for n in notes if n["status"] == FIXED)
        tail = f"(対応済み {fixed} 件は --all で表示)" if fixed and not a.all else ""
        print(f"指摘 {len(shown)} 件{tail}")
        return 0

    if ts is None:
        print(f"エラー: {tsp.name} が無い(先に tts_generate.py を実行する)")
        return 2
    out = w / a.out

    def cell(n: dict) -> str:
        mark = ("【古い】" if n["stale"] else "") + (
            "【対応済み】" if n["status"] == FIXED else ""
        )
        return mark + n["note"]

    by_line: dict[int, str] = {}
    for n in notes:
        by_line[n["line"]] = (
            by_line[n["line"]] + " / " + cell(n) if n["line"] in by_line else cell(n)
        )
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

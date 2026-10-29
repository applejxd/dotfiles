#!/usr/bin/env python3
"""公開前チェック: 機械で確かめられる項目と、人が確かめる 4 項目(ADR-0004)。

機械チェック(`machine_checks`):
- assets: 素材台帳に「仮」・出典の欠けが無い(`assets_ledger check --public` と同じ)
- yomi: 読み辞書に状態が「候補」の語が残っていない
- notes: 未対応(open)の指摘が無い
- fresh: video.mp4 が、台本・script.py・辞書・台帳・音声・時刻より新しい(最新の入力から作られた)
- credit: description.txt に VOICEVOX のクレジットがある

`--pre`(`finish.py --final` が動画を作る前に使う)は、動画の完成後にしか成り立たない fresh・credit を除く。
機械で確かめられないこと(`HUMAN`)は、確認画面のチェックリストで人が確かめ、承認の記録に残る。

終了コード: 0 = すべて通過、1 = 通らない項目あり。
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assets_ledger  # noqa: E402
import review_sheet  # noqa: E402
import yomi  # noqa: E402

# 機械では確かめられないので、人が確かめる 4 項目(確認画面のチェックリスト)
HUMAN = [
    (
        "source",
        "出典の表示(画面・説明文・台帳の 3 か所)が、使った素材すべてについて出ている",
    ),
    ("rights", "権利者の条件(公開の可否・クレジット・改変の可否)を確かめた"),
    ("reading", "音声を聞いて、読み(固有名詞・略語)が正しい"),
    ("numbers", "数値・固有名詞を、論文など原典と照合した"),
]
HUMAN_IDS = [i for i, _ in HUMAN]
# fresh: video.mp4 より新しくてはいけない入力
INPUTS = (
    "narration.txt",
    "script.py",
    "yomi.json",
    "assets.json",
    "timestamps.json",
    "voiceover.wav",
)


class Check(NamedTuple):
    id: str
    label: str
    ok: bool
    detail: str


def _check_assets(w: Path) -> Check:
    label = "素材台帳に仮・出典の欠けが無い"
    p = w / "assets.json"
    if not p.is_file():
        return Check("assets", label, True, "台帳なし(他者の素材を使っていない)")
    try:
        rows = assets_ledger.load(p)
    except (ValueError, OSError) as e:
        return Check("assets", label, False, f"読めない: {e}")
    issues, _ = assets_ledger.check(rows, w, public=True)
    if issues:
        return Check("assets", label, False, " / ".join(issues))
    return Check("assets", label, True, f"{len(rows)} 件")


def _check_yomi(w: Path) -> Check:
    label = "読み辞書に候補が残っていない"
    try:
        entries = yomi.resolve(None, w)
    except (ValueError, OSError) as e:
        return Check("yomi", label, False, f"読めない: {e}")
    cands = yomi.candidates_in(entries)
    if cands:
        return Check("yomi", label, False, "候補のまま: " + "、".join(cands))
    return Check("yomi", label, True, f"{len(entries)} 語")


def _check_notes(w: Path) -> Check:
    label = "未対応の指摘が無い"
    try:
        notes = review_sheet.read_notes(w)
    except ValueError as e:
        return Check("notes", label, False, f"読めない: {e}")
    open_n = [n for n in notes if n["status"] == review_sheet.OPEN]
    if open_n:
        return Check("notes", label, False, f"未対応 {len(open_n)} 件(--notes で一覧)")
    return Check("notes", label, True, f"対応済み {len(notes)} 件")


# 生成経路の順序(古い→新しい)。後ろの成果物は、前の入力より新しくなければならない
# (どこか 1 段だけやり直して、古い音声・映像を新しい動画に包み直す事故を止める)。
CHAIN = [
    ("voiceover.wav", ("narration.txt", "yomi.json"), "tts_generate.py で再合成する"),
    ("timestamps.json", ("narration.txt", "yomi.json"), "tts_generate.py で再合成する"),
    ("video_silent.mp4", ("timestamps.json", "script.py"), "build.py か manim で描画し直す"),
    ("video.mp4", INPUTS + ("video_silent.mp4",), "finish.py --final で最終版を作り直す"),
]


def _mtime(w: Path, name: str) -> float | None:
    p = w / name
    return p.stat().st_mtime if p.is_file() else None


def _check_fresh(w: Path) -> Check:
    label = "動画が最新の入力から作られた"
    if not (w / "video.mp4").is_file():
        return Check("fresh", label, False, "video.mp4 が無い(finish.py --final で作る)")
    for out, ins, redo in CHAIN:
        t = _mtime(w, out)
        if t is None:  # 無い成果物は確かめられない(別の経路で作った)
            continue
        newer = [n for n in ins if (m := _mtime(w, n)) is not None and m > t]
        if newer:
            return Check(
                "fresh", label, False,
                f"{out} より新しい入力: {', '.join(newer)}。{redo}",
            )
    return Check("fresh", label, True, "")


def release_rev(workdir: Path | str) -> str:
    """人が確かめる対象(最終動画・説明文・素材台帳)の版。変われば、人の確認はやり直す。"""
    w = Path(workdir)
    parts = []
    for name in ("video.mp4", "description.txt", "assets.json"):
        try:
            st = (w / name).stat()
            parts.append(f"{name}:{st.st_size}:{st.st_mtime_ns}")
        except OSError:
            parts.append(f"{name}:-")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def _check_credit(w: Path) -> Check:
    label = "説明文に VOICEVOX のクレジットがある"
    p = w / "description.txt"
    if not p.is_file():
        return Check(
            "credit",
            label,
            False,
            "description.txt が無い(finish.py --credit … --final)",
        )
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        return Check("credit", label, False, f"読めない: {e}")
    if "VOICEVOX:" not in text:
        return Check("credit", label, False, "VOICEVOX:<キャラクター名> の行が無い")
    return Check("credit", label, True, "")


def machine_checks(workdir: Path | str, pre: bool = False) -> list[Check]:
    w = Path(workdir)
    out = [_check_assets(w), _check_yomi(w), _check_notes(w)]
    if not pre:
        out += [_check_fresh(w), _check_credit(w)]
    return out


def failures(checks: list[Check]) -> list[str]:
    return [f"{c.label}: {c.detail}" for c in checks if not c.ok]


def report(workdir: Path | str, pre: bool = False) -> dict:
    """画面・CLI 用: 機械チェックの結果と、人が確かめる項目。"""
    checks = machine_checks(workdir, pre)
    return {
        "checks": [c._asdict() for c in checks],
        "human": [{"id": i, "label": t} for i, t in HUMAN],
        "ok": not failures(checks),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--workdir", default=".")
    ap.add_argument(
        "--pre", action="store_true", help="動画の完成後にしか成り立たない項目を除く"
    )
    a = ap.parse_args(argv)
    checks = machine_checks(a.workdir, a.pre)
    for c in checks:
        print(
            f"{'OK' if c.ok else 'NG'}  {c.label}"
            + (f"  [{c.detail}]" if c.detail else "")
        )
    if not a.pre:
        print("人が確かめる項目(確認画面の「動画」タブのチェックリスト):")
        for _, t in HUMAN:
            print(f"  - {t}")
    return 1 if failures(checks) else 0


if __name__ == "__main__":
    sys.exit(main())

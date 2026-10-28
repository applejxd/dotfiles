#!/usr/bin/env python3
"""台本(narration.txt)の検査。音声合成の前に実行する。

検査項目:
- 数式・記号の混入(TeX 記号や = ∪ など。読み上げ用に言い換える)
- 読み辞書に無い英字、状態が「候補」のままの語(誤読のもと。yomi.json で確認済みにする)
- 総時間(実測の timestamps.json があればそれ、無ければ文字数からの推定)

終了コード: 0 = 問題なし、1 = 指摘あり、2 = 入力が不正。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import yomi  # noqa: E402

SYMBOLS = re.compile(r"[\\$^_{}=∪∩≤≥∑∫√∈∀∃→←↔⊂⊆≈≠±×÷<>|]")
LONG_LINE = 70
DEFAULT_SEC_PER_CHAR = (
    0.18  # 推定値(SLAM-MER 試験で実測 0.179、VOICEVOX 四国めたん 速度 1.0)
)


def parse_subtitles(path: str | Path) -> list[str]:
    """vendor の tts-generate.py と同じ形式: `subtitles:` の下の `- ` 行。"""
    text = Path(path).read_text(encoding="utf-8")
    stripped = re.sub(r"```[^\n]*\n", "", text).replace("```", "")
    m = re.search(
        r"^subtitles:\s*\n(.*?)(?=\n[^\s\-\n]|\Z)", stripped, re.MULTILINE | re.DOTALL
    )
    if not m:
        raise ValueError(f"`subtitles:` のブロックが無い: {path}")
    items = [
        re.sub(r"^[ \t]*-\s*", "", ln).strip()
        for ln in m.group(1).splitlines()
        if re.match(r"^[ \t]*-", ln)
    ]
    if not items:
        raise ValueError("subtitles の項目が空")
    return items


def estimate_seconds(lines: list[str], sec_per_char: float) -> float:
    return sum(len(re.sub(r"\s", "", ln)) for ln in lines) * sec_per_char


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("narration")
    ap.add_argument(
        "--yomi", nargs="*", default=None, help="読み辞書(JSON)。無指定なら層の合成"
    )
    ap.add_argument(
        "--allow-candidates", action="store_true", help="状態が候補の語を指摘しない"
    )
    ap.add_argument("--target-sec", type=float, help="目標の総時間(秒)")
    ap.add_argument("--timestamps", help="実測の timestamps.json")
    ap.add_argument("--sec-per-char", type=float, default=DEFAULT_SEC_PER_CHAR)
    a = ap.parse_args(argv)

    try:
        lines = parse_subtitles(a.narration)
        entries = yomi.resolve(a.yomi, Path(a.narration).resolve().parent)
    except (ValueError, FileNotFoundError) as e:
        print(f"エラー: {e}")
        return 2

    issues = []
    for i, ln in enumerate(lines, 1):
        sym = sorted(set(SYMBOLS.findall(ln)))
        if sym:
            issues.append(
                f"{i}行目: 読み上げに向かない記号 {' '.join(sym)}(言い換える): {ln}"
            )
        for tok in yomi.missing(ln, entries):
            issues.append(
                f"{i}行目: 「{tok}」が辞書にありません(yomi.py candidates で候補を作る): {ln}"
            )
        if not a.allow_candidates:
            for tok in dict.fromkeys(
                yomi.present_compounds(ln, entries) + yomi.latin_tokens(ln)
            ):
                if entries.get(tok, {}).get("status") == yomi.CANDIDATE:
                    issues.append(
                        f"{i}行目: 「{tok}」の読みが未確認です(`yomi.py set <表記> <読み>` か確認画面の「読み」タブで、状態を「確認済み」に): {ln}"
                    )
        if len(ln) > LONG_LINE:
            print(
                f"注意: {i}行目は {len(ln)} 文字と長い(字幕が 2 行を超える): {ln[:20]}…"
            )

    if a.timestamps:
        total = float(
            json.loads(Path(a.timestamps).read_text(encoding="utf-8"))[
                "total_duration_s"
            ]
        )
        basis = "実測"
    else:
        total = estimate_seconds(lines, a.sec_per_char)
        basis = f"推定 {a.sec_per_char} 秒/文字"
    print(f"{len(lines)} 行、総時間 {total:.1f} 秒({basis})")
    if a.target_sec is not None and total > a.target_sec:
        issues.append(
            f"目標 {a.target_sec:.0f} 秒を超過: {total - a.target_sec:.1f} 秒"
        )

    for s in issues:
        print(f"指摘: {s}")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())

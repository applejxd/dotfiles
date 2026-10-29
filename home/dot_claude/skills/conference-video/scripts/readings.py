#!/usr/bin/env python3
"""台本の各行を VOICEVOX ENGINE がどう読むか(仮名)を表示する。

合成の前に実行し、誤読を見つけて読み辞書(yomi.json)を直す。
表示は 行番号: 原文 / 続けて アクセント句ごとの仮名(句の区切りは `|`、
モーラは `/` で区切らず連結)。終了コード 0 = 表示した、2 = ENGINE に接続できない・入力が不正。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import narration_check  # noqa: E402
import yomi  # noqa: E402
from voicevox_engine import DEFAULT_URL, DOCKER_HINT, Engine, EngineUnavailable  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--narration", default="narration.txt")
    ap.add_argument("--engine-url", default=DEFAULT_URL)
    ap.add_argument("--speaker", type=int, default=2)
    ap.add_argument(
        "--yomi", nargs="*", default=None, help="読み辞書(JSON)。無指定なら層の合成"
    )
    ap.add_argument("--connect-timeout", type=float, default=5.0)
    a = ap.parse_args(argv)
    try:
        lines = narration_check.parse_subtitles(a.narration)
        entries = yomi.confirmed(
            yomi.resolve(a.yomi, Path(a.narration).resolve().parent)
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    eng = Engine(a.engine_url, connect_timeout=a.connect_timeout)
    try:
        eng.version()
        yomi.register(eng, entries)  # 空の辞書でも、辞書に無いツールの登録を取り除く
        for i, text in enumerate(lines, 1):
            q = eng.audio_query(yomi.speech_text(text, entries), a.speaker)
            kana = "|".join(
                "".join(m["text"] for m in ap_["moras"]) for ap_ in q["accent_phrases"]
            )
            print(f"{i}: {text}\n   {kana}")
    except EngineUnavailable as e:
        print(f"エラー: {e}\n起動例: {DOCKER_HINT}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

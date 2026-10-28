#!/usr/bin/env python3
"""台本(narration.txt)を VOICEVOX で音声化する。vendor の tts-generate.py の VOICEVOX 版。

入力は同じ形式(`subtitles:` の下の `- ` 行)。出力も互換:
- voiceover.wav  全行を連結した音声(24kHz モノラル。最終の AAC 化は finish.py)
- timestamps.json  行ごとの start_s / end_s / duration_s(vendor と同じ)に、
  アクセント句ごとの時刻(phrases)、話者、速度を加えたもの

行ごとの音声は .tts-cache/ にキャッシュする。キャッシュの鍵は
テキスト・話者・速度・読み辞書・ENGINE の版。

終了コード: 0 = 成功、2 = ENGINE に接続できない・入力が不正(既存の出力は変えない)。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import narration_check  # noqa: E402
import yomi  # noqa: E402
from wavutil import concat_wavs, wav_info  # noqa: E402
from voicevox_engine import (
    DEFAULT_URL,
    DOCKER_HINT,
    Engine,
    EngineUnavailable,
    phrase_lengths,
)  # noqa: E402

DEFAULT_SPEAKER = 2  # 四国めたん ノーマル(環境の話者一覧で確認する)


def cache_key(
    text: str, speaker: int, speed: float, dict_digest: str, version: str
) -> str:
    blob = json.dumps(
        {"t": text, "s": speaker, "v": speed, "d": dict_digest, "e": version},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def synth_line(
    engine: Engine, text: str, speaker: int, speed: float
) -> tuple[bytes, dict]:
    q = engine.audio_query(text, speaker)
    q["speedScale"] = speed
    wav = engine.synthesis(q, speaker)
    _, _, _, dur = wav_info(wav)
    t = float(q.get("prePhonemeLength", 0.0)) / speed
    phrases = []
    for kana, sec in phrase_lengths(q):
        sec /= speed
        phrases.append(
            {"text": kana, "start_s": round(t, 3), "end_s": round(min(t + sec, dur), 3)}
        )
        t += sec
    return wav, {"duration_s": dur, "phrases": phrases}


def changed_lines(prev: list[dict], now: list[dict], tol: float = 0.02) -> list[int]:
    """前回の timestamps と比べて、文・長さ(tol 秒超)・行数が変わった行(1 始まり)。"""
    out = []
    for i, s in enumerate(now):
        if i >= len(prev):
            out.append(i + 1)
        elif (
            prev[i].get("text") != s["text"]
            or abs(prev[i].get("duration_s", -1) - s["duration_s"]) > tol
        ):
            out.append(i + 1)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--narration", default="narration.txt")
    ap.add_argument(
        "--workdir", default=".", help="出力とキャッシュの場所(既定: 現在のフォルダ)"
    )
    ap.add_argument("--engine-url", default=DEFAULT_URL)
    ap.add_argument(
        "--speaker",
        type=int,
        default=DEFAULT_SPEAKER,
        help="スタイル ID(/speakers で確認)",
    )
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument(
        "--yomi",
        nargs="*",
        default=None,
        help="読み辞書(JSON)。無指定なら 既定 < ユーザー共通 < workdir の yomi.json を合成",
    )
    ap.add_argument("--connect-timeout", type=float, default=5.0)
    a = ap.parse_args(argv)

    work = Path(a.workdir)
    cache = work / ".tts-cache"
    try:
        lines = narration_check.parse_subtitles(a.narration)
        entries_all = yomi.resolve(a.yomi, work)
        if a.yomi is None:
            print("読み辞書(後のものが優先):")
            print("\n".join(yomi.describe_layers(work)))
        entries = yomi.confirmed(entries_all)  # 候補は未確認のため使わない
        pending = yomi.candidates_in(entries_all)
        if pending:
            print(
                f"注意: 候補 {len(pending)} 語は未確認のため辞書に使っていない: {', '.join(pending)}"
            )
    except (ValueError, FileNotFoundError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2

    engine = Engine(a.engine_url, connect_timeout=a.connect_timeout)
    try:
        version = engine.version()
        registered = yomi.register(engine, entries) if entries else 0
        speaker_name = engine.speaker_name(a.speaker)
        if speaker_name is None:
            print(
                f"エラー: 話者 ID {a.speaker} が ENGINE に無い(/speakers で確認)",
                file=sys.stderr,
            )
            return 2

        words = yomi.engine_words(engine)  # 登録後の ENGINE の辞書を行ごとの鍵に使う
        print(
            f"{len(lines)} 行、話者 {speaker_name}({a.speaker})、速度 {a.speed}、"
            f"辞書 {len(entries)} 語(新規 {registered})、ENGINE {version}"
        )
        cache.mkdir(parents=True, exist_ok=True)
        wavs, metas, hits = [], [], 0
        for i, text in enumerate(lines):
            speech = yomi.speech_text(
                text, entries
            )  # ENGINE に渡す文(複合語はハイフンを除く)
            key = cache_key(
                text,
                a.speaker,
                a.speed,
                yomi.line_digest(words, speech),
                str(version),
            )
            wp, mp = cache / f"{key}.wav", cache / f"{key}.json"
            if wp.is_file() and mp.is_file():
                wav, meta = wp.read_bytes(), json.loads(mp.read_text(encoding="utf-8"))
                hits += 1
                tag = "cache"
            else:
                wav, meta = synth_line(engine, speech, a.speaker, a.speed)
                wp.write_bytes(wav)
                mp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
                tag = "合成"
            print(f"  [{i}] {tag} {meta['duration_s']:.2f}s {text[:24]}")
            wavs.append(wav)
            metas.append(meta)
    except EngineUnavailable as e:
        print(
            f"エラー: {e}\nENGINE を起動してから再実行する。例:\n  {DOCKER_HINT}",
            file=sys.stderr,
        )
        return 2
    except RuntimeError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2

    work.mkdir(parents=True, exist_ok=True)
    tmp_wav = work / "voiceover.wav.tmp"
    tmp = work / "timestamps.json.tmp"
    try:
        concat_wavs(wavs, tmp_wav)
    except (RuntimeError, OSError, wave.Error) as e:
        tmp_wav.unlink(missing_ok=True)
        print(
            f"エラー: 音声を連結できない(既存の出力は変えていない): {e}",
            file=sys.stderr,
        )
        return 2
    prev = None
    try:
        prev = json.loads((work / "timestamps.json").read_text(encoding="utf-8"))[
            "subtitles"
        ]
    except (OSError, ValueError, KeyError):
        pass  # 初回、または前の結果が読めない
    t = 0.0
    subs = []
    for i, (text, meta) in enumerate(zip(lines, metas)):
        d = meta["duration_s"]
        subs.append(
            {
                "index": i,
                "text": text,
                "start_s": round(t, 3),
                "end_s": round(t + d, 3),
                "duration_s": round(d, 3),
                "phrases": [
                    {
                        "text": p["text"],
                        "start_s": round(t + p["start_s"], 3),
                        "end_s": round(t + p["end_s"], 3),
                    }
                    for p in meta["phrases"]
                ],
            }
        )
        t += d
    out = {
        "total_duration_s": round(t, 3),
        "speaker": a.speaker,
        "speaker_name": speaker_name,
        "speed": a.speed,
        "engine_version": str(version),
        "subtitles": subs,
    }
    try:
        tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_wav, work / "voiceover.wav")
        os.replace(tmp, work / "timestamps.json")
    except OSError as e:
        tmp_wav.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)
        print(f"エラー: 出力を書けない: {e}", file=sys.stderr)
        return 2
    print(
        f"完了: voiceover.wav + timestamps.json。合計 {t:.1f} 秒(キャッシュ {hits}/{len(lines)})"
    )
    if prev is not None:
        changed = changed_lines(prev, subs)
        if changed:
            print(
                f"時間が変わった行: {', '.join(map(str, changed))}"
                " → これらを含むシーンを再描画する(リンタ → manim → concat → finish --force)"
            )
        else:
            print("時間の変更なし(描画のやり直しは不要。finish --force だけでよい)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

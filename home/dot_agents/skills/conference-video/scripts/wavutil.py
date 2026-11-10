"""wav の読み書きの小さな道具(標準ライブラリのみ)。"""

from __future__ import annotations

import io
import wave
from pathlib import Path


def wav_info(data: bytes) -> tuple[int, int, int, float]:
    """(チャンネル数, バイト幅, サンプリング周波数, 秒)。"""
    with wave.open(io.BytesIO(data)) as w:
        return (
            w.getnchannels(),
            w.getsampwidth(),
            w.getframerate(),
            w.getnframes() / w.getframerate(),
        )


def silence_like(data: bytes, seconds: float) -> bytes:
    """data と同じ形式の無音の wav を返す。"""
    ch, width, rate, _ = wav_info(data)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x00" * (int(seconds * rate) * ch * width))
    return buf.getvalue()


def concat_wavs(parts: list[bytes], out: Path) -> None:
    """wav を連結して out に書く。形式が違えば RuntimeError(置き換えは呼び出し側)。"""
    params = None
    frames = []
    for data in parts:
        with wave.open(io.BytesIO(data)) as w:
            p = (w.getnchannels(), w.getsampwidth(), w.getframerate())
            if params is None:
                params = p
            elif p != params:
                raise RuntimeError(f"wav の形式が行ごとに違う: {params} と {p}")
            frames.append(w.readframes(w.getnframes()))
    with wave.open(str(out), "wb") as w:
        w.setnchannels(params[0])
        w.setsampwidth(params[1])
        w.setframerate(params[2])
        for f in frames:
            w.writeframes(f)

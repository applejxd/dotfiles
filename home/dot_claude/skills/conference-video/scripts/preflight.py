#!/usr/bin/env python3
"""作り始める前の環境確認。足りないものを一覧にして、直し方を示す。

確認: ffmpeg/ffprobe(ass フィルタ)、manim、LaTeX、日本語フォント、
VOICEVOX ENGINE、manim_videomobject。終了コード 0 = すべて OK、1 = 不足あり。
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from voicevox_engine import DEFAULT_URL, DOCKER_HINT, Engine, EngineUnavailable  # noqa: E402


def check_ffmpeg() -> tuple[bool, str]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        return False, "ffmpeg/ffprobe が無い(apt install ffmpeg)"
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True
    )
    missing = [
        f for f in ("ass", "sidechaincompress", "loudnorm") if f" {f} " not in r.stdout
    ]
    if missing:
        return (
            False,
            f"ffmpeg にフィルタが無い: {', '.join(missing)}(libass 付きの版が要る)",
        )
    return True, "ffmpeg(ass / sidechaincompress / loudnorm)"


def check_font(name: str) -> tuple[bool, str]:
    if not shutil.which("fc-list"):
        return False, "fc-list が無く、フォントを確認できない"
    r = subprocess.run(["fc-list", f":family={name}"], capture_output=True, text=True)
    if not r.stdout.strip():
        return False, f"フォント {name} が無い(apt install fonts-noto-cjk)"
    return True, f"フォント {name}"


def check_engine(url: str) -> tuple[bool, str]:
    try:
        v = Engine(url, connect_timeout=2).version()
        return True, f"VOICEVOX ENGINE {v}({url})"
    except EngineUnavailable:
        return False, f"VOICEVOX ENGINE に接続できない({url})。起動: {DOCKER_HINT}"


def check_module(mod: str, hint: str) -> tuple[bool, str]:
    if importlib.util.find_spec(mod) is None:
        return False, f"Python モジュール {mod} が無い({hint})"
    return True, f"Python モジュール {mod}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engine-url", default=DEFAULT_URL)
    ap.add_argument("--font", default="Noto Sans CJK JP")
    a = ap.parse_args(argv)

    results = [
        check_ffmpeg(),
        (
            bool(shutil.which("manim"))
            or importlib.util.find_spec("manim") is not None,
            "manim"
            if importlib.util.find_spec("manim")
            else "manim が無い(uv sync。SKILL.md の環境)",
        ),
        (
            bool(shutil.which("latex")),
            "LaTeX"
            if shutil.which("latex")
            else "latex が無い(TeX Live。MathTex に必要)",
        ),
        check_font(a.font),
        check_engine(a.engine_url),
        check_module("manim_videomobject", "uv sync。実動画の貼り込みに必要"),
    ]
    bad = 0
    for ok, msg in results:
        print(("OK  " if ok else "NG  ") + msg)
        bad += 0 if ok else 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

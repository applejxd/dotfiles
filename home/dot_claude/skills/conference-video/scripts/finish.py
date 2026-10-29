#!/usr/bin/env python3
"""シーン動画 + 音声 + 字幕を 1 本の video.mp4 に仕上げる。

- 字幕: timestamps.json から ASS を作って焼き込む(日本語フォントは既定 Noto Sans CJK JP)
- 音声: voiceover.wav(+ 任意の BGM を声でダッキング)を loudnorm 2 パスで -16 LUFS に揃える
- クレジット: --credit を動画の末尾と description.txt に入れる

入力(--workdir 内): video_silent.mp4, voiceover.wav, timestamps.json
出力: video.mp4, subtitles.ass, description.txt(--credit / --title があるとき)
終了コード: 0 = 成功、2 = 入力が無い・出力が既にある・ffmpeg の失敗。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CREDIT_PREFIX = "VOICEVOX:"


def credit_text(character: str) -> str:
    return f"{CREDIT_PREFIX}{character}"


def description_text(
    title: str | None, credit: str | None, extra: list[str] | None = None
) -> str:
    parts = [title or "", "", "音声合成: " + credit if credit else ""]
    parts += extra or []
    return "\n".join(p for p in parts).strip() + "\n"


def _t(sec: float) -> str:
    cs = int(round(sec * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def ass_escape(text: str) -> str:
    """ASS の制御用文字を無害化する(改行・波括弧・バックスラッシュ)。"""
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return text.replace("\\", "＼").replace("{", "(").replace("}", ")")


def wrap(text: str, max_chars: int) -> str:
    """読点・句点・空白の後で折り返す。無ければ max_chars+8 字で強制的に折る。"""
    text = ass_escape(text)
    lines, cur = [], ""
    for ch in text:
        cur += ch
        n = len(cur)
        if (n >= max_chars and ch in "、。 　") or n >= max_chars + 8:
            lines.append(cur.strip())
            cur = ""
    if cur.strip():
        lines.append(cur.strip())
    return r"\N".join(lines)


def build_ass(
    ts: dict,
    width: int,
    height: int,
    font: str,
    max_chars: int = 28,
    credit: str | None = None,
    video_sec: float | None = None,
    credit_sec: float = 4.0,
    draft: bool = False,
) -> str:
    size = round(height * 0.052)
    margin_v = round(height * 0.05)
    outline = max(
        2, round(height * 0.0035)
    )  # 縁取りは解像度に比例させる(480p: 2、1080p: 4)
    csize = round(height * 0.032)
    out = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,{outline},0,2,"
        f"{round(width * 0.05)},{round(width * 0.05)},{margin_v},1",
        f"Style: Credit,{font},{csize},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,9,"
        f"{round(width * 0.03)},{round(width * 0.03)},{round(height * 0.04)},1",
        f"Style: Draft,{font},{csize},&H003C3CFF,&H000000FF,&H00FFFFFF,&H80000000,1,0,0,0,100,100,0,0,1,2,0,7,"
        f"{round(width * 0.02)},{round(width * 0.02)},{round(height * 0.03)},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for s in ts["subtitles"]:
        out.append(
            f"Dialogue: 0,{_t(s['start_s'])},{_t(s['end_s'])},Default,,0,0,0,,{wrap(s['text'], max_chars)}"
        )
    if credit and video_sec:
        out.append(
            f"Dialogue: 1,{_t(max(0.0, video_sec - credit_sec))},{_t(video_sec)},Credit,,0,0,0,,{ass_escape(credit)}"
        )
    if draft and video_sec:  # 下書きの取り違えを防ぐ(公開しない)。動画全体に出す
        out.append(
            f"Dialogue: 2,{_t(0.0)},{_t(video_sec)},Draft,,0,0,0,,DRAFT 下書き(公開不可)"
        )
    return "\n".join(out) + "\n"


def probe(path: Path) -> tuple[int, int, float]:
    r = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    j = json.loads(r.stdout)
    return (
        j["streams"][0]["width"],
        j["streams"][0]["height"],
        float(j["format"]["duration"]),
    )


def audio_graph(has_bgm: bool, bgm_gain: float) -> str:
    """loudnorm の手前までの音声グラフ。出力ラベルは [pre]。"""
    if not has_bgm:
        return "[1:a]anull[pre]"
    return (
        f"[1:a]asplit=2[v1][v2];[2:a]volume={bgm_gain}[b];"
        "[b][v1]sidechaincompress=threshold=0.03:ratio=6:attack=40:release=600[duck];"
        "[duck][v2]amix=inputs=2:normalize=0:duration=longest[pre]"
    )


def measure_loudness(
    inputs: list[str], graph: str, lufs: float, seconds: float
) -> dict:
    """完成品と同じ長さ(seconds)で測る。BGM の無限ループでも止まらない。"""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        *inputs,
        "-filter_complex",
        f"{graph};[pre]loudnorm=I={lufs}:TP=-1.5:LRA=11:print_format=json[o]",
        "-map",
        "[o]",
        "-t",
        f"{seconds:.3f}",
        "-f",
        "null",
        "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.DOTALL)
    if r.returncode != 0 or not m:
        raise RuntimeError("音量の測定に失敗: " + r.stderr[-400:])
    return json.loads(m.group(0))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--workdir", default=".")
    ap.add_argument("--video", help="既定: video_silent.mp4(--draft は draft_silent.mp4)")
    ap.add_argument("--voice", default="voiceover.wav")
    ap.add_argument("--timestamps", default="timestamps.json")
    ap.add_argument("--out", help="既定: video.mp4(--draft は draft.mp4)")
    ap.add_argument("--bgm", help="BGM(任意)。声でダッキングする")
    ap.add_argument("--bgm-gain", type=float, default=0.3)
    ap.add_argument("--font", default="Noto Sans CJK JP")
    ap.add_argument("--lufs", type=float, default=-16.0)
    ap.add_argument("--credit", help="例: VOICEVOX:四国めたん")
    ap.add_argument("--title")
    ap.add_argument(
        "--assets", help="素材台帳(assets.json)。出典の行を description.txt に入れる"
    )
    ap.add_argument("--no-subs", action="store_true", help="字幕を焼き込まない")
    ap.add_argument("--force", action="store_true", help="既存の出力を上書きする")
    ap.add_argument(
        "--draft",
        action="store_true",
        help="下書き: draft_silent.mp4 から draft.mp4 を作る(DRAFT を焼く。軽い画質・音量調整なし。"
        "video.mp4 には触れず、上書きに --force は要らない)",
    )
    ap.add_argument(
        "--final",
        action="store_true",
        help="公開用: 公開前の機械チェック(台帳の仮・欠け、読み辞書の候補、未対応の指摘)が通らなければ"
        "動画を作らない(release_check.py --pre。終了コード 2)",
    )
    a = ap.parse_args(argv)
    if a.final and a.draft:
        print("エラー: --final と --draft は併用できない")
        return 2
    a.video = a.video or ("draft_silent.mp4" if a.draft else "video_silent.mp4")
    a.out = a.out or ("draft.mp4" if a.draft else "video.mp4")
    if a.draft:
        if Path(a.out).name == "video.mp4":
            print("エラー: 下書きは video.mp4 に書けない(--out を変える)")
            return 2
        a.force = True
        a.title = a.assets = a.credit = None  # 下書きは説明文を作らない

    w = Path(a.workdir)
    if a.final:
        import release_check

        fails = release_check.failures(release_check.machine_checks(w, pre=True))
        if fails:
            print("エラー: 公開前チェックが通らない(最終動画を作らない):")
            for f in fails:
                print(f"  - {f}")
            return 2
    video, voice, tsp, out = w / a.video, w / a.voice, w / a.timestamps, w / a.out
    need = [video, voice, tsp] + ([Path(a.bgm)] if a.bgm else [])
    missing = [p.name for p in need if not p.is_file()]
    if missing:
        print(f"エラー: 入力が無い: {', '.join(missing)}")
        return 2
    if shutil.which("ffmpeg") is None:
        print("エラー: ffmpeg が見つからない")
        return 2
    burn = bool(a.credit) or not a.no_subs or a.draft  # クレジットだけでも ASS を焼く
    ass = w / ("subtitles.draft.ass" if a.draft else "subtitles.ass")
    desc = w / "description.txt"
    asset_lines: list[str] = []
    if a.assets:
        import assets_ledger

        ap_ = Path(a.assets)
        try:
            asset_lines = assets_ledger.credit_lines(
                assets_ledger.load(ap_ if ap_.is_absolute() else w / ap_)
            )
        except (ValueError, FileNotFoundError) as e:
            print(f"エラー: {e}")
            return 2
    want_desc = bool(a.credit or a.title or a.assets)
    outputs = [out] + ([ass] if burn else []) + ([desc] if want_desc else [])
    exists = [p.name for p in outputs if p.exists()]
    if exists and not a.force:
        print(f"エラー: 既にある: {', '.join(exists)}。上書きするなら --force")
        return 2

    try:
        ts = json.loads(tsp.read_text(encoding="utf-8"))
        width, height, vsec = probe(video)
    except (
        subprocess.CalledProcessError,
        KeyError,
        IndexError,
        ValueError,
        OSError,
    ) as e:
        print(f"エラー: 入力を読めない({video.name} / {tsp.name}): {e}")
        return 2
    ass_existed = ass.exists()
    if burn:
        events = {"subtitles": [] if a.no_subs else ts["subtitles"]}
        ass.write_text(
            build_ass(
                events,
                width,
                height,
                a.font,
                credit=a.credit,
                video_sec=vsec,
                draft=a.draft,
            ),
            encoding="utf-8",
        )

    inputs = ["-i", str(video), "-i", str(voice)]
    if a.bgm:
        inputs += ["-stream_loop", "-1", "-i", a.bgm]
    graph = audio_graph(bool(a.bgm), a.bgm_gain)

    def fail(msg: str) -> int:
        print(msg)
        if burn and not ass_existed:
            ass.unlink(missing_ok=True)  # 今回作った中間ファイルだけ消す
        return 2

    try:
        if a.draft:  # 下書きは音量調整(2 パス)を省く
            m, ln = {"input_i": "未調整"}, "anull"
        else:
            m = measure_loudness(inputs, graph, a.lufs, vsec)
            ln = None
        ln = ln or (
            f"loudnorm=I={a.lufs}:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
            f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
            f"offset={m['target_offset']}:linear=true"
        )
    except (RuntimeError, KeyError) as e:
        return fail(f"エラー: {e}")

    vf = f"ass={ass.name}" if burn else "null"
    tmp = w / f"{out.stem}.tmp{out.suffix}"  # 完成してから out に置き換える
    tmp.unlink(missing_ok=True)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *inputs,
        "-filter_complex",
        f"{graph};[pre]{ln},apad[a];[0:v]{vf}[v]",
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-t",
        f"{vsec:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast" if a.draft else "medium",
        "-crf",
        "28" if a.draft else "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        tmp.name,
    ]
    r = subprocess.run(cmd, cwd=w, capture_output=True, text=True)
    if r.returncode != 0:
        tmp.unlink(missing_ok=True)
        return fail("エラー: ffmpeg が失敗した:\n" + r.stderr[-800:])
    os.replace(tmp, out)

    if want_desc:
        desc.write_text(
            description_text(a.title, a.credit, asset_lines), encoding="utf-8"
        )
    if a.draft:
        print(f"完了(下書き): {out}({vsec:.1f} 秒、{width}x{height}。DRAFT 表示つき・音量未調整)")
        return 0
    print(
        f"完了: {out}({vsec:.1f} 秒、{width}x{height}、測定 {m['input_i']} LUFS → {a.lufs} LUFS)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

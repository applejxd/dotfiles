#!/usr/bin/env python3
"""下書きビルド: 変更のあったシーンだけを再描画し、下書き動画(draft.mp4)を作る。

「構想を決めたら、まず動画を作り、見ながら台本・読みを直す」(ADR-0004)ための、軽い再生成。
流れ: 事前確認 → 音声合成(行キャッシュ)→ リンタ → シーンごとに「変わったか」を判定して描画
→ 結合 → `finish.py --draft`。各段の所要時間を表示する。最終版(1080p)は従来の手順で作る。

シーンが変わったかは、シーンごとの指紋で判定する(曖昧なら再描画する安全側):
- script.py の、そのシーンのクラス(と親シーン)・共通部分(シーン以外のコード)のソース
- そのシーンが参照する素材ファイル(文字列リテラルの `.mp4` `.png` など)の大きさと更新時刻、台帳の項目
- 前回描画したときに使った台本の行(本文と時間)。Manim が出す字幕(srt)から求める
結果は build.json(状態の窓口 state_store 経由)に残す。

終了コード: 0 = 成功、1 = 描画・リンタの失敗(結合しない)、2 = 入力・環境の不備(何も描画しない)。
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import state_store  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
LINT = SKILL_DIR / "vendor" / "manim-skill" / "tools" / "lint-subtitles.py"
DEFAULT_MANIM = f"uv run --project {SKILL_DIR} manim"
MEDIA_EXT = (
    ".mp4",
    ".mov",
    ".webm",
    ".mkv",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
)
RES_DIR = "480p15"  # 下書きは -ql(480p15)
TIME_EPS = 0.005  # 行の時間の比較(秒)


# ───────────── script.py の読み取り(構文だけ。実行しない) ─────────────


def parse_script_text(src: str) -> ast.Module:
    return ast.parse(src)


def _base_name(b: ast.expr) -> str:
    if isinstance(b, ast.Name):
        return b.id
    if isinstance(b, ast.Attribute):
        return b.attr
    return ""


def scene_classes(tree: ast.Module) -> dict[str, ast.ClassDef]:
    """Scene を継承するクラス(親が同じファイルのシーンでもよい)を、ファイルの順に返す。"""
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    names: set[str] = set()
    changed = True
    while changed:
        changed = False
        for c in classes:
            if c.name in names:
                continue
            if any(
                _base_name(b).endswith("Scene") or _base_name(b) in names
                for b in c.bases
            ):
                names.add(c.name)
                changed = True
    return {c.name: c for c in classes if c.name in names}


def _seg(src: str, node: ast.AST) -> str:
    return ast.get_source_segment(src, node) or ""


def _own_nodes(name: str, classes: dict[str, ast.ClassDef]) -> list[ast.ClassDef]:
    """そのシーンのクラスと、同じファイルにある親シーン(再帰)。"""
    out, todo, seen = [], [name], set()
    while todo:
        n = todo.pop()
        if n in seen or n not in classes:
            continue
        seen.add(n)
        out.append(classes[n])
        todo.extend(_base_name(b) for b in classes[n].bases)
    return out


def _common_nodes(tree: ast.Module, classes: dict[str, ast.ClassDef]) -> list[ast.stmt]:
    """シーン以外のトップレベル(import・定数・関数・Clock など)。モジュールの docstring は除く。"""
    out = []
    for i, n in enumerate(tree.body):
        if isinstance(n, ast.ClassDef) and n.name in classes:
            continue
        if (
            i == 0
            and isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
        ):
            continue
        out.append(n)
    return out


def fingerprints(tree: ast.Module, src: str, token: str) -> dict[str, str]:
    """シーンごとの指紋(ソースの内容。素材・台本の行は含めない)。token は画質などの条件。"""
    classes = scene_classes(tree)
    common = "\n".join(_seg(src, n) for n in _common_nodes(tree, classes))
    out = {}
    for name in classes:
        own = "\n".join(_seg(src, n) for n in _own_nodes(name, classes))
        blob = "\x00".join([token, common, own])
        out[name] = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return out


def _literals(nodes) -> set[str]:
    refs = set()
    for n in nodes:
        for x in ast.walk(n):
            if (
                isinstance(x, ast.Constant)
                and isinstance(x.value, str)
                and x.value.lower().endswith(MEDIA_EXT)
                and "\n" not in x.value
            ):
                refs.add(x.value)
            # DEPENDS = ["data.csv", "dir"](モジュール先頭 = 全シーン、クラス属性 = そのシーン)
            if (
                isinstance(x, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "DEPENDS" for t in x.targets)
                and isinstance(x.value, (ast.List, ast.Tuple))
            ):
                for c in x.value.elts:
                    if isinstance(c, ast.Constant) and isinstance(c.value, str):
                        refs.add(c.value)
    return refs


def media_refs(tree: ast.Module, src: str) -> dict[str, list[str]]:
    """シーンごとの、参照する素材ファイル(文字列リテラル)。共通部分の参照は全シーンに含める。"""
    classes = scene_classes(tree)
    common = _literals(_common_nodes(tree, classes))
    return {
        name: sorted(common | _literals(_own_nodes(name, classes))) for name in classes
    }


def read_srt_texts(srt: str) -> list[str]:
    """Manim が出す字幕(srt)の本文を、出た順に返す。"""
    out = []
    for block in re.split(r"\n\s*\n", srt.strip()):
        lines = block.strip().splitlines()
        if len(lines) >= 3 and "-->" in lines[1]:
            out.append("".join(lines[2:]))
    return out


def match_candidates(texts: list[str], ts_lines: list[dict]) -> list[list[int]]:
    """字幕の本文ごとに、同じ本文の台本の行(すべて)を返す。無ければ空。

    同じ本文の行が複数あるときは、どれを使ったかを推定せず、候補のすべてを依存とみなす(安全側)。
    """
    return [[i for i, s in enumerate(ts_lines) if s["text"] == t] for t in texts]


# ───────────── 記録(build.json) ─────────────


def validate_scene(key: str, e) -> None:
    if not isinstance(key, str) or not key:
        raise ValueError("キーはシーン名")
    if not isinstance(e, dict):
        raise ValueError("項目は辞書")
    for k in ("fingerprint", "mp4", "rendered_at"):
        if not isinstance(e.get(k), str):
            raise ValueError(f"{k} は文字列")
    lines = e.get("lines")
    if not isinstance(lines, list) or not all(
        isinstance(x, dict) and isinstance(x.get("text"), str) for x in lines
    ):
        raise ValueError("lines は {idx, text, dur} の配列")


def manifest_store(workdir: Path) -> state_store.Store:
    return state_store.Store(workdir / "build.json", validate=validate_scene)


# ───────────── 判定 ─────────────


def stamp(path: Path) -> str:
    st = path.stat()
    return f"{st.st_size}:{st.st_mtime_ns}"


def ref_stamp(path: Path) -> str:
    """参照先の版。ファイルは大きさと更新時刻、ディレクトリは中のすべてのファイル。無ければ "-"。"""
    if path.is_file():
        return stamp(path)
    if path.is_dir():
        parts = [
            f"{f.relative_to(path).as_posix()}={stamp(f)}"
            for f in sorted(path.rglob("*"))
            if f.is_file()
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
    return "-"


AUX_SKIP = {"media", ".build-logs", "__pycache__", "node_modules"}


def aux_py_hash(workdir: Path, script: Path) -> str:
    """作業フォルダの補助 .py(script.py 自身を除く)の内容。script.py が import するモジュールの変更を拾う。"""
    parts = []
    for f in sorted(workdir.rglob("*.py")):
        rel = f.relative_to(workdir)
        if f == script or any(x in AUX_SKIP or x.startswith(".") for x in rel.parts[:-1]):
            continue
        try:
            parts.append(f"{rel.as_posix()}={hashlib.sha256(f.read_bytes()).hexdigest()[:16]}")
        except OSError:
            parts.append(f"{rel.as_posix()}=?")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def ledger_hash(workdir: Path, ref: str) -> str:
    p = workdir / "assets.json"
    try:
        entries = json.loads(p.read_text(encoding="utf-8")).get("entries", {})
    except (OSError, ValueError):
        return ""
    return hashlib.sha256(
        json.dumps(entries.get(ref), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:12]


def full_fingerprint(workdir: Path, base: str, refs: list[str]) -> str:
    parts = [base]
    for r in refs:
        f = workdir / r
        parts.append(f"{r}={ref_stamp(f)}={ledger_hash(workdir, r)}")
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()


def stale_reason(rec: dict | None, fp: str, mp4: Path, ts_lines: list[dict]) -> str | None:
    """再描画が要る理由(要らなければ None)。"""
    if rec is None:
        return "初回"
    if not mp4.is_file():
        return "シーンの動画が無い"
    if rec["fingerprint"] != fp:
        return "script.py か参照する素材が変わった"
    if not rec["lines"]:
        return "字幕(srt)が無く、使う台本の行を判定できないので描画する"
    for l in rec["lines"]:
        cands = l.get("cands")
        if not cands:
            return "字幕の本文が台本の行と一致しない(影響を判定できないので描画する)"
        for idx, dur in cands:  # 同じ本文の行が複数あれば、そのすべてを見る
            if idx >= len(ts_lines):
                return f"台本から {idx + 1} 行目が無くなった"
            cur = ts_lines[idx]
            if cur["text"] != l["text"]:
                return f"台本の {idx + 1} 行目の本文が変わった"
            if abs(float(cur["duration_s"]) - float(dur)) > TIME_EPS:
                return (
                    f"{idx + 1} 行目の時間が変わった"
                    f"({float(dur):.2f} → {float(cur['duration_s']):.2f} 秒)"
                )
    return None


# ───────────── 実行 ─────────────


class Stage:
    """段の所要時間を表示する。"""

    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        self.t0 = time.monotonic()
        return self

    def __exit__(self, *exc):
        print(f"[{self.name}] {time.monotonic() - self.t0:.1f} 秒")
        return False


def _split(cmd: str) -> list[str]:
    return shlex.split(cmd, posix=(os.name != "nt"))


def python_cmd_for(manim_cmd: str, override: str | None = None) -> list[str]:
    """リンタを動かす python のコマンド。manim と同じ環境(venv)の python にする。

    script.py は manim_videomobject など venv にしか無いモジュールを import する。
    manim のコマンドの最後が `manim` なら、そこを `python` に置き換える。判定できないときは
    このプロセスの python。
    """
    if override:
        return _split(override)
    toks = _split(manim_cmd)
    if toks and Path(toks[-1]).name in ("manim", "manim.exe"):
        last = Path(toks[-1])
        py = "python" if last.parent == Path(".") else str(last.with_name("python"))
        return [*toks[:-1], py]
    return [sys.executable]


def run_tts(a, w: Path) -> int:
    import tts_generate

    argv = ["--workdir", str(w), "--narration", str(w / "narration.txt")]
    argv += ["--connect-timeout", str(a.connect_timeout)]
    if a.speaker is not None:
        argv += ["--speaker", str(a.speaker)]
    if a.speed is not None:
        argv += ["--speed", str(a.speed)]
    if a.engine_url:
        argv += ["--engine-url", a.engine_url]
    if a.yomi is not None:
        argv += ["--yomi", *a.yomi]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = tts_generate.main(argv)
    for ln in buf.getvalue().splitlines():
        if code != 0 or not re.match(r"^\s+\[\d+\]", ln):
            print(ln)
    return code


def render_scene(a, w: Path, script: Path, scene: str) -> tuple[bool, str]:
    log_dir = w / ".build-logs"
    log_dir.mkdir(exist_ok=True)
    cmd = [*_split(a.manim), "-ql", script.name, scene]
    env = {k: v for k, v in os.environ.items() if k != "CONF_VIDEO_QUALITY"}
    r = subprocess.run(cmd, cwd=w, capture_output=True, text=True, env=env)
    (log_dir / f"{scene}.log").write_text(
        (r.stdout or "") + (r.stderr or ""), encoding="utf-8"
    )
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-12:]
        return False, "\n".join(tail)
    return True, ""


def scene_mp4(w: Path, script: Path, scene: str) -> Path:
    return w / "media" / "videos" / script.stem / RES_DIR / f"{scene}.mp4"


def record_lines(w: Path, script: Path, scene: str, ts_lines: list[dict]) -> list[dict]:
    """そのシーンが使った台本の行(字幕 srt から)。同じ本文の行が複数あれば候補をすべて記録する。"""
    srt = scene_mp4(w, script, scene).with_suffix(".srt")
    try:
        texts = read_srt_texts(srt.read_text(encoding="utf-8"))
    except OSError:
        return []  # 字幕が無ければ空。次回は必ず描画し直す(判定できない)
    out = []
    for t, cands in zip(texts, match_candidates(texts, ts_lines)):
        out.append(
            {
                "idx": cands[0] if cands else None,
                "text": t,
                "dur": float(ts_lines[cands[0]]["duration_s"]) if cands else 0.0,
                "cands": [[i, float(ts_lines[i]["duration_s"])] for i in cands],
            }
        )
    return out


def write_concat(w: Path, script: Path, scenes: list[str]) -> bool:
    """concat.draft.txt を書く。内容が変わったら True。"""
    lines = []
    for s in scenes:
        rel = scene_mp4(w, script, s).relative_to(w).as_posix().replace("'", "'\\''")
        lines.append(f"file '{rel}'")
    text = "\n".join(lines) + "\n"
    p = w / "concat.draft.txt"
    old = p.read_text(encoding="utf-8") if p.is_file() else None
    p.write_text(text, encoding="utf-8")
    return old != text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--workdir", default=".")
    ap.add_argument("--script", default="script.py")
    ap.add_argument(
        "--manim",
        default=os.environ.get("CONF_VIDEO_MANIM", DEFAULT_MANIM),
        help="manim の実行コマンド(既定: uv run --project <スキル> manim。環境変数 CONF_VIDEO_MANIM)",
    )
    ap.add_argument("--full", action="store_true", help="全シーンを描画し直す")
    ap.add_argument(
        "--rerender", nargs="+", metavar="SCENE", help="指定したシーンを描画し直す"
    )
    ap.add_argument(
        "--no-tts", action="store_true", help="音声合成を飛ばす(timestamps.json を使う)"
    )
    ap.add_argument("--no-lint", action="store_true", help="字幕リンタを飛ばす")
    ap.add_argument(
        "--python",
        help="リンタを動かす python(既定: manim と同じ環境の python)",
    )
    ap.add_argument("--speaker", type=int)
    ap.add_argument("--speed", type=float)
    ap.add_argument("--engine-url")
    ap.add_argument("--yomi", nargs="*", default=None)
    ap.add_argument("--connect-timeout", type=float, default=5.0)
    a = ap.parse_args(argv)

    t_start = time.monotonic()
    w = Path(a.workdir).resolve()
    script = w / a.script

    # ── 事前確認(重い処理の前に、足りないものを全部出す)──
    problems: list[str] = []
    if not script.is_file():
        problems.append(f"{a.script} が無い")
    if not (w / "narration.txt").is_file():
        problems.append("narration.txt が無い")
    if a.no_tts and not (w / "timestamps.json").is_file():
        problems.append("timestamps.json が無い(--no-tts を外すと音声合成で作る)")
    if shutil.which("ffmpeg") is None:
        problems.append("ffmpeg が見つからない")
    manim_cmd = _split(a.manim)
    if not manim_cmd or shutil.which(manim_cmd[0]) is None:
        problems.append(
            f"manim の実行コマンドが見つからない: {a.manim}"
            "(--manim か環境変数 CONF_VIDEO_MANIM で指定。プロジェクトの venv の manim が要る)"
        )
    tree = src = None
    if script.is_file():
        try:
            src = script.read_text(encoding="utf-8")
            tree = parse_script_text(src)
        except (SyntaxError, ValueError, OSError) as e:
            problems.append(f"{a.script} を読めない: {e}")
    scenes: dict[str, ast.ClassDef] = scene_classes(tree) if tree else {}
    if tree and not scenes:
        problems.append(f"{a.script} に、Scene を継承するクラスが無い")
    refs = media_refs(tree, src) if tree and scenes else {}
    missing = sorted({r for rs in refs.values() for r in rs if not (w / r).exists()})
    for r in missing:
        problems.append(
            f"素材・データが無い: {r}(script.py が参照または DEPENDS で宣言している。複製したときは素材も要る)"
        )
    unknown = [s for s in (a.rerender or []) if s not in scenes]
    for s in unknown:
        problems.append(f"--rerender のシーンが無い: {s}")
    store = manifest_store(w)
    try:
        records = store.read().entries
    except state_store.Corrupt as e:
        problems.append(
            f"build.json が壊れている({e})。消すと全シーンを描画し直す(消すのは利用者が決める)"
        )
        records = {}
    if problems:
        for p in problems:
            print(f"エラー: {p}")
        return 2

    # ── 音声合成 ──
    if not a.no_tts:
        with Stage("tts"):
            code = run_tts(a, w)
        if code != 0:
            return 2
    try:
        ts_lines = json.loads((w / "timestamps.json").read_text(encoding="utf-8"))[
            "subtitles"
        ]
    except (OSError, ValueError, KeyError) as e:
        print(f"エラー: timestamps.json を読めない: {e}")
        return 2

    # ── リンタ ──
    if not a.no_lint:
        with Stage("lint"):
            r = subprocess.run(
                [*python_cmd_for(a.manim, a.python), str(LINT), script.name],
                cwd=w,
                capture_output=True,
                text=True,
            )
        if r.returncode != 0:
            print("エラー: 字幕リンタが通らない(時間の不整合・模擬が不完全)")
            print("\n".join((r.stdout + r.stderr).strip().splitlines()[-15:]))
            return 1

    # ── 判定 ──
    base = fingerprints(tree, src, token=f"ql|{a.manim}|{aux_py_hash(w, script)}")
    plan: dict[str, str | None] = {}
    fps: dict[str, str] = {}
    for name in scenes:
        fps[name] = full_fingerprint(w, base[name], refs[name])
        if a.full:
            plan[name] = "--full"
        elif a.rerender and name in a.rerender:
            plan[name] = "--rerender で指定"
        else:
            plan[name] = stale_reason(
                records.get(name), fps[name], scene_mp4(w, script, name), ts_lines
            )
    todo = [n for n, why in plan.items() if why]
    for name in scenes:
        print(
            f"  {name}: "
            + (f"描画({plan[name]})" if plan[name] else "再利用(変更なし)")
        )

    # ── 描画 ──
    failed: list[str] = []
    rendered = 0
    for name in todo:
        with Stage(f"render {name}"):
            ok, tail = render_scene(a, w, script, name)
        if ok and not scene_mp4(w, script, name).is_file():
            ok, tail = False, "manim は成功したが、シーンの動画ができていない"
        if not ok:
            failed.append(name)
            print(f"エラー: {name} の描画に失敗\n{tail}")
            continue
        rendered += 1
        new = {
            "fingerprint": fps[name],
            "lines": record_lines(w, script, name, ts_lines),
            "mp4": scene_mp4(w, script, name).relative_to(w).as_posix(),
            "rendered_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        try:
            store.update(name, records.get(name), new)
            records[name] = new
        except state_store.StoreError as e:
            print(f"注意: build.json に書けなかった({e})。次回は描画し直す")
    if failed:
        print(f"失敗したシーン: {', '.join(failed)}(結合・仕上げに進まない)")
        return 1

    # ── 結合 ──
    draft_silent, draft = w / "draft_silent.mp4", w / "draft.mp4"
    changed = write_concat(w, script, list(scenes))
    if rendered or changed or not draft_silent.is_file():
        with Stage("concat"):
            tmp = w / "draft_silent.tmp.mp4"
            draft_silent.unlink(missing_ok=True)  # 失敗したとき、古い映像を次回に再利用しない
            r = subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    "concat.draft.txt",
                    "-c",
                    "copy",
                    tmp.name,
                ],
                cwd=w,
                capture_output=True,
                text=True,
            )
            if r.returncode != 0:
                tmp.unlink(missing_ok=True)
                print("エラー: 結合に失敗\n" + r.stderr[-600:])
                return 1
            os.replace(tmp, draft_silent)
        need_finish = True
    else:
        need_finish = False

    # ── 仕上げ(下書き)──
    newest = max(
        (
            p.stat().st_mtime_ns
            for p in (draft_silent, w / "voiceover.wav", w / "timestamps.json")
            if p.is_file()
        ),
        default=0,
    )
    if need_finish or not draft.is_file() or draft.stat().st_mtime_ns < newest:
        import finish

        with Stage("finish"):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = finish.main(["--workdir", str(w), "--draft"])
        if code != 0:
            print("エラー: 下書きの仕上げに失敗\n" + buf.getvalue()[-600:])
            return 1
        print(buf.getvalue().strip())
    else:
        print("[finish] 変更なし(draft.mp4 を再利用)")
    reused = len(scenes) - rendered
    print(
        f"完了: {draft}(描画 {rendered} シーン、再利用 {reused} シーン)。"
        f"合計 {time.monotonic() - t_start:.1f} 秒"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

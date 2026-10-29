"""読み辞書: JSON 窓口(state_store)の読み書き・検証・層の合成・VOICEVOX への登録。

辞書は `yomi.json`(`{"schema": 1, "entries": {表記: {pron, accent, status, note}}}`)。
人が手で編集せず、このモジュールの CLI(`list` / `set` / `rm` / `confirm`)か確認サーバの画面で直す
(ADR-0003)。更新は state_store を通るので、サーバと CLI が同時に書いても更新が消えない。

- pron: 全角カタカナ。accent: アクセント核のモーラ位置(0 は平板)。拗音(キョ)・促音・撥音・
  長音は 1 モーラ。CLI では `ス'ラム` のように、核の直後に ' を 1 つ書く
- status: 確認済み / 候補。候補は台本検査が止める

層(後のものが前を上書き): スキル同梱の既定 < ユーザー共通
(`$CONF_VIDEO_HOME/yomi.json`、既定 `~/.conference-video/`) < 動画ごと(セッション内の yomi.json)。
表記は全角に正規化して ENGINE に登録する(ENGINE は半角英数を全角として扱うため)。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import state_store  # noqa: E402

KATAKANA = re.compile(r"^[ァ-ヴー]+$")
LATIN = re.compile(r"[A-Za-z][A-Za-z0-9]*")
SMALL = set("ャュョァィゥェォヮ")  # 直前の仮名と合わせて 1 モーラ
CONFIRMED, CANDIDATE = "確認済み", "候補"
DEFAULT_JSON = Path(__file__).resolve().parent.parent / "assets" / "yomi.default.json"


def to_fullwidth(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        out.append(chr(o + 0xFEE0) if 0x21 <= o <= 0x7E else ch)
    return "".join(out)


# ───────────── 読みの記法 ─────────────


def count_moras(kana: str) -> int:
    return sum(1 for ch in kana if ch not in SMALL)


def parse_reading(text: str) -> tuple[str, int]:
    """'ス'ラム' → ('スラム', 1)。アクセント核の直後に ' を 1 つ。無ければ 0(平板)。"""
    if text.count("'") > 1:
        raise ValueError(f"アクセントの ' は 1 つだけ: {text!r}")
    before, _, after = text.partition("'")
    kana = before + after
    if not KATAKANA.match(kana):
        raise ValueError(f"読みは全角カタカナだけ(空白・英数は不可): {text!r}")
    if "'" in text and not before:
        raise ValueError(f"' を先頭に置けない(1 モーラ目の後ろに): {text!r}")
    accent = count_moras(before) if "'" in text else 0
    return kana, accent


def format_reading(kana: str, accent: int) -> str:
    """('スラム', 1) → 'ス'ラム'。accent が 0 なら平板。"""
    if accent <= 0:
        return kana
    n = 0
    for i, ch in enumerate(kana):
        if ch not in SMALL:
            n += 1
        nxt = kana[i + 1] if i + 1 < len(kana) else ""
        if n == accent and nxt not in SMALL:
            return kana[: i + 1] + "'" + kana[i + 1 :]
    return kana


# ───────────── 読み込み・保存 ─────────────


def validate_entry(surface: str, e) -> None:
    """1 語の検証(state_store の validate に渡す)。不正なら ValueError。"""
    if not surface.strip():
        raise ValueError("表記が空")
    if not isinstance(e, dict) or "pron" not in e or "accent" not in e:
        raise ValueError("pron と accent が要る")
    if not isinstance(e["pron"], str) or not KATAKANA.match(e["pron"]):
        raise ValueError(f"読みは全角カタカナだけ: {e['pron']!r}")
    if (
        not isinstance(e["accent"], int)
        or isinstance(e["accent"], bool)
        or e["accent"] < 0
    ):
        raise ValueError("accent は 0 以上の整数")
    if e.get("status", CONFIRMED) not in (CONFIRMED, CANDIDATE):
        raise ValueError(f"状態は {CONFIRMED} か {CANDIDATE}: {e.get('status')!r}")
    if not isinstance(e.get("note", ""), str):
        raise ValueError("note は文字列")


def make_entry(reading: str, status: str = CONFIRMED, note: str = "") -> dict:
    """`ス'ラム` 形式の読みから 1 語の値を作る(ValueError)。"""
    pron, accent = parse_reading(reading.strip())
    entry = {"pron": pron, "accent": accent, "status": status, "note": note}
    validate_entry("x", entry)
    return entry


def dict_store(path: Path | str) -> state_store.Store:
    return state_store.Store(path, validate=validate_entry)


def read_entries(path: Path | str) -> dict:
    """1 つの辞書ファイルを読む(無ければ FileNotFoundError、壊れていれば ValueError)。"""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"読み辞書が無い: {p}")
    try:
        entries = dict_store(p).read().entries
    except state_store.Corrupt as e:
        raise ValueError(str(e)) from e
    return {s: {"status": CONFIRMED, "note": "", **e} for s, e in entries.items()}


def load(*paths) -> dict:
    merged: dict = {}
    for p in paths:
        merged.update(read_entries(p))
    return merged


def user_home() -> Path:
    return Path(os.environ.get("CONF_VIDEO_HOME") or Path.home() / ".conference-video")


def layer_paths(session: Path | str | None, default: Path = DEFAULT_JSON) -> list[Path]:
    """存在する層のパスを、弱い順に返す(既定 < ユーザー共通 < 動画ごと)。"""
    cands = [Path(default), user_home() / "yomi.json"]
    if session is not None:
        cands.append(Path(session) / "yomi.json")
    return [p for p in cands if p.is_file()]


def describe_layers(session: Path | str) -> list[str]:
    """利用者がどこを直すか分かるよう、各層の絶対パスと有無を並べる(後のものが優先)。"""
    s = Path(os.path.abspath(session))
    items = [
        ("既定", DEFAULT_JSON),
        ("ユーザー共通", user_home() / "yomi.json"),
        ("この動画(ここを直す)", s / "yomi.json"),
    ]
    return [f"  {label}: {p}({'有' if p.is_file() else '無し'})" for label, p in items]


def load_layers(session: Path | str | None, default: Path = DEFAULT_JSON) -> dict:
    return load(*layer_paths(session, default))


def resolve(explicit: list | None, session: Path | str | None) -> dict:
    """--yomi が指定されればそのファイルだけ(空指定なら辞書なし)、無ければ層の合成。"""
    if explicit is None:
        return load_layers(session)
    return load(*explicit) if explicit else {}


def digest(entries: dict) -> str:
    """読みを変えうる内容(読みとアクセント)だけのハッシュ。状態・メモは含めない。"""
    core = {s: [e["pron"], e["accent"]] for s, e in entries.items()}
    blob = json.dumps(core, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def candidates_in(entries: dict) -> list[str]:
    return [s for s, e in entries.items() if e.get("status") == CANDIDATE]


def confirmed(entries: dict) -> dict:
    """確認済みの語だけ(候補は ENGINE の登録もキャッシュ鍵にも使わない)。"""
    return {s: e for s, e in entries.items() if e.get("status") != CANDIDATE}


# ───────────── ENGINE との連携 ─────────────


def engine_words(engine) -> list[dict]:
    """ENGINE に登録されているユーザー辞書の全語(別セッションの登録語も含む)。"""
    return list(engine.user_dict().values())


def line_digest(words: list[dict], text: str) -> str:
    """この行の読みを変えうる辞書の状態(表記が行に現れる語だけ)のハッシュ。

    読みを変えうるのは指定した辞書だけではない(別セッションが登録した語も効く)ので、
    ENGINE に登録された語を見る。一方、行に現れない語の変更では再合成しない
    (1 語直しても、その語を含む行だけがキャッシュを失う)。
    """
    fw = to_fullwidth(text)
    hit = sorted(
        (w["surface"], w["pronunciation"], w["accent_type"], w.get("priority"))
        for w in words
        if w["surface"] and (w["surface"] in fw or w["surface"] in text)
    )
    blob = json.dumps(hit, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


TOOL_PRIORITY = 9  # ツールが ENGINE に登録する語の優先度(既定辞書に負けないため)。ユーザー自身の登録(既定 5)と区別する目印にもする


def prune_engine(engine, entries: dict, priority: int = TOOL_PRIORITY) -> int:
    """現在の辞書(entries)に無い、ツールが登録した語(優先度 priority)を ENGINE から取り除き、数を返す。

    辞書から消した語・候補に戻した語が、同じ ENGINE に残って削除前と同じ読みを使い続けないようにする。
    ユーザー自身の登録(他の優先度)には触れない。
    """
    wanted = {to_fullwidth(engine_surface(s)) for s in entries}
    n = 0
    for uuid, w in list(engine.user_dict().items()):
        if w.get("priority") == priority and w.get("surface") not in wanted:
            engine.delete_word(uuid)
            n += 1
    return n


def register(
    engine, entries: dict, priority: int = TOOL_PRIORITY, prune: bool = True
) -> int:
    """未登録・変更のある語だけ登録し、登録した数を返す(prune=True なら、辞書に無いツールの登録を先に取り除く)。

    読み・アクセント・優先度のいずれかが違う既存の語は、削除してから登録し直す(重複させない)。
    """
    if prune:
        prune_engine(engine, entries, priority)
    existing = {
        w["surface"]: (uuid, (w["pronunciation"], w["accent_type"], w.get("priority")))
        for uuid, w in engine.user_dict().items()
    }
    n = 0
    for surface, e in entries.items():
        key = to_fullwidth(engine_surface(surface))
        want = (e["pron"], e["accent"], priority)
        old = existing.get(key)
        if old and old[1] == want:
            continue
        if old:
            engine.delete_word(old[0])
        engine.add_word(key, e["pron"], e["accent"], priority)
        n += 1
    return n


def latin_tokens(text: str) -> list[str]:
    return LATIN.findall(text)


def is_compound(surface: str) -> bool:
    """ハイフンでつながる語(SLAM-MER、7-Scenes)。英字を 2 語以上含む表記も含む。"""
    return "-" in surface or len(LATIN.findall(surface)) >= 2


def _compound_re(surface: str):
    """表記そのものと、ハイフンを除いた形(7Scenes)のどちらも拾う。"""
    forms = sorted({surface, engine_surface(surface)}, key=len, reverse=True)
    alt = "|".join(re.escape(f) for f in forms)
    return re.compile(r"(?<![A-Za-z0-9])(?:" + alt + r")(?![A-Za-z0-9])")


def engine_surface(surface: str) -> str:
    """ENGINE の辞書に登録する表記。複合語はハイフン等を除く。

    ENGINE は SLAM-MER のようなハイフン入りの表記を辞書で一致させられない
    (実測: 登録しても読みが変わらない。ハイフンを除いた SLAMMER なら効く)。
    """
    return re.sub(r"[^A-Za-z0-9]", "", surface) if is_compound(surface) else surface


def speech_text(text: str, entries: dict) -> str:
    """ENGINE に渡す文。複合語の表記を engine_surface の形に置き換える(字幕は元のまま)。"""
    for s in present_compounds(text, entries):
        text = _compound_re(s).sub(engine_surface(s), text)
    return text


def present_compounds(text: str, entries: dict) -> list[str]:
    """行に現れる複合語の表記(長い順)。"""
    found = [
        s
        for s in sorted(entries, key=len, reverse=True)
        if is_compound(s) and _compound_re(s).search(text)
    ]
    return found


def missing(text: str, entries: dict) -> list[str]:
    """辞書に無い英字の語。複合語の表記(SLAM-MER)があればその範囲はカバーされる。

    複合語だけを、前後に英数字が続かない範囲で隔てる(1 文字の表記 C が CVPR を崩さない)。
    """
    masked = text
    for s in present_compounds(text, entries):
        masked = _compound_re(s).sub(" ", masked)
    seen, out = set(), []
    for t in latin_tokens(masked):
        if t not in entries and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def engine_reading(engine, text: str, speaker: int = 2) -> str:
    """ENGINE が text を今どう読むか(先頭のアクセント句のアクセントで ' を付けた仮名)。

    ENGINE は長音を母音の繰り返し(オオ)で返すので、直前と同じ母音を持つ
    子音なしのモーラを「ー」に直す(下書き。利用者が直しやすい形にする)。
    """
    q = engine.audio_query(text, speaker)
    phrases = q["accent_phrases"]
    if not phrases:
        return ""
    chars, prev = [], None
    for ap in phrases:
        for m in ap["moras"]:
            vowel = m.get("vowel")
            long = (
                prev is not None
                and not m.get("consonant")
                and vowel == prev
                and vowel in ("a", "i", "u", "e", "o")
            )
            chars.append("ー" if long else m["text"])
            prev = vowel
    return format_reading("".join(chars), int(phrases[0].get("accent") or 0))


# ───────────── コマンド ─────────────


def _add_candidates(out: Path, new: dict) -> int:
    """候補を辞書に追加する(既にある語は変えない)。追加した数を返す。"""
    store = dict_store(out)
    n = 0
    for surface, entry in new.items():
        try:
            store.update(surface, None, entry)
            n += 1
        except state_store.Conflict:
            pass  # 別の書き手が先に入れた。上書きしない
    return n


def cmd_register(a, engine) -> int:
    entries = resolve(a.yomi or None, Path.cwd()) if not a.files else load(*a.files)
    n = register(engine, confirmed(entries), prune=False)
    removed = 0 if a.no_prune else prune_engine(engine, confirmed(entries))
    print(
        f"{n} 語を登録した(全 {len(entries)} 語、候補 {len(candidates_in(entries))} 語)"
    )
    if removed:
        print(f"{removed} 語を取り除いた(辞書に無いツールの登録)")
    return 0


def cmd_candidates(a, engine) -> int:
    import narration_check

    lines = narration_check.parse_subtitles(a.narration)
    out = Path(a.out)
    dict_store(
        out
    ).initialize()  # 候補がゼロでも動画ごとの辞書を作る(無いと読みの承認できない)。既存は触らない
    known = resolve(a.yomi, out.parent)
    if out.is_file():
        known = {**known, **load(out)}
    found, seen, unknown = {}, set(), []
    for text in lines:
        for tok in missing(text, known):
            if tok in seen:
                continue
            seen.add(tok)
            try:
                found[tok] = make_entry(
                    engine_reading(engine, to_fullwidth(tok), a.speaker),
                    CANDIDATE,
                    "エンジンの現在の読み(下書き)",
                )
            except ValueError:
                unknown.append(
                    tok
                )  # エンジンがカタカナで返さなかった語は下書きを作れない
    added = _add_candidates(out, found) if found else 0
    print(f"候補 {added} 語を {out} に追加した: {', '.join(found) or '(なし)'}")
    if unknown:
        print(
            f"読みを推定できなかった語: {', '.join(unknown)}"
            f"(`yomi.py set <表記> <読み> --file {out}` で入れる)",
            file=sys.stderr,
        )
    return 0


def _target(a) -> Path:
    return user_home() / "yomi.json" if a.user else Path(a.file)


def _edit(a, surface: str, make) -> int:
    """`make(現在の値)` で新しい値(削除は None)を作り、窓口で更新する。
    CLI は「この操作を適用する」意図なので、競合したら読み直して数回やり直す。"""
    store = dict_store(_target(a))
    for _ in range(3):
        cur = store.read().entries.get(surface)
        try:
            store.update(surface, cur, make(cur))
            return 0
        except state_store.Conflict:
            continue
    raise state_store.Conflict(None, f"「{surface}」が他の書き手と競合し続けている")


def cmd_list(a, _engine) -> int:
    entries = (
        resolve(None, Path.cwd())
        if a.all
        else (read_entries(_target(a)) if _target(a).is_file() else {})
    )
    for surface, e in entries.items():
        print(
            f"{surface}\t{format_reading(e['pron'], e['accent'])}\t{e['status']}\t{e['note']}"
        )
    print(f"({len(entries)} 語)", file=sys.stderr)
    return 0


def cmd_set(a, _engine) -> int:
    def make(cur):
        status = a.status or CONFIRMED  # 人が読みを指定した＝確認した
        note = a.note if a.note is not None else (cur or {}).get("note", "")
        return make_entry(a.reading, status, note)

    code = _edit(a, a.surface, make)
    print(f"「{a.surface}」を {a.reading} にした({_target(a)})")
    return code


def cmd_rm(a, _engine) -> int:
    removed = []

    def make(cur):
        if cur is not None:
            removed.append(1)
        return None

    _edit(a, a.surface, make)
    print(
        f"「{a.surface}」を消した"
        if removed
        else f"「{a.surface}」は辞書に無い({_target(a)})"
    )
    return 0 if removed else 1


def cmd_confirm(a, _engine) -> int:
    missing_words = []
    for surface in a.surfaces:
        done = []

        def make(cur):
            if cur is None:
                return None
            done.append(1)
            return {**cur, "status": CONFIRMED}

        _edit(a, surface, make)
        if not done:
            missing_words.append(surface)
    ok = [s for s in a.surfaces if s not in missing_words]
    if ok:
        print(f"確認済みにした: {', '.join(ok)}")
    if missing_words:
        print(f"辞書に無い: {', '.join(missing_words)}({_target(a)})", file=sys.stderr)
        return 1
    return 0


def cmd_audition(a, engine) -> int:
    import tts_generate
    import wavutil

    entries = resolve(a.yomi, Path.cwd())
    register(engine, confirmed(entries))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    parts, index = [], []
    for i, (surface, e) in enumerate(entries.items(), 1):
        wav, _ = tts_generate.synth_line(
            engine, f"{engine_surface(surface)}。", a.speaker, a.speed
        )
        name = f"{i:02d}_{re.sub(r'[^A-Za-z0-9]+', '', surface) or 'x'}.wav"
        (out / name).write_bytes(wav)
        parts += [wav, wavutil.silence_like(wav, 0.5)]
        index.append([i, surface, format_reading(e["pron"], e["accent"]), name])
    if parts:
        wavutil.concat_wavs(parts, out / "all.wav")
    with (out / "index.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["番号", "表記", "読み", "ファイル"])
        w.writerows(index)
    print(
        f"{len(index)} 語の試聴音声を {out} に作った(all.wav は全語を順に連結、順序は index.csv)"
    )
    return 0


def main(argv=None) -> int:
    from voicevox_engine import DEFAULT_URL, DOCKER_HINT, Engine, EngineUnavailable

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--engine-url", default=DEFAULT_URL)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser(
        "register",
        parents=[common],
        help="辞書を ENGINE に登録する(ファイル無指定なら層の合成)",
    )
    p.add_argument("files", nargs="*")
    p.add_argument("--yomi", nargs="*")
    p.add_argument(
        "--no-prune",
        action="store_true",
        help="辞書に無いツールの登録(優先度 9)を ENGINE から取り除かない",
    )
    p.set_defaults(fn=cmd_register)

    p = sub.add_parser(
        "candidates",
        parents=[common],
        help="台本の英字で未登録の語を、ENGINE の読みを下書きに辞書(JSON)へ追加する(候補がゼロでも空の辞書を作る)",
    )
    p.add_argument("narration")
    p.add_argument("--out", default="yomi.json")
    p.add_argument("--yomi", nargs="*", help="既知の辞書(無指定なら層の合成)")
    p.add_argument("--speaker", type=int, default=2)
    p.set_defaults(fn=cmd_candidates)

    p = sub.add_parser(
        "audition", parents=[common], help="辞書の語を 1 語ずつ読み上げた試聴音声を作る"
    )
    p.add_argument("--yomi", nargs="*")
    p.add_argument("--out", default="audition")
    p.add_argument("--speaker", type=int, default=2)
    p.add_argument("--speed", type=float, default=1.0)
    p.set_defaults(fn=cmd_audition)

    def edit_args(p):
        p.add_argument(
            "--file", default="yomi.json", help="直す辞書(既定: ./yomi.json)"
        )
        p.add_argument("--user", action="store_true", help="ユーザー共通の辞書を直す")

    p = sub.add_parser("list", help="辞書の語を一覧する")
    edit_args(p)
    p.add_argument("--all", action="store_true", help="層を合成した結果")
    p.set_defaults(fn=cmd_list, offline=True)

    p = sub.add_parser("set", help="語の読みを設定する(既定で確認済み)")
    edit_args(p)
    p.add_argument("surface")
    p.add_argument("reading", help="全角カタカナ。アクセント核の直後に ' (例: ス'ラム)")
    p.add_argument("--status", choices=[CONFIRMED, CANDIDATE])
    p.add_argument("--note")
    p.set_defaults(fn=cmd_set, offline=True)

    p = sub.add_parser("rm", help="語を辞書から消す")
    edit_args(p)
    p.add_argument("surface")
    p.set_defaults(fn=cmd_rm, offline=True)

    p = sub.add_parser("confirm", help="語を確認済みにする")
    edit_args(p)
    p.add_argument("surfaces", nargs="+")
    p.set_defaults(fn=cmd_confirm, offline=True)

    # 旧形式 `yomi.py FILE...`(サブコマンド無し)も受ける
    argv = list(sys.argv[1:] if argv is None else argv)
    if (
        argv
        and not argv[0].startswith("-")
        and argv[0]
        not in ("register", "candidates", "audition", "list", "set", "rm", "confirm")
    ):
        argv = ["register", *argv]
    a = ap.parse_args(argv)
    try:
        return a.fn(a, None if getattr(a, "offline", False) else Engine(a.engine_url))
    except EngineUnavailable as e:
        print(f"エラー: {e}\n起動例: {DOCKER_HINT}", file=sys.stderr)
        return 2
    except state_store.Conflict as e:
        print(f"エラー(競合): {e}", file=sys.stderr)
        return 3
    except (ValueError, FileNotFoundError, state_store.StoreError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

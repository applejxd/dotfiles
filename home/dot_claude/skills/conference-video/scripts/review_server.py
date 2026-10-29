#!/usr/bin/env python3
"""確認サーバ: 台本・読み・素材・動画の確認・承認・修正を、ブラウザの 1 画面で行う。

正本は作業フォルダの既存ファイルで、サーバはそれを読み書きする窓に過ぎない
(narration.txt / yomi.json / assets.json / notes.json / approvals.json)。
エージェントは、利用者が画面で操作した後、ファイルか `--summary` を読んで続ける。

  review_server.py --workdir DIR [--port N] [--no-open]
      127.0.0.1 だけで待ち受け、`REVIEW_READY <URL>` を出す(URL は作業フォルダのパスから決まる)。
  review_server.py --workdir DIR --summary
      サーバなしで、承認の状態(承認 / 要修正 / 未承認 / 古い)と指摘の件数を出す。

承認は内容のハッシュと一緒に記録し、承認後に内容が変わると「古い」になる。
終了コード: 0 = 成功、2 = 入力が不正(作業フォルダが無いなど)。
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import errno
import json
import math
import mimetypes
import os
import re
import shutil
import signal
import socket
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import assets_ledger  # noqa: E402
import narration_check  # noqa: E402
import review_sheet  # noqa: E402
import state_store  # noqa: E402
import yomi  # noqa: E402

PAGE = Path(__file__).resolve().parent.parent / "assets" / "review.html"
ITEMS = {
    "plan": ("構成案", "brief.md"),
    "script": ("台本", "narration.txt"),
    "yomi": ("読み", "yomi.json"),
    "assets": ("素材", "assets.json"),
    "video": ("動画", "video.mp4"),
}
APPROVED, NEEDS_FIX, CLEARED = "承認", "要修正", "未承認"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".m4v"}
MAX_BODY = 1_000_000
MAX_CONNECTIONS = 128  # 同時に処理する接続の上限(超えた接続はすぐ閉じる)
BODY_DEADLINE = 15.0  # 本文の受信全体の締切(秒)。少しずつ送り続けても切る
CHUNK = 1 << 16


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def store_api_error(e: Exception, key: str = "") -> "ApiError":
    """state_store の例外を API の応答に写す(窓口の契約: 409 / 400 / 503 / 500)。"""
    if isinstance(e, state_store.Conflict):
        what = f"「{key}」" if key else "この項目"
        return ApiError(
            409,
            f"表示後に{what}が変わりました。再読み込みして、内容を確かめてから直してください",
        )
    if isinstance(e, (state_store.Corrupt, state_store.Invalid)):
        return ApiError(400, str(e))
    if isinstance(e, state_store.LockTimeout):
        return ApiError(503, str(e))
    return ApiError(500, str(e))


def validate_approval(item: str, rec) -> None:
    """承認 1 件の検証(state_store の validate に渡す)。不正なら ValueError。"""
    if item not in ITEMS:
        raise ValueError(f"不明な項目: {item!r}")
    if not isinstance(rec, dict) or rec.get("status") not in (APPROVED, NEEDS_FIX):
        raise ValueError("status は 承認 / 要修正")
    if not isinstance(rec.get("hash"), str):
        raise ValueError("hash が要る")
    for k in ("comment", "at"):
        if k in rec and not isinstance(rec[k], str):
            raise ValueError(f"{k} は文字列")


# 書き込みルート: パス → (Workspace のメソッド名, 画面で見た版を示す必須フィールドの組)。
# hash = 対象ファイルの版、expected = 更新する記録そのものの、画面が見た値(新規は null)。
# 書き込みの入口はここに登録する(試験が、表と Workspace の公開メソッドの一致、
# 各ルートの「版が無ければ 400」「壊れた入力で何も書かない」を表から検査する)。
# approve の hash は「未承認に戻す」ときだけ要らない(expected は常に要る)。
ROUTES = {
    "/api/approve": ("approve", ("hash", "expected")),
    "/api/narration": ("edit_narration", ("hash",)),
    "/api/yomi": ("yomi_set", ("expected",)),
    "/api/yomi/delete": ("yomi_delete", ("expected",)),
    "/api/asset": ("asset_set", ("expected",)),
    "/api/note": ("note_set", ("hash", "expected")),
}
# 読み取り専用の公開メソッド(上の表に無い公開メソッドは、書き込みの入口とみなして試験が止める)
READ_ONLY_METHODS = {
    "state",
    "approvals",
    "approvals_store",
    "read_approvals",
    "source_problem",
    "hash_of",
    "p",
}


class ApprovalsError(ValueError):
    """approvals.json が壊れている(黙って空扱いにすると承認の記録を失う)。"""


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def atomic_write(path: Path, data: bytes, mode: int | None = None) -> None:
    """一時ファイル経由で原子的に置き換える。既存ファイルの権限は引き継ぎ、
    新規ファイルは mode(既定 0644)。mkstemp の 0600 をそのまま残さない。"""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if mode is not None:
            os.chmod(tmp, mode)  # 秘密のファイルは、既存が緩い権限でも必ず引き締める
        elif path.exists():
            shutil.copymode(path, tmp)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


SERVICE = "conference-video-review"
PORT_BASE, PORT_SPAN = 8700, 100  # 作業フォルダのパスから決める既定ポートの範囲


def workspace_id(workdir: Path | str) -> str:
    """作業フォルダのパスの識別子(絶対パスそのものは外へ出さない)。"""
    return hashlib.sha256(str(Path(workdir).resolve()).encode("utf-8")).hexdigest()[:12]


def default_port(workdir: Path | str) -> int:
    """作業フォルダのパスから決めた基準ポート(同じフォルダは常に同じ URL。Python の hash() は使わない)。"""
    return PORT_BASE + int(workspace_id(workdir), 16) % PORT_SPAN


def ping(port: int, timeout: float = 0.8) -> dict | None:
    """127.0.0.1:port の確認サーバの /api/ping。このサービスでなければ None。
    総時間の締切(timeout)を持つ(少しずつ答え続ける相手で待ち続けない)。200 以外は本文を待たない。"""
    deadline = time.monotonic() + timeout
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        try:
            conn.request("GET", "/api/ping")
            r = conn.getresponse()
            if r.status != 200:
                return None
            body = b""
            while len(body) < 4096:
                if time.monotonic() > deadline:
                    return None
                chunk = r.read1(512)
                if not chunk:
                    break
                body += chunk
        finally:
            conn.close()
        d = json.loads(body)
        return d if isinstance(d, dict) and d.get("service") == SERVICE else None
    except (OSError, ValueError, http.client.HTTPException):
        return None


def live_url(workdir: Path | str, port: int | None = None) -> str | None:
    """この作業フォルダの確認サーバが動いていれば、その URL。"""
    port = port or default_port(workdir)
    d = ping(port)
    return (
        f"http://127.0.0.1:{port}/"
        if d and d.get("workspace_id") == workspace_id(workdir)
        else None
    )


def _file_signature(path: Path) -> tuple[int, int]:
    """承認の対象ファイルの、軽い版の署名(大きさと更新時刻)。ロックの中の再確認に使う。"""
    st = path.stat()
    return st.st_size, st.st_mtime_ns


def bytes_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    return "image" if ext in IMAGE_EXT else "video" if ext in VIDEO_EXT else "other"


class Workspace:
    """作業フォルダの読み書き。書き込みは 1 つずつ(ロック)で、置き換えは原子的に行う。"""

    def __init__(self, workdir: Path | str):
        self.dir = Path(workdir).resolve()
        self.lock = threading.Lock()
        self._hash_cache: dict = {}

    def hash_of(self, path: Path) -> str:
        """内容のハッシュ(表示用)。大きな動画を毎回読まないよう、更新時刻とサイズでキャッシュする。
        承認と編集の判定は、キャッシュなしでその場で計算したハッシュで行う。"""
        st = path.stat()
        key = (st.st_mtime_ns, st.st_size)
        hit = self._hash_cache.get(path)
        if hit and hit[0] == key:
            return hit[1]
        h = file_hash(path)
        self._hash_cache[path] = (key, h)
        return h

    def p(self, name: str) -> Path:
        return self.dir / name

    # ───── 読み取り ─────
    def _timestamps(self, errors: dict) -> dict | None:
        """timestamps.json を読む。無ければ None。壊れているときは errors に理由を入れて None。"""
        p = self.p("timestamps.json")
        if not p.is_file():
            return None
        try:
            ts = json.loads(p.read_text(encoding="utf-8"))
            subs = ts.get("subtitles") if isinstance(ts, dict) else None
            if not isinstance(subs, list) or not all(
                isinstance(s, dict)
                and isinstance(s.get("text"), str)
                and _is_num(s.get("start_s"))
                and _is_num(s.get("duration_s"))
                and isinstance(s.get("phrases", []), list)
                and all(
                    isinstance(x, dict) and isinstance(x.get("text"), str)
                    for x in s.get("phrases", [])
                )
                for s in subs
            ):
                raise ValueError("subtitles の形式が不正")
            return ts
        except (ValueError, OSError) as e:
            errors["timestamps"] = f"timestamps.json が読めない: {e}"
            return None

    def _script(self, errors: dict) -> dict:
        ts = self._timestamps(errors)
        subs = (ts or {}).get("subtitles", [])
        texts: list[str] | None = None
        if self.p("narration.txt").is_file():
            try:
                texts = narration_check.parse_subtitles(self.p("narration.txt"))
            except ValueError as e:
                errors["script"] = str(e)
        stale = False
        if texts is None:
            texts = [s["text"] for s in subs]
        elif subs:
            stale = texts != [s["text"] for s in subs]
        lines = []
        for i, text in enumerate(texts):
            s = subs[i] if i < len(subs) else None
            lines.append(
                {
                    "index": i,
                    "text": text,
                    "start_s": s["start_s"] if s else None,
                    "duration_s": s["duration_s"] if s else None,
                    "reading": "|".join(x["text"] for x in s.get("phrases", []))
                    if s
                    else "",
                }
            )
        audio = "voiceover.wav" if self.p("voiceover.wav").is_file() else None
        return {"lines": lines, "audio": audio, "stale": stale}

    def _yomi(self, errors: dict) -> list[dict]:
        p = self.p("yomi.json")
        if not p.is_file():
            return []
        try:
            raw = (
                yomi.dict_store(p).read().entries
            )  # 1 回の読み取りから、表示と expected を作る
        except state_store.Corrupt as e:
            errors["yomi"] = str(e)
            return []
        out = []
        for k, v in raw.items():
            full = {"status": yomi.CONFIRMED, "note": "", **v}  # 表示は既定値を補う
            out.append(
                {
                    "surface": k,
                    "reading": yomi.format_reading(full["pron"], full["accent"]),
                    "status": full["status"],
                    "note": full["note"],
                    "entry": v,  # 補完前の生の値。画面が「見た値」として更新に添える(比較交換)
                }
            )
        return out

    def _assets(self, errors: dict) -> list[dict]:
        p = self.p("assets.json")
        if not p.is_file():
            return []
        try:
            raw = (
                assets_ledger.store(p).read().entries
            )  # 1 回の読み取りから、表示と expected を作る
            rows = assets_ledger.rows_from_entries(raw)
        except (ValueError, assets_ledger.state_store.StoreError) as e:
            errors["assets"] = str(e)
            return []
        out = []
        for r in rows:
            d = dict(r)
            d["kind"] = kind_of(r["ファイル"])
            d["url"] = "/files/" + quote(r["ファイル"])
            d["credit"] = assets_ledger.short_credit(r)
            d["exists"] = self.p(r["ファイル"]).is_file()
            d["entry"] = raw[
                r["ファイル"]
            ]  # 画面が「見た値」として更新に添える(比較交換)
            out.append(d)
        return out

    def _notes(self) -> list[dict]:
        """指摘の一覧(notes.json)。壊れていれば ValueError。台本が読めないときは古い判定をしない。"""
        try:
            script = self._script({})["lines"]
        except (ValueError, OSError):
            script = None
        texts = [x["text"] for x in script] if script else None
        out = []
        for n in review_sheet.read_notes(self.dir, texts):
            t = (
                script[n["line"] - 1]["start_s"]
                if script and n["line"] <= len(script)
                else None
            )
            out.append(
                {
                    "line": n["line"],
                    "start": review_sheet.mmss(t) if t is not None else "",
                    "text": n["text"],
                    "note": n["note"],
                    "stale": n["stale"],
                    "entry": n["entry"],
                }
            )
        return out

    def approvals_store(self) -> state_store.Store:
        return state_store.Store(self.p("approvals.json"), validate=validate_approval)

    def read_approvals(self) -> dict:
        """approvals.json の生の記録。無ければ {}。壊れていれば ApprovalsError(黙って空にしない)。"""
        try:
            return self.approvals_store().read().entries
        except state_store.Corrupt as e:
            raise ApprovalsError(
                f"approvals.json が壊れている({e})。内容を確認して直すか、"
                "別名に退避してから承認し直してください"
            ) from e

    def approvals(self, fresh: bool = False) -> dict:
        """承認の状態(現在の内容とのハッシュ比較つき)。壊れていれば ApprovalsError。
        fresh=True はキャッシュを使わず、その場でハッシュを計算する(ゲート・要約用)。"""
        out = {}
        for item, rec in self.read_approvals().items():
            f = self.p(ITEMS[item][1])
            if not f.is_file():
                now = ""
            else:
                now = file_hash(f) if fresh else self.hash_of(f)
            out[item] = {**rec, "stale": rec.get("hash") != now}
        return out

    def source_problem(self, item: str) -> str | None:
        """承認の対象の正本が読めないときの理由(読めれば None)。ゲートで使う。"""
        try:
            if item == "script":
                narration_check.parse_subtitles(self.p("narration.txt"))
            elif item == "plan" and self.p("brief.md").is_file():
                self.p("brief.md").read_text(
                    encoding="utf-8"
                )  # 表示できない構成案は承認しない
            elif item == "yomi" and self.p("yomi.json").is_file():
                yomi.read_entries(self.p("yomi.json"))
            elif item == "assets" and self.p("assets.json").is_file():
                assets_ledger.load(self.p("assets.json"))
        except (ValueError, OSError) as e:
            return str(e)
        return None

    def _guard(self, errors: dict, key: str, fn, default):
        try:
            return fn()
        except (ValueError, OSError) as e:
            errors[key] = str(e)
            return default

    def state(self) -> dict:
        errors: dict = {}
        brief = self.p("brief.md")
        # ハッシュは内容を読む**前**に取る。読む最中に外部で変わっても、未確認の版を
        # 承認しない(変わったら承認は 409 になり、安全側に倒れる)。
        hashes = {
            item: (self.hash_of(self.p(f)) if self.p(f).is_file() else None)
            for item, (_, f) in ITEMS.items()
        }
        return {
            "workdir": str(self.dir),
            "script": self._guard(
                errors,
                "script",
                lambda: self._script(errors),
                {"lines": [], "audio": None, "stale": False},
            ),
            "yomi": self._guard(errors, "yomi", lambda: self._yomi(errors), []),
            "yomi_layers": yomi.describe_layers(self.dir),
            "assets": self._guard(errors, "assets", lambda: self._assets(errors), []),
            "notes": self._guard(errors, "notes", self._notes, []),
            "approvals": self._guard(errors, "approvals", self.approvals, {}),
            "hashes": hashes,
            "video": "video.mp4" if self.p("video.mp4").is_file() else None,
            "brief": self._guard(
                errors,
                "brief",
                lambda: brief.read_text(encoding="utf-8") if brief.is_file() else "",
                "",
            ),
            "errors": errors,
        }

    # ───── 書き込み ─────
    def approve(self, body: dict) -> dict:
        item, status = body.get("item"), body.get("status")
        if not isinstance(item, str) or item not in ITEMS:
            raise ApiError(400, f"item は {' / '.join(ITEMS)} のどれか")
        if status not in (APPROVED, NEEDS_FIX, CLEARED):
            raise ApiError(400, f"status は {APPROVED} / {NEEDS_FIX} / {CLEARED}")
        comment = str(body.get("comment", "")).strip()
        target = self.p(ITEMS[item][1])
        given = body.get("hash")
        if status != CLEARED and (not isinstance(given, str) or not given):
            raise ApiError(400, "hash が要る(画面で見た版のハッシュ)")
        expected = self._expected(body)  # 画面が見たこの項目の承認記録(無ければ null)
        if status == APPROVED and (problem := self.source_problem(item)):
            raise ApiError(
                400, f"読めない正本は承認できません(先に直してください): {problem}"
            )
        changed = ApiError(
            409,
            f"表示後に {target.name} が変わりました。再読み込みして、内容を確かめてから承認してください",
        )
        sig = None
        if status != CLEARED:
            if not target.is_file():
                raise ApiError(400, f"対象のファイルが無い: {target.name}")
            sig = _file_signature(target)
            if file_hash(target) != given:  # 重いハッシュ計算はロックの外で行う
                raise changed

        def guard():  # ロックの中では、軽い確認(大きさと更新時刻が、ハッシュを取った時から不変)だけ行う
            if sig is not None and _file_signature(target) != sig:
                raise changed

        new = (
            None
            if status == CLEARED
            else {
                "status": status,
                "comment": comment,
                "hash": given,
                "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
        )
        try:
            self.approvals_store().update(
                item, expected, new, guard=guard if sig else None
            )
        except state_store.Corrupt as e:
            raise ApiError(
                409,
                f"approvals.json が壊れている({e})。内容を確認して直すか、"
                "別名に退避してから承認し直してください",
            ) from e
        except state_store.StoreError as e:
            raise store_api_error(e, item) from e
        return {"ok": True}

    def edit_narration(self, body: dict) -> dict:
        idx, text = body.get("index"), body.get("text")
        if isinstance(idx, bool) or not isinstance(idx, int) or idx < 0:
            raise ApiError(400, "index は 0 以上の整数")
        if not isinstance(text, str) or not text.strip():
            raise ApiError(400, "本文が空")
        text = text.strip()
        given = body.get("hash")
        if not isinstance(given, str) or not given:
            raise ApiError(400, "hash が要る(画面で見た台本のハッシュ)")
        if "\n" in text or "\r" in text:
            raise ApiError(400, "本文は 1 行にする")
        p = self.p("narration.txt")
        if not p.is_file():
            raise ApiError(400, "narration.txt が無い")
        with self.lock:
            raw = p.read_bytes()
            if bytes_hash(raw) != given:  # 見た版と違う(同じ本文の行が増えた場合も含む)
                raise ApiError(
                    409,
                    "表示後に narration.txt が変わりました。"
                    "再読み込みして、内容を確かめてから直してください",
                )
            try:
                lines = raw.decode("utf-8").splitlines(keepends=True)
            except UnicodeDecodeError as e:
                raise ApiError(400, f"narration.txt が UTF-8 で読めない: {e}") from e
            in_block, n, hit = False, -1, None
            for i, ln in enumerate(lines):
                if not in_block:
                    in_block = re.match(r"^subtitles:\s*$", ln) is not None
                    continue
                m = re.match(r"^([ \t]*-[ \t]*)(.*?)(\r?\n?)$", ln)
                if m:
                    n += 1
                    if n == idx:
                        hit = (i, m.group(1), m.group(3))
                        break
                elif ln.strip() and not ln[0].isspace():
                    break
            if hit is None:
                raise ApiError(400, f"{idx} 行目は台本に無い")
            i, prefix, eol = hit
            lines[i] = f"{prefix}{text}{eol}"
            atomic_write(self.p("narration.txt.bak"), raw)
            atomic_write(p, "".join(lines).encode("utf-8"))
        return {"ok": True, "needs_resynthesis": True}

    @staticmethod
    def _expected(body: dict):
        """画面が見た、その項目の値(新規は null)。無ければ 400。"""
        if "expected" not in body:
            raise ApiError(400, "expected が要る(画面で見たその項目の値。新規は null)")
        exp = body["expected"]
        if exp is not None and not isinstance(exp, dict):
            raise ApiError(400, "expected は項目の値(辞書)か null")
        return exp

    def yomi_set(self, body: dict) -> dict:
        surface = str(body.get("surface", "")).strip()
        if not surface or "\n" in surface or "\r" in surface:
            raise ApiError(400, "表記が空か不正")
        status = body.get("status", yomi.CONFIRMED)
        if status not in (yomi.CONFIRMED, yomi.CANDIDATE):
            raise ApiError(400, f"状態は {yomi.CONFIRMED} か {yomi.CANDIDATE}")
        try:
            entry = yomi.make_entry(
                str(body.get("reading", "")).strip(),
                status,
                str(body.get("note", "")).strip(),
            )
        except ValueError as e:
            raise ApiError(400, f"読みが不正: {e}") from e
        expected = self._expected(body)
        try:
            yomi.dict_store(self.p("yomi.json")).update(surface, expected, entry)
        except state_store.StoreError as e:
            raise store_api_error(e, surface) from e
        return {"ok": True}

    def yomi_delete(self, body: dict) -> dict:
        surface = str(body.get("surface", "")).strip()
        expected = self._expected(body)
        if expected is None:
            raise ApiError(400, f"この動画の辞書に無い: {surface}")
        try:
            yomi.dict_store(self.p("yomi.json")).update(surface, expected, None)
        except state_store.StoreError as e:
            raise store_api_error(e, surface) from e
        return {"ok": True}

    def asset_set(self, body: dict) -> dict:
        status = body.get("status")
        if status not in assets_ledger.STATUSES:
            raise ApiError(400, f"状態は {' / '.join(assets_ledger.STATUSES)}")
        p = self.p("assets.json")
        if not p.is_file():
            raise ApiError(400, "assets.json が無い")
        name = body.get("file")
        if not isinstance(name, str) or not name:
            raise ApiError(400, "file が要る(台帳のファイル名)")
        expected = self._expected(body)
        if expected is None:
            raise ApiError(400, f"台帳に無い: {name}")
        new = {**expected, "状態": status, "メモ": str(body.get("note", "")).strip()}
        try:
            assets_ledger.store(p).update(name, expected, new)
        except assets_ledger.state_store.StoreError as e:
            raise store_api_error(e, name) from e
        return {"ok": True}

    def note_set(self, body: dict) -> dict:
        line = body.get("line")
        if isinstance(line, bool) or not isinstance(line, int):
            raise ApiError(400, "line は整数(1 始まり)")
        note = str(body.get("note", "")).strip()
        seen = body.get("hash")  # 画面で見た台本のハッシュ(必須)。変わっていれば 409
        if not isinstance(seen, str) or not seen:
            raise ApiError(400, "hash が要る(画面で見た台本のハッシュ)")
        expected = self._expected(body)  # 画面が見たこの行の指摘(無ければ null)
        narr = self.p("narration.txt")
        if not narr.is_file():
            raise ApiError(400, "narration.txt が無い")
        changed = ApiError(
            409,
            "表示後に narration.txt が変わりました。再読み込みしてから書いてください",
        )

        def same_script() -> bool:
            try:
                return (
                    bytes_hash(narr.read_bytes()) == seen
                )  # 同じ本文の行が増えた場合も含む
            except OSError:
                return False

        if not same_script():
            raise changed
        try:
            cur = [x["text"] for x in self._script({})["lines"]]
        except (ValueError, OSError) as e:
            raise ApiError(400, f"台本が読めない: {e}") from e
        deleting = not note
        if not 1 <= line <= len(cur):
            # 台本から消えた行の古い指摘は、見たうえで消せる。範囲外への新規の指摘は拒否する
            if not (deleting and expected is not None and line >= 1):
                raise ApiError(400, f"{line} 行目は台本に無い")

        def guard():  # 見た台本の版を、ロックの中でも確かめる
            if not same_script():
                raise changed

        new = (
            None
            if deleting
            else {
                "note": note,
                "text": cur[
                    line - 1
                ],  # 指摘したときの本文(台本が変わったら「古い」と分かる)
                "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
        )
        try:
            review_sheet.notes_store(self.dir).update(
                str(line), expected, new, guard=guard
            )
        except state_store.StoreError as e:
            raise store_api_error(e, str(line)) from e
        return {"ok": True}


def gate_problems(ws: Workspace, required: list[str]) -> list[str]:
    """必要な承認が揃っていない理由(空なら通過)。承認済みでも、正本が読めないと停止。
    approvals.json が壊れていれば ApprovalsError。"""
    ap = ws.approvals(fresh=True)  # 安全の要。表示用のキャッシュを信じない
    out = []
    for item in required:
        label = ITEMS[item][0]
        rec = ap.get(item)
        if rec is None:
            out.append(f"{label}: {CLEARED}")
        elif rec["stale"]:
            out.append(f"{label}: 古い(承認後に変更)")
        elif rec["status"] == NEEDS_FIX:
            out.append(f"{label}: {NEEDS_FIX}({rec.get('comment', '')})")
        elif msg := ws.source_problem(item):
            out.append(f"{label}: 読めない({msg})")
    return out


def summary_lines(ws: Workspace) -> tuple[list[str], bool]:
    """(行, 問題なしか)。approvals.json が壊れていれば ApprovalsError。
    指摘を読めない(notes.json が壊れている)ときは、問題ありを返す。"""
    ap = ws.approvals(fresh=True)
    out = []
    for item, (label, _) in ITEMS.items():
        rec = ap.get(item)
        if rec is None:
            state = CLEARED
        elif rec["stale"]:
            state = "古い"
        elif rec["status"] == NEEDS_FIX:
            state = f"要修正({rec['comment']})" if rec.get("comment") else NEEDS_FIX
        else:
            state = APPROVED
        out.append(f"{label}: {state}")
    ok = True
    try:
        out.append(f"指摘 {len(ws._notes())} 件")
    except ValueError as e:
        ok = False
        out.append(f"指摘: 読めない({e})")
    return out, ok


# ───────────── HTTP ─────────────


def parse_range(header: str, size: int) -> tuple[int, int] | None:
    """`bytes=a-b` / `a-` / `-n` を (開始, 終了) に。満たせなければ ValueError。"""
    if size <= 0:
        raise ValueError("range")
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if not m or (m.group(1) == "" and m.group(2) == ""):
        raise ValueError("range")
    a, b = m.groups()
    if a == "":
        n = int(b)
        if n == 0:
            raise ValueError("range")
        return max(size - n, 0), size - 1
    start = int(a)
    end = min(int(b), size - 1) if b else size - 1
    if start >= size or end < start:
        raise ValueError("range")
    return start, end


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        # スレッドを作る前に上限を確かめる(超えた接続はすぐ閉じ、資源を使い切らせない)
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()
    # Windows の SO_REUSEADDR は同じポートへの二重バインドを許してしまうので、使わない
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request, client_address):
        """ブラウザが接続を閉じただけのエラーでログを埋めない(それ以外は従来どおり表示)。"""
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def inline_safe(ctype: str) -> bool:
    """ブラウザの中で表示してよい型(画像・動画・音声)。SVG は直接開くとスクリプトを実行できるので除く。"""
    base = ctype.split(";")[0].strip().lower()
    return base != "image/svg+xml" and base.split("/")[0] in ("image", "video", "audio")


def make_server(workdir, port: int = 0, host="127.0.0.1"):
    ws = Workspace(workdir)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "review"
        timeout = 10  # 1 回の受信の待ち時間。本文全体は BODY_DEADLINE でも切る

        def log_message(self, *a):  # 静かに
            pass

        # ── 共通 ──
        def end_headers(self):
            self._security_headers()
            super().end_headers()

        def _security_headers(self):
            # 他サイトからの埋め込み・MIME の推測を拒否する(全応答で共通)
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")

        def _send(self, status: int, body: bytes, ctype: str, extra=None, close=False):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if close:  # 未読の本文が残る接続は再利用しない
                self.send_header("Connection", "close")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, obj, close=False):
            self._send(
                status,
                json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                "application/json; charset=utf-8",
                close=close,
            )

        def _internal_error(self):
            traceback.print_exc()  # 詳細はサーバのログだけ。画面には返さない
            try:
                self._json(
                    500, {"error": "内部エラー(サーバのログを見てください)"}, close=True
                )
            except OSError:
                pass

        def _authorized(self) -> bool:
            port_ = self.server.server_address[1]
            if self.headers.get("Host", "") not in (
                f"127.0.0.1:{port_}",
                f"localhost:{port_}",
            ):
                return False
            origin = self.headers.get("Origin")
            if origin is not None and origin not in (
                f"http://127.0.0.1:{port_}",
                f"http://localhost:{port_}",
            ):
                return False  # 他のサイトからの要求(ブラウザは Origin を付ける)
            return True

        # ── GET ──
        def do_GET(self):
            u = urlparse(self.path)
            if not self._authorized():
                return self._json(403, {"error": "forbidden"})
            try:
                if u.path == "/":
                    return self._send(
                        200, PAGE.read_bytes(), "text/html; charset=utf-8"
                    )
                if (
                    u.path == "/api/ping"
                ):  # 同じフォルダのサーバが動いているかの確認用(絶対パスは返さない)
                    return self._json(
                        200,
                        {
                            "service": SERVICE,
                            "version": 1,
                            "workspace_id": workspace_id(ws.dir),
                        },
                    )
                if u.path == "/api/state":
                    return self._json(200, ws.state())
                if u.path.startswith("/files/"):
                    return self._file(u.path[len("/files/") :])
            except ApiError as e:
                return self._json(e.status, {"error": e.message})
            except Exception:
                return self._internal_error()
            self._json(404, {"error": "not found"})

        def _file(self, rel_quoted: str):
            rel = unquote(rel_quoted)
            if (
                not rel
                or rel.startswith("/")
                or "\x00" in rel
                or ".." in Path(rel).parts
            ):
                return self._json(404, {"error": "not found"})
            p = (ws.dir / rel).resolve()
            if not p.is_relative_to(ws.dir) or not p.is_file():
                return self._json(404, {"error": "not found"})
            try:
                f = p.open("rb")  # 先に開き、開いた実体の大きさで長さを決める(差し替え・短縮に備える)
            except OSError:
                return self._json(404, {"error": "not found"})
            with f:
                size = os.fstat(f.fileno()).st_size
                ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                status, start, end, extra = 200, 0, size - 1, {"Accept-Ranges": "bytes"}
                rng = self.headers.get("Range")
                if rng:
                    try:
                        start, end = parse_range(rng, size)
                    except ValueError:
                        return self._send(
                            416, b"", "text/plain", {"Content-Range": f"bytes */{size}"}
                        )
                    status = 206
                    extra["Content-Range"] = f"bytes {start}-{end}/{size}"
                length = end - start + 1 if size else 0
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(length))
                self.send_header("Cache-Control", "no-cache")
                if not inline_safe(ctype):  # メディア以外は表示せず保存に回す(スクリプトを実行させない)
                    self.send_header("Content-Disposition", "attachment")
                for k, v in extra.items():
                    self.send_header(k, v)
                self.end_headers()
                try:
                    f.seek(start)
                    left = length
                    while left > 0:
                        chunk = f.read(min(CHUNK, left))
                        if not chunk:
                            self.close_connection = True  # 宣言した長さに足りない: 接続を閉じる(応答の境界を壊さない)
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
                except OSError:
                    self.close_connection = True

        def _read_body(self, n: int) -> bytes:
            """宣言した長さの本文を、総締切つきで読む。足りなければ 400、遅すぎれば 408(接続は閉じる)。"""
            deadline = time.monotonic() + BODY_DEADLINE
            buf = bytearray()
            while len(buf) < n:
                if time.monotonic() > deadline:
                    raise ApiError(408, "本文の受信が遅すぎます")
                chunk = self.rfile.read1(min(CHUNK, n - len(buf)))
                if not chunk:
                    raise ApiError(400, "本文が途中で切れています(Content-Length に足りない)")
                buf += chunk
            return bytes(buf)

        # ── POST ──
        def do_POST(self):
            u = urlparse(self.path)
            if not self._authorized():
                return self._json(403, {"error": "forbidden"}, close=True)
            route = ROUTES.get(u.path)
            fn = getattr(ws, route[0]) if route else None
            if fn is None:
                return self._json(404, {"error": "not found"}, close=True)
            ctype = (
                (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            )
            if (
                ctype != "application/json"
            ):  # 他サイトのフォーム送信(事前確認なし)を拒否
                return self._json(
                    415, {"error": "Content-Type は application/json"}, close=True
                )
            try:
                consumed = False
                raw_len = self.headers.get("Content-Length")
                if raw_len is None:
                    raise ApiError(400, "Content-Length が要る")
                try:
                    n = int(raw_len)
                except ValueError:
                    raise ApiError(400, "Content-Length が不正") from None
                if n < 0:
                    raise ApiError(400, "Content-Length が不正")
                if n > MAX_BODY:
                    return self._json(413, {"error": "本文が大きすぎる"}, close=True)
                raw = self._read_body(n)
                consumed = True
                body = json.loads(raw or b"{}")
                if not isinstance(body, dict):
                    raise ApiError(400, "JSON のオブジェクトが要る")
                self._json(200, fn(body))
            except ApiError as e:
                self._json(
                    e.status,
                    {"error": e.message},
                    close=not consumed,
                )
            except (ValueError, RecursionError):
                self._json(400, {"error": "JSON が不正"})
            except Exception:
                self._internal_error()

    httpd = _Server((host, port), Handler)
    httpd.daemon_threads = True
    httpd.workspace = ws
    return httpd


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--workdir", default=".")
    ap.add_argument(
        "--port",
        type=int,
        default=None,
        help="既定は作業フォルダのパスから決めたポート(8700〜8799)。0 なら空いているポート",
    )
    ap.add_argument("--no-open", action="store_true", help="ブラウザを自動で開かない")
    ap.add_argument(
        "--summary", action="store_true", help="承認の状態と指摘の件数だけ出す"
    )
    ap.add_argument(
        "--require",
        help="--summary と併用。先へ進むに必要な承認(plan,script,yomi,assets,video のカンマ区切り)。"
        "揃っていない・古い・要修正・正本が読めないと終了コード 1",
    )
    a = ap.parse_args(argv)

    w = Path(a.workdir)
    if not w.is_dir():
        print(f"エラー: 作業フォルダが無い: {w}")
        return 2
    required: list[str] = []
    if a.require is not None:
        if not a.summary:
            print("エラー: --require は --summary と併用する")
            return 2
        required = [x.strip() for x in a.require.split(",") if x.strip()]
        bad = [x for x in required if x not in ITEMS]
        if bad or not required:
            print(
                f"エラー: --require は {','.join(ITEMS)} のうちから指定する: {bad or a.require!r}"
            )
            return 2
    if a.summary:
        try:
            ws = Workspace(w)
            lines, ok = summary_lines(ws)
            problems = gate_problems(ws, required)
        except ApprovalsError as e:
            print(f"エラー: {e}")
            return 1
        print("\n".join(lines))
        shown = live_url(ws.dir, a.port or None)
        print(
            f"確認画面: {shown}"
            if shown
            else f"確認画面: 停止中(起動: python3 {Path(__file__).resolve()} --workdir {ws.dir})"
        )
        if required:
            if problems:
                print("ゲート: 停止")
                print("\n".join(f"  - {x}" for x in problems))
            else:
                print(f"ゲート: 通過({', '.join(ITEMS[x][0] for x in required)})")
        return 0 if ok and not problems else 1
    w = Path(w).resolve()
    print(f"作業フォルダ: {w}", flush=True)
    port = default_port(w) if a.port is None else a.port  # --port 0 は空いているポート
    if not 0 <= port <= 65535:
        print(f"エラー: --port は 0〜65535: {port}")
        return 2
    try:
        httpd = make_server(w, port)
    except OSError as e:
        in_use = {errno.EADDRINUSE, 10048} | ({10013} if os.name == "nt" else set())
        if e.errno not in in_use:
            print(f"エラー: ポート {port} で待ち受けられません({e.strerror or e})。--port で別のポートを指定してください")
            return 2
        # ポートが使用中: 同じフォルダのサーバならその URL を案内して終わる(自動では繰り上げない)
        for _ in range(6):  # 起動直後で応答できないことがあるので、少し待つ
            d = ping(port)
            if d:
                break
            time.sleep(0.25)
        if d and d.get("workspace_id") == workspace_id(w):
            print("既に起動中です(新しいサーバは起動しません)", flush=True)
            print(f"REVIEW_READY http://127.0.0.1:{port}/", flush=True)
            return 0
        why = (
            "別の作業フォルダの確認サーバが使っています"
            if d
            else "他のプログラムが使っています"
        )
        print(
            f"エラー: ポート {port} は使用中です({why})。--port で別のポートを指定してください: {e}"
        )
        return 2
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"

    def _term(*_):
        raise KeyboardInterrupt  # SIGTERM でも正常終了する

    signal.signal(signal.SIGTERM, _term)
    try:
        print(f"REVIEW_READY {url}", flush=True)
        print("終了するには Ctrl+C", flush=True)
        if not a.no_open:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

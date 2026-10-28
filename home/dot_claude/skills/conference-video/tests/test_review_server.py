"""確認サーバ(review_server.py): ブラウザでの確認・承認・修正。AC-17〜AC-24。"""

import contextlib
import hashlib
import http.client
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import review_server  # noqa: E402
import yomi  # noqa: E402
from dict_fixture import write_assets, write_dict  # noqa: E402
import assets_ledger  # noqa: E402

NARRATION = """# 台本
```
subtitles:
- 単眼 SLAM です。
- 次に地図です。
- 最後に結果です。
```
"""

TS = {
    "total_duration_s": 12.0,
    "subtitles": [
        {
            "index": 0,
            "text": "単眼 SLAM です。",
            "start_s": 0.0,
            "end_s": 4.0,
            "duration_s": 4.0,
            "phrases": [{"text": "タンガン"}, {"text": "スラム"}, {"text": "デス"}],
        },
        {
            "index": 1,
            "text": "次に地図です。",
            "start_s": 4.0,
            "end_s": 8.0,
            "duration_s": 4.0,
            "phrases": [{"text": "ツギニ"}, {"text": "チズデス"}],
        },
        {
            "index": 2,
            "text": "最後に結果です。",
            "start_s": 8.0,
            "end_s": 12.0,
            "duration_s": 4.0,
            "phrases": [{"text": "サイゴニ"}, {"text": "ケッカデス"}],
        },
    ],
}

YOMI = {"SLAM": ("スラ'ム", "確認済み", ""), "KL": ("ケーエル", "候補", "下書き")}
ASSETS = {
    "assets/a.png": {
        "出典URL": "https://example.org/a",
        "作者": "太郎",
        "ライセンス": "CC BY 4.0",
        "状態": "確認済み",
        "場面": "動機",
        "メモ": "",
        "取得日": "2026-10-27",
    },
    "assets/b.webm": {
        "出典URL": "https://example.org/b",
        "作者": "花子",
        "ライセンス": "不明",
        "状態": "仮",
        "場面": "動機",
        "メモ": "",
        "取得日": "2026-10-27",
    },
}
VIDEO = bytes(range(256)) * 8  # 2048 バイト


def sha12(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "work"
        (self.dir / "assets").mkdir(parents=True)
        (self.dir / "narration.txt").write_text(NARRATION, encoding="utf-8")
        (self.dir / "timestamps.json").write_text(
            json.dumps(TS, ensure_ascii=False), encoding="utf-8"
        )
        write_dict(self.dir / "yomi.json", YOMI)
        write_assets(self.dir / "assets.json", ASSETS)
        (self.dir / "assets" / "a.png").write_bytes(b"\x89PNG....")
        (self.dir / "assets" / "b.webm").write_bytes(b"webm")
        (self.dir / "video.mp4").write_bytes(VIDEO)
        (self.dir / "voiceover.wav").write_bytes(b"RIFF....WAVE")
        self.httpd = review_server.make_server(self.dir, port=0)
        self.port = self.httpd.server_address[1]
        t = threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        t.start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            h["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=h)
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        return r.status, dict(r.getheaders()), raw

    def get_json(self, path="/api/state"):
        status, _, raw = self.req("GET", path)
        self.assertEqual(status, 200, raw[:200])
        return json.loads(raw)

    def post(self, path, body, auto=True):
        """画面がするように、現在の版(hash / old / text)を自動で添える。auto=False で生の送信。"""
        body = dict(body)
        if auto:
            self._fill(path, body)
        status, _, raw = self.req("POST", path, body)
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, {}

    def _fill(self, path, body):
        s = self.get_json()
        lines = s["script"]["lines"]
        idx = body.get("index")
        line = body.get("line")
        if (
            path == "/api/approve"
            and body.get("status") in ("承認", "要修正")
            and s["hashes"].get(body.get("item"))
        ):
            body.setdefault("hash", s["hashes"][body["item"]])
        elif (
            path == "/api/narration" and isinstance(idx, int) and 0 <= idx < len(lines)
        ):
            body.setdefault("hash", s["hashes"]["script"])
        elif path == "/api/note" and isinstance(line, int) and 1 <= line <= len(lines):
            body.setdefault("hash", s["hashes"]["script"])
        elif path in ("/api/yomi", "/api/yomi/delete"):
            cur = {y["surface"]: y["entry"] for y in s["yomi"]}
            body.setdefault("expected", cur.get(str(body.get("surface", "")).strip()))
        elif path == "/api/asset":
            cur = {a["ファイル"]: a["entry"] for a in s["assets"]}
            body.setdefault("expected", cur.get(body.get("file")))


class TestAccess(Base):
    """AC-17: localhost のみ、Host、パスの封じ込め、Range。"""

    def test_index_page_served(self):
        status, h, raw = self.req("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", h.get("Content-Type", ""))
        self.assertIn("<html", raw.decode("utf-8").lower())

    def test_ping_identifies_the_workspace_without_exposing_the_path(self):
        status, _, raw = self.req("GET", "/api/ping")
        self.assertEqual(status, 200)
        d = json.loads(raw)
        self.assertEqual(d["service"], review_server.SERVICE)
        self.assertEqual(d["workspace_id"], review_server.workspace_id(self.dir))
        self.assertNotIn(str(self.dir), raw.decode("utf-8"))  # 絶対パスは返さない
        status, _, _ = self.req("GET", "/api/ping", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)

    def test_foreign_host_is_forbidden(self):
        status, _, _ = self.req("GET", "/api/state", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)

    def test_bound_to_loopback(self):
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")

    def test_path_traversal_rejected(self):
        secret = self.dir.parent / "secret.txt"
        secret.write_text("秘密", encoding="utf-8")
        for p in [
            "/files/../secret.txt",
            "/files/%2e%2e/secret.txt",
            "/files//etc/passwd",
        ]:
            status, _, raw = self.req("GET", p)
            self.assertIn(status, (400, 403, 404), p)
            self.assertNotIn("秘密".encode("utf-8"), raw)

    def test_symlink_escape_rejected(self):
        secret = self.dir.parent / "secret.txt"
        secret.write_text("秘密", encoding="utf-8")
        try:
            os.symlink(secret, self.dir / "assets" / "link.txt")
        except (OSError, NotImplementedError):
            self.skipTest("シンボリックリンクを作れない")
        status, _, raw = self.req("GET", "/files/assets/link.txt")
        self.assertIn(status, (403, 404))
        self.assertNotIn("秘密".encode("utf-8"), raw)

    def test_file_served_whole(self):
        status, h, raw = self.req("GET", "/files/video.mp4")
        self.assertEqual(status, 200)
        self.assertEqual(raw, VIDEO)
        self.assertEqual(h.get("Accept-Ranges"), "bytes")

    def test_range_request_returns_206(self):
        status, h, raw = self.req(
            "GET", "/files/video.mp4", headers={"Range": "bytes=10-19"}
        )
        self.assertEqual(status, 206)
        self.assertEqual(raw, VIDEO[10:20])
        self.assertEqual(h.get("Content-Range"), f"bytes 10-19/{len(VIDEO)}")

    def test_open_ended_and_suffix_ranges(self):
        status, _, raw = self.req(
            "GET", "/files/video.mp4", headers={"Range": "bytes=2040-"}
        )
        self.assertEqual((status, raw), (206, VIDEO[2040:]))
        status, _, raw = self.req(
            "GET", "/files/video.mp4", headers={"Range": "bytes=-8"}
        )
        self.assertEqual((status, raw), (206, VIDEO[-8:]))

    def test_unsatisfiable_range(self):
        status, _, _ = self.req(
            "GET", "/files/video.mp4", headers={"Range": "bytes=99999-"}
        )
        self.assertEqual(status, 416)

    def test_missing_file_404(self):
        status, _, _ = self.req("GET", "/files/nothing.mp4")
        self.assertEqual(status, 404)


class TestState(Base):
    """AC-18: 状態を一度に返す。無いファイルは空で返す。"""

    def test_state_contents(self):
        s = self.get_json()
        self.assertEqual(Path(s["workdir"]), self.dir.resolve())
        lines = s["script"]["lines"]
        self.assertEqual([x["text"] for x in lines][0], "単眼 SLAM です。")
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[1]["start_s"], 4.0)
        self.assertEqual(lines[0]["reading"], "タンガン|スラム|デス")
        self.assertEqual(s["script"]["audio"], "voiceover.wav")
        ymap = {y["surface"]: y for y in s["yomi"]}
        self.assertEqual(ymap["SLAM"]["reading"], "スラ'ム")
        self.assertEqual(ymap["KL"]["status"], "候補")
        self.assertEqual(
            ymap["KL"]["entry"]["status"], "候補"
        )  # 画面が expected に使う値
        amap = {a["ファイル"]: a for a in s["assets"]}
        self.assertEqual(amap["assets/a.png"]["kind"], "image")
        self.assertEqual(amap["assets/b.webm"]["kind"], "video")
        self.assertTrue(amap["assets/a.png"]["url"].startswith("/files/assets/a.png"))
        self.assertEqual(s["video"], "video.mp4")
        self.assertEqual(s["notes"], [])
        self.assertEqual(s["approvals"], {})

    def test_state_without_optional_files(self):
        for name in [
            "timestamps.json",
            "yomi.json",
            "assets.json",
            "video.mp4",
            "voiceover.wav",
        ]:
            (self.dir / name).unlink()
        s = self.get_json()
        self.assertEqual(len(s["script"]["lines"]), 3)
        self.assertIsNone(s["script"]["lines"][0]["start_s"])
        self.assertIsNone(s["script"]["audio"])
        self.assertEqual(s["yomi"], [])
        self.assertEqual(s["assets"], [])
        self.assertIsNone(s["video"])

    def test_state_without_narration(self):
        (self.dir / "narration.txt").unlink()
        s = self.get_json()
        self.assertEqual(s["script"]["lines"][0]["text"], "単眼 SLAM です。")

    def test_broken_yomi_reports_error_not_crash(self):
        (self.dir / "yomi.json").write_text("{壊れ", encoding="utf-8")
        s = self.get_json()
        self.assertIn("yomi", s["errors"])


class TestApprovals(Base):
    """AC-19: 承認の記録、内容のハッシュ、古い承認。"""

    def test_approve_records_hash_and_comment(self):
        status, _ = self.post(
            "/api/approve", {"item": "script", "status": "承認", "comment": "OK"}
        )
        self.assertEqual(status, 200)
        rec = json.loads((self.dir / "approvals.json").read_text(encoding="utf-8"))[
            "entries"
        ]["script"]
        self.assertEqual(rec["status"], "承認")
        self.assertEqual(rec["comment"], "OK")
        self.assertEqual(rec["hash"], sha12(self.dir / "narration.txt"))
        self.assertTrue(rec["at"])
        st = self.get_json()["approvals"]["script"]
        self.assertFalse(st["stale"])

    def test_approval_becomes_stale_after_change(self):
        self.post("/api/approve", {"item": "script", "status": "承認", "comment": ""})
        (self.dir / "narration.txt").write_text(NARRATION + "\n", encoding="utf-8")
        self.assertTrue(self.get_json()["approvals"]["script"]["stale"])

    def test_needs_fix_is_recorded(self):
        self.post(
            "/api/approve", {"item": "yomi", "status": "要修正", "comment": "KL を直す"}
        )
        a = self.get_json()["approvals"]["yomi"]
        self.assertEqual((a["status"], a["comment"]), ("要修正", "KL を直す"))

    def test_clear_with_unapproved(self):
        self.post("/api/approve", {"item": "assets", "status": "承認", "comment": ""})
        status, _ = self.post(
            "/api/approve", {"item": "assets", "status": "未承認", "comment": ""}
        )
        self.assertEqual(status, 200)
        self.assertNotIn("assets", self.get_json()["approvals"])

    def test_invalid_item_or_status_writes_nothing(self):
        for body in [
            {"item": "bogus", "status": "承認", "comment": ""},
            {"item": "script", "status": "たぶん", "comment": ""},
            {"status": "承認"},
        ]:
            status, _ = self.post("/api/approve", body)
            self.assertEqual(status, 400, body)
        self.assertFalse((self.dir / "approvals.json").exists())

    def test_approving_missing_file_is_rejected(self):
        status, _ = self.post(
            "/api/approve", {"item": "plan", "status": "承認", "comment": ""}
        )
        self.assertEqual(status, 400)  # brief.md が無い
        self.assertFalse((self.dir / "approvals.json").exists())

    def test_other_items_are_kept(self):
        self.post("/api/approve", {"item": "script", "status": "承認", "comment": ""})
        self.post("/api/approve", {"item": "video", "status": "承認", "comment": ""})
        d = json.loads((self.dir / "approvals.json").read_text(encoding="utf-8"))
        self.assertEqual(set(d["entries"]), {"script", "video"})

    def test_an_approval_written_meanwhile_by_another_writer_is_kept(self):
        review_server.Workspace(self.dir).approvals_store().update(
            "assets", None, {"status": "承認", "comment": "", "hash": "x", "at": "t"}
        )
        self.post("/api/approve", {"item": "script", "status": "承認", "comment": ""})
        d = json.loads((self.dir / "approvals.json").read_text(encoding="utf-8"))
        self.assertEqual(set(d["entries"]), {"assets", "script"})


class TestNarrationEdit(Base):
    """AC-20: 行の本文だけを置き換える。"""

    def test_replaces_only_that_line(self):
        status, body = self.post(
            "/api/narration", {"index": 1, "text": "次に、地図の話です。"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(body.get("needs_resynthesis"))
        text = (self.dir / "narration.txt").read_text(encoding="utf-8")
        self.assertEqual(
            text,
            NARRATION.replace("- 次に地図です。", "- 次に、地図の話です。"),
        )

    def test_backup_keeps_previous_content(self):
        self.post("/api/narration", {"index": 0, "text": "変更。"})
        self.assertEqual(
            (self.dir / "narration.txt.bak").read_text(encoding="utf-8"), NARRATION
        )

    def test_invalid_requests_change_nothing(self):
        for body in [
            {"index": 9, "text": "あ"},
            {"index": -1, "text": "あ"},
            {"index": 0, "text": "  "},
            {"index": 0, "text": "二行\nにわたる"},
            {"index": "x", "text": "あ"},
        ]:
            status, _ = self.post("/api/narration", body)
            self.assertEqual(status, 400, body)
        self.assertEqual(
            (self.dir / "narration.txt").read_text(encoding="utf-8"), NARRATION
        )
        self.assertFalse((self.dir / "narration.txt.bak").exists())

    def test_state_reflects_edit_and_marks_stale_timing(self):
        self.post("/api/narration", {"index": 2, "text": "最後に、結果です。"})
        s = self.get_json()["script"]
        self.assertEqual(s["lines"][2]["text"], "最後に、結果です。")
        self.assertTrue(s["stale"])  # timestamps.json は古い


class TestYomiEdit(Base):
    """AC-21: 動画ごとの辞書(yomi.json)だけを編集する。更新は窓口の比較交換(見た値 expected)で束縛する。"""

    def entries(self):
        return yomi.read_entries(self.dir / "yomi.json")

    def good(self, surface="AR", **kw):
        return {
            "surface": surface,
            "reading": "エ'ーアール",
            "status": "確認済み",
            "note": "",
            **kw,
        }

    def test_add_new_word(self):
        status, _ = self.post(
            "/api/yomi",
            {
                "surface": "RANSAC",
                "reading": "ラ'ンサック",
                "status": "確認済み",
                "note": "x",
            },
        )
        self.assertEqual(status, 200)
        e = self.entries()["RANSAC"]
        self.assertEqual(
            (e["pron"], e["accent"], e["status"], e["note"]),
            ("ランサック", 1, "確認済み", "x"),
        )
        self.assertIn("SLAM", self.entries())  # 既存は残る

    def test_update_and_confirm_candidate(self):
        self.post(
            "/api/yomi",
            {"surface": "KL", "reading": "ケ'ーエル", "status": "確認済み", "note": ""},
        )
        e = self.entries()["KL"]
        self.assertEqual(e["status"], "確認済み")
        self.assertEqual(e["accent"], 1)

    def test_invalid_reading_or_status_rejected(self):
        before = (self.dir / "yomi.json").read_bytes()
        for body in [
            {"surface": "X", "reading": "abc", "status": "確認済み", "note": ""},
            {"surface": "X", "reading": "エックス", "status": "たぶん", "note": ""},
            {"surface": "", "reading": "エックス", "status": "確認済み", "note": ""},
            {
                "surface": "A\nB",
                "reading": "エックス",
                "status": "確認済み",
                "note": "",
            },
        ]:
            status, _ = self.post("/api/yomi", body)
            self.assertEqual(status, 400, body)
        self.assertEqual((self.dir / "yomi.json").read_bytes(), before)

    def test_delete(self):
        status, _ = self.post("/api/yomi/delete", {"surface": "KL"})
        self.assertEqual(status, 200)
        self.assertNotIn("KL", self.entries())
        status, _ = self.post("/api/yomi/delete", {"surface": "無い語"})
        self.assertEqual(status, 400)

    def test_creates_file_when_missing(self):
        (self.dir / "yomi.json").unlink()
        status, _ = self.post("/api/yomi", self.good())
        self.assertEqual(status, 200)
        self.assertIn("AR", self.entries())

    def test_does_not_touch_other_layers(self):
        home = Path(self._tmp.name) / "home"
        home.mkdir()
        (home / "yomi.json").write_bytes(b"x")
        old = os.environ.get("CONF_VIDEO_HOME")
        os.environ["CONF_VIDEO_HOME"] = str(home)
        try:
            self.post("/api/yomi", self.good())
        finally:
            if old is None:
                del os.environ["CONF_VIDEO_HOME"]
            else:
                os.environ["CONF_VIDEO_HOME"] = old
        self.assertEqual((home / "yomi.json").read_bytes(), b"x")

    # ── 見た値への束縛(比較交換) ──

    def seen(self, surface):
        return {y["surface"]: y["entry"] for y in self.get_json()["yomi"]}.get(surface)

    def test_stale_expected_is_conflict_and_nothing_is_written(self):
        seen_kl = self.seen("KL")
        # 別の書き手(CLI など)が先に KL を直す
        store = yomi.dict_store(self.dir / "yomi.json")
        store.update(
            "KL", seen_kl, yomi.make_entry("ケ'ーエル", "確認済み", "先に直した")
        )
        before = (self.dir / "yomi.json").read_bytes()
        body = self.good("KL", expected=seen_kl)
        status, resp = self.post("/api/yomi", body, auto=False)
        self.assertEqual(status, 409)
        self.assertIn("再読み込み", resp["error"])
        status, _ = self.post(
            "/api/yomi/delete", {"surface": "KL", "expected": seen_kl}, auto=False
        )
        self.assertEqual(status, 409)
        self.assertEqual((self.dir / "yomi.json").read_bytes(), before)

    def test_change_to_another_word_does_not_conflict(self):
        seen_kl = self.seen("KL")
        yomi.dict_store(self.dir / "yomi.json").update(
            "SLAM", self.seen("SLAM"), yomi.make_entry("ス'ラム", "確認済み", "別の語")
        )
        status, _ = self.post(
            "/api/yomi", self.good("KL", expected=seen_kl), auto=False
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            self.entries()["SLAM"]["note"], "別の語"
        )  # 他の語の更新は消えない

    def test_adding_a_word_that_appeared_meanwhile_is_conflict(self):
        yomi.dict_store(self.dir / "yomi.json").update(
            "AR", None, yomi.make_entry("エーアール")
        )
        status, _ = self.post("/api/yomi", self.good("AR", expected=None), auto=False)
        self.assertEqual(status, 409)
        self.assertEqual(self.entries()["AR"]["accent"], 0)

    def test_expected_is_required_and_must_be_an_object_or_null(self):
        before = (self.dir / "yomi.json").read_bytes()
        for path, body in [
            ("/api/yomi", self.good("KL")),
            ("/api/yomi/delete", {"surface": "KL"}),
            ("/api/yomi", self.good("KL", expected="x")),
            ("/api/yomi", self.good("KL", expected=[1])),
        ]:
            status, _ = self.post(path, body, auto=False)
            self.assertEqual(status, 400, (path, body))
        self.assertEqual((self.dir / "yomi.json").read_bytes(), before)

    def test_corrupt_dictionary_is_refused_and_untouched(self):
        (self.dir / "yomi.json").write_text("{壊れ", encoding="utf-8")
        status, resp = self.post("/api/yomi", self.good(expected=None), auto=False)
        self.assertEqual(status, 400)
        self.assertIn("yomi.json", resp["error"])
        self.assertEqual((self.dir / "yomi.json").read_text(encoding="utf-8"), "{壊れ")

    def test_replace_failure_returns_a_cause_hint_and_keeps_the_file(self):
        from unittest import mock

        before = (self.dir / "yomi.json").read_bytes()
        with mock.patch("state_store.REPLACE_RETRY_DELAY", 0.001):
            with mock.patch(
                "state_store.os.replace", side_effect=PermissionError(13, "denied")
            ):
                status, resp = self.post("/api/yomi", self.good("KL"))
        self.assertEqual(status, 500)
        self.assertIn("他のアプリ", resp["error"])
        self.assertEqual((self.dir / "yomi.json").read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.dir.glob(".yomi.json*")), [])


class TestAssetsEdit(Base):
    """AC-22: 台帳(assets.json)の状態とメモだけを書く。更新は窓口の比較交換(見た値 expected)で束縛する。"""

    def rows(self):
        return {r["ファイル"]: r for r in assets_ledger.load(self.dir / "assets.json")}

    def seen(self, name):
        return {a["ファイル"]: a["entry"] for a in self.get_json()["assets"]}.get(name)

    def test_status_and_note_updated(self):
        status, _ = self.post(
            "/api/asset",
            {"file": "assets/b.webm", "status": "出典表示", "note": "10 秒だけ"},
        )
        self.assertEqual(status, 200)
        r = self.rows()
        self.assertEqual(r["assets/b.webm"]["状態"], "出典表示")
        self.assertEqual(r["assets/b.webm"]["メモ"], "10 秒だけ")
        self.assertEqual(r["assets/b.webm"]["作者"], "花子")  # 他の項目は不変
        self.assertEqual(r["assets/a.png"]["状態"], "確認済み")  # 他の素材は不変

    def test_citation_fields_are_kept_and_shown(self):
        entry = {
            **ASSETS["assets/a.png"],
            "種別": "論文の図",
            "書誌": "X et al., 2026",
            "位置": "Fig. 2",
        }
        write_assets(self.dir / "assets.json", {"assets/a.png": entry})
        a = self.get_json()["assets"][0]
        self.assertEqual(a["credit"], "X et al., 2026, Fig. 2")
        self.post(
            "/api/asset", {"file": "assets/a.png", "status": "出典表示", "note": "m"}
        )
        row = self.rows()["assets/a.png"]
        self.assertEqual(
            (row["種別"], row["書誌"], row["位置"]),
            ("論文の図", "X et al., 2026", "Fig. 2"),
        )

    def test_note_with_newline_round_trips(self):
        status, _ = self.post(
            "/api/asset",
            {"file": "assets/a.png", "status": "仮", "note": "1 行目\n2 行目"},
        )
        self.assertEqual(status, 200)
        r = self.rows()
        self.assertEqual(r["assets/a.png"]["メモ"], "1 行目\n2 行目")
        self.assertIn("assets/b.webm", r)

    def test_invalid_status_or_file(self):
        before = (self.dir / "assets.json").read_bytes()
        for body in [
            {"file": "assets/b.webm", "status": "たぶん", "note": ""},
            {"file": "assets/none.png", "status": "確認済み", "note": ""},
            {"file": "", "status": "確認済み", "note": ""},
        ]:
            status, _ = self.post("/api/asset", body)
            self.assertEqual(status, 400, body)
        self.assertEqual((self.dir / "assets.json").read_bytes(), before)

    def test_stale_expected_is_conflict_and_nothing_is_written(self):
        seen = self.seen("assets/a.png")
        store = assets_ledger.store(self.dir / "assets.json")
        store.update("assets/a.png", seen, {**seen, "メモ": "先に直した"})
        before = (self.dir / "assets.json").read_bytes()
        status, resp = self.post(
            "/api/asset",
            {"file": "assets/a.png", "status": "仮", "note": "", "expected": seen},
            auto=False,
        )
        self.assertEqual(status, 409)
        self.assertIn("再読み込み", resp["error"])
        self.assertEqual((self.dir / "assets.json").read_bytes(), before)

    def test_change_to_another_asset_does_not_conflict(self):
        seen = self.seen("assets/a.png")
        other = self.seen("assets/b.webm")
        assets_ledger.store(self.dir / "assets.json").update(
            "assets/b.webm", other, {**other, "メモ": "別の素材"}
        )
        status, _ = self.post(
            "/api/asset",
            {"file": "assets/a.png", "status": "仮", "note": "x", "expected": seen},
            auto=False,
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            self.rows()["assets/b.webm"]["メモ"], "別の素材"
        )  # 他の素材の更新は消えない

    def test_expected_is_required(self):
        before = (self.dir / "assets.json").read_bytes()
        status, _ = self.post(
            "/api/asset",
            {"file": "assets/a.png", "status": "仮", "note": ""},
            auto=False,
        )
        self.assertEqual(status, 400)
        self.assertEqual((self.dir / "assets.json").read_bytes(), before)

    def test_corrupt_ledger_is_refused_and_untouched(self):
        seen = self.seen("assets/a.png")
        (self.dir / "assets.json").write_text("{壊れ", encoding="utf-8")
        status, resp = self.post(
            "/api/asset",
            {"file": "assets/a.png", "status": "仮", "note": "", "expected": seen},
            auto=False,
        )
        self.assertEqual(status, 400)
        self.assertEqual(
            (self.dir / "assets.json").read_text(encoding="utf-8"), "{壊れ"
        )

    def test_replace_failure_returns_a_cause_hint_and_keeps_the_file(self):
        from unittest import mock

        before = (self.dir / "assets.json").read_bytes()
        with mock.patch("state_store.REPLACE_RETRY_DELAY", 0.001):
            with mock.patch(
                "state_store.os.replace", side_effect=PermissionError(13, "denied")
            ):
                status, resp = self.post(
                    "/api/asset", {"file": "assets/a.png", "status": "仮", "note": ""}
                )
        self.assertEqual(status, 500)
        self.assertIn("他のアプリ", resp["error"])
        self.assertEqual((self.dir / "assets.json").read_bytes(), before)


class TestNotes(Base):
    """AC-23: 聞き取りの指摘は notes.json に書く(窓口経由)。review.csv は書き出し専用。"""

    def notes_json(self):
        return json.loads((self.dir / "notes.json").read_text(encoding="utf-8"))[
            "entries"
        ]

    def test_note_is_saved_to_notes_json_with_the_current_text(self):
        status, _ = self.post("/api/note", {"line": 2, "note": "地図の読みが違う"})
        self.assertEqual(status, 200)
        e = self.notes_json()["2"]
        self.assertEqual((e["note"], e["text"]), ("地図の読みが違う", "次に地図です。"))
        self.assertTrue(e["at"])
        self.assertEqual(
            self.get_json()["notes"],
            [
                {
                    "line": 2,
                    "start": "0:04",
                    "text": "次に地図です。",
                    "note": "地図の読みが違う",
                    "stale": False,
                }
            ],
        )
        self.assertFalse(
            (self.dir / "review.csv").exists()
        )  # サーバは review.csv を書かない

    def test_review_sheet_notes_reads_it(self):
        import review_sheet

        self.post("/api/note", {"line": 1, "note": "速い"})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = review_sheet.main(["--workdir", str(self.dir), "--notes"])
        self.assertEqual(rc, 0)
        self.assertIn("速い", buf.getvalue())

    def test_clearing_a_note_removes_it(self):
        self.post("/api/note", {"line": 1, "note": "速い"})
        self.post("/api/note", {"line": 1, "note": ""})
        self.assertEqual(self.get_json()["notes"], [])
        self.assertEqual(self.notes_json(), {})

    def test_existing_notes_are_kept(self):
        self.post("/api/note", {"line": 1, "note": "A"})
        self.post("/api/note", {"line": 3, "note": "B"})
        self.assertEqual([n["note"] for n in self.get_json()["notes"]], ["A", "B"])

    def test_note_written_meanwhile_by_another_writer_is_kept(self):
        import review_sheet

        review_sheet.notes_store(self.dir).update(
            "3", None, {"note": "先の指摘", "text": "最後に結果です。", "at": "t"}
        )
        self.post("/api/note", {"line": 1, "note": "A"})
        self.assertEqual(sorted(self.notes_json()), ["1", "3"])

    def test_invalid_line_rejected(self):
        for body in [
            {"line": 0, "note": "x"},
            {"line": 99, "note": "x"},
            {"note": "x"},
        ]:
            status, _ = self.post("/api/note", body)
            self.assertEqual(status, 400, body)
        self.assertFalse((self.dir / "notes.json").exists())

    def test_note_does_not_need_timestamps(self):
        (self.dir / "timestamps.json").unlink()
        status, _ = self.post("/api/note", {"line": 1, "note": "x"})
        self.assertEqual(status, 200)
        self.assertEqual(self.get_json()["notes"][0]["start"], "")

    def test_note_becomes_stale_when_the_line_text_changes(self):
        self.post("/api/note", {"line": 2, "note": "地図の読み"})
        self.post("/api/narration", {"index": 1, "text": "次に、全く別の話です。"})
        n = self.get_json()["notes"][0]
        self.assertTrue(n["stale"])
        self.assertEqual(
            n["text"], "次に地図です。"
        )  # 指摘したときの本文を保つ(別の行へ付け直さない)

    def test_corrupt_notes_json_is_reported_and_refused(self):
        (self.dir / "notes.json").write_text("{壊れ", encoding="utf-8")
        s = self.get_json()
        self.assertIn("notes", s["errors"])
        self.assertEqual(s["notes"], [])
        status, _ = self.post("/api/note", {"line": 1, "note": "x"})
        self.assertEqual(status, 400)
        self.assertEqual((self.dir / "notes.json").read_text(encoding="utf-8"), "{壊れ")


class TestSummary(Base):
    """AC-24: サーバなしで承認の状態と指摘件数を出す。"""

    def run_summary(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = review_server.main(["--workdir", str(self.dir), "--summary"])
        return rc, buf.getvalue()

    def test_unapproved_by_default(self):
        rc, out = self.run_summary()
        self.assertEqual(rc, 0)
        self.assertIn("台本: 未承認", out)
        self.assertIn("指摘 0 件", out)

    def test_approved_stale_and_needs_fix(self):
        self.post("/api/approve", {"item": "script", "status": "承認", "comment": ""})
        self.post("/api/approve", {"item": "yomi", "status": "要修正", "comment": "KL"})
        self.post("/api/note", {"line": 1, "note": "x"})
        (self.dir / "narration.txt").write_text(NARRATION + "\n", encoding="utf-8")
        rc, out = self.run_summary()
        self.assertIn("台本: 古い", out)
        self.assertIn("読み: 要修正(KL)", out)
        self.assertIn("指摘 1 件", out)

    def test_approved(self):
        self.post("/api/approve", {"item": "assets", "status": "承認", "comment": ""})
        _, out = self.run_summary()
        self.assertIn("素材: 承認", out)

    def test_missing_workdir(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = review_server.main(["--workdir", str(self.dir / "none"), "--summary"])
        self.assertEqual(rc, 2)


class TestRobustness(Base):
    """R1-1/3/4: 壊れた正本・異常な入力でも、記録を壊さず、状態を返し続ける。"""

    def write_approvals(self, text: str):
        (self.dir / "approvals.json").write_text(text, encoding="utf-8")

    def raw_post(self, headers: dict, body: bytes = b""):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest("POST", "/api/approve")
        for k, v in {"Content-Type": "application/json", **headers}.items():
            conn.putheader(k, v)
        conn.endheaders(body)
        r = conn.getresponse()
        status, raw = r.status, r.read()
        conn.close()
        return status, raw

    def test_corrupt_approvals_is_not_overwritten(self):
        for bad in [
            "{ここは壊れている",
            "[1, 2]",
            '{"script": {"hash": "x"}}',
            '{"bogus": {}}',
        ]:
            self.write_approvals(bad)
            status, body = self.post(
                "/api/approve", {"item": "script", "status": "承認", "comment": ""}
            )
            self.assertEqual(status, 409, bad)
            self.assertIn("approvals.json", body.get("error", ""))
            self.assertEqual(
                (self.dir / "approvals.json").read_text(encoding="utf-8"), bad
            )

    def test_corrupt_approvals_state_reports_error(self):
        self.write_approvals("[1, 2]")
        s = self.get_json()
        self.assertIn("approvals", s["errors"])
        self.assertEqual(s["approvals"], {})
        self.assertEqual(len(s["script"]["lines"]), 3)  # 他の部分は返る

    def test_corrupt_approvals_summary_stops(self):
        self.write_approvals("{壊れ")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = review_server.main(["--workdir", str(self.dir), "--summary"])
        self.assertEqual(rc, 1)
        self.assertIn("approvals.json が壊れている", buf.getvalue())

    def test_timestamps_with_wrong_type(self):
        for bad in ["[1, 2]", '{"subtitles": 5}', '{"subtitles": [1]}', "{壊れ"]:
            (self.dir / "timestamps.json").write_text(bad, encoding="utf-8")
            s = self.get_json()
            self.assertIn("timestamps", s["errors"], bad)
            self.assertEqual(s["script"]["lines"][0]["text"], "単眼 SLAM です。", bad)

    def test_unreadable_notes_json(self):
        (self.dir / "notes.json").write_bytes(b"\xff\xfe\x00bad")
        s = self.get_json()
        self.assertIn("notes", s["errors"])
        self.assertEqual(s["notes"], [])
        before = (self.dir / "notes.json").read_bytes()
        status, _ = self.post("/api/note", {"line": 1, "note": "x"})
        self.assertEqual(status, 400)
        self.assertEqual((self.dir / "notes.json").read_bytes(), before)

    def test_undecodable_narration(self):
        (self.dir / "narration.txt").write_bytes(b"subtitles:\n- \xff\xfe\n")
        s = self.get_json()
        self.assertIn("script", s["errors"])
        status, _ = self.post("/api/narration", {"index": 0, "text": "あ"})
        self.assertEqual(status, 400)

    def test_unexpected_exception_returns_json_500(self):
        def boom():
            raise RuntimeError("秘密のパス /home/x")

        self.httpd.workspace.state = boom
        with contextlib.redirect_stderr(io.StringIO()) as err:
            status, _, raw = self.req("GET", "/api/state")
        self.assertIn("RuntimeError", err.getvalue())  # 詳細はサーバのログに残る
        self.assertEqual(status, 500)
        self.assertNotIn("/home/x".encode("utf-8"), raw)  # 内部の詳細を返さない
        self.assertIn("error", json.loads(raw))

    def test_negative_or_bad_content_length(self):
        for value in ["-5", "abc", "1.5"]:
            status, _ = self.raw_post({"Content-Length": value})
            self.assertEqual(status, 400, value)

    def test_oversized_body_rejected_and_connection_closed(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest("POST", "/api/approve")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(review_server.MAX_BODY + 1))
        conn.endheaders()
        r = conn.getresponse()
        r.read()
        self.assertEqual(r.status, 413)
        self.assertEqual(r.getheader("Connection"), "close")
        conn.close()

    def test_missing_content_length_is_bad_request(self):
        status, _ = self.raw_post({})
        self.assertEqual(status, 400)


class TestRobustness2(Base):
    """R2-2: 入れ子の型、--summary の終了コード。"""

    def test_nested_phrase_types(self):
        for bad in [
            '{"subtitles":[{"text":"あ","start_s":0,"duration_s":1,"phrases":[1]}]}',
            '{"subtitles":[{"text":"あ","start_s":0,"duration_s":1,"phrases":[{"text":5}]}]}',
            '{"subtitles":[{"text":"あ","start_s":0,"duration_s":1,"phrases":[{}]}]}',
        ]:
            (self.dir / "timestamps.json").write_text(bad, encoding="utf-8")
            s = self.get_json()
            self.assertIn("timestamps", s["errors"], bad)

    def test_summary_fails_when_notes_json_unreadable(self):
        (self.dir / "notes.json").write_bytes(b"\xff\xfe\x00bad")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = review_server.main(["--workdir", str(self.dir), "--summary"])
        self.assertEqual(rc, 1)
        self.assertIn("notes.json", buf.getvalue())


class TestBinding(Base):
    """R1-2: 承認・編集は、利用者が見た版に束縛する(変わっていれば 409)。"""

    def test_state_has_hashes(self):
        s = self.get_json()
        self.assertEqual(s["hashes"]["script"], sha12(self.dir / "narration.txt"))
        self.assertEqual(s["hashes"]["video"], sha12(self.dir / "video.mp4"))
        self.assertIsNone(s["hashes"]["plan"])  # brief.md が無い

    def test_approve_requires_hash(self):
        status, _ = self.post(
            "/api/approve",
            {"item": "script", "status": "承認", "comment": ""},
            auto=False,
        )
        self.assertEqual(status, 400)
        self.assertFalse((self.dir / "approvals.json").exists())

    def test_approve_with_stale_hash_is_conflict(self):
        seen = self.get_json()["hashes"]["script"]
        (self.dir / "narration.txt").write_text(NARRATION + "\n", encoding="utf-8")
        status, body = self.post(
            "/api/approve",
            {"item": "script", "status": "承認", "comment": "", "hash": seen},
            auto=False,
        )
        self.assertEqual(status, 409)
        self.assertIn("再読み込み", body["error"])
        self.assertFalse((self.dir / "approvals.json").exists())

    def test_clearing_needs_no_hash(self):
        self.post("/api/approve", {"item": "script", "status": "承認", "comment": ""})
        status, _ = self.post(
            "/api/approve",
            {"item": "script", "status": "未承認", "comment": ""},
            auto=False,
        )
        self.assertEqual(status, 200)

    def test_narration_edit_requires_matching_hash(self):
        before = (self.dir / "narration.txt").read_text(encoding="utf-8")
        for body in [
            {"index": 1, "text": "新しい。"},  # hash 無し
            {"index": 1, "text": "新しい。", "hash": "000000000000"},  # 不一致
        ]:
            status, _ = self.post("/api/narration", body, auto=False)
            self.assertIn(status, (400, 409), body)
        self.assertEqual(
            (self.dir / "narration.txt").read_text(encoding="utf-8"), before
        )
        seen = self.get_json()["hashes"]["script"]
        status, _ = self.post(
            "/api/narration",
            {"index": 1, "text": "新しい。", "hash": seen},
            auto=False,
        )
        self.assertEqual(status, 200)

    def test_narration_edit_after_external_change_is_conflict(self):
        seen = self.get_json()["hashes"]["script"]
        (self.dir / "narration.txt").write_text(
            NARRATION.replace("- 次に地図です。", "- 先頭に足した。\n- 次に地図です。"),
            encoding="utf-8",
        )
        status, _ = self.post(
            "/api/narration", {"index": 1, "text": "X", "hash": seen}, auto=False
        )
        self.assertEqual(status, 409)  # 行がずれている

    def test_edit_after_same_text_line_inserted_is_conflict(self):
        """R3-5: 同じ本文の行が前に挿入されても、別の行を直さない。"""
        seen = self.get_json()["hashes"]["script"]
        (self.dir / "narration.txt").write_text(
            NARRATION.replace("- 次に地図です。", "- 次に地図です。\n- 次に地図です。"),
            encoding="utf-8",
        )
        status, _ = self.post(
            "/api/narration", {"index": 1, "text": "X", "hash": seen}, auto=False
        )
        self.assertEqual(status, 409)

    def test_note_with_mismatched_hash_is_conflict(self):
        status, _ = self.post(
            "/api/note", {"line": 1, "note": "x", "hash": "000000000000"}, auto=False
        )
        self.assertEqual(status, 409)
        self.assertFalse((self.dir / "review.csv").exists())

    def test_note_after_same_text_line_inserted_is_conflict(self):  # R4-4
        seen = self.get_json()["hashes"]["script"]
        (self.dir / "narration.txt").write_text(
            NARRATION.replace("- 次に地図です。", "- 次に地図です。\n- 次に地図です。"),
            encoding="utf-8",
        )
        status, _ = self.post(
            "/api/note", {"line": 3, "note": "x", "hash": seen}, auto=False
        )
        self.assertEqual(status, 409)
        self.assertFalse((self.dir / "review.csv").exists())

    def test_note_requires_hash(self):  # R3-6 / R4-4
        status, _ = self.post("/api/note", {"line": 1, "note": "x"}, auto=False)
        self.assertEqual(status, 400)
        self.assertFalse((self.dir / "review.csv").exists())

    def test_hash_is_taken_before_reading(self):
        """R3-7: 表示を読んでいる最中に外部で変わっても、未確認の内容を承認できない
        (ハッシュは読む前に取る。変えられたら承認は 409 になる)。"""
        ws = self.httpd.workspace
        original = ws._script
        before = sha12(self.dir / "narration.txt")

        def racing(errors):
            (self.dir / "narration.txt").write_text(NARRATION + "\n", encoding="utf-8")
            return original(errors)

        ws._script = racing
        s = self.get_json()
        ws._script = original
        self.assertEqual(s["hashes"]["script"], before)  # 読む前のハッシュ
        status, _ = self.post(
            "/api/approve",
            {
                "item": "script",
                "status": "承認",
                "comment": "",
                "hash": s["hashes"]["script"],
            },
            auto=False,
        )
        self.assertEqual(status, 409)


class TestGate(Base):
    """R1-5: `--summary --require` が終了コードでゲートを判定する。"""

    def gate(self, *items):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = review_server.main(
                ["--workdir", str(self.dir), "--summary", "--require", ",".join(items)]
            )
        return rc, buf.getvalue()

    def approve(self, *items):
        for it in items:
            status, _ = self.post(
                "/api/approve", {"item": it, "status": "承認", "comment": ""}
            )
            self.assertEqual(status, 200, it)

    def test_passes_when_all_required_are_approved(self):
        self.approve("script", "yomi")
        rc, out = self.gate("script", "yomi")
        self.assertEqual(rc, 0)
        self.assertIn("ゲート: 通過", out)

    def test_stops_on_unapproved_with_reasons(self):
        self.approve("script")
        rc, out = self.gate("script", "yomi")
        self.assertEqual(rc, 1)
        self.assertIn("ゲート: 停止", out)
        self.assertIn("読み: 未承認", out)

    def test_stops_on_stale(self):
        self.approve("script")
        (self.dir / "narration.txt").write_text(NARRATION + "\n", encoding="utf-8")
        rc, out = self.gate("script")
        self.assertEqual(rc, 1)
        self.assertIn("古い", out)

    def test_stops_on_needs_fix(self):
        self.post("/api/approve", {"item": "yomi", "status": "要修正", "comment": "KL"})
        rc, out = self.gate("yomi")
        self.assertEqual(rc, 1)
        self.assertIn("要修正", out)

    def test_stops_when_required_source_is_unreadable(self):
        (self.dir / "yomi.json").write_text("{壊れ", encoding="utf-8")
        self.approve("yomi")  # 壊れたファイルでもハッシュは一致している
        rc, out = self.gate("yomi")
        self.assertEqual(rc, 1)
        self.assertIn("読めない", out)

    def test_stops_when_approvals_json_is_corrupt(self):
        (self.dir / "approvals.json").write_text("{壊れ", encoding="utf-8")
        rc, _ = self.gate("script")
        self.assertEqual(rc, 1)

    def test_invalid_arguments(self):
        rc, _ = self.gate("bogus")
        self.assertEqual(rc, 2)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = review_server.main(["--workdir", str(self.dir), "--require", "script"])
        self.assertEqual(rc, 2)  # --summary が無い


class TestFileModes(Base):
    """保存で、既存ファイルの権限を変えない(一時ファイル経由の置き換で 0600 にならない)。"""

    def mode(self, name):
        return (self.dir / name).stat().st_mode & 0o777

    def test_modes_preserved_after_saves(self):
        for name in ["narration.txt", "yomi.json", "assets.json", "timestamps.json"]:
            os.chmod(self.dir / name, 0o664)
        self.post("/api/note", {"line": 1, "note": "x"})
        os.chmod(self.dir / "notes.json", 0o664)
        self.post("/api/note", {"line": 2, "note": "y"})
        self.post("/api/narration", {"index": 0, "text": "変更。"})
        self.post(
            "/api/yomi",
            {
                "surface": "AR",
                "reading": "エ'ーアール",
                "status": "確認済み",
                "note": "",
            },
        )
        self.post("/api/asset", {"file": "assets/a.png", "status": "仮", "note": ""})
        for name in ["narration.txt", "yomi.json", "assets.json", "notes.json"]:
            self.assertEqual(self.mode(name), 0o664, name)

    def test_new_files_are_not_world_writable(self):
        self.post("/api/approve", {"item": "script", "status": "承認", "comment": ""})
        self.assertEqual(self.mode("approvals.json") & 0o022, 0)


class TestStartup(unittest.TestCase):
    """起動: URL は作業フォルダのパスから決まる(トークン無し)。使用中なら ping で同じフォルダか確かめ、
    同じなら URL を案内して終わり、違えば --port を求めて終わる(自動では繰り上げない)。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "work"
        self.dir.mkdir()
        (self.dir / "narration.txt").write_text(NARRATION, encoding="utf-8")
        self.procs = []
        self.addCleanup(self._kill)

    def _kill(self):
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
            if p.stdout:
                p.stdout.close()

    def spawn(self, *extra, workdir=None):
        p = subprocess.Popen(
            [
                sys.executable,
                "-u",
                str(HERE.parent / "scripts" / "review_server.py"),
                "--workdir",
                str(workdir or self.dir),
                "--no-open",
                *extra,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.procs.append(p)
        return p

    @staticmethod
    def read_until_ready(p):
        url, out = None, []
        for line in p.stdout:
            out.append(line)
            if line.startswith("REVIEW_READY "):
                url = line.split(None, 1)[1].strip()
                break
        return url, "".join(out)

    def start(self, *extra, workdir=None):
        p = self.spawn(*extra, workdir=workdir)
        url, out = self.read_until_ready(p)
        return p, url, out

    def finish(self, p, timeout=15):
        out = p.stdout.read()
        p.wait(timeout)
        return p.returncode, out

    def free_port(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def fetch(self, url, path="/api/state"):
        u = urlparse(url)
        conn = http.client.HTTPConnection(u.hostname, u.port, timeout=5)
        conn.request("GET", path)
        r = conn.getresponse()
        body = r.read()
        conn.close()
        return r.status, body

    def test_default_port_is_stable_and_in_range(self):
        port = review_server.default_port(self.dir)
        self.assertTrue(8700 <= port <= 8799)
        self.assertEqual(port, review_server.default_port(str(self.dir)))
        self.assertEqual(port, review_server.default_port(str(self.dir) + os.sep))
        rel = os.path.relpath(self.dir)
        self.assertEqual(port, review_server.default_port(rel))
        others = {
            review_server.default_port(Path(self._tmp.name) / f"w{i}")
            for i in range(12)
        }
        self.assertGreater(len(others), 3)  # フォルダごとに散らばる

    def test_start_prints_a_stable_url_without_token_and_leaves_no_files(self):
        port = self.free_port()
        p, url, out = self.start("--port", str(port))
        self.assertEqual(url, f"http://127.0.0.1:{port}/", out)
        self.assertNotIn("t=", url)
        self.assertIn(str(self.dir.resolve()), out)  # 作業フォルダも出す
        self.assertEqual(self.fetch(url)[0], 200)
        leftovers = [x.name for x in self.dir.iterdir() if x.name.startswith(".review")]
        self.assertEqual(leftovers, [])  # トークン・URL・ロックのファイルは作らない

    def test_default_port_is_used_when_not_specified(self):
        port = review_server.default_port(self.dir)
        p, url, out = self.start()
        if url is None:  # このポートを他が使っている環境
            self.skipTest(out)
        self.assertEqual(url, f"http://127.0.0.1:{port}/", out)

    def test_port_zero_picks_a_free_port(self):
        p, url, out = self.start("--port", "0")
        self.assertIsNotNone(url, out)

    def test_second_start_for_the_same_folder_reuses_the_running_server(self):
        port = self.free_port()
        p1, url1, _ = self.start("--port", str(port))
        p2, url2, out2 = self.start("--port", str(port))
        self.assertEqual(url2, url1)
        self.assertIn("既に起動中", out2)
        rc, _ = self.finish(p2)
        self.assertEqual(rc, 0)
        self.assertIsNone(p1.poll())  # 1 つ目は生きている

    def test_port_used_by_another_folders_server_asks_for_another_port(self):
        port = self.free_port()
        other = Path(self._tmp.name) / "other"
        other.mkdir()
        (other / "narration.txt").write_text(NARRATION, encoding="utf-8")
        p1, url1, _ = self.start("--port", str(port), workdir=other)
        self.assertIsNotNone(url1)
        p2, url2, out2 = self.start("--port", str(port))
        self.assertIsNone(url2)
        rc, out = self.finish(p2)
        self.assertEqual(rc, 2, out2 + out)
        text = out2 + out
        self.assertIn("--port", text)
        self.assertIn("別の作業フォルダ", text)
        self.assertIsNone(p1.poll())

    def test_port_used_by_another_program_asks_for_another_port(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)  # 接続は受けるが HTTP には答えない
            port = s.getsockname()[1]
            p, url, out = self.start("--port", str(port))
            self.assertIsNone(url)
            rc, rest = self.finish(p, timeout=30)
        self.assertEqual(rc, 2, out + rest)
        self.assertIn("--port", out + rest)

    def test_simultaneous_starts_make_one_server(self):
        port = self.free_port()
        procs = [self.spawn("--port", str(port)) for _ in range(3)]
        urls = [self.read_until_ready(p)[0] for p in procs]
        self.assertEqual(len(set(urls)), 1, urls)  # みな同じ URL を案内する
        time.sleep(1.0)
        alive = [p for p in procs if p.poll() is None]
        self.assertEqual(len(alive), 1)  # 動き続けるサーバは 1 つだけ

    def test_live_url_matches_only_the_same_folder(self):
        port = self.free_port()
        p, url, _ = self.start("--port", str(port))
        self.assertEqual(review_server.live_url(self.dir, port), url)
        other = Path(self._tmp.name) / "other"
        other.mkdir()
        self.assertIsNone(review_server.live_url(other, port))
        self.assertIsNone(review_server.live_url(self.dir, self.free_port()))

    def test_summary_mentions_the_review_page(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = review_server.main(["--workdir", str(self.dir), "--summary"])
        self.assertEqual(rc, 0)
        self.assertIn("確認画面:", buf.getvalue())

    def test_sigterm_exits_cleanly(self):
        p, url, _ = self.start("--port", str(self.free_port()))
        p.terminate()
        rc, _ = self.finish(p, timeout=10)
        self.assertEqual(rc, 0)


class TestRound4(Base):
    """R4-1/2/3/5: 改行を含むセル、BOM、承認ゲートのハッシュのキャッシュ、review.csv の忠実性、排他。"""

    def test_gate_does_not_trust_the_hash_cache(self):
        """同じサイズ・更新時刻で内容だけ変わっても、ゲートは「古い」と判定する。"""
        ws = self.httpd.workspace
        narr = self.dir / "narration.txt"
        h = ws.hash_of(narr)
        ws.approve({"item": "script", "status": "承認", "comment": "", "hash": h})
        st = narr.stat()
        data = narr.read_bytes()
        new = data.replace("単眼".encode("utf-8"), "双眼".encode("utf-8"))
        self.assertEqual(len(new), len(data))
        narr.write_bytes(new)
        os.utime(narr, ns=(st.st_atime_ns, st.st_mtime_ns))
        self.assertEqual(
            ws.hash_of(narr), h
        )  # 表示用のキャッシュは古いまま(限界の記録)
        self.assertTrue(ws.approvals(fresh=True)["script"]["stale"])
        self.assertTrue(review_server.gate_problems(ws, ["script"]))


class TestServerLogging(Base):
    def test_connection_reset_is_not_logged(self):
        try:
            raise ConnectionResetError("x")
        except ConnectionResetError:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.httpd.handle_error(None, ("127.0.0.1", 1))
        self.assertEqual(err.getvalue(), "")

    def test_other_errors_are_still_logged(self):
        try:
            raise RuntimeError("想定外")
        except RuntimeError:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.httpd.handle_error(None, ("127.0.0.1", 1))
        self.assertIn("RuntimeError", err.getvalue())


class TestRoutes(Base):
    """書き込みルートの表(ROUTES)から、すべてのルートに共通の不変条件を検査する(ADR-0003)。"""

    # 版(ROUTES の第 2 要素のフィールド)以外はそろった、正しい本文
    VALID_WITHOUT_VERSION = {
        "/api/approve": {"item": "script", "status": "承認", "comment": ""},
        "/api/narration": {"index": 0, "text": "変更。"},
        "/api/yomi": {
            "surface": "KL",
            "reading": "ケ'ーエル",
            "status": "確認済み",
            "note": "",
        },
        "/api/yomi/delete": {"surface": "KL"},
        "/api/asset": {"file": "assets/a.png", "status": "仮", "note": ""},
        "/api/note": {"line": 1, "note": "x"},
    }
    GARBAGE = [
        {},
        {"x": 1},
        {"item": None, "status": None},
        {"index": "a", "text": 1},
        {"line": "a", "note": 1},
        {"surface": 1, "reading": 2},
        {"file": [1], "status": {}},
        {"hash": 5, "expected": 5},
        {"hash": "", "expected": []},
    ]

    def snapshot(self):
        return {
            str(p.relative_to(self.dir)): p.read_bytes()
            for p in sorted(self.dir.rglob("*"))
            if p.is_file()
        }

    def test_table_and_workspace_agree(self):
        public = {
            n
            for n in dir(review_server.Workspace)
            if not n.startswith("_") and callable(getattr(review_server.Workspace, n))
        }
        registered = {m for m, _ in review_server.ROUTES.values()}
        self.assertEqual(
            public - review_server.READ_ONLY_METHODS,
            registered,
            "公開メソッドを足したら ROUTES に登録する(読み取り専用なら READ_ONLY_METHODS に)",
        )
        self.assertEqual(set(self.VALID_WITHOUT_VERSION), set(review_server.ROUTES))
        for path, (method, field) in review_server.ROUTES.items():
            self.assertTrue(callable(getattr(review_server.Workspace, method)), path)
            self.assertNotIn(field, self.VALID_WITHOUT_VERSION[path], path)

    def test_garbage_bodies_write_nothing_and_never_500(self):
        before = self.snapshot()
        for path in review_server.ROUTES:
            for body in self.GARBAGE:
                with self.subTest(path=path, body=body):
                    status, _ = self.post(path, body, auto=False)
                    self.assertIn(status, (400, 409), (path, body))
        self.assertEqual(self.snapshot(), before)

    def test_missing_version_is_400_and_writes_nothing(self):
        before = self.snapshot()
        for path, body in self.VALID_WITHOUT_VERSION.items():
            with self.subTest(path=path):
                status, resp = self.post(path, body, auto=False)
                self.assertEqual(status, 400, (path, resp))
        self.assertEqual(self.snapshot(), before)

    def test_with_the_seen_version_the_same_body_succeeds(self):
        for path, body in self.VALID_WITHOUT_VERSION.items():
            with self.subTest(path=path):
                status, resp = self.post(path, body)  # 画面と同じく、現在の版を添える
                self.assertEqual(status, 200, (path, resp))

    def test_stale_version_is_409_and_writes_nothing(self):
        stale = {
            "hash": "deadbeefdead",
            "expected": {
                "pron": "ア",
                "accent": 0,
                "status": "確認済み",
                "note": "古い",
            },
        }
        for path, body in self.VALID_WITHOUT_VERSION.items():
            field = review_server.ROUTES[path][1]
            with self.subTest(path=path):
                before = self.snapshot()
                status, resp = self.post(
                    path, {**body, field: stale[field]}, auto=False
                )
                if path == "/api/asset":  # 台帳の素材の値は別の形(同じ「古い値」の意味)
                    status, resp = self.post(
                        path, {**body, field: {"状態": "仮", "古い": "値"}}, auto=False
                    )
                self.assertEqual(status, 409, (path, resp))
                self.assertEqual(self.snapshot(), before)


class TestBrowserBoundary(Base):
    """他のサイトからの送信を防ぐ(トークンの代わり): JSON の Content-Type だけ、Origin 検査、
    フレーム拒否、nosniff、メディア以外は添付として配信する。"""

    def send(self, method, path, data=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, f"{path}", body=data, headers=headers or {})
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, raw

    def note_body(self):
        h = self.get_json()["hashes"]["script"]
        return json.dumps(
            {"line": 1, "note": "x", "hash": h}, ensure_ascii=False
        ).encode("utf-8")

    def test_write_requires_json_content_type(self):
        before = (self.dir / "notes.json").exists()
        for ctype in (
            None,
            "text/plain",
            "application/x-www-form-urlencoded",
            "multipart/form-data; boundary=x",
        ):
            with self.subTest(ctype=ctype):
                headers = {"Content-Type": ctype} if ctype else {}
                status, _, raw = self.send(
                    "POST", "/api/note", self.note_body(), headers
                )
                self.assertEqual(status, 415, raw)
        self.assertEqual((self.dir / "notes.json").exists(), before)
        status, _, raw = self.send(
            "POST",
            "/api/note",
            self.note_body(),
            {"Content-Type": "application/json; charset=utf-8"},
        )
        self.assertEqual(status, 200, raw)

    def test_foreign_origin_is_forbidden_for_reads_and_writes(self):
        own = f"http://127.0.0.1:{self.port}"
        for origin in (
            "http://evil.example",
            "null",
            "http://127.0.0.1:1",
            "https://localhost:%d" % self.port,
        ):
            with self.subTest(origin=origin):
                status, _, _ = self.send("GET", "/api/state", None, {"Origin": origin})
                self.assertEqual(status, 403)
                status, _, _ = self.send(
                    "POST",
                    "/api/note",
                    self.note_body(),
                    {"Content-Type": "application/json", "Origin": origin},
                )
                self.assertEqual(status, 403)
        self.assertFalse((self.dir / "notes.json").exists())
        for origin in (own, f"http://localhost:{self.port}"):
            status, _, _ = self.send("GET", "/api/state", None, {"Origin": origin})
            self.assertEqual(status, 200, origin)

    def test_security_headers_on_every_kind_of_response(self):
        for path in (
            "/",
            "/api/state",
            "/files/video.mp4",
            "/files/none.png",
            "/api/nothing",
        ):
            with self.subTest(path=path):
                _, h, _ = self.send("GET", path)
                self.assertEqual(h.get("x-frame-options"), "DENY")
                self.assertEqual(h.get("x-content-type-options"), "nosniff")

    def test_only_media_is_served_inline(self):
        (self.dir / "page.html").write_text(
            "<script>alert(1)</script>", encoding="utf-8"
        )
        (self.dir / "x.svg").write_text(
            "<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8"
        )
        (self.dir / "data.json").write_text("{}", encoding="utf-8")
        for name in ("page.html", "x.svg", "data.json"):
            with self.subTest(name=name):
                _, h, _ = self.send("GET", f"/files/{name}")
                self.assertTrue(
                    h.get("content-disposition", "").startswith("attachment"), h
                )
        for name in ("assets/a.png", "video.mp4", "voiceover.wav"):
            with self.subTest(name=name):
                _, h, _ = self.send("GET", f"/files/{name}")
                self.assertNotIn("content-disposition", h)


class TestPageShowsErrors(unittest.TestCase):
    """R2-3: 画面は errors を表示し、承認記録が壊れている間は承認ボタンを無効にする。
    (実際の表示は目視で確かめる。ここではページが errors を扱うことだけを粗く押さえる)"""

    def test_page_handles_errors(self):
        html = review_server.PAGE.read_text(encoding="utf-8")
        self.assertIn("S.errors", html)
        self.assertIn("errors.approvals", html)


if __name__ == "__main__":
    unittest.main()

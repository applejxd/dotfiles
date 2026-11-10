"""VOICEVOX ENGINE の最小の偽サーバ(テスト用)。

実エンジンと同じく、音声の長さは (モーラ長の合計 + 前後の無音) / speedScale。
合成した音声は 24kHz モノラル 16bit の正弦波。
"""

import io
import json
import math
import threading
import urllib.parse
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MORA = 0.1
PUNCT = "、。 　"


def make_query(text: str, speed: float = 1.0) -> dict:
    phrases = []
    cur = []
    for ch in text:
        if ch in "、。":
            if cur:
                phrases.append(cur)
            cur = []
        elif ch not in PUNCT:
            cur.append(ch)
    if cur:
        phrases.append(cur)
    return {
        "accent_phrases": [
            {
                "moras": [
                    {
                        "text": c,
                        "consonant": None,
                        "consonant_length": None,
                        "vowel": "a",
                        "vowel_length": MORA,
                        "pitch": 5.0,
                    }
                    for c in p
                ],
                "accent": 1,
                "pause_mora": None,
                "is_interrogative": False,
            }
            for p in phrases
        ],
        "speedScale": speed,
        "pitchScale": 0.0,
        "intonationScale": 1.0,
        "volumeScale": 1.0,
        "prePhonemeLength": 0.1,
        "postPhonemeLength": 0.1,
        "outputSamplingRate": 24000,
        "outputStereo": False,
        "kana": "",
    }


def make_wav(seconds: float, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(seconds * rate)
        frames = bytearray()
        for i in range(n):
            v = int(8000 * math.sin(2 * math.pi * 220 * i / rate))
            frames += v.to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))
    return buf.getvalue()


class FakeVoicevox:
    """with FakeVoicevox() as fake: fake.url"""

    def __init__(self):
        self.calls = []
        self.words = {}
        self.rates = []  # 合成ごとに先頭から使うサンプリング周波数(失敗系の試験用)
        self.kana = {}  # 文 → エンジンが返す読み(無い文は 1 文字 1 モーラとして返す)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, body: bytes, ctype="application/json"):
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _handle(self):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                outer.calls.append((self.command, u.path, q))
                if u.path == "/version":
                    return self._send(b'"0.0-fake"')
                if u.path == "/speakers":
                    return self._send(
                        json.dumps(
                            [
                                {
                                    "name": "四国めたん",
                                    "styles": [{"id": 2, "name": "ノーマル"}],
                                },
                                {
                                    "name": "ずんだもん",
                                    "styles": [{"id": 3, "name": "ノーマル"}],
                                },
                            ],
                            ensure_ascii=False,
                        ).encode()
                    )
                if u.path == "/audio_query":
                    return self._send(
                        json.dumps(
                            make_query(outer.kana.get(q["text"], q["text"]))
                        ).encode()
                    )
                if u.path == "/synthesis":
                    query = json.loads(body)
                    total = sum(
                        m["vowel_length"]
                        for ap in query["accent_phrases"]
                        for m in ap["moras"]
                    )
                    total += query["prePhonemeLength"] + query["postPhonemeLength"]
                    rate = outer.rates.pop(0) if outer.rates else 24000
                    return self._send(
                        make_wav(total / query["speedScale"], rate), "audio/wav"
                    )
                if u.path == "/user_dict" and self.command == "GET":
                    return self._send(
                        json.dumps(
                            {
                                k: {
                                    "surface": k,
                                    "pronunciation": v[0],
                                    "accent_type": v[1],
                                    "priority": v[2],
                                }
                                for k, v in outer.words.items()
                            },
                            ensure_ascii=False,
                        ).encode()
                    )
                if u.path == "/user_dict_word" and self.command == "POST":
                    outer.words[q["surface"]] = (
                        q["pronunciation"],
                        int(q["accent_type"]),
                        int(q.get("priority", 5)),
                    )
                    return self._send(b'"uuid"')
                if u.path.startswith("/user_dict_word/") and self.command == "DELETE":
                    outer.words.pop(
                        urllib.parse.unquote(u.path.rsplit("/", 1)[1]), None
                    )
                    return self._send(b"null")
                self.send_response(404)
                self.end_headers()

            do_GET = do_POST = do_DELETE = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def synthesis_count(self) -> int:
        return sum(1 for m, p, _ in self.calls if p == "/synthesis")

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

"""VOICEVOX ENGINE の最小クライアント(標準ライブラリのみ)。

ENGINE は HTTP API。Docker での起動例:
    docker run --rm -d --name vv -p 127.0.0.1:50021:50021 \\
        voicevox/voicevox_engine:cpu-latest
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "http://127.0.0.1:50021"
DOCKER_HINT = (
    "docker run --rm -d --name vv -p 127.0.0.1:50021:50021 "
    "voicevox/voicevox_engine:cpu-latest"
)


class EngineUnavailable(RuntimeError):
    """ENGINE に接続できない。"""


class Engine:
    def __init__(
        self,
        url: str = DEFAULT_URL,
        timeout: float = 120.0,
        connect_timeout: float = 5.0,
    ):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.connect_timeout = connect_timeout

    def _call(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        body=None,
        raw: bool = False,
        timeout: float | None = None,
    ):
        url = self.url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        elif method == "POST":
            data = b""
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                payload = r.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"VOICEVOX が {e.code} を返した: {method} {path}: "
                f"{e.read()[:200].decode(errors='replace')}"
            ) from e
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            raise EngineUnavailable(f"{self.url} に接続できない: {e}") from e
        if raw:
            return payload
        return json.loads(payload) if payload.strip() else None

    def version(self) -> str:
        return self._call("GET", "/version", timeout=self.connect_timeout)

    def wait_ready(self, seconds: float = 0.0) -> str:
        """接続できるまで最大 seconds 秒待つ。できなければ EngineUnavailable。"""
        end = time.time() + seconds
        while True:
            try:
                return self.version()
            except EngineUnavailable:
                if time.time() >= end:
                    raise
                time.sleep(0.5)

    def speakers(self) -> list:
        return self._call("GET", "/speakers")

    def speaker_name(self, style_id: int) -> str | None:
        for sp in self.speakers():
            for st in sp.get("styles", []):
                if st["id"] == style_id:
                    return sp["name"]
        return None

    def audio_query(self, text: str, speaker: int) -> dict:
        return self._call("POST", "/audio_query", {"text": text, "speaker": speaker})

    def synthesis(self, query: dict, speaker: int) -> bytes:
        return self._call(
            "POST", "/synthesis", {"speaker": speaker}, body=query, raw=True
        )

    def user_dict(self) -> dict:
        return self._call("GET", "/user_dict")

    def add_word(
        self, surface: str, pronunciation: str, accent_type: int, priority: int = 9
    ) -> None:
        # priority は 0〜10(既定 5)。既定辞書に負けないよう高めにする
        self._call(
            "POST",
            "/user_dict_word",
            {
                "surface": surface,
                "pronunciation": pronunciation,
                "accent_type": accent_type,
                "priority": priority,
            },
        )

    def delete_word(self, uuid: str) -> None:
        self._call("DELETE", f"/user_dict_word/{urllib.parse.quote(uuid, safe='')}")


def phrase_lengths(query: dict) -> list[tuple[str, float]]:
    """アクセント句ごと (読み, 長さ秒)。speedScale は含めない生の値。"""
    out = []
    for ap in query["accent_phrases"]:
        sec = sum(
            (m.get("consonant_length") or 0.0) + m["vowel_length"] for m in ap["moras"]
        )
        if ap.get("pause_mora"):
            sec += ap["pause_mora"]["vowel_length"]
        out.append(("".join(m["text"] for m in ap["moras"]), sec))
    return out

"""Pi の画像ガード。外部 API、実際の認証、実際のセッションを使わない。"""

from __future__ import annotations

import base64
import json
import os
import shutil
import struct
import subprocess
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PACKAGE = ROOT / "home" / "dot_pi" / "agent" / "local-packages" / "pi-copilot-image-guard"
GUARD_TEST = ROOT / "test" / "agents" / "pi_stock" / "copilot_image_guard.test.mjs"
MODEL = "gemini-4-neon"


def test_image_guard_hooks():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js が無いため拡張の単体試験を実行できない")
    result = subprocess.run(
        [node, "--test", str(GUARD_TEST)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _image(color: int, *, padding: int = 0) -> dict:
    def chunk(name: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))

    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    if padding:
        data += chunk(b"tEXt", b"Description\0" + b"x" * padding)
    data += chunk(b"IDAT", zlib.compress(bytes([0, color, 0, 0]))) + chunk(b"IEND", b"")
    return {"type": "image", "mimeType": "image/png", "data": base64.b64encode(data).decode("ascii")}


class _MockHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append((self.path, body))
        envelope = {"id": "mock", "object": "chat.completion.chunk", "created": 0, "model": MODEL}
        content = body["messages"][-1]["content"]
        needs_read = isinstance(content, list) and any(part.get("text") in {"tool nine", "tool ten"} for part in content)
        if needs_read:
            delta = {"role": "assistant", "tool_calls": [{
                "index": 0, "id": f"call_mock_{len(self.server.requests)}", "type": "function",
                "function": {"name": "read", "arguments": json.dumps({"path": str(self.server.image_path)})},
            }]}
        else:
            delta = {"role": "assistant", "content": "ok"}
        first = {**envelope, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
        last = {**envelope, "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if needs_read else "stop"}]}
        result = f"data: {json.dumps(first)}\n\ndata: {json.dumps(last)}\n\ndata: [DONE]\n\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(result)))
        self.end_headers()
        self.wfile.write(result)

    def log_message(self, _format, *_args):
        pass


def test_pi_mock_gateway(tmp_path):
    # 本物の Pi の版を指定して手動で実行する。通常の検証は Node の単体試験だけで足りる。
    executable = os.environ.get("PI_IMAGE_GUARD_TEST_PI")
    if not executable:
        pytest.skip("模擬ゲートウェイ検査は PI_IMAGE_GUARD_TEST_PI に試験用の Pi を指定する")
    if not (pi := shutil.which(executable)):
        pytest.fail("PI_IMAGE_GUARD_TEST_PI の Pi が見つからない")
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    # -e を使わず、配備と同じ相対パスを package に登録して読み込む。
    shutil.copytree(SOURCE_PACKAGE, agent_dir / "local-packages" / "pi-copilot-image-guard")
    (agent_dir / "settings.json").write_text(json.dumps({
        "packages": ["./local-packages/pi-copilot-image-guard"],
        "images": {"autoResize": False}, "retry": {"enabled": False},
    }), encoding="utf-8")

    # Pi が動く Node 内では、模擬サーバ以外の HTTP リクエストを拒む。
    network_guard = tmp_path / "loopback-only.mjs"
    network_guard.write_text(
        "const original = globalThis.fetch;\n"
        "globalThis.fetch = (input, ...rest) => {\n"
        "  const url = new URL(input instanceof Request ? input.url : input);\n"
        "  if (url.origin !== process.env.IMAGE_GUARD_MOCK_ORIGIN) throw new Error('mock origin only');\n"
        "  return original.call(globalThis, input, ...rest);\n"
        "};\n"
    )
    with ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler) as server:
        server.requests = []
        server.image_path = tmp_path / "tool.png"
        server.image_path.write_bytes(base64.b64decode(_image(33)["data"]))
        origin = f"http://127.0.0.1:{server.server_port}"
        (agent_dir / "models.json").write_text(json.dumps({
            "providers": {"github-copilot": {
                "baseUrl": origin + "/v1", "api": "openai-completions", "apiKey": "mock-only",
                "models": [{"id": MODEL, "input": ["text", "image"], "reasoning": False, "contextWindow": 2_000_000}],
            }},
        }))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            _exercise_rpc(pi, tmp_path, agent_dir, origin, network_guard, server.requests)
        finally:
            server.shutdown()
            thread.join()


def _exercise_rpc(pi, tmp_path, agent_dir, origin, network_guard, requests):
    environment = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "PI_MANAGED_INSTALL_ROOT") if key in os.environ}
    environment.update({
        "HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "PI_CODING_AGENT_DIR": str(agent_dir),
        "NODE_OPTIONS": f'--import="{network_guard.as_uri()}"', "IMAGE_GUARD_MOCK_ORIGIN": origin,
    })
    args = [pi, "--offline", "--mode", "rpc", "--no-session", "--tools", "read",
            "--no-skills", "--provider", "github-copilot", "--model", MODEL]
    with subprocess.Popen(args, cwd=tmp_path, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, encoding="utf-8") as process:
        records = Queue()

        def read_records():
            for line in process.stdout:
                records.put(line)
            records.put(None)

        Thread(target=read_records, daemon=True).start()

        def prompt(label, images):
            command = {"id": label, "type": "prompt", "message": label, "images": list(images)}
            process.stdin.write(json.dumps(command) + "\n")
            process.stdin.flush()
            seen = []
            while True:
                try:
                    line = records.get(timeout=10)
                except Empty:
                    pytest.fail(f"Pi が 10 秒間応答しない: {label} / {[x.get('type') for x in seen]}")
                if line is None:
                    pytest.fail(f"Pi が終了した: {label}: {process.stderr.read()[-1200:]}")
                event = json.loads(line)
                seen.append(event)
                if event.get("id") == label and event.get("type") == "response":
                    assert event.get("success"), event
                if event.get("type") == "agent_settled":
                    return seen

        try:
            prompt("old", (_image(v) for v in range(1, 11)))
            assert len(requests) == 1
            prompt("current", [_image(11)])
            assert len(requests) == 2
            assert requests[-1][0] == "/v1/chat/completions"
            def sent_urls():
                return [part["image_url"]["url"] for msg in requests[-1][1]["messages"] if isinstance(msg["content"], list)
                        for part in msg["content"] if part.get("type") == "image_url"]

            def expected_urls(colors):
                return ["data:image/png;base64," + _image(color)["data"] for color in colors]

            def notified(events, text):
                return any(text in event.get("message", "") for event in events if event.get("type") == "extension_ui_request")

            assert sent_urls() == expected_urls(range(2, 12))
            # 実際の read が返した画像は、Pi が送信時に user メッセージに変換する。
            prompt("tool nine", (_image(v) for v in range(20, 29)))
            assert len(requests) == 4
            assert sent_urls() == expected_urls([*range(20, 29), 33])
            events = prompt("tool ten", (_image(v) for v in range(40, 50)))
            assert len(requests) == 5  # 添付10枚の POST は到達したが、read 後の POST は到達しない。
            assert notified(events, "現在ターンだけで画像が 11 枚")
            events = prompt("too many", (_image(v) for v in range(60, 71)))
            assert len(requests) == 5
            assert notified(events, "現在ターンだけで画像が 11 枚")
            events = prompt("too large", [_image(40, padding=3_200_000)])
            assert len(requests) == 5
            assert notified(events, "上限 10 枚・4 MiB")
            # 長いテキストのあとでも、過去画像を削って全体 4 MiB 以下なら送信できる。
            # さらに過去画像を全削除して画像 0 枚になれば、テキストが 4 MiB 超でも画像ガードで止めない。
            big_img = _image(80, padding=700_000)
            events = prompt("long text " + ("a" * 2_400_000), [big_img])
            assert len(requests) == 6
            assert sent_urls() == ["data:image/png;base64," + big_img["data"]]
            events = prompt("continue " + ("b" * 2_000_000), [])
            assert len(requests) == 7
            assert sent_urls() == []
            assert notified(events, "過去の画像を")
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

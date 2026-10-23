#!/usr/bin/env python3
"""Copilot の短命トークンを、ホスト側で取得して、Envoy 用の SDS ファイルへ書く (CHG-0037 段 U7a の使い捨て)。

pi の auth.json (ホスト側) の長期の GitHub トークンで copilot_internal/v2/token を引き、
短命の Copilot トークンを SDS の形式でアトミックに書き出す。値は標準出力に出さない。
境界の外 (ホスト) でだけ実行する。内側 (pis) には、このファイルも auth.json も渡さない。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

# pi-ai (dist/auth/oauth/github-copilot.js) の COPILOT_HEADERS と同じ
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "GitHubCopilotChat/0.35.0",
    "Editor-Version": "vscode/1.107.0",
    "Editor-Plugin-Version": "copilot-chat/0.35.0",
    "Copilot-Integration-Id": "vscode-chat",
}
SECRET_NAME = "copilot_token"


def agent_dir() -> Path:
    return Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent")


def load_refresh_token(auth_json: Path) -> str:
    data = json.loads(auth_json.read_text(encoding="utf-8"))
    entry = data.get("github-copilot")
    if not isinstance(entry, dict) or not isinstance(entry.get("refresh"), str):
        raise SystemExit(
            "auth.json に github-copilot の OAuth の資格情報が無い。pi で /login して先に作る"
        )
    return entry["refresh"]


def exchange(refresh_token: str) -> tuple[str, int]:
    request = urllib.request.Request(
        "https://api.github.com/copilot_internal/v2/token",
        headers={**HEADERS, "Authorization": f"Bearer {refresh_token}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # 固定の https のみ
        raw = json.loads(response.read().decode("utf-8"))
    token, expires_at = raw.get("token"), raw.get("expires_at")
    if not isinstance(token, str) or not isinstance(expires_at, int):
        raise SystemExit("Copilot のトークンの応答の形が想定と違う")
    return token, expires_at


def write_sds(path: Path, token: str) -> None:
    """Envoy が監視するディレクトリへ、rename でアトミックに置く (0600)。"""
    body = {
        "resources": [
            {
                "@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.Secret",
                "name": SECRET_NAME,
                "generic_secret": {"secret": {"inline_string": token}},
            }
        ]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".sds-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(body, handle)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", required=True, help="SDS ファイル (Envoy が監視するディレクトリの中)"
    )
    parser.add_argument("--auth-json", default=None, help="既定は <agent dir>/auth.json")
    parser.add_argument("--loop", action="store_true", help="期限の 5 分前に取り直し続ける")
    args = parser.parse_args()

    refresh = load_refresh_token(
        Path(args.auth_json) if args.auth_json else agent_dir() / "auth.json"
    )
    out = Path(args.out)
    while True:
        token, expires_at = exchange(refresh)
        write_sds(out, token)
        remaining = expires_at - int(time.time())
        print(f"書き出した: {out} (有効期限まで {remaining} 秒。値は表示しない)", flush=True)
        if not args.loop:
            return 0
        time.sleep(max(60, remaining - 5 * 60))


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""判定 API の CLI。stdin の JSON を判定し、stdout に JSON を 1 つ書く。

入力: {"tool", "input", "cwd", "role", "bypass"?, "boundary"?}
出力: {"decision": "allow" | "ask" | "deny", "reason",
       "source": "rule" | "check" | "default" | "error", ...}

どんな異常でも、形の正しい deny を出して exit 0 で終わる。呼び出し側は、形の正しい応答
以外 (空・不正な JSON・異常終了・タイムアウト) を deny と読む。
see docs/spec/pi-decide.md
"""

from __future__ import annotations

import json
import signal
import sys
from pathlib import Path

# 自前のタイムアウト秒。呼び出し側のタイムアウトより手前で打ち切る
_SELF_TIMEOUT_SEC = 10


def _emit(response: dict) -> None:
    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    sys.exit(0)


def _deny(reason: str) -> None:
    _emit({"decision": "deny", "reason": reason, "source": "error"})


def main() -> None:
    def _on_timeout(signum: int, frame: object) -> None:  # pragma: no cover
        _deny("判定が時間内に終わりませんでした")

    try:
        signal.signal(signal.SIGALRM, _on_timeout)
        signal.alarm(_SELF_TIMEOUT_SEC)
    except (AttributeError, ValueError):  # pragma: no cover - Windows など
        pass

    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    try:
        from decide import decide
    except Exception as exc:  # pragma: no cover - 構文エラー・TOML 破損なども拾う
        _deny(f"判定器を読み込めませんでした ({type(exc).__name__}: {exc})")
    try:
        request = json.loads(sys.stdin.read())
    except ValueError as exc:
        _deny(f"入力が JSON ではありません ({exc})")
    _emit(decide(request))


if __name__ == "__main__":
    main()

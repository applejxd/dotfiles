#!/usr/bin/env python3
"""圧縮の直後、最初のツール実行に相乗りして checkpoint をコンテキストへ戻す。

登録先: Copilot ``PostToolUse`` (**Copilot 専用**)

Claude には ``SessionStart`` matcher ``compact`` があり、作業を再開する前に
割り込める。Copilot にはそれが無い。代わりに次の 2 つを繋いで同じ結果を得る。

1. ``PreCompact`` が印を残す (通知専用のイベントでも、印を置くことはできる)
2. 次の ``PostToolUse`` が印を見て ``additionalContext`` として本文を返す

``PostToolUse`` の出力仕様:

    Additional guidance appended to ``textResultForLlm`` so the model sees it
    after the tool output on the same turn.

出典: <https://docs.github.com/en/copilot/reference/hooks-reference>

自動圧縮は assistant ターンの境界で起き、圧縮後は同じツールループが続く
(記録 E6)。したがって圧縮の直後にはほぼ確実にツール呼び出しが来る。Claude が
「再開前」なのに対しこちらは「最初のツール実行の直後」で、1 回分だけ遅い。

**このイベントは全てのツール呼び出しで発火する。** 印が無いときに git や
スキル本体へ触ってはいけない。stat 1 回で抜ける。

exit code は常に 0。出力が空なら Copilot は元の結果をそのまま使う。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

# ★checkpoint_core ではなく checkpoint_pending を読む。全ツール呼び出しで
#   発火するので、印が無いときに subprocess / importlib / datetime を読み込む
#   コスト (実測 +13ms/回) を払わない。
from checkpoint_pending import (
    debug_log,
    read_input,
    take_restore_pending,
    truncate_for_context,
)

HEADER = (
    "【圧縮前の引き継ぎ記録】直前に context compaction が起きました。"
    "以下は圧縮前に保存した記録です。作業を続ける前に読んでください。\n"
    "（この内容は既に注入済みなので、ファイルを開き直す必要はありません）\n"
)


def main() -> int:
    data = read_input()
    text = take_restore_pending(data)

    if text is None:
        # 印が無い = 圧縮していない。これが大多数の経路なので、何もしない。
        debug_log("restore_pending", {"ok": False, "reason": "no pending marker"})
        return 0

    body = truncate_for_context(HEADER + text)
    json.dump({"additionalContext": body}, sys.stdout, ensure_ascii=False)
    debug_log("restore_pending", {"ok": True, "chars": len(body)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

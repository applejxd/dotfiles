#!/usr/bin/env python3
"""圧縮の直後に、自分の checkpoint をコンテキストへ戻す。

登録先: Claude ``SessionStart`` matcher ``compact`` (**Claude 専用**)

Claude はここで作業再開の**前**に割り込める。Copilot には対応するイベントが
無いため、``checkpoint_restore_pending.py`` が ``PostToolUse`` に相乗りして
同じ結果を得る (1 ツール分だけ遅い)。詳細は記録 E1 / E7。

``SessionStart`` は「plain stdout already reaches Claude for this event」なので、
全文を出すだけでよい。JSON を組む必要は無い。

**安全規則:**

- 読むのは ``resolve_paths()`` が返した**自分のファイルだけ**。
  他セッションのファイルは決して読まない
- 読めなかった場合は全文を注入せず、読めなかったことだけを伝える

exit code は常に 0。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from checkpoint_core import clear_restore_pending, debug_log, read_checkpoint, read_input

HEADER = (
    "以下は圧縮前に保存した作業の引き継ぎ記録です。"
    "作業を再開する前に読んでください。\n"
    "（この内容は既に注入済みなので、ファイルを開き直す必要はありません）\n"
)


def main() -> int:
    data = read_input()
    text = read_checkpoint(data)

    # ここで戻せたので、Copilot 向けの印は用済み。残すと次のツール実行で
    # 二重に注入される。
    clear_restore_pending(data)

    if text is None:
        # 記録が無い / 読めないことを伝えるだけ。他のファイルを探しに行かせない。
        print(
            "圧縮前の引き継ぎ記録は見つかりませんでした。"
            "必要なら `checkpoint` スキルで新しく作ってください。"
        )
        debug_log("restore", {"ok": False, "reason": "no checkpoint"})
        return 0

    print(HEADER)
    print(text)
    debug_log("restore", {"ok": True, "chars": len(text)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

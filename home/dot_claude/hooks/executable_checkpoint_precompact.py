#!/usr/bin/env python3
"""圧縮の直前に、機械的な事実だけを checkpoint へ記録する。

登録先: Claude ``PreCompact`` / Copilot ``PreCompact``

これは**保険**である。本来は圧縮より前に `checkpoint` スキルが実行されていて
ほしいが、間に合わなかった場合でも「どのコミットで、何を触っていたか」だけは
残す。意味内容は書かない (書けない)。

**絶対にブロックしない。**

公式ドキュメントは、context-limit エラーからの回復として発火した自動圧縮を
ブロックすると「元のエラーが表面化し、現在のリクエストが失敗する」と明記して
いる。機械記録のためにユーザの作業を失わせるのは割に合わない。

``trigger: "manual"`` の条件付きブロックは段 8 の検討事項として分けてある。
ここでは実装しない。

exit code は常に 0。hook の失敗でセッションを止めない。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from checkpoint_core import debug_log, read_input, write_snapshot


def main() -> int:
    data = read_input()
    result = write_snapshot(data)
    debug_log("precompact", result)
    # 成否にかかわらず 0。ブロックしないことが最優先。
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Claude Code Stop hook: docs/adr の更新を促す

docs/adr/ にファイルが存在する場合のみ、ADR の更新を促す。
exit 0: 停止を許可
exit 2: 停止をブロックし、stderr のメッセージを Claude へのフィードバックとして渡す
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def find_adr_dir(cwd: str) -> Path | None:
    """cwd から docs/adr ディレクトリを探す"""
    adr_path = Path(cwd) / "docs" / "adr"
    if adr_path.is_dir():
        return adr_path
    return None


def has_adr_files(adr_dir: Path) -> bool:
    """docs/adr にファイル（.md 等）が存在するか確認"""
    return any(adr_dir.iterdir())


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)  # 解析失敗時は許可

    hook_event = data.get("hook_event_name", "")
    if hook_event != "Stop":
        sys.exit(0)

    # stop_hook_active が True の場合は無限ループ防止のためスキップ
    if data.get("stop_hook_active", False):
        sys.exit(0)

    cwd = data.get("cwd", os.getcwd())
    adr_dir = find_adr_dir(cwd)

    if adr_dir is None or not has_adr_files(adr_dir):
        sys.exit(0)  # ADR がなければ何もしない

    # ADR ファイル一覧を取得（参考情報として）
    adr_files = sorted(adr_dir.glob("*.md"))
    adr_list = "\n".join(f"  - {f.name}" for f in adr_files) if adr_files else "  (非 .md ファイルを含む)"

    message = (
        f"docs/adr/ にアーキテクチャ決定記録（ADR）が存在します。\n"
        f"{adr_list}\n\n"
        f"今回の作業内容を踏まえ、以下を確認・更新してください：\n"
        f"  1. 既存の ADR に影響する変更があれば Status を更新する\n"
        f"  2. 新しいアーキテクチャ上の決定があれば新規 ADR を追加する\n"
        f"  3. 更新不要と判断した場合はその理由を一言添えて停止してください\n"
        f"\n"
        f"更新が不要な場合は「ADR 更新不要：（理由）」と返答してから終了してください。"
    )

    print(message, file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Claude Code TaskCompleted hook: docs/adr の更新を促す

docs/adr/ にファイルが存在する場合のみ、ADR の更新を促す。
セッションごとに1回のみ実行し、無限ループを防止する。
exit 0: タスク完了を許可
exit 2: タスク完了をブロックし、stderr のメッセージを Claude へのフィードバックとして渡す
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
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
    if hook_event != "TaskCompleted":
        sys.exit(0)

    # セッションごとに1回のみ実行（TaskCompleted の無限ループ防止）
    session_id = data.get("session_id", "")
    if session_id:
        marker = Path(tempfile.gettempdir()) / f"claude_adr_checked_{session_id}"
        if marker.exists():
            sys.exit(0)
        marker.touch()

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

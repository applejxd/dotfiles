#!/usr/bin/env python3
"""Web 検索・ページ取得・論文検索の CLI。核は ``~/.config/agents/websearch/core.py`` にあり、これは呼ぶだけの薄い入口。

核 (検索・取得・論文・鍵の同期・秘匿チェック・SSRF 防止) は MCP サーバ (``mcp_server.py``) と共有する。
コマンドと出力は核の ``main`` が決める (``search`` / ``fetch`` / ``papers`` / ``status`` / ``sync-keys``)。
see docs/spec/web-search.md
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

CORE_ENV = "WEBSEARCH_CORE"  # 核のファイルの場所を上書きする (試験用)


def core_candidates() -> list[Path]:
    here = Path(__file__).resolve()
    out = [Path(os.environ[CORE_ENV])] if os.environ.get(CORE_ENV) else []
    # 配備後 (~/.config/agents/websearch/core.py)
    out.append(Path.home() / ".config" / "agents" / "websearch" / "core.py")
    # リポジトリの中 (home/dot_claude/skills/web-search/scripts → home/dot_config/agents/websearch)
    out.append(here.parents[4] / "dot_config" / "agents" / "websearch" / "core.py")
    return out


def load_core():
    for path in core_candidates():
        if path.is_file():
            spec = importlib.util.spec_from_file_location("websearch_core", path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules["websearch_core"] = module  # dataclass が自分のモジュールを引く
                spec.loader.exec_module(module)
                return module
    searched = ", ".join(str(p) for p in core_candidates())
    print(f"websearch の核が見つからない ({searched})。chezmoi apply で配備する", file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(load_core().main())

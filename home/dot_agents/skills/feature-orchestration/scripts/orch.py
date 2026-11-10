#!/usr/bin/env python3
"""並列実装のオーケストレーションの入口。いまのサブコマンドは profile だけ (start・list などは後の段)。

    orch.py profile [--json] [--integration BRANCH] [--prefix PREFIX ...] [--worktrees-dir DIR]

終了コード: 0=確定、2=使い方・前提違反 (bare・コミット無し・git リポジトリでない)、4=曖昧 (候補と設定例を出す)。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import orchlib


def _fmt(v: Any) -> str:
    if v is None or v == [] or v == "":
        return "-"
    return ", ".join(map(str, v)) if isinstance(v, list) else str(v)


def render(p: dict[str, Any]) -> str:
    """人が読む 1 画面。"""
    s = p["sources"]
    t, w = p["topic"], p["worktrees"]
    rows = [
        ("flow", p["flow"], s.get("flow")),
        ("integration", p["integration"]["branch"], s.get("integration")),
        ("  ref", p["integration"]["ref"], ""),
        ("trunk", p["trunk"], s.get("trunk")),
        ("topic.prefixes", t["prefixes"], s.get("topic.prefixes")),
        ("topic.new_prefix", t["new_prefix"], ""),
        ("topic.start_point", t["start_point"], ""),
        ("topic.also_list", t["also_list"], ""),
        ("worktrees.template", w["template"], s.get("worktrees")),
        ("worktrees.base_abs", w["base_abs"], f"repo 内={w['inside_repo']} ignore={w['ignored']}"),
        ("verify", (p["verify"] or {}).get("cmd"), s.get("verify")),
        ("overlay", p["overlay"], s.get("overlay")),
        ("repo.toplevel", p["repo"]["toplevel"], ""),
        ("repo.main_worktree", p["repo"]["main_worktree"], ""),
    ]
    lines = [f"{k:<20} {_fmt(v)}" + (f"   ({src})" if src else "") for k, v, src in rows]
    if p["ambiguous"]:
        lines.append("")
        lines.append(orchlib.format_ambiguities(p["ambiguous"]))
    for w_ in p["warnings"]:
        lines.append(f"警告: {w_}")
    return "\n".join(lines)


def cmd_profile(args: argparse.Namespace) -> int:
    try:
        profile = orchlib.detect_profile(
            Path.cwd(),
            integration=args.integration,
            prefixes=args.prefix or None,
            worktrees_dir=args.worktrees_dir,
        )
    except orchlib.OrchError as e:
        print(f"orch: {e}", file=sys.stderr)
        return e.code
    if args.json:
        print(json.dumps(profile, ensure_ascii=False, indent=2))
    else:
        print(render(profile))
    return orchlib.EXIT_AMBIGUOUS if profile["ambiguous"] else orchlib.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="orch.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("profile", help="リポジトリのプロファイルを検出して表示する")
    pp.add_argument("--json", action="store_true", help="機械可読の JSON で出す")
    pp.add_argument("--integration", help="統合先の枝 (1 回だけの上書き)")
    pp.add_argument("--prefix", action="append", help="作業枝の接頭辞 (複数可。1 回だけの上書き)")
    pp.add_argument("--worktrees-dir", help="worktree を置くディレクトリ (1 回だけの上書き)")
    pp.set_defaults(func=cmd_profile)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

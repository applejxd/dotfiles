"""コマンドラインの入口: tb add / list / done / rm / export。"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import date

from taskboard import store


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tb", description="ローカルのタスク管理")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="タスクを追加する")
    add.add_argument("title")
    add.add_argument("--due", help="期限(YYYY-MM-DD)")
    add.add_argument("--tag", action="append", default=[], help="タグ(複数回指定できる)")
    ls = sub.add_parser("list", help="タスクを一覧する")
    ls.add_argument("--tag", help="このタグのタスクだけ")
    ls.add_argument("--json", action="store_true", help="JSON で出力する")
    done = sub.add_parser("done", help="タスクを完了にする")
    done.add_argument("id", type=int)
    rm = sub.add_parser("rm", help="タスクを削除する")
    rm.add_argument("id", type=int)
    export = sub.add_parser("export", help="ファイルへ書き出す")
    export.add_argument("--format", choices=("json", "csv"), default="json")
    export.add_argument("--out", required=True, help="出力先のファイル")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    tasks = store.load()
    if args.command == "add":
        if args.due:
            try:
                date.fromisoformat(args.due)
            except ValueError:
                print("tb: --due は YYYY-MM-DD で指定してください", file=sys.stderr)
                return 2
        next_id = max((t["id"] for t in tasks), default=0) + 1
        tasks.append({"id": next_id, "title": args.title, "due": args.due, "tags": args.tag, "done": False})
        store.save(tasks)
        print(f"追加しました: #{next_id} {args.title}")
    elif args.command == "list":
        shown = [t for t in tasks if not args.tag or args.tag in t["tags"]]
        if args.json:
            print(json.dumps(shown, ensure_ascii=False))
        else:
            for t in shown:
                mark = "x" if t["done"] else " "
                due = f" (期限 {t['due']})" if t["due"] else ""
                print(f"[{mark}] #{t['id']} {t['title']}{due}")
    elif args.command in ("done", "rm"):
        target = next((t for t in tasks if t["id"] == args.id), None)
        if target is None:
            print(f"tb: #{args.id} は見つかりません", file=sys.stderr)
            return 1
        if args.command == "done":
            target["done"] = True
        else:
            tasks.remove(target)
        store.save(tasks)
        print(f"{'完了' if args.command == 'done' else '削除'}しました: #{args.id}")
    elif args.command == "export":
        if args.format == "json":
            text = json.dumps(tasks, ensure_ascii=False, indent=2)
        else:
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["id", "title", "due", "tags", "done"])
            for t in tasks:
                writer.writerow([t["id"], t["title"], t["due"] or "", ";".join(t["tags"]), t["done"]])
            text = buffer.getvalue()
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"書き出しました: {args.out}")
    return 0

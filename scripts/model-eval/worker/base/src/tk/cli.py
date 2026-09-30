"""Command line entry point."""

import argparse
import json
import sys

from .client import Client
from .config import load_config
from .paginate import page_count, paginate


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tk")
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list", help="print one page of lines from a file")
    ls.add_argument("--page", type=int, default=1)
    ls.add_argument("--per-page", type=int, default=10)
    ls.add_argument("file")

    post = sub.add_parser("post", help="POST a JSON payload")
    post.add_argument("--base-url", required=True)
    post.add_argument("--retries", type=int, default=3)
    post.add_argument("path")
    post.add_argument("payload")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "list":
        with open(args.file) as f:
            items = [line.rstrip("\n") for line in f]
        if args.page > 1:
            shown = paginate(items, args.page - 1, args.per_page)
        else:
            shown = items[: args.per_page]
        for item in shown:
            print(item)
        print(f"-- page {args.page}/{page_count(len(items), args.per_page)}", file=sys.stderr)
        return 0
    cfg = load_config({"base_url": args.base_url, "retries": args.retries})
    result = Client(cfg).post(args.path, json.loads(args.payload))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

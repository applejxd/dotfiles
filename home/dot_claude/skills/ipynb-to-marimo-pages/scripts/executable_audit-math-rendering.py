#!/usr/bin/env python3
"""生成済み HTML を Chromium で開き、数式が実際に描画されたか検査する。

`check-display-math.py` は書式しか見ない。marimo の HTML は Markdown を JSON と
して埋め込み、KaTeX の描画はブラウザ上で行われるため、崩れているかどうかは
DOM を見るまで分からない。この検査はソース中の `$$` の対数と、ページ内の
`.katex-display` の数を照合する。

使い方:
    uv run --with playwright python audit-math-rendering.py \\
        --site site --notebooks notebooks
    # 初回のみ: uv run --with playwright playwright install chromium

`--site` / `--notebooks` には**それぞれのルート**を渡す。両者の相対パスの対応
（`notebooks/a/b.py` ↔ `site/a/b.html`）で照合するため、片方だけ下位ディレクトリ
を指定すると全ページが missing_html になる。

失敗条件は「数式の数の不一致」「`.katex-error` の存在」「描画に関係する console
エラー」の3つ。資産の 404 など数式に無関係な console エラーは
`other_console_errors` として報告するだけで失敗にしない。

終了コードは、差異が1件でもあれば 1。
"""

from __future__ import annotations

import argparse
import ast
import functools
import json
import re
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CODE_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"(`+).*?\1")
# 数式描画に関係しないブラウザの雑音（資産の404など）で失敗させない。
RENDERING_ERROR = re.compile(r"katex|latex|mathml", re.IGNORECASE)


def markdown_sources(path: Path) -> list[str]:
    """`mo.md(...)` に渡された Markdown を返す。

    静的検査側（check-display-math.py）と同じ規則で抽出する。f-string は
    差し込み部分を潰し、コードフェンスとインラインコードは除去する。
    両者の数え方がずれると、偽の不一致や見逃しが起きる。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    sources: list[str] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "md"
            and node.args
        ):
            continue
        argument = node.args[0]
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            sources.append(argument.value)
        elif isinstance(argument, ast.JoinedStr):
            sources.append(
                "".join(
                    part.value if isinstance(part, ast.Constant) else "EXPR"
                    for part in argument.values
                )
            )
    return sources


def prose(markdown: str) -> list[str]:
    """コードフェンス内の行を落とし、インラインコードを除去した行を返す。"""
    lines: list[str] = []
    fence: str | None = None
    for line in markdown.splitlines():
        if match := CODE_FENCE.match(line):
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append(INLINE_CODE.sub("", line))
    return lines


def expected_display_math(path: Path) -> int:
    """ソース中の `mo.md()` に含まれるディスプレイ数式の数を数える。"""
    return sum(
        sum(line.count("$$") for line in prose(markdown)) // 2
        for markdown in markdown_sources(path)
    )


class QuietHandler(SimpleHTTPRequestHandler):
    """検査結果の JSON だけを標準出力へ残すため、アクセスログを捨てる。"""

    def log_message(self, format: str, *args: object) -> None:
        return


def serve(directory: Path) -> tuple[ThreadingHTTPServer, str]:
    """site ディレクトリを一時的な HTTP サーバで配信する。

    `file://` で開くと相対パスの資産や fetch がブロックされる場合があるため、
    必ず HTTP 経由で読み込む。
    """
    handler = functools.partial(QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}"


def audit(page, url: str, expected: int, name: str) -> dict:
    console_errors: list[str] = []
    page.on(
        "console",
        lambda message: (
            console_errors.append(message.text) if message.type == "error" else None
        ),
    )
    for attempt in range(3):
        try:
            page.goto(url, wait_until="networkidle")
            break
        except Exception:
            if attempt == 2:
                raise
            page.wait_for_timeout(500)
    page.wait_for_timeout(500)
    # 遅延描画される数式があるため、一度ページ全体をスクロールする。
    page.evaluate(
        """async () => {
            for (let y = 0; y < document.body.scrollHeight; y += 800) {
                window.scrollTo(0, y);
                await new Promise((resolve) => setTimeout(resolve, 30));
            }
            window.scrollTo(0, 0);
        }"""
    )
    page.wait_for_timeout(300)
    errors = sorted(set(console_errors))
    return {
        "page": name,
        "expected_display": expected,
        "rendered_display": page.locator(".katex-display").count(),
        "katex_errors": page.locator(".katex-error").count(),
        # 描画に関係するものだけを失敗条件に使い、残りは参考情報として残す。
        "console_errors": [text for text in errors if RENDERING_ERROR.search(text)],
        "other_console_errors": [
            text for text in errors if not RENDERING_ERROR.search(text)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=Path("site"))
    parser.add_argument("--notebooks", type=Path, default=Path("notebooks"))
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        print(
            "playwright is required: uv run --with playwright python "
            f"{Path(__file__).name} ... (then `playwright install chromium`)",
            file=sys.stderr,
        )
        return 2

    server, base_url = serve(args.site)
    results: list[dict] = []
    failures: list[dict] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for source in sorted(args.notebooks.rglob("*.py")):
                relative = source.relative_to(args.notebooks).with_suffix(".html")
                if not (args.site / relative).exists():
                    failures.append({"page": relative.as_posix(), "missing_html": True})
                    continue
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                result = audit(
                    page,
                    f"{base_url}/{relative.as_posix()}",
                    expected_display_math(source),
                    relative.as_posix(),
                )
                page.close()
                results.append(result)
                if (
                    result["expected_display"] != result["rendered_display"]
                    or result["katex_errors"]
                    or result["console_errors"]
                ):
                    failures.append(result)
            browser.close()
    finally:
        server.shutdown()

    print(
        json.dumps(
            {"pages": len(results), "failures": failures},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

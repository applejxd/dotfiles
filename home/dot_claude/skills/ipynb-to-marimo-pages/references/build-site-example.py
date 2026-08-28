#!/usr/bin/env python3
"""marimo notebook を自動検出して実行・HTML化し、index と manifest を書き出す雛形。

`build-site-example.sh` は notebook の一覧を手で持つ小規模向け。冊数が増えたら
こちらを使う。要点は次の3つ。

1. `notebooks/` を再帰的に走査し、AST で marimo notebook を判定する（一覧を
   手動管理しない）
2. export の失敗を stdout・終了コード・生成HTMLの3方向から検出し、失敗した
   出力は削除する（`marimo export html` はセルが落ちても exit 0 を返す）
3. ソースと生成HTMLの SHA-256 を manifest へ記録する。この manifest を CI で
   照合して鮮度を検査する（照合側は本スクリプトではなく、デプロイ前の
   検査スクリプトが行う。`large-scale-migration.md` の7節）

使い方:
    uv run python scripts/build_site.py                 # 全冊を実行して再生成
    uv run python scripts/build_site.py --notebook a/b.py   # 一部だけ再生成
    uv run python scripts/build_site.py --discover-only     # 実行せず index だけ
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = ROOT / "notebooks"
SITE = ROOT / "site"
LOGS = ROOT / "build" / "logs"
ERROR_MARKERS = (
    "some cells failed to execute",
    "MarimoExceptionRaisedError",
    "Traceback (most recent call last)",
)
HEADING_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Notebook:
    source: Path
    relative: Path
    title: str

    @property
    def output(self) -> Path:
        return SITE / self.relative.with_suffix(".html")


def is_marimo_notebook(path: Path) -> bool:
    """marimo を import し `app` を定義しているファイルだけを notebook とみなす。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return False
    imports_marimo = any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and (
            any(alias.name == "marimo" for alias in node.names)
            if isinstance(node, ast.Import)
            else node.module == "marimo"
        )
        for node in tree.body
    )
    has_app = any(
        isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "app" for target in node.targets
        )
        for node in tree.body
    )
    return imports_marimo and has_app


def extract_title(path: Path) -> str:
    """先頭の Markdown 見出しを index のタイトルに使う。"""
    source = path.read_text(encoding="utf-8")
    for string in (
        node.value
        for node in ast.walk(ast.parse(source, filename=str(path)))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ):
        if match := HEADING_RE.search(string):
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return path.stem.replace("_", " ").replace("-", " ").title()


def discover() -> list[Notebook]:
    return [
        Notebook(source, source.relative_to(NOTEBOOKS), extract_title(source))
        for source in sorted(NOTEBOOKS.rglob("*.py"))
        if is_marimo_notebook(source)
    ]


def export(notebook: Notebook, log_dir: Path) -> str | None:
    """1冊を実行して HTML 化する。失敗したら理由を返し、出力を残さない。"""
    notebook.output.parent.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / notebook.relative.with_suffix(".log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # --sandbox は付けない。PEP 723 のインライン依存が無いと解決に失敗する。
    result = subprocess.run(
        [
            "uv", "run", "--all-groups", "marimo", "export", "html",
            str(notebook.source), "-o", str(notebook.output), "--force",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log_path.write_text(result.stdout, encoding="utf-8")
    output_text = (
        notebook.output.read_text(encoding="utf-8", errors="replace")
        if notebook.output.exists()
        else ""
    )
    marker = next(
        (
            candidate
            for candidate in ERROR_MARKERS
            if candidate in result.stdout or candidate in output_text
        ),
        None,
    )
    if result.returncode == 0 and marker is None and notebook.output.exists():
        return None
    notebook.output.unlink(missing_ok=True)
    reason = marker or f"marimo exited with status {result.returncode}"
    return f"{notebook.relative}: {reason} (log: {log_path})"


def write_index(notebooks: list[Notebook]) -> None:
    groups: dict[str, list[Notebook]] = {}
    for notebook in notebooks:
        category = (
            notebook.relative.parts[0] if len(notebook.relative.parts) > 1 else "other"
        )
        groups.setdefault(category, []).append(notebook)
    sections = []
    for category, entries in sorted(groups.items()):
        links = "\n".join(
            f'<li><a href="{html.escape(entry.relative.with_suffix(".html").as_posix())}">'
            f"{html.escape(entry.title)}</a></li>"
            for entry in entries
        )
        sections.append(
            f"<section><h2>{html.escape(category.title())}</h2><ul>{links}</ul></section>"
        )
    payload = f"""<!doctype html>
<html lang="ja">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>marimo notebooks</title>
    <style>
      :root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
      body {{ max-width: 64rem; margin: 0 auto; padding: 2rem 1rem 4rem; line-height: 1.6; }}
      main {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); gap: 1rem; }}
      section {{ border: 1px solid #8886; border-radius: .75rem; padding: .5rem 1.25rem; }}
    </style>
  </head>
  <body>
    <h1>marimo notebooks</h1>
    <p>{len(notebooks)} notebooks are generated automatically from <code>notebooks/</code>.</p>
    <main>
{chr(10).join(sections)}
    </main>
  </body>
</html>
"""
    (SITE / "index.html").write_text(payload, encoding="utf-8")
    # Jekyll による加工を止め、エクスポートした資産をそのまま配信する。
    (SITE / ".nojekyll").touch()


def write_manifest(
    notebooks: list[Notebook], updated_notebooks: list[Notebook] | None = None
) -> None:
    """ソースと生成HTMLの SHA-256 を記録する。

    部分ビルドでは既存 manifest を読み、更新した冊のハッシュだけ差し替える。
    全冊を取り直すと、編集済みだが未再生成の冊まで「最新」と記録され、
    鮮度ゲートが素通りする。
    """
    manifest_path = SITE / "notebooks-manifest.json"
    if updated_notebooks is None:
        entries: dict[str, dict[str, str]] = {}
        targets = notebooks
    else:
        if not manifest_path.exists():
            raise FileNotFoundError(
                "A partial build requires an existing manifest; run a full build first."
            )
        entries = json.loads(manifest_path.read_text(encoding="utf-8")).get(
            "notebooks", {}
        )
        targets = updated_notebooks
    for notebook in targets:
        if not notebook.output.exists():
            raise FileNotFoundError(f"Missing exported notebook: {notebook.output}")
        entries[notebook.relative.as_posix()] = {
            "source_sha256": hashlib.sha256(notebook.source.read_bytes()).hexdigest(),
            "html": notebook.relative.with_suffix(".html").as_posix(),
            "html_sha256": hashlib.sha256(notebook.output.read_bytes()).hexdigest(),
        }
    # notebook の追加・削除後に部分ビルドを続行させない。
    if set(entries) != {notebook.relative.as_posix() for notebook in notebooks}:
        raise ValueError(
            "Manifest source set differs from discovered notebooks; run a full build."
        )
    manifest_path.write_text(
        json.dumps({"version": 1, "notebooks": entries}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--notebook", action="append", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    notebooks = discover()
    if args.notebook:
        selected = {path.with_suffix(".py") for path in args.notebook}
        notebooks = [notebook for notebook in notebooks if notebook.relative in selected]
    if not notebooks:
        print("No marimo notebooks found.", file=sys.stderr)
        return 1

    SITE.mkdir(exist_ok=True)
    if args.discover_only:
        write_index(notebooks)
        print(json.dumps({"notebooks": len(notebooks), "executed": False}))
        return 0

    if not args.notebook:
        # 削除された notebook の HTML が残らないよう、全ビルドでは一度消す。
        for stale_html in SITE.rglob("*.html"):
            stale_html.unlink()
        shutil.rmtree(LOGS, ignore_errors=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    failures = []
    for index, notebook in enumerate(notebooks, start=1):
        print(f"[{index}/{len(notebooks)}] {notebook.relative}", flush=True)
        if failure := export(notebook, LOGS):
            failures.append(failure)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1

    all_notebooks = discover()
    write_index(all_notebooks)
    write_manifest(all_notebooks, notebooks if args.notebook else None)
    print(json.dumps({"notebooks": len(notebooks), "executed": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

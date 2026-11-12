#!/usr/bin/env python3
"""pi-mcp-servers.toml を描画して TOML とスキーマの妥当性を確認する。

pi-mcp-servers.toml は chezmoi テンプレートなので ``check-toml`` が使えない。
構文エラーや壊れた ``[[mcp]]`` はそのまま pi の MCP 設定が生成できない (apply が止まる) ことに
直結するので、描画結果を機械で検査する。

TOML として読めるかは ``scripts/lint_templates.py`` も見る。こちらの主目的は
**``[[mcp]]`` の形** (``generate.mcp_servers`` が受け付けること) の確認。

ユーザによる出し分けがあるので、分岐の両側 (個人の機・会社 PC) を描画して検査する。
chezmoi が無い環境では検査できないので、skip せず失敗させる。

Usage:
    validate_mcp.py [--source REPO]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = "pi-mcp-servers.toml"
INCLUDE = f'{{{{ includeTemplate "{TEMPLATE}" . }}}}'
# 出し分けの両側を通す。pi-mcp-servers.toml に新しい分岐を足したらここも足す。
USERS = ["applejxd", "other-user"]


def render(source: Path, username: str) -> str:
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        raise SystemExit("chezmoi が見つかりません (描画できないので検査できません)")
    context = json.dumps(
        json.dumps({"chezmoi": {"username": username, "homeDir": "/validate-home"}})
    )
    result = subprocess.run(
        [
            chezmoi,
            "--source",
            str(source),
            "execute-template",
            f"{{{{ with {context} | fromJson }}}}{INCLUDE}{{{{ end }}}}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"{username}: 描画に失敗しました\n{result.stderr}")
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(REPO), help="リポジトリのルート")
    parser.add_argument("paths", nargs="*", help="pre-commit が渡すファイル (未使用)")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(Path(args.source) / "scripts" / "agents"))
    import generate as gen

    for username in USERS:
        rendered = render(Path(args.source), username)
        try:
            declared = tomllib.loads(rendered)
        except tomllib.TOMLDecodeError as exc:
            raise SystemExit(f"{username}: 描画結果が TOML として不正です: {exc}") from exc

        if not declared.get("mcp"):
            raise SystemExit(f"{username}: [[mcp]] が空です")

        try:
            gen.mcp_servers(declared)
        except ValueError as exc:
            raise SystemExit(f"{username}: [[mcp]] が不正です: {exc}") from exc

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""common.toml を描画して TOML とスキーマの妥当性を確認する。

common.toml は chezmoi テンプレートなので ``check-toml`` が使えない。
このファイルは hook が fail-closed で読むポリシーの正本で、構文エラーは
そのまま「全部 deny」に直結するため、描画結果を機械で検査する。

TOML として読めるかは ``scripts/lint_templates.py`` も見る。こちらの主目的は
**ポリシー固有のスキーマ** (必須の deny リスト、``[[mcp]]`` の形) の確認。

ユーザによる出し分けがあるので、分岐の両側を描画して検査する。
chezmoi が無い環境では検査できないので、skip せず失敗させる。

Usage:
    validate_common.py [--source REPO]
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
TEMPLATE = "dot_config/agents/common.toml.tmpl"
INCLUDE = f'{{{{ includeTemplate "{TEMPLATE}" . }}}}'
# 出し分けの両側を通す。common.toml に新しい分岐を足したらここも足す。
USERS = ["applejxd", "other-user"]
# 欠けると hook が fail-closed で全部 deny するキー
REQUIRED = [
    ("bash", "deny"),
    ("bash", "ask"),
    ("bash", "allow"),
    ("file", "read_deny_globs"),
    ("sandbox", "deny"),
]


def render(source: Path, username: str) -> str:
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        raise SystemExit("chezmoi が見つかりません (描画できないので検査できません)")
    context = json.dumps(json.dumps({"chezmoi": {"username": username}}))
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
            common = tomllib.loads(rendered)
        except tomllib.TOMLDecodeError as exc:
            raise SystemExit(f"{username}: 描画結果が TOML として不正です: {exc}") from exc

        for section, key in REQUIRED:
            if not common.get(section, {}).get(key):
                raise SystemExit(f"{username}: [{section}] {key} が空です")

        try:
            gen.mcp_servers(common)
        except ValueError as exc:
            raise SystemExit(f"{username}: [[mcp]] が不正です: {exc}") from exc

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""chezmoi テンプレートを描画して、描画後の言語の linter にかける。

``identify`` は ``*.tmpl`` に一切タグを付けないため、pre-commit の
``check-toml`` / ruff / shellcheck はテンプレートを素通りする。
描画してから振り分けることで、通常のファイルと同じ検査を通す。

分岐の両側を通すために、ファイルごとに描画コンテキストを変える:

- OS 軸は ``home/.chezmoiscripts/`` のディレクトリ規約から決める
  (``100_linux/`` なら linux だけ、など)。
- username 軸は ``.chezmoi.username`` を参照するファイルだけ 2 通り回す。

``--skip-secrets`` を付けるので Bitwarden 等は呼ばれない。秘密を使う
テンプレートは chezmoi が "skip template" を返すので、それはスキップ扱いにする。

Usage:
    lint_templates.py [--source REPO] [PATH...]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# ディレクトリ規約は docs/spec/structure.md を参照
OS_BY_DIRECTORY = {
    "000_unix": ("linux", "darwin"),
    "100_linux": ("linux",),
    "200_mac": ("darwin",),
    "300_windows": ("windows",),
    "400_unix": ("linux", "darwin"),
}
EVERY_OS = ("linux", "darwin", "windows")
# 「個人用」と「それ以外」の両方の分岐を通す
USERS = ("applejxd", "other-user")

EXCLUDED = {
    # `execute-template --init` が要る (別経路)
    "home/.chezmoi.toml.tmpl",
    # 描画結果は ignore 記法で、対応する linter が無い
    "home/.chezmoiignore.tmpl",
}
# 単体では描画できない (呼び出し側から dict を受け取る)。
# test_modifier_wrappers.py が呼び出し側ごと検査している。
EXCLUDED_PREFIXES = ("home/.chezmoitemplates/",)

# chezmoi が --skip-secrets でテンプレートを飛ばすときの目印
SKIP_SENTINEL = "skip template"


def lint_toml(rendered: str) -> str | None:
    import tomllib

    try:
        tomllib.loads(rendered)
    except tomllib.TOMLDecodeError as exc:
        return str(exc)
    return None


def lint_python(rendered: str) -> str | None:
    try:
        compile(rendered, "<rendered>", "exec")
    except SyntaxError as exc:
        return f"{exc.msg} (line {exc.lineno})"
    return None


def lint_shell(rendered: str) -> str | None:
    if shutil.which("shellcheck") is None:
        raise SystemExit("shellcheck が見つかりません")
    # shebang があれば shellcheck に方言を判定させる (既存の *.sh と同じ扱い)。
    # source される断片には shebang が無いので、そのときだけ bash を仮定する。
    dialect = [] if rendered.lstrip().startswith("#!") else ["-s", "bash"]
    result = subprocess.run(
        ["shellcheck", *dialect, "-"],
        input=rendered,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or None if result.returncode != 0 else None


# 拡張子 -> linter。ここに足せば対象が広がる。
# .ps1 は PSScriptAnalyzer (pwsh 本体) が要るため対象外。
# .zsh は shellcheck が zsh をサポートしないため対象外
# (bash として検査すると `else;` 等が誤検知になる)。
LINTERS = {
    ".toml": lint_toml,
    ".py": lint_python,
    ".sh": lint_shell,
}


def target_platforms(path: str) -> tuple[str, ...]:
    for directory, platforms in OS_BY_DIRECTORY.items():
        if f"/{directory}/" in f"/{path}":
            return platforms
    return EVERY_OS


def target_users(text: str) -> tuple[str, ...]:
    return USERS if ".chezmoi.username" in text else USERS[:1]


def render(source: Path, text: str, platform: str, username: str) -> tuple[str | None, str]:
    """(描画結果, 理由) を返す。秘密でスキップしたときは (None, 理由)。"""
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        raise SystemExit("chezmoi が見つかりません (描画できないので検査できません)")
    override = json.dumps({"chezmoi": {"os": platform, "username": username}})
    result = subprocess.run(
        [
            chezmoi,
            "--source",
            str(source),
            "execute-template",
            "--skip-secrets",
            "--override-data",
            override,
        ],
        input=text,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        if SKIP_SENTINEL in result.stderr:
            return None, "秘密を含むためスキップ"
        return None, f"描画に失敗しました\n{result.stderr.strip()}"
    return result.stdout, ""


def check(source: Path, path: str) -> list[str]:
    text = (source / path).read_text(encoding="utf-8-sig")
    suffix = Path(path).with_suffix("").suffix
    linter = LINTERS.get(suffix)
    if linter is None:
        return []

    failures: list[str] = []
    for platform in target_platforms(path):
        for username in target_users(text):
            where = f"{path} [os={platform} user={username}]"
            rendered, reason = render(source, text, platform, username)
            if rendered is None:
                if not reason.startswith("秘密"):
                    failures.append(f"{where}: {reason}")
                continue
            # {{ if }} で中身が全部消えるテンプレートがある
            if not rendered.replace("\ufeff", "").strip():
                continue
            problem = linter(rendered)
            if problem:
                failures.append(f"{where}:\n{problem}")
    return failures


def templates(source: Path, paths: list[str]) -> list[str]:
    if not paths:
        listed = subprocess.run(
            ["git", "-C", str(source), "ls-files", "*.tmpl"],
            capture_output=True,
            text=True,
            check=True,
        )
        paths = listed.stdout.split()
    return [
        path
        for path in sorted(paths)
        if path.endswith(".tmpl")
        and path not in EXCLUDED
        and not path.startswith(EXCLUDED_PREFIXES)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(REPO), help="リポジトリのルート")
    parser.add_argument("paths", nargs="*", help="検査するテンプレート (既定は全件)")
    args = parser.parse_args(argv)

    source = Path(args.source)
    failures: list[str] = []
    for path in templates(source, args.paths):
        failures.extend(check(source, path))

    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

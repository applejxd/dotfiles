#!/usr/bin/env python3
"""SKILL.md の YAML frontmatter を検証する。

Claude Code / Copilot CLI は frontmatter のパースに失敗したスキルを黙って
読み飛ばし、起動時に "Failed to load 1 skill." とだけ表示する。原因の特定に
`copilot skill list` が要るので、リポジトリ側で先に弾く。

実行方法:

    # 全 SKILL.md
    uv run --with pyyaml --no-project python scripts/agents/validate_skills.py

    # ファイルを明示（pre-commit が渡す形）
    uv run --with pyyaml --no-project python scripts/agents/validate_skills.py PATH...
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

# ホームに配る skill は chezmoi のソースツリー配下にまとまっている。
SKILL_GLOB = "home/*/skills/*/SKILL.md"

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Anthropic / GitHub 双方のローダが description をこの長さで切る。
MAX_DESCRIPTION_LEN = 1024

# 引用符なしの平文スカラーでは YAML の構文として特別扱いされ、
# パースエラーか無言の切り詰めを起こす並び。
FRAGILE_PLAIN_PATTERNS = {
    ": ": "コロン+空白は mapping value と解釈される",
    " #": "空白+# 以降がコメントとして捨てられる",
}


def split_frontmatter(text: str) -> tuple[str, str] | None:
    """先頭の `---` ブロックを (frontmatter, 残り) で返す。無ければ None。"""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    return text[4:end], text[end + 4 :]


def raw_value(frontmatter: str, key: str) -> str | None:
    """`key:` の行に書かれた値を、YAML に解釈させる前の文字列で返す。"""
    for line in frontmatter.split("\n"):
        if line.startswith(f"{key}:"):
            return line[len(key) + 1 :].strip()
    return None


def check_plain_scalar(frontmatter: str, key: str, errors: list[str]) -> None:
    """引用符なしで書くと壊れる値を、パースが通っていても弾く。"""
    value = raw_value(frontmatter, key)
    if value is None or value[:1] in {"'", '"', "|", ">"}:
        return
    for pattern, reason in FRAGILE_PLAIN_PATTERNS.items():
        if pattern in value:
            errors.append(
                f"{key} に {pattern!r} が含まれるので引用符で囲むこと"
                f"（{reason}）"
            )


def validate(path: Path) -> list[str]:
    """1 つの SKILL.md を検証し、エラーメッセージの一覧を返す。"""
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")

    parts = split_frontmatter(text)
    if parts is None:
        return ["先頭の `---` で囲んだ YAML frontmatter が無い"]
    frontmatter, _ = parts

    try:
        data = yaml.safe_load(frontmatter)
    except yaml.YAMLError as exc:
        return [f"frontmatter の YAML パースに失敗: {exc}"]

    if not isinstance(data, dict):
        return ["frontmatter がマッピングになっていない"]

    name = data.get("name")
    if not isinstance(name, str) or not name:
        errors.append("name が無い、または文字列でない")
    else:
        if not NAME_RE.match(name):
            errors.append(f"name {name!r} は小文字英数とハイフンのみにすること")
        if name != path.parent.name:
            errors.append(
                f"name {name!r} がディレクトリ名 {path.parent.name!r} と一致しない"
            )

    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append("description が無い、または空")
    elif len(description) > MAX_DESCRIPTION_LEN:
        errors.append(
            f"description が {len(description)} 文字で "
            f"{MAX_DESCRIPTION_LEN} 文字を超える"
        )

    for key in ("name", "description"):
        check_plain_scalar(frontmatter, key, errors)

    return errors


def collect(argv: list[str]) -> list[Path]:
    if argv:
        return [Path(a) for a in argv]
    return sorted(ROOT.glob(SKILL_GLOB))


def main(argv: list[str]) -> int:
    paths = collect(argv)
    if not paths:
        print("SKILL.md が見つからない", file=sys.stderr)
        return 1

    failed = 0
    for path in paths:
        errors = validate(path)
        if errors:
            failed += 1
            for error in errors:
                print(f"{path}: {error}", file=sys.stderr)

    if failed:
        print(f"\n{failed} 件の SKILL.md が不正", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""環境変数の診断 (読み取り専用)。値を出してよいものだけを出す。

    python3 ~/.claude/skills/env-check/scripts/env_check.py names
    python3 ~/.claude/skills/env-check/scripts/env_check.py show
    python3 ~/.claude/skills/env-check/scripts/env_check.py get NAME

  names  変数名だけを並べる (値は出さない)
  show   許可リストの値と、プロキシ・ブローカー系の値を出す (URL の認証情報は伏せる)
  get    1 つの変数の設定の有無。値は許可リストかプロキシ・ブローカー系だけ。それ以外は長さだけ

秘密らしい名前 (TOKEN / KEY / SECRET など) は、どの形でも値を出さない。
許可リストは hook が使う tables.toml の ``[rules_files] env_readable_names`` と同じ。
see docs/spec/guard/agent-command-policy.md#環境変数の診断
"""

from __future__ import annotations

import os
import re
import sys
import tomllib
from pathlib import Path

# bashrules/_shared.py の _SENSITIVE_ENV_RE と同じ (試験 test_env_check.py が一致を固定する)
SENSITIVE_ENV_PATTERN = (
    r"(?:SECRET|TOKEN|PASSWORD|PASSWD|PASSPHRASE|CREDENTIAL|SESSION"
    r"|API[_-]?KEY|PRIV(?:ATE)?[_-]?KEY|ACCESS[_-]?KEY"
    r"|(?:^|[_-])(?:PAT|KEY|AUTH)S?(?:[_-]|$))"
)
SENSITIVE = re.compile(SENSITIVE_ENV_PATTERN, re.IGNORECASE)
# 値を (認証情報を伏せて) 見せる、通信まわりの変数
NETWORK = re.compile(r"proxy|broker|_CA_BUNDLE|SSL_CERT|BASE_URL", re.IGNORECASE)
USERINFO = re.compile(r"(?<=://)[^/@\s,]*@")


def _tables_path() -> Path:
    here = Path(__file__).resolve()
    candidates = []
    if len(here.parents) > 5:  # リポジトリのソースから動かすとき
        candidates.append(
            here.parents[5] / "home" / "dot_config" / "pi" / "harness" / "judge" / "tables.toml"
        )
    candidates.append(Path.home() / ".config" / "pi" / "harness" / "judge" / "tables.toml")
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError("tables.toml が見つからない: " + ", ".join(map(str, candidates)))


def readable_names() -> list[str]:
    with _tables_path().open("rb") as fh:
        return list(tomllib.load(fh)["rules_files"]["env_readable_names"])


def mask(value: str) -> str:
    """URL の認証情報 (``user:pass@``) を伏せる。"""
    return USERINFO.sub("***@", value)


def describe(name: str, readable: list[str]) -> str:
    """``name`` の表示。値を出してよいときだけ値を含める。"""
    if name not in os.environ:
        return f"{name}: (未設定)"
    value = os.environ[name]
    if SENSITIVE.search(name):
        return f"{name}: (設定あり。秘密の名前なので値は出さない)"
    if name in readable or NETWORK.search(name):
        return f"{name}={mask(value)}"
    return f"{name}: (設定あり。{len(value)} 文字。許可リスト外なので値は出さない)"


def cmd_names() -> int:
    for name in sorted(os.environ):
        print(name)
    return 0


def cmd_show() -> int:
    readable = readable_names()
    shown = sorted(
        {n for n in os.environ if n in readable or (NETWORK.search(n) and not SENSITIVE.search(n))}
    )
    for name in shown:
        print(describe(name, readable))
    unset = [n for n in readable if n not in os.environ]
    if unset:
        print("# 許可リストのうち未設定: " + ", ".join(unset))
    hidden = sum(1 for n in os.environ if n not in shown)
    print(f"# 値を出さない変数: {hidden} 個 (`names` で名前だけ見られる)")
    return 0


def cmd_get(name: str) -> int:
    print(describe(name, readable_names()))
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 1 and argv[0] == "names":
        return cmd_names()
    if len(argv) == 1 and argv[0] == "show":
        return cmd_show()
    if len(argv) == 2 and argv[0] == "get" and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", argv[1]):
        return cmd_get(argv[1])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

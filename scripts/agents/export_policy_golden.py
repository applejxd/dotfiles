"""判定器の部品 (shlex・コマンドの分割と正規化・照合) の正解データを書き出す。

``export_decide_golden.py`` は判定の入口 (``decide()``) の結果を残すが、食い違ったときに
どの部品が原因かを切り分けにくい。ここでは、TS へ移す部品ごとに Python 版の出力を残す:

- ``shlex``: ``shlex.split`` (POSIX モード)。引用が閉じない等のエラーも残す
- ``split``: ``split_command_segments``
- ``normalize``: ``normalize``
- ``subst`` / ``funcs``: ``extract_command_substitutions`` / ``extract_function_bodies``
- ``find_match``: deny / ask / allow の各一覧に対する ``find_match``

入力は、hook の試験のコマンド、その正規化後のセグメント、手書きの境界の入力。
正規化は ``decide()`` と同じく、1 回ごとに状態を初期化して流す。

使い方::

    uv run --no-project --with pytest,pyyaml python scripts/agents/export_policy_golden.py
    uv run --no-project --with pytest,pyyaml python scripts/agents/export_policy_golden.py --check

see docs/spec/pi-decide.md#ts-版への移植
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "test" / "agents" / "golden" / "policy_golden.jsonl"

sys.path.insert(0, str(ROOT / "test" / "agents"))
from agents_common import agents_config_dir  # noqa: E402

CONFIG_DIR = agents_config_dir()
os.environ["AGENTS_CONFIG_DIR"] = str(CONFIG_DIR)
sys.path.insert(0, str(ROOT / "home" / "dot_claude" / "hooks" / "lib"))
from policy_loader import load_policy  # noqa: E402
from test_decide import _hook_test_commands  # noqa: E402

policy = load_policy().module

# 手書きの境界の入力 (引用・エスケープ・空白・Unicode など)
EXTRA = (
    "",
    " ",
    "\t",
    "'",
    '"',
    "\\",
    "a\\",
    "''",
    '""',
    "x ''",
    "'a' \"b\" c",
    'a"b c"d',
    "a\\ b",
    '"a\\"b"',
    '"a\\nb"',
    "'a\\\\'",
    "a\tb\nc",
    "a'b",
    "$'a b'",
    "echo $(date)",
    "echo `date`",
    "ls  -l\u3000/tmp",
    "echo 日本語 'テスト'",
    "echo \U0001f600 \\\U0001f600",
    "cd /x && git push",
    "git -C /x -C /y status",
    "FOO=1 BAR='a b' cmd arg",
    "/usr/bin/git --no-pager push",
    "timeout 5s git push",
    "timeout -k 3 5 git push",
    "xargs -I{} sh -c 'git push {}'",
    "find . -exec git push \\;",
    "find . -exec git push {} +",
    "env -u LANG bash -c 'git push'",
    "if true; then git push; fi",
    "case x in x) git push;; esac",
    "f() { git push; }; f",
    "function g { git push; }",
    "alias gp='git push'; gp",
    "p=push; git $p",
    "p=push q=origin; git $p $q",
    "bash <<< 'git push'",
    "make -f /dev/stdin <<< 'all:\\n\\tgit push'",
    "sh <(echo git push)",
    "python3 -c \"os.system('git push')\"",
    "perl -e 'system(\"git push\")'",
    "awk 'BEGIN{system(\"git push\")}'",
    "docker run --rm -it ubuntu git push",
    "tmux new-session -d 'git push'",
    "screen -dm git push",
    "git submodule foreach 'git push'",
    "mise exec -- git push",
    "npm run x -- git push",
    "uv run python -c 'import os'",
    "npm -g install x",
    "npm install --global x",
    "npm i -g x",
    "git send-pack",
    "gh -R a/b pr list",
    "gh --hostname github.com api x",
    "constructor push",
    "__proto__ push",
    "toString -c x",
    "trap 'git push' EXIT",
    "eval 'git push'",
    "source ./x.sh",
    "$SHELL -c 'git push'",
    "! git push",
    "(git push)",
    "{ git push; }",
    "> /dev/null git push",
    "2>&1 git push",
    "echo a | sh",
    "a && b || c ; d & e\nf",
)


def corpus() -> list[str]:
    seen: dict[str, None] = {}
    for command in [*_hook_test_commands(), *EXTRA]:
        seen.setdefault(command, None)
    return list(seen)


def _shlex(s: str) -> Any:
    try:
        return {"tokens": shlex.split(s)}
    except ValueError as exc:
        return {"error": str(exc)}


def _reset() -> None:
    """判定のたびに、プロセス内の状態を初期化する (decide() と同じ前提)。"""
    from bashrules import _shared

    _shared._LITERAL_HEREDOC_BODIES.clear()


def _patterns() -> dict[str, list[str]]:
    with (CONFIG_DIR / "common.toml").open("rb") as f:
        data = tomllib.load(f)
    return {
        "deny": list(data.get("bash", {}).get("deny", [])),
        "ask": list(data.get("bash", {}).get("ask", [])),
        "allow": list((data.get("pi", {}).get("shell", {}) or {}).get("allow", [])),
    }


def build() -> list[str]:
    commands = corpus()
    patterns = _patterns()
    entries: list[dict[str, Any]] = []
    shlex_inputs: dict[str, None] = {}
    for command in commands:
        _reset()
        normalized = policy.normalize(command)
        entries.append(
            {"fn": "split", "arg": command, "out": policy.split_command_segments(command)}
        )
        entries.append({"fn": "normalize", "arg": command, "out": normalized})
        entries.append(
            {"fn": "subst", "arg": command, "out": policy.extract_command_substitutions(command)}
        )
        entries.append(
            {"fn": "funcs", "arg": command, "out": policy.extract_function_bodies(command)}
        )
        for name, pats in patterns.items():
            entries.append(
                {
                    "fn": "find_match",
                    "list": name,
                    "arg": command,
                    "out": policy.find_match(command, pats),
                }
            )
        shlex_inputs.setdefault(command, None)
        for segment in normalized:
            shlex_inputs.setdefault(segment, None)
    for s in shlex_inputs:
        entries.append({"fn": "shlex", "arg": s, "out": _shlex(s)})
    return [json.dumps(e, ensure_ascii=False, sort_keys=True) for e in entries]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="書き出さず、いまのファイルが最新か確かめる"
    )
    args = parser.parse_args()
    lines = build()
    text = "\n".join(lines) + "\n"
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if current != text:
            print(f"古い: {OUT.relative_to(ROOT)} (引数なしで書き出し直す)")
            return 1
        print(f"最新: {len(lines)} 件")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"{len(lines)} 件を書き出した: {OUT.relative_to(ROOT)} ({len(text) // 1024} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

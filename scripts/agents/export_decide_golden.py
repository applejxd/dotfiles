"""判定 API (``decide``) の正解データを書き出す。TS 版との差分試験に使う。

Python 版の ``decide()`` を、固定の入力の集合に流して、その応答を JSONL に残す。
TS へ移植した判定器は、同じ入力で同じ応答 (decision / source / reason など) を返すことを確かめる。

- 入力: ``test_check_bash_*.py`` に並ぶコマンド (hook の試験と同じ集合) × 役割 × bypass、
  ファイルツールと対象パスの組、そのほかのツール、形の壊れた入力
- パスは ``${ROOT}`` (このリポジトリ) と ``${HOME}`` の記号に置き換えて保存する。
  試験側が自分の場所に展開して使う (Linux・WSL・Windows で同じデータが使える)
- 規則 (``common.toml``) が変わると応答が変わる。``--check`` で最新かどうかを確かめる

使い方::

    uv run --no-project --with pytest,pyyaml python scripts/agents/export_decide_golden.py
    uv run --no-project --with pytest,pyyaml python scripts/agents/export_decide_golden.py --check

see docs/spec/pi-decide.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "test" / "agents" / "golden" / "decide_golden.jsonl"
COMMON_OUT = ROOT / "test" / "agents" / "golden" / "common.json"

sys.path.insert(0, str(ROOT / "test" / "agents"))
from agents_common import agents_config_dir  # noqa: E402

CONFIG_DIR = agents_config_dir()
os.environ["AGENTS_CONFIG_DIR"] = str(CONFIG_DIR)
sys.path.insert(0, str(ROOT / "home" / "dot_claude" / "hooks" / "lib"))
from decide import decide  # noqa: E402
from test_decide import _hook_test_commands  # noqa: E402

ROLES = ("implementer", "reader", "committer", "worker")
HOME = str(Path.home())

# ファイルツールの対象。${ROOT} / ${HOME} は試験側で展開する
FILE_TOOLS = ("read", "grep", "find", "ls", "edit", "write")
FILE_PATHS = (
    "README.md",
    "docs/spec/pi-decide.md",
    "${ROOT}/README.md",
    "${ROOT}/home/dot_config/pi/harness/index.ts",
    "${ROOT}/no-such-file.txt",
    ".env",
    ".env.example",
    "src/../.env",
    "${ROOT}/.git/config",
    "${HOME}/.ssh/id_rsa",
    "${HOME}/.aws/credentials",
    "${HOME}/.config/gh/hosts.yml",
    "~/.ssh/id_rsa",
    "/etc/passwd",
    "/etc/shadow",
    "../outside.txt",
    "/tmp/scratch.txt",
    ".",
)
FILE_CWDS = ("${ROOT}", "/tmp")

OTHER_TOOLS = (
    {"tool": "task", "input": {"agent": "explore", "task": "x"}},
    {"tool": "todo", "input": {"action": "list"}},
    {"tool": "mcp__x__y", "input": {}},
    {"tool": "unknown", "input": {}},
)

INVALID = (
    None,
    [],
    "bash",
    {"tool": "bash"},
    {"tool": "bash", "input": {"command": "ls"}, "cwd": "relative", "role": "implementer"},
    {"tool": "bash", "input": {"command": "ls"}, "cwd": "/", "role": "nobody"},
    {
        "tool": "bash",
        "input": {"command": "ls"},
        "cwd": "/",
        "role": "implementer",
        "bypass": "yes",
    },
    {"tool": "bash", "input": {}, "cwd": "/", "role": "implementer"},
    {"tool": "read", "input": {}, "cwd": "/", "role": "implementer"},
    {"tool": 1, "input": {}, "cwd": "/", "role": "implementer"},
)


def _expand(value: Any) -> Any:
    """${ROOT} / ${HOME} を、いまの場所に展開する。"""
    if isinstance(value, str):
        return value.replace("${ROOT}", str(ROOT)).replace("${HOME}", HOME)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def _tokenize(value: Any) -> Any:
    """いまの場所を ${ROOT} / ${HOME} に戻す (長い方を先に置き換える)。"""
    if isinstance(value, str):
        return value.replace(str(ROOT), "${ROOT}").replace(HOME, "${HOME}")
    if isinstance(value, list):
        return [_tokenize(v) for v in value]
    if isinstance(value, dict):
        return {k: _tokenize(v) for k, v in value.items()}
    return value


def _request(
    tool: str, role: str, cwd: str, bypass: bool = False, **tool_input: Any
) -> dict[str, Any]:
    return {"tool": tool, "input": tool_input, "cwd": cwd, "role": role, "bypass": bypass}


def requests() -> list[Any]:
    """記号つきの入力の一覧 (順序は固定)。"""
    out: list[Any] = []
    for command in _hook_test_commands():
        for role in ROLES:
            out.append(_request("bash", role, "${ROOT}", command=command))
        out.append(_request("bash", "implementer", "${ROOT}", bypass=True, command=command))
    for tool in FILE_TOOLS:
        for role in ROLES:
            for cwd in FILE_CWDS:
                for path in FILE_PATHS:
                    out.append(_request(tool, role, cwd, path=path))
                    if role == "implementer":
                        out.append(_request(tool, role, cwd, bypass=True, path=path))
    for other in OTHER_TOOLS:
        for role in ROLES:
            out.append({**other, "cwd": "${ROOT}", "role": role, "bypass": False})
    out.extend(INVALID)
    return out


def build() -> list[str]:
    lines = []
    for request in requests():
        response = decide(_expand(request))
        lines.append(
            json.dumps(
                {"request": request, "response": _tokenize(response)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return lines


def common_json() -> str:
    """描画した common.toml を JSON にしたもの。TS 版の判定器が読む (TOML は TS で読まない)。"""
    with (CONFIG_DIR / "common.toml").open("rb") as f:
        data = tomllib.load(f)
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="書き出さず、いまのファイルが最新か確かめる"
    )
    args = parser.parse_args()
    lines = build()
    text = "\n".join(lines) + "\n"
    common = common_json()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        current_common = COMMON_OUT.read_text(encoding="utf-8") if COMMON_OUT.is_file() else ""
        if current != text or current_common != common:
            print(f"古い: {OUT.relative_to(ROOT)} (規則か判定器が変わった。引数なしで書き出し直す)")
            return 1
        print(f"最新: {len(lines)} 件")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    COMMON_OUT.write_text(common, encoding="utf-8", newline=chr(10))
    print(f"{len(lines)} 件を書き出した: {OUT.relative_to(ROOT)} ({len(text) // 1024} KiB)")
    print(f"設定を書き出した: {COMMON_OUT.relative_to(ROOT)} ({len(common) // 1024} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

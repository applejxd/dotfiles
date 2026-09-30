#!/usr/bin/env python3
"""away-shift skill の事前判定 (pre-flight)。

無人実行で最も困るのは、承認プロンプトが出たまま誰も答えず、離席時間を丸ごと
無駄にすることである。プロンプトは**コマンドを実行する前**に出るので、
タイムアウトでは救えない。実行してから困るのではなく、**実行する前に同じ
判定器へ問い合わせて避ける**。

判定には PreToolUse hook 本体 (``~/.claude/hooks/check_bash.py``) をそのまま
使う。Claude Code と Copilot CLI が実際に使うものと同じなので、予測と実際が
ずれない。

    $ preflight.py "git commit -m x"
    ASK  `git commit` は承認が必要な操作です ...

exit code:

    0  hook の判定上は許可 (hook は正常終了し、沈黙または allow を返した)。
       CLI の permission / sandbox 全体で承認が不要なことまでは保証しない
    3  承認を求められる (ask) / 拒否される (deny)。実行しないこと
    2  判定不能 (判定器が無い・非ゼロ終了・タイムアウト・不正な出力)。
       実行しないこと

判定できるのは bash コマンドだけで、ファイル書き込みツールは対象外。
また hook の判定であって、CLI 側の事前承認設定は考慮しない (事前承認は
プロンプトを減らす方向にしか働かないので、安全側の見積もりになる)。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK_PATH = Path.home() / ".claude" / "hooks" / "check_bash.py"

EXIT_SAFE = 0
EXIT_BLOCKED = 3
EXIT_UNAVAILABLE = 2


def decide(command: str, cwd: str) -> tuple[str, str]:
    """(判定, 理由) を返す。判定は "allow" / "ask" / "deny"。"""
    if not HOOK_PATH.exists():
        raise FileNotFoundError(f"判定器が見つかりません: {HOOK_PATH}")
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "bash",
            "tool_input": {"command": command},
            "cwd": cwd,
        }
    )
    try:
        proc = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("判定器がタイムアウトしました") from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip().splitlines()[-1:] or [""]
        raise RuntimeError(f"判定器が終了コード {proc.returncode} で終了: {detail[0]}")
    out = proc.stdout.strip()
    if not out:
        return "allow", ""
    try:
        data = json.loads(out)
        verdict = data["permissionDecision"]
        reason = data.get("permissionDecisionReason", "")
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise RuntimeError(f"判定器の出力を解釈できません: {out[:200]}") from exc
    if verdict not in ("allow", "ask", "deny") or not isinstance(reason, str):
        raise RuntimeError(f"判定器の出力が不正です: {out[:200]}")
    return verdict, reason


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", help="実行しようとしている bash コマンド")
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument(
        "--quiet", action="store_true", help="判定だけを出力する (理由を省く)"
    )
    args = parser.parse_args(argv)

    try:
        verdict, reason = decide(args.command, args.cwd)
    except Exception as exc:
        print(f"判定できません: {exc}", file=sys.stderr)
        return EXIT_UNAVAILABLE

    if verdict == "allow":
        print("ALLOW")
        return EXIT_SAFE
    label = verdict.upper()
    print(label if args.quiet else f"{label}  {reason.splitlines()[0] if reason else ''}")
    return EXIT_BLOCKED


if __name__ == "__main__":
    sys.exit(main())

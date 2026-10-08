#!/usr/bin/env python3
"""CHG-0019 段 3 の試作用の判定 API。本物の判定器ではなく、契約だけを持つ最小の実装。

入力: stdin に {"tool", "input", "cwd"}。出力: {"decision": allow|ask|deny, "reason"}。
see docs/research/agents/pi-harness-spike.md
"""

import json
import os
import sys
import time

ALLOW = ("echo ", "pwd", "ls", "python3 ")
FILE_TOOLS = ("read", "grep", "find", "ls")
WRITE_TOOLS = ("edit", "write")
DENY = ("rm -rf", "cat ~/.ssh")


def decide(req: dict) -> dict:
    tool = req.get("tool")
    if tool in FILE_TOOLS or tool in WRITE_TOOLS:
        path = str(req.get("input", {}).get("path", "."))
        if ".ssh" in path or path.endswith(".env"):
            return {"decision": "deny", "reason": "secret path"}
        if tool in WRITE_TOOLS:
            cwd = os.path.realpath(str(req.get("cwd", ".")))
            full = os.path.realpath(os.path.join(cwd, os.path.expanduser(path)))
            if not full.startswith(cwd + os.sep):
                return {"decision": "ask", "reason": f"outside cwd: {path}"}
        return {"decision": "allow", "reason": tool}
    if tool == "bash":
        cmd = str(req.get("input", {}).get("command", ""))
        if any(cmd.startswith(p) for p in DENY):
            return {"decision": "deny", "reason": f"denied: {cmd}"}
        if any(cmd.startswith(p) for p in ALLOW) and not any(c in cmd for c in ";&|><`$"):
            return {"decision": "allow", "reason": "listed"}
        return {"decision": "ask", "reason": f"unlisted: {cmd}"}
    if tool == "task":
        return {"decision": "allow", "reason": "child runs under the same guard"}
    if tool in os.environ.get("SPIKE_ALLOW_TOOLS", "").split(","):
        return {"decision": "allow", "reason": "allowed by SPIKE_ALLOW_TOOLS"}
    return {"decision": "deny", "reason": f"unknown tool: {tool}"}


def main() -> None:
    mode = os.environ.get("SPIKE_POLICY_FAULT", "")
    if mode == "empty":
        return
    if mode == "invalid":
        print("{not json")
        return
    if mode == "crash":
        sys.exit(2)
    if mode == "timeout":
        time.sleep(10)
    if mode == "wrong-shape":
        print(json.dumps({"decision": "yes"}))
        return
    print(json.dumps(decide(json.load(sys.stdin))))


if __name__ == "__main__":
    main()

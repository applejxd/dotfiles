from __future__ import annotations

import argparse
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


def evaluate(query: str, cwd: Path, timeout: int) -> bool:
    environment = os.environ.copy()
    environment.pop("CLAUDECODE", None)
    command = [
        "claude",
        "-p",
        query,
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
    ]
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "assistant":
            continue
        for block in event.get("message", {}).get("content", []):
            if block.get("type") != "tool_use":
                continue
            name = block.get("name", "")
            tool_input = block.get("input", {})
            if name == "Skill" and "powerpoint-studio" in str(tool_input.get("skill", "")):
                return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate real Claude skill triggering.")
    parser.add_argument("eval_set", type=Path)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    items: list[dict[str, Any]] = json.loads(args.eval_set.read_text(encoding="utf-8"))
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        triggered = list(
            executor.map(
                lambda item: evaluate(item["query"], args.cwd, args.timeout),
                items,
            )
        )
    results = []
    for item, did_trigger in zip(items, triggered, strict=True):
        expected = bool(item["should_trigger"])
        results.append(
            {
                **item,
                "triggered": did_trigger,
                "passed": did_trigger == expected,
            }
        )
    passed = sum(item["passed"] for item in results)
    report = {
        "summary": {
            "passed": passed,
            "failed": len(results) - passed,
            "total": len(results),
            "pass_rate": passed / len(results),
        },
        "results": results,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

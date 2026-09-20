#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_events(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        events = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
        return events


def value(data: dict[str, Any], *names: str) -> int:
    for name in names:
        if name in data and data[name] is not None:
            return int(data[name])
    return 0


def extract(events: list[dict[str, Any]]) -> dict[str, Any]:
    results = [event for event in events if event.get("type") == "result"]
    if not results:
        raise ValueError("No Claude Code result message found.")
    result = results[-1]
    model_usage = result.get("modelUsage") or result.get("model_usage") or {}
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_write_5m_tokens": 0,
        "cache_write_1h_tokens": 0,
        "cache_read_tokens": 0,
    }
    models = {}
    if isinstance(model_usage, dict) and model_usage:
        for model_name, usage in model_usage.items():
            if not isinstance(usage, dict):
                continue
            normalized = {
                "input_tokens": value(usage, "inputTokens", "input_tokens"),
                "output_tokens": value(usage, "outputTokens", "output_tokens"),
                "cache_write_tokens": value(
                    usage,
                    "cacheCreationInputTokens",
                    "cache_creation_input_tokens",
                    "cacheWriteInputTokens",
                ),
                "cache_read_tokens": value(
                    usage, "cacheReadInputTokens", "cache_read_input_tokens"
                ),
                "cost_usd": usage.get("costUSD", usage.get("cost_usd")),
                "cost_basis": usage.get("costBasis", usage.get("cost_basis")),
            }
            models[model_name] = normalized
            totals["input_tokens"] += normalized["input_tokens"]
            totals["output_tokens"] += normalized["output_tokens"]
            totals["cache_write_5m_tokens"] += normalized["cache_write_tokens"]
            totals["cache_read_tokens"] += normalized["cache_read_tokens"]
    else:
        usage = result.get("usage") or {}
        totals["input_tokens"] = value(usage, "input_tokens", "inputTokens")
        totals["output_tokens"] = value(usage, "output_tokens", "outputTokens")
        totals["cache_write_5m_tokens"] = value(
            usage, "cache_creation_input_tokens", "cacheCreationInputTokens"
        )
        totals["cache_read_tokens"] = value(
            usage, "cache_read_input_tokens", "cacheReadInputTokens"
        )

    return {
        "runtime": "Claude Code",
        "backend": "Amazon Bedrock",
        "actual_usage": totals,
        "actual_cost_override_usd": result.get("total_cost_usd", result.get("totalCostUsd")),
        "actual_cost_source": (
            "Claude Code client-side total_cost_usd estimate; includes subagents. "
            "Reconcile authoritative billing with AWS CUR."
        ),
        "model_usage": models,
        "session_id": result.get("session_id"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract whole-tree usage from Claude Code JSON output."
    )
    parser.add_argument("claude_output", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = extract(read_events(args.claude_output))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

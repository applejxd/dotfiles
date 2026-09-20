#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_write_5m_tokens",
    "cache_write_1h_tokens",
    "cache_read_tokens",
)


def token_cost(usage: dict[str, Any], rates: dict[str, Any], multiplier: float) -> float:
    mapping = {
        "input_tokens": "input_per_mtok",
        "output_tokens": "output_per_mtok",
        "cache_write_5m_tokens": "cache_write_5m_per_mtok",
        "cache_write_1h_tokens": "cache_write_1h_per_mtok",
        "cache_read_tokens": "cache_read_per_mtok",
    }
    total = 0.0
    for token_field, rate_field in mapping.items():
        tokens = float(usage.get(token_field, 0) or 0)
        rate = float(rates.get(rate_field, 0) or 0)
        total += tokens / 1_000_000 * rate * multiplier
    return total


def estimate(config: dict[str, Any]) -> dict[str, Any]:
    rates = config["rates"]
    multiplier = float(config.get("pricing_multiplier", 1.0))
    exchange_rate = float(config.get("exchange_rate", 1.0))
    actual_usage = config.get("actual_usage")
    actual_available = isinstance(actual_usage, dict)
    actual_override = config.get("actual_cost_override_usd")
    actual_usd = (
        float(actual_override)
        if actual_override is not None
        else token_cost(actual_usage, rates, multiplier)
        if actual_available
        else None
    )
    remaining = {}
    for scenario in ("low", "base", "high"):
        usage = config.get("remaining_usage", {}).get(scenario, {})
        usd = token_cost(usage, rates, multiplier)
        remaining[scenario] = {
            "usage": {field: int(usage.get(field, 0) or 0) for field in TOKEN_FIELDS},
            "cost_usd": round(usd, 4),
            "cost_converted": round(usd * exchange_rate, 2),
        }
    return {
        "provider": config.get("provider"),
        "model": config.get("model"),
        "endpoint": config.get("endpoint"),
        "pricing_source": config.get("pricing_source"),
        "pricing_as_of": config.get("pricing_as_of"),
        "pricing_basis": config.get("pricing_basis", "public list price, pre-tax"),
        "currency": config.get("currency", "USD"),
        "exchange_rate": exchange_rate,
        "pricing_multiplier": multiplier,
        "actual_usage_available": actual_available,
        "actual_usage": actual_usage if actual_available else None,
        "actual_cost_source": config.get(
            "actual_cost_source",
            "calculated from token usage and configured rates" if actual_available else None,
        ),
        "actual_cost_usd": round(actual_usd, 4) if actual_usd is not None else None,
        "actual_cost_converted": (
            round(actual_usd * exchange_rate, 2) if actual_usd is not None else None
        ),
        "remaining_estimate": remaining,
        "excluded_costs": config.get(
            "excluded_costs",
            ["tax", "private discounts", "image generation", "storage", "data transfer"],
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate a presentation cost checkpoint.")
    parser.add_argument("config", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = estimate(json.loads(args.config.read_text(encoding="utf-8")))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from scripts.estimate_cost import estimate


def test_cost_estimate_separates_actual_and_forecast() -> None:
    report = estimate(
        {
            "provider": "Bedrock",
            "model": "Sonnet",
            "currency": "JPY",
            "exchange_rate": 150,
            "rates": {
                "input_per_mtok": 2,
                "output_per_mtok": 10,
                "cache_write_5m_per_mtok": 2.5,
                "cache_write_1h_per_mtok": 4,
                "cache_read_per_mtok": 0.2,
            },
            "actual_usage": {
                "input_tokens": 1_000_000,
                "output_tokens": 100_000,
            },
            "remaining_usage": {
                "low": {"input_tokens": 100_000},
                "base": {"input_tokens": 200_000},
                "high": {"input_tokens": 300_000},
            },
        }
    )
    assert report["actual_cost_usd"] == 3
    assert report["actual_cost_converted"] == 450
    assert report["remaining_estimate"]["base"]["cost_usd"] == 0.4


def test_actual_cost_can_be_unavailable() -> None:
    report = estimate(
        {
            "rates": {},
            "remaining_usage": {"low": {}, "base": {}, "high": {}},
        }
    )
    assert not report["actual_usage_available"]
    assert report["actual_cost_usd"] is None

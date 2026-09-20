from scripts.extract_claude_code_usage import extract


def test_extracts_whole_tree_model_usage() -> None:
    report = extract(
        [
            {
                "type": "result",
                "session_id": "abc",
                "total_cost_usd": 1.25,
                "usage": {"input_tokens": 1, "output_tokens": 2},
                "modelUsage": {
                    "claude-sonnet-5": {
                        "inputTokens": 100,
                        "outputTokens": 20,
                        "cacheReadInputTokens": 300,
                        "cacheCreationInputTokens": 40,
                        "costUSD": 1.25,
                        "costBasis": "list",
                    }
                },
            }
        ]
    )
    assert report["actual_cost_override_usd"] == 1.25
    assert report["actual_usage"]["input_tokens"] == 100
    assert report["actual_usage"]["output_tokens"] == 20
    assert report["actual_usage"]["cache_read_tokens"] == 300


def test_uses_last_result_message() -> None:
    report = extract(
        [
            {"type": "result", "total_cost_usd": 1, "usage": {}},
            {
                "type": "result",
                "total_cost_usd": 2,
                "usage": {"input_tokens": 50},
            },
        ]
    )
    assert report["actual_cost_override_usd"] == 2
    assert report["actual_usage"]["input_tokens"] == 50

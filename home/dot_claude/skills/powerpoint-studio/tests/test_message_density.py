from scripts.audit_message_density import audit


def test_focused_slide_passes_with_five_or_fewer_units() -> None:
    plan = {
        "meta": {"message_policy": {"enabled": True}},
        "slides": [
            {
                "role": "mechanism",
                "claim": "検索失敗は観測信号から修理境界へ戻して直す。",
                "message_mode": "focused",
                "detail_policy": "explain",
                "information_units": ["症状", "観測", "境界", "介入"],
                "timing_seconds": 90,
            }
        ],
    }
    assert audit(plan)["passed"]


def test_focused_slide_fails_above_unit_cutoff() -> None:
    plan = {
        "meta": {"message_policy": {"enabled": True, "focused_max_units": 5}},
        "slides": [
            {
                "role": "mechanism",
                "claim": "一枚で多数の独立事項を詳説する。",
                "message_mode": "focused",
                "detail_policy": "explain",
                "information_units": ["a", "b", "c", "d", "e", "f"],
                "timing_seconds": 120,
            }
        ],
    }
    report = audit(plan)
    assert not report["passed"]
    assert any(item["category"] == "information-unit-cutoff" for item in report["findings"])


def test_overview_allows_seven_regions_with_reading_goal() -> None:
    plan = {
        "meta": {"message_policy": {"enabled": True}},
        "slides": [
            {
                "role": "mechanism",
                "claim": "本番境界は六つの責任領域で強制する。",
                "message_mode": "overview",
                "detail_policy": "recognize",
                "reading_goal": "六領域の位置と所有者だけを認識し、細部は読み上げない。",
                "information_units": [
                    "data",
                    "retrieval",
                    "tool",
                    "human",
                    "telemetry",
                    "release",
                ],
                "timing_seconds": 90,
            }
        ],
    }
    assert audit(plan)["passed"]


def test_overview_requires_reading_goal() -> None:
    plan = {
        "meta": {"message_policy": {"enabled": True}},
        "slides": [
            {
                "role": "mechanism",
                "claim": "全体構造を示す。",
                "message_mode": "overview",
                "detail_policy": "recognize",
                "information_units": ["a", "b", "c"],
                "timing_seconds": 60,
            }
        ],
    }
    report = audit(plan)
    assert not report["passed"]
    assert any(item["category"] == "overview-reading-goal" for item in report["findings"])


def test_policy_is_optional_for_legacy_plans() -> None:
    report = audit({"meta": {}, "slides": [{"claim": "Legacy"}]})
    assert report["enabled"] is False
    assert report["passed"]

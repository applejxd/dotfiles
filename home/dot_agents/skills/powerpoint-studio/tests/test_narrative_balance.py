from scripts.audit_narrative_balance import audit


def test_technical_tutorial_requires_how_and_operate_time() -> None:
    plan = {
        "meta": {"technical_tutorial": True},
        "slides": [
            {"narrative_layer": "why", "timing_seconds": 60},
            {"narrative_layer": "how", "timing_seconds": 180},
            {"narrative_layer": "operate", "timing_seconds": 60},
            {"narrative_layer": "proof", "timing_seconds": 60},
            {"narrative_layer": "action", "timing_seconds": 60},
        ],
    }
    assert audit(plan)["passed"]


def test_why_heavy_tutorial_fails_how_gate() -> None:
    plan = {
        "meta": {"technical_tutorial": True},
        "slides": [
            {"narrative_layer": "why", "timing_seconds": 300},
            {"narrative_layer": "what", "timing_seconds": 100},
            {"narrative_layer": "how", "timing_seconds": 100},
            {"narrative_layer": "proof", "timing_seconds": 50},
            {"narrative_layer": "action", "timing_seconds": 50},
        ],
    }
    report = audit(plan)
    assert not report["passed"]
    assert any("How + Operate" in item["message"] for item in report["findings"])

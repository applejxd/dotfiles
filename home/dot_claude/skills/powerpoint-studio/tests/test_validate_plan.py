from scripts.validate_plan import validate_plan


def valid_plan() -> dict:
    return {
        "meta": {
            "title": "Test deck",
            "audience": "Reviewers",
            "duration_minutes": 10,
            "objective": "Approve the test",
            "language": "en",
        },
        "slides": [
            {
                "id": "s1",
                "role": "hook",
                "title": "The test starts here",
                "claim": "A concise hook.",
                "evidence": [],
                "visual": {
                    "type": "chart",
                    "source": "data.csv",
                    "purpose": "Show the gap",
                },
                "layout": "hero",
                "speaker_goal": "Frame the problem.",
                "transition": "Move to the decision.",
            },
            {
                "id": "s2",
                "role": "decision",
                "title": "Approve the pilot",
                "claim": "The pilot is low risk.",
                "evidence": ["risk register"],
                "visual": {
                    "type": "native-shapes",
                    "source": "plan",
                    "purpose": "Show safeguards",
                },
                "layout": "decision",
                "speaker_goal": "Ask for approval.",
                "transition": "Close.",
            },
        ],
    }


def test_valid_plan_passes() -> None:
    assert validate_plan(valid_plan()) == []


def test_content_slide_cannot_be_text_only() -> None:
    plan = valid_plan()
    plan["slides"][1]["visual"]["type"] = "none"
    assert any("cannot be 'none'" in error for error in validate_plan(plan))


def test_three_repeated_layouts_fail() -> None:
    plan = valid_plan()
    repeated = dict(plan["slides"][1])
    repeated["id"] = "s3"
    repeated["layout"] = "hero"
    plan["slides"][1]["layout"] = "hero"
    plan["slides"].append(repeated)
    assert any("three consecutive slides" in error for error in validate_plan(plan))


def test_timing_must_match_duration() -> None:
    plan = valid_plan()
    plan["meta"]["duration_minutes"] = 2
    plan["meta"]["session_duration_minutes"] = 3
    plan["meta"]["buffer_minutes"] = 1
    plan["slides"][0]["timing_seconds"] = 60
    plan["slides"][0]["optional_cut_seconds"] = 10
    plan["slides"][1]["timing_seconds"] = 60
    plan["slides"][1]["optional_cut_seconds"] = 10
    assert validate_plan(plan) == []
    plan["slides"][1]["timing_seconds"] = 90
    assert any("timing totals" in error for error in validate_plan(plan))


def test_long_form_requires_title_agenda_and_summary() -> None:
    plan = valid_plan()
    plan["meta"]["session_duration_minutes"] = 45
    plan["slides"][0]["role"] = "title"
    plan["slides"][1]["role"] = "agenda"
    summary = dict(plan["slides"][1])
    summary["id"] = "s3"
    summary["role"] = "summary"
    summary["layout"] = "summary"
    plan["slides"].append(summary)
    assert validate_plan(plan) == []

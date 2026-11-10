from scripts.audit_source_review import audit


def review_plan() -> dict:
    return {
        "meta": {
            "source_review": {
                "enabled": True,
                "review_label": "Two-project implementation review",
                "minimum_direct_slide_ratio": 0.6,
                "max_sections_per_slide": 5,
                "works": [
                    {
                        "id": "rag",
                        "title": "RAG From Scratch",
                        "sections": ["1-4", "5-9", "10-11"],
                        "minimum_review_slides": 2,
                    }
                ],
                "omissions": [
                    {
                        "work": "rag",
                        "section": "10-11",
                        "reason": "時間内では診断表へ統合する。",
                    }
                ],
            }
        },
        "slides": [
            {"role": "title", "claim": "二つの教材を実装順にレビューする。"},
            {
                "role": "mechanism",
                "claim": "Parts 1-4で最小RAGを通す。",
                "source_sections": [{"work": "rag", "sections": ["1-4"]}],
                "review_lens": {
                    "builds": "Indexing, Retrieval, Generation",
                    "why_next": "baselineの失敗を変換で補う",
                    "takeaway": "最小経路を先に通す",
                    "caveat": "正しさは保証しない",
                },
            },
            {
                "role": "mechanism",
                "claim": "Parts 5-9で質問変換を比較する。",
                "source_sections": [{"work": "rag", "sections": ["5-9"]}],
                "review_lens": {
                    "builds": "Multi QueryからHyDE",
                    "why_next": "経路選択へ進む",
                    "takeaway": "症状で技法を選ぶ",
                    "caveat": "常時併用しない",
                },
            },
            {"role": "summary", "claim": "教材の流れを再現する。"},
        ],
    }


def test_source_review_passes_with_ordered_coverage() -> None:
    assert audit(review_plan())["passed"]


def test_source_review_fails_when_section_is_unaccounted() -> None:
    plan = review_plan()
    plan["meta"]["source_review"]["omissions"] = []
    report = audit(plan)
    assert not report["passed"]
    assert any(item["category"] == "source-coverage" for item in report["findings"])


def test_source_review_fails_when_review_lens_is_missing() -> None:
    plan = review_plan()
    del plan["slides"][1]["review_lens"]["why_next"]
    report = audit(plan)
    assert not report["passed"]
    assert any(item["category"] == "review-lens" for item in report["findings"])


def test_source_review_fails_when_too_abstract() -> None:
    plan = review_plan()
    plan["meta"]["source_review"]["minimum_direct_slide_ratio"] = 0.8
    plan["slides"].insert(
        -1,
        {"role": "context", "claim": "一般的な設計原則を説明する。"},
    )
    report = audit(plan)
    assert not report["passed"]
    assert any(item["category"] == "direct-slide-ratio" for item in report["findings"])


def test_source_review_policy_is_optional() -> None:
    report = audit({"meta": {}, "slides": []})
    assert report["enabled"] is False
    assert report["passed"]

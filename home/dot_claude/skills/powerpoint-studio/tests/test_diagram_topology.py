from scripts.audit_diagram_topology import audit


def valid_spec() -> dict:
    return {
        "entry": "start",
        "nodes": ["start", "decision", "continue", "human"],
        "main_path": ["start", "decision", "continue"],
        "edges": [
            {"from": "start", "to": "decision", "kind": "main"},
            {
                "from": "decision",
                "to": "continue",
                "kind": "main",
                "label": "明確",
            },
            {
                "from": "decision",
                "to": "human",
                "kind": "branch",
                "label": "曖昧",
            },
            {
                "from": "human",
                "to": "decision",
                "kind": "return",
                "label": "再開",
                "route": "outside",
            },
        ],
    }


def test_clear_main_path_and_outside_return_pass() -> None:
    assert audit(valid_spec())["passed"]


def test_missing_entry_fails() -> None:
    spec = valid_spec()
    spec["entry"] = ""
    report = audit(spec)
    assert not report["passed"]
    assert any(item["category"] == "entry" for item in report["findings"])


def test_branch_edges_require_unique_labels() -> None:
    spec = valid_spec()
    spec["edges"][1]["label"] = ""
    report = audit(spec)
    assert not report["passed"]
    assert any(item["category"] == "branch-label" for item in report["findings"])


def test_return_edge_must_route_outside() -> None:
    spec = valid_spec()
    spec["edges"][-1]["route"] = "direct"
    report = audit(spec)
    assert not report["passed"]
    assert any(item["category"] == "return-route" for item in report["findings"])


def test_main_path_requires_declared_edges() -> None:
    spec = valid_spec()
    spec["edges"] = spec["edges"][1:]
    report = audit(spec)
    assert not report["passed"]
    assert any(item["category"] == "main-path" for item in report["findings"])

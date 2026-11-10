from scripts.choose_diagram_renderer import choose


def test_simple_flow_uses_native_shapes() -> None:
    assert (
        choose(
            {
                "nodes": 4,
                "edges": 3,
                "branch_points": 0,
                "loops": 0,
                "frequent_powerpoint_editing": True,
            }
        )["recommendation"]
        == "native"
    )


def test_complex_graph_uses_external_tool() -> None:
    assert (
        choose(
            {
                "nodes": 9,
                "edges": 12,
                "branch_points": 3,
                "loops": 2,
                "nested_groups": 1,
                "edge_crossing_risk": True,
                "exact_topology_required": True,
            }
        )["recommendation"]
        == "external"
    )


def test_native_failure_forces_external_tool() -> None:
    assert (
        choose({"nodes": 2, "edges": 1, "native_render_failed": True})["recommendation"]
        == "external"
    )


def test_return_loop_prefers_external_routing() -> None:
    report = choose(
        {
            "nodes": 7,
            "edges": 8,
            "branch_points": 1,
            "return_edges": 1,
            "exception_branches": 1,
            "exact_topology_required": True,
        }
    )
    assert report["recommendation"] == "external"
    assert any("outside" in item for item in report["layout_guidance"])

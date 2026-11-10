from pathlib import Path

import pytest
from scripts.validate_svg import validate


def test_valid_svg_passes(tmp_path: Path) -> None:
    path = tmp_path / "valid.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">'
        '<text x="10" y="25" font-size="12">Node</text></svg>',
        encoding="utf-8",
    )
    assert validate(path)["passed"]


def test_external_asset_fails(tmp_path: Path) -> None:
    path = tmp_path / "external.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 100 50">'
        '<image xlink:href="https://example.com/a.png"/></svg>',
        encoding="utf-8",
    )
    report = validate(path)
    assert not report["passed"]
    assert any(item["category"] == "asset" for item in report["findings"])


def test_graphviz_group_translation_resolves_negative_local_coordinates(tmp_path):
    path = tmp_path / "graphviz.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">'
        '<g transform="scale(1 1) rotate(0) translate(4 46)">'
        '<text x="10" y="-20" font-size="12">Node</text></g></svg>'
    )
    assert validate(path)["passed"]


@pytest.mark.parametrize(
    "outer,inner,x,y,passed",
    [
        ("translate(90 0) scale(2)", "", 10, 10, False),
        ("translate(60 0)", "scale(2)", 0, 10, True),
        ("scale(2)", "translate(60 0)", 0, 10, False),
        ("matrix(1 0 0 1 -20 0)", "", 10, 20, False),
        ("rotate(90 50 25)", "", 75, 25, True),
        ("rotate(180)", "", 10, 20, False),
        ("skewX(45)", "", 80, 30, False),
        ("skewY(45)", "", 30, 30, False),
    ],
)
def test_bounds_use_composed_svg_transforms(tmp_path, outer, inner, x, y, passed):
    path = tmp_path / "transformed.svg"
    path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">'
        f'<g transform="{outer}"><g transform="{inner}">'
        f'<text x="{x}" y="{y}" font-size="12">Node</text></g></g></svg>'
    )
    assert validate(path)["passed"] is passed


@pytest.mark.parametrize(
    "transform",
    [
        "unknown(1)",
        "translate(NaN)",
        "matrix(1 0)",
        "scale(1e309)",
        "translate(1px)",
    ],
)
def test_unsupported_or_invalid_transforms_fail_explicitly(tmp_path, transform):
    path = tmp_path / "invalid.svg"
    path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">'
        f'<g transform="{transform}"><text x="10" y="20">Node</text></g></svg>'
    )
    report = validate(path)
    assert not report["passed"]
    assert any(item["category"] == "transform" for item in report["findings"])

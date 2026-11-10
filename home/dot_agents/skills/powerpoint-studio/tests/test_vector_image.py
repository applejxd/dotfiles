import math

from scripts.quality_gate import image_ppi


class VectorImage:
    ext = "svg"


class VectorShape:
    width = 4 * 914_400
    height = 2 * 914_400
    image = VectorImage()


def test_svg_picture_is_treated_as_vector() -> None:
    assert image_ppi(VectorShape()) == math.inf

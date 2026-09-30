import pytest

from tk.durations import format_duration, parse_duration


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1h30m", 5400),
        ("45s", 45),
        ("2d", 172800),
        ("1d2h3m4s", 93784),
        ("0s", 0),
        ("1H30M", 5400),
        ("2D", 172800),
        (" 1h 30m ", 5400),
        ("1d 1s", 86401),
        ("\t3m\n", 180),
        ("90m", 5400),
        ("100s", 100),
    ],
)
def test_valid(text, expected):
    assert parse_duration(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", "   ", "90", "1w", "-1h", "1.5h", "1h,30m", "30m1h", "1h1h", "h", "1h30", "s1", "1hm"],
)
def test_invalid(text):
    with pytest.raises(ValueError):
        parse_duration(text)


@pytest.mark.parametrize("value", [None, 5, 1.5, b"1h"])
def test_type_error(value):
    with pytest.raises(TypeError):
        parse_duration(value)


def test_round_trip():
    for n in [*range(0, 4000, 7), 86399, 86400, 90061, 10**7]:
        assert parse_duration(format_duration(n)) == n

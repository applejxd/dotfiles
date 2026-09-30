import pytest

from tk.semver import compare, parse, satisfies


def test_parse_fields():
    v = parse("1.2.3-alpha.10.x-y+build.007")
    assert (v.major, v.minor, v.patch) == (1, 2, 3)
    assert tuple(v.prerelease) == ("alpha", 10, "x-y")
    assert tuple(v.build) == ("build", "007")
    w = parse("0.0.0")
    assert (w.major, w.minor, w.patch) == (0, 0, 0)
    assert tuple(w.prerelease) == () and tuple(w.build) == ()
    assert tuple(parse("1.0.0-0a.1").prerelease) == ("0a", 1)


def test_version_immutable():
    v = parse("1.2.3")
    with pytest.raises(Exception):
        v.major = 5


@pytest.mark.parametrize(
    "text",
    ["1.2", "1", "01.2.3", "1.02.3", "1.2.03", "1.2.3-", "1.2.3-01", "1.2.3+", "1.2.3-a..b",
     "v1.2.3", " 1.2.3", "1.2.3 ", "1.2.3-a_b", "1.2.3+a..b", "a.b.c", "1.2.3.4", "", "1.2.-3"],
)
def test_parse_invalid(text):
    with pytest.raises(ValueError):
        parse(text)


ORDER = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2",
         "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0", "1.0.1", "1.1.0", "1.10.0", "2.0.0-0", "2.0.0"]


def test_order():
    for i, a in enumerate(ORDER):
        for j, b in enumerate(ORDER):
            assert compare(a, b) == (i > j) - (i < j), (a, b)


def test_compare_misc():
    assert compare("1.0.0+a", "1.0.0+b") == 0
    assert compare("1.0.0-1", "1.0.0-a") == -1
    assert compare("1.0.0-B", "1.0.0-a") == -1
    assert compare("1.0.0-2", "1.0.0-10") == -1
    assert compare("1.0.0-a.b", "1.0.0-a") == 1
    assert compare("10.0.0", "9.0.0") == 1
    with pytest.raises(ValueError):
        compare("1.0", "1.0.0")


@pytest.mark.parametrize(
    ("version", "spec", "expected"),
    [
        ("1.2.3", ">=1.2.3", True),
        ("1.2.2", ">=1.2.3", False),
        ("1.2.3", ">1.2.3", False),
        ("1.2.4", ">1.2.3", True),
        ("1.2.3", "<=1.2.3", True),
        ("1.2.3", "<1.2.3", False),
        ("1.2.3", "=1.2.3", True),
        ("1.2.3", "1.2.3", True),
        ("1.2.3+b", "1.2.3", True),
        ("1.2.4", "1.2.3", False),
        ("1.5.0", ">=1.2.3 <2.0.0", True),
        ("2.0.0", ">=1.2.3 <2.0.0", False),
        ("1.5.0", "  >=1.2.3    <2.0.0  ", True),
        ("3.0.0", "<2.0.0 || >=3.0.0", True),
        ("2.5.0", "<2.0.0 || >=3.0.0", False),
        ("3.0.0", "<2.0.0||>=3.0.0", True),
        ("1.9.9", "^1.2.3", True),
        ("2.0.0", "^1.2.3", False),
        ("1.2.2", "^1.2.3", False),
        ("0.2.9", "^0.2.3", True),
        ("0.3.0", "^0.2.3", False),
        ("0.0.3", "^0.0.3", True),
        ("0.0.4", "^0.0.3", False),
        ("0.1.0", "^0.0.3", False),
        ("1.2.9", "~1.2.3", True),
        ("1.3.0", "~1.2.3", False),
        ("0.2.5", "~0.2.3", True),
        ("1.2.3", "1.2.3 - 2.3.4", True),
        ("2.3.4", "1.2.3 - 2.3.4", True),
        ("2.3.5", "1.2.3 - 2.3.4", False),
        ("1.2.2", "1.2.3 - 2.3.4", False),
        ("99.0.0", "*", True),
        ("0.0.0", "*", True),
        # prerelease の規則
        ("1.2.4-beta", ">=1.2.3", False),
        ("1.2.4-beta", ">=1.2.4-alpha", True),
        ("1.2.4-alpha", ">=1.2.4-beta", False),
        ("1.2.4-beta", ">=1.2.3-alpha <2.0.0", False),
        ("1.2.3-beta", ">=1.2.3-alpha <2.0.0", True),
        ("1.2.3-beta.4", "^1.2.3-beta.2", True),
        ("1.2.4-beta", "^1.2.3-beta.2", False),
        ("1.2.3-beta.4", "~1.2.3-beta.2", True),
        ("2.3.4-rc.1", "1.2.3 - 2.3.4-rc.2", True),
        ("2.3.4-rc.1", "1.2.3 - 2.3.4", False),
        ("1.0.0-rc.1", "*", False),
        ("1.0.0-rc.1", "<1.0.0", False),
        ("1.0.0-rc.1", "<1.0.0 || >=1.0.0-rc.0", True),
        ("2.0.0-alpha", "^1.2.3", False),
    ],
)
def test_satisfies(version, spec, expected):
    assert satisfies(version, spec) is expected


@pytest.mark.parametrize(
    ("version", "spec"),
    [("1.2", "*"), ("1.2.3", ""), ("1.2.3", "   "), ("1.2.3", "!1.2.3"), ("1.2.3", ">=1.2"),
     ("1.2.3", ">=1.2.3 ||"), ("1.2.3", "|| >=1.2.3"), ("1.2.3", "^1.x"), ("1.2.3", "~>1.2.3")],
)
def test_satisfies_invalid(version, spec):
    with pytest.raises(ValueError):
        satisfies(version, spec)

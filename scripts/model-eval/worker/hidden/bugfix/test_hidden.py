import pytest

from tk.paginate import page_count, page_window, paginate


def test_paginate():
    items = list(range(10))
    assert paginate(items, 1, 3) == [0, 1, 2]
    assert paginate(items, 2, 3) == [3, 4, 5]
    assert paginate(items, 4, 3) == [9]
    assert paginate(items, 5, 3) == []
    assert paginate(items, 1, 20) == items
    assert paginate([], 1, 5) == []


def test_paginate_errors():
    for page, per in [(0, 1), (-1, 3), (1, 0), (1, -2)]:
        with pytest.raises(ValueError):
            paginate([1, 2, 3], page, per)


def test_page_count():
    assert page_count(9, 3) == 3
    assert page_count(10, 3) == 4
    assert page_count(0, 3) == 0
    assert page_count(1, 3) == 1
    assert page_count(3, 1) == 3
    with pytest.raises(ValueError):
        page_count(3, 0)


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ((1, 10), [1, 2, 3, 4, 5]),
        ((10, 10), [6, 7, 8, 9, 10]),
        ((5, 10), [3, 4, 5, 6, 7]),
        ((5, 10, 4), [3, 4, 5, 6]),
        ((2, 3), [1, 2, 3]),
        ((3, 3), [1, 2, 3]),
        ((1, 1), [1]),
        ((1, 0), []),
        ((9, 10), [6, 7, 8, 9, 10]),
        ((2, 10), [1, 2, 3, 4, 5]),
        ((4, 10), [2, 3, 4, 5, 6]),
        ((7, 10, 3), [6, 7, 8]),
        ((1, 10, 1), [1]),
    ],
)
def test_page_window(args, expected):
    assert page_window(*args) == expected

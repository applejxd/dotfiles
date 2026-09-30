import pytest

from tk.paginate import paginate


def test_rejects_bad_arguments():
    with pytest.raises(ValueError):
        paginate([1, 2], 0, 1)
    with pytest.raises(ValueError):
        paginate([1, 2], 1, 0)

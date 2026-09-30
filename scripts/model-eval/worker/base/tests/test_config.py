import pytest

from tk.config import Config, load_config


def test_defaults():
    assert load_config({"base_url": "http://x"}) == Config(base_url="http://x", retries=3)


def test_requires_base_url():
    with pytest.raises(ValueError):
        load_config({})

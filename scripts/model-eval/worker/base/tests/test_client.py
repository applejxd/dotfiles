import pytest

from tk import transport
from tk.client import Client
from tk.config import Config


def test_post_retries(monkeypatch):
    calls = []

    def fake_send(url, payload, **kwargs):
        calls.append(url)
        if len(calls) < 3:
            raise ConnectionError("boom")
        return {"ok": True}

    monkeypatch.setattr(transport, "send", fake_send)
    assert Client(Config(base_url="http://x/", retries=2)).post("/jobs", {}) == {"ok": True}
    assert calls == ["http://x/jobs"] * 3


def test_post_gives_up(monkeypatch):
    def fake_send(url, payload, **kwargs):
        raise ConnectionError("down")

    monkeypatch.setattr(transport, "send", fake_send)
    with pytest.raises(ConnectionError):
        Client(Config(base_url="http://x", retries=1)).post("jobs", {})

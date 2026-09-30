from decimal import Decimal

import pytest

from tk import config as config_mod
from tk import transport
from tk.cli import main
from tk.client import Client
from tk.config import Config, load_config


def test_config_default():
    cfg = load_config({"base_url": "http://x"})
    assert cfg == Config(base_url="http://x", retries=3, timeout=30.0)
    assert cfg.timeout == 30.0 and isinstance(cfg.timeout, float)


def test_config_positional_order():
    assert Config("http://x", 1, 2.5).timeout == 2.5


@pytest.mark.parametrize(("value", "expected"), [(5, 5.0), (0.5, 0.5), (120, 120.0)])
def test_config_values(value, expected):
    cfg = load_config({"base_url": "http://x", "timeout": value})
    assert cfg.timeout == expected and isinstance(cfg.timeout, float)


@pytest.mark.parametrize("value", [0, -1, -0.1, True, False, "5", Decimal("5"), [5]])
def test_config_rejects(value):
    with pytest.raises(ValueError):
        load_config({"base_url": "http://x", "timeout": value})


def test_config_keeps_retries_checks():
    with pytest.raises(ValueError):
        load_config({"base_url": "http://x", "retries": -1})
    with pytest.raises(ValueError):
        load_config({})


def test_client_passes_timeout_on_every_attempt(monkeypatch):
    seen = []

    def fake_send(url, payload, **kwargs):
        seen.append(kwargs)
        if len(seen) < 3:
            raise ConnectionError("x")
        return {"ok": 1}

    monkeypatch.setattr(transport, "send", fake_send)
    assert Client(Config("http://x", 2, 7.5)).post("/p", {}) == {"ok": 1}
    assert seen == [{"timeout": 7.5}] * 3


def _run_cli(monkeypatch, capsys, argv):
    seen = []

    def fake_send(url, payload, **kwargs):
        seen.append((url, payload, kwargs))
        return {"ok": True}

    monkeypatch.setattr(transport, "send", fake_send)
    assert main(argv) == 0
    return seen, capsys.readouterr().out


def test_cli_timeout(monkeypatch, capsys):
    seen, out = _run_cli(monkeypatch, capsys, ["post", "--base-url", "http://x", "--timeout", "2.5", "/jobs", '{"a": 1}'])
    assert seen == [("http://x/jobs", {"a": 1}, {"timeout": 2.5})]
    assert out.strip() == '{"ok": true}'


def test_cli_default_timeout(monkeypatch, capsys):
    seen, _ = _run_cli(monkeypatch, capsys, ["post", "--base-url", "http://x", "/jobs", "{}"])
    assert seen == [("http://x/jobs", {}, {"timeout": 30.0})]


def test_cli_uses_load_config(monkeypatch, capsys):
    got = []
    orig = config_mod.load_config

    def spy(data):
        got.append(dict(data))
        return orig(data)

    import tk.cli as cli

    monkeypatch.setattr(cli, "load_config", spy)
    _run_cli(monkeypatch, capsys, ["post", "--base-url", "http://x", "--timeout", "4", "/j", "{}"])
    assert got and float(got[0]["timeout"]) == 4.0


def test_readme_mentions_timeout():
    from pathlib import Path

    text = Path(__file__).resolve().parents[1].joinpath("README.md").read_text()
    section = text.split("## Configuration", 1)[1].split("\n## ", 1)[0]
    line = next(line for line in section.splitlines() if "timeout" in line)
    assert "30" in line
    assert "second" in line.lower() or "秒" in line or "sec" in line.lower() or " s" in line

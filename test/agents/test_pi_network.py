"""``[pis.network]`` (common.toml) → rules.json の ``network`` → ``pi.read_network_setting``。

拒否リスト型 (denylist) の設定の生成と、起動側の読み取り (破損は起動を拒否する)。
中継そのものの試験は test_relay.py。
see docs/spec/guard/pi-guard.md#拒否リスト型の通信
"""

from __future__ import annotations

import json
import sys

import pytest
from agents_common import ROOT, load_common
from test_broker import _ocs

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen


def _with_network(section):
    common = load_common()
    common["pis"] = {} if section is None else {"network": section}
    return common


def test_network_defaults_to_allowlist_without_the_table():
    assert gen.build_pi_harness({}, _with_network(None))["network"] == {"mode": "allowlist"}


def test_denylist_setting_is_normalized():
    section = {"mode": "denylist", "deny": [" a.example ", "a.example", "*.b.example"]}
    network = gen.build_pi_harness({}, _with_network(section))["network"]
    assert network == {
        "mode": "denylist",
        "deny": ["a.example", "*.b.example"],
        "allow_loopback": False,
        "local_ports": [],
    }


@pytest.mark.parametrize(
    "section",
    [
        "denylist",
        {"mode": "open"},
        {"mode": "denylist", "deny": "a.example"},
        {"mode": "denylist", "deny": ["a b"]},
        {"mode": "denylist", "deny": ["https://a.example/x"]},
        {"mode": "denylist", "deny": [""]},
        {"mode": "denylist", "allow_loopback": "yes"},
        {"mode": "denylist", "local_ports": [80]},
        {"mode": "denylist", "local_ports": ["3000"]},
        {"mode": "denylist", "local_ports": [True]},
        {"mode": "denylist", "local_ports": 3000},
        {"mode": "denylist", "unknown": 1},
    ],
)
def test_invalid_network_setting_stops_generation(section):
    with pytest.raises((SystemExit, ValueError)):  # 未知のキーは ValueError
        gen.build_pi_harness({}, _with_network(section))


def _rules(tmp_path, monkeypatch, pi, body):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setattr(pi, "RULES", path)


def test_read_network_setting_returns_none_for_allowlist_or_missing(monkeypatch, tmp_path):
    pi = _ocs().pi
    _rules(tmp_path, monkeypatch, pi, {})
    assert pi.read_network_setting() is None
    _rules(tmp_path, monkeypatch, pi, {"network": {"mode": "allowlist"}})
    assert pi.read_network_setting() is None


def test_read_network_setting_returns_the_denylist(monkeypatch, tmp_path):
    pi = _ocs().pi
    body = {
        "network": {
            "mode": "denylist",
            "deny": ["a.example"],
            "allow_loopback": True,
            "local_ports": [3000],
        }
    }
    _rules(tmp_path, monkeypatch, pi, body)
    assert pi.read_network_setting() == {
        "mode": "denylist",
        "deny": ["a.example"],
        "allow_loopback": True,
        "local_ports": [3000],
    }


@pytest.mark.parametrize(
    "network",
    [
        None,
        "denylist",
        [],
        {},
        {"mode": "open"},
        {"mode": None},
        {"mode": "denylist", "deny": "a.example"},
        {"mode": "denylist", "deny": [1]},
        {"mode": "denylist", "deny": [""]},
        {"mode": "denylist", "allow_loopback": "true"},
        {"mode": "denylist", "local_ports": ["3000"]},
        {"mode": "denylist", "local_ports": [80]},
    ],
    ids=lambda v: repr(v)[:30],
)
def test_broken_network_setting_fails_closed(monkeypatch, tmp_path, capsys, network):
    """★壊れた設定を、開く側 (denylist) にも閉じる側にも倒さず、起動を拒否する。"""
    pi = _ocs().pi
    _rules(tmp_path, monkeypatch, pi, {"network": network})
    with pytest.raises(SystemExit):
        pi.read_network_setting()
    assert "network" in capsys.readouterr().err


def _populate(pi, tmp_path, name, **kwargs):
    real = tmp_path / "real"
    real.mkdir(exist_ok=True)
    (real / "auth.json").write_text(
        json.dumps({"github-copilot": {"token": "real"}, "openai": {"token": "other"}}),
        encoding="utf-8",
    )
    agent = tmp_path / name
    agent.mkdir()
    pi.populate_agent_dir(agent, real, "http://127.0.0.1:18080", **kwargs)
    return json.loads((agent / "auth.json").read_text(encoding="utf-8"))


def test_other_providers_auth_is_copied_unless_the_denylist_is_on(tmp_path):
    """★拒否リスト型は任意のホストへ送れるので、ブローカーの無い他プロバイダーの認証は内側へ写さない。"""
    pi = _ocs().pi
    assert _populate(pi, tmp_path, "allow") == {"openai": {"token": "other"}}
    assert _populate(pi, tmp_path, "deny", keep_other_auth=False) == {}


# ─── local.toml (chezmoi 管理外) からの上書き ───────────────────────────


def _with_local(shared, local):
    common = load_common()
    common["pis"] = {} if shared is None else {"network": shared}
    return gen.apply_local_overlay(common, {"pis": {"network": local}})


def test_local_toml_appends_deny_and_ports_and_replaces_mode():
    shared = {"mode": "allowlist", "deny": ["a.example"], "local_ports": [3000]}
    local = {"mode": "denylist", "deny": ["b.example", "a.example"], "local_ports": [8080]}
    network = gen.build_pi_harness({}, _with_local(shared, local))["network"]
    assert network == {
        "mode": "denylist",
        "deny": ["a.example", "b.example"],
        "allow_loopback": False,
        "local_ports": [3000, 8080],
    }


def test_local_toml_works_without_a_shared_table():
    network = gen.build_pi_harness(
        {}, _with_local(None, {"mode": "denylist", "deny": ["x.example"]})
    )["network"]
    assert network["mode"] == "denylist"
    assert network["deny"] == ["x.example"]


def test_local_toml_never_removes_shared_denies():
    shared = {"mode": "denylist", "deny": ["keep.example"]}
    network = gen.build_pi_harness({}, _with_local(shared, {"deny": []}))["network"]
    assert network["deny"] == ["keep.example"]


def test_local_toml_unknown_key_is_ignored_with_a_warning(capsys):
    shared = {"mode": "allowlist"}
    network = gen.build_pi_harness({}, _with_local(shared, {"denny": ["x"], "mode": "denylist"}))[
        "network"
    ]
    assert network["mode"] == "denylist"
    assert "denny" in capsys.readouterr().err


@pytest.mark.parametrize(
    "local",
    [{"mode": "open"}, {"deny": "a.example"}, {"local_ports": [80]}, {"allow_loopback": "yes"}],
)
def test_broken_local_toml_stops_generation(local):
    with pytest.raises(SystemExit):
        gen.build_pi_harness({}, _with_local({"mode": "allowlist"}, local))


# ─── local.toml: [pi.sandbox] の追記と [pis.broker] の置き換え ─────────────


def _overlay(local):
    return gen.apply_local_overlay(load_common(), local)


def test_local_toml_appends_pi_sandbox_read_network_and_deny_read():
    before = gen.pi_sandbox(load_common())["base"]
    local = {
        "pi": {
            "sandbox": {
                "read": ["/data/sets"],
                "network_allow": ["files.example"],
                "deny_read": ["/data/sets/private"],
            }
        }
    }
    after = gen.pi_sandbox(_overlay(local))["base"]
    assert set(before["read"]) <= set(after["read"])  # 共有側は消えない
    assert "/data/sets" in after["read"]
    assert "files.example" in after["network"]["allowedDomains"]
    assert "/data/sets/private" in after["deny_read"]


def test_local_toml_cannot_loosen_write_or_protection(capsys):
    before = gen.pi_sandbox(load_common())["base"]
    local = {
        "pi": {
            "sandbox": {
                "write": ["/data/out"],
                "protected": [],
                "control_dirs": ["/x"],
                "read": ["/data/sets"],
            }
        }
    }
    after = gen.pi_sandbox(_overlay(local))["base"]
    assert after["write"] == before["write"]
    assert after["protected"] == before["protected"]
    assert after["control_dirs"] == before["control_dirs"]
    assert "/data/sets" in after["read"]
    err = capsys.readouterr().err
    assert "write" in err and "protected" in err and "control_dirs" in err


def test_local_toml_replaces_the_broker_token_source_without_leaving_both():
    shared = load_common().get("pis", {}).get("broker", {})
    local = {"pis": {"broker": {"github_token_file": "~/.config/pis/other-token"}}}
    broker = gen.build_pi_harness({}, _overlay(local))["broker"]
    assert broker["github_token_file"] == "~/.config/pis/other-token"
    assert "github_token_command" not in broker
    # 触っていないキーは共有側のまま
    assert broker["github"] == shared.get("github", "off")

    local = {"pis": {"broker": {"github_token_command": ["bw", "get", "password", "x"]}}}
    broker = gen.build_pi_harness({}, _overlay(local))["broker"]
    assert broker["github_token_command"] == ["bw", "get", "password", "x"]
    assert "github_token_file" not in broker


def test_local_toml_can_turn_brokers_off():
    local = {"pis": {"broker": {"copilot": "off", "search": "off", "github": "off"}}}
    broker = gen.build_pi_harness({}, _overlay(local))["broker"]
    assert (broker["copilot"], broker["github"], broker["search"]) == ("off", "off", "off")


@pytest.mark.parametrize(
    "local",
    [
        {"pi": {"sandbox": {"read": "/data"}}},
        {"pi": {"sandbox": "x"}},
        {"pis": {"broker": {"copilot": "maybe"}}},
        {"pis": {"broker": {"github_token_command": "gh auth token"}}},
        {"pis": {"broker": "auto"}},
    ],
)
def test_broken_local_toml_for_sandbox_or_broker_stops_generation(local):
    with pytest.raises(SystemExit):
        gen.pi_sandbox(_overlay(local))
        gen.build_pi_harness({}, _overlay(local))

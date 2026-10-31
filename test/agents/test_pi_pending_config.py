"""``[pi.pending]`` の検証 (生成器)。足場だけの段で、挙動は変わらない。

see docs/change/0055-async-approval.md
"""

from __future__ import annotations

import sys

import pytest
from agents_common import ROOT, load_common

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen

DEFAULTS = {
    "enabled": False,
    "modes": ["tui"],
    "retention_days": 30,
    "result_retention_days": 90,
    "max_pending": 50,
}


def _with_pending(section):
    common = load_common()
    if section is None:
        common["pi"].pop("pending", None)
    else:
        common["pi"]["pending"] = section
    return common


def test_pending_defaults_when_omitted():
    assert gen.pi_pending(_with_pending(None)) == DEFAULTS


def test_shipped_config_is_disabled_with_defaults():
    assert gen.pi_pending(load_common()) == DEFAULTS


def test_pending_accepts_all_keys():
    section = {
        "enabled": True,
        "modes": ["tui", "rpc"],
        "retention_days": 7,
        "result_retention_days": 7,
        "max_pending": 500,
    }
    assert gen.pi_pending(_with_pending(section)) == section


def test_pending_fills_missing_keys():
    out = gen.pi_pending(_with_pending({"enabled": True, "modes": ["rpc"]}))
    assert out == {**DEFAULTS, "enabled": True, "modes": ["rpc"]}


def test_rules_json_carries_pending():
    judge = gen.build_pi_harness({}, load_common())["judge"]["common"]["pi"]
    assert judge["pending"] == DEFAULTS


def test_pending_is_not_shared_to_other_clis():
    assert not any("pending" in src for src in gen.PI_SHARED_TO_OPENCODE)
    assert not any("pending" in dst for dst in gen.PI_SHARED_TO_OPENCODE.values())


@pytest.mark.parametrize(
    "section",
    [
        {"enabled": "yes"},
        {"enabled": 1},
        {"modes": "tui"},
        {"modes": []},
        {"modes": [1]},
        {"modes": ["http"]},
        {"modes": ["tui", "tui"]},
        {"retention_days": "30"},
        {"retention_days": 30.5},
        {"retention_days": True},
        {"retention_days": 0},
        {"retention_days": 366},
        {"result_retention_days": 0},
        {"result_retention_days": 3651},
        {"result_retention_days": False},
        {"retention_days": 100, "result_retention_days": 99},
        {"retention_days": 100},  # 既定の result_retention_days (90) を超える
        {"max_pending": 0},
        {"max_pending": 501},
        {"max_pending": True},
        {"max_pending": "50"},
    ],
)
def test_pending_rejects_bad_values(section):
    with pytest.raises(SystemExit, match=r"\[pi\.pending\]"):
        gen.pi_pending(_with_pending(section))


def test_pending_rejects_non_table():
    with pytest.raises(SystemExit):
        gen.pi_pending(_with_pending("on"))


def test_pending_rejects_unknown_keys():
    with pytest.raises(ValueError, match="unknown_key"):
        gen.pi_pending(_with_pending({"unknown_key": True}))

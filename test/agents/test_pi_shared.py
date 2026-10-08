"""``[pi]`` が正本の共有の節を、OpenCode の生成が読む位置へ写す処理の試験。

see docs/spec/agent-config-generation.md#pi-と共有する節
"""

from __future__ import annotations

import sys

import pytest
from agents_common import ROOT, load_common

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen

USERS = pytest.mark.parametrize("username", ["applejxd", "other-user"])


@USERS
def test_shared_sections_live_only_under_pi(username):
    raw = load_common(username, raw=True)
    for src, dst in gen.PI_SHARED_TO_OPENCODE.items():
        node = raw["pi"]
        for key in src:
            node = node[key]
        assert node, f"[pi.{'.'.join(src)}] が空"
        parent = raw.get("opencode", {})
        for key in dst[:-1]:
            parent = parent.get(key, {})
        assert dst[-1] not in parent, f"[opencode.{'.'.join(dst)}] が残っている"


@USERS
def test_resolved_common_has_the_pi_values_in_opencode_positions(username):
    raw = load_common(username, raw=True)
    resolved = gen.resolve_pi_shared(raw)
    assert resolved["opencode"]["shell"]["allow"] == raw["pi"]["shell"]["allow"]
    assert resolved["opencode"]["redact"] == raw["pi"]["redact"]
    assert resolved["opencode"]["external_read"] == raw["pi"]["external_read"]
    assert resolved["opencode"]["skill_scripts"] == raw["pi"]["skill_scripts"]
    # 元の dict は書き換えない
    assert "allow" not in raw.get("opencode", {}).get("shell", {})


def test_writing_both_places_stops_generation():
    common = {"pi": {"shell": {"allow": ["wc"]}}, "opencode": {"shell": {"allow": ["wc"]}}}
    with pytest.raises(SystemExit, match=r"\[pi.shell.allow\] が正本"):
        gen.resolve_pi_shared(common)


def test_without_pi_the_input_is_returned_as_is():
    common = {"opencode": {"shell": {"allow": ["wc"]}}}
    assert gen.resolve_pi_shared(common) is common

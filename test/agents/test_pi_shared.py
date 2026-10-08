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


def test_opencode_guides_take_pi_guides_by_id_in_place():
    raw = load_common(raw=True)
    by_id = {g["id"]: {k: v for k, v in g.items() if k != "id"} for g in raw["pi"]["guide"]}
    refs = [g.get("pi") for g in raw["opencode"]["shell"]["guide"]]
    resolved = gen.resolve_pi_shared(raw)["opencode"]["shell"]["guide"]
    assert len(resolved) == len(refs)
    for ref, guide in zip(refs, resolved, strict=True):
        if ref is not None:
            assert guide == by_id[ref]
        assert "pi" not in guide


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"pi": "missing"}, "に無い"),
        ({"pi": "a", "message": "x"}, "他のキー"),
    ],
)
def test_bad_guide_references_stop_generation(entry, message):
    common = {
        "pi": {"guide": [{"id": "a", "pattern": "x", "message": "m"}]},
        "opencode": {"shell": {"guide": [entry]}},
    }
    with pytest.raises(SystemExit, match=message):
        gen.resolve_pi_shared(common)


def test_pi_guides_mean_the_same_in_python_and_javascript():
    """[[pi.guide]] は判定器 (Python) と guide plugin (JavaScript) の両方が使う。"""
    import json
    import re
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    probes = [
        "cat README.md",
        "cat README.md | wc -l",
        "cd docs && head -5 index.md",
        "tail -f log.txt",
        "sed -n 1,5p README.md",
        "cat > out.txt <<'EOF'\nx\nEOF",
        "python3 - <<'PY'\nprint(1)\nPY",
        "git commit -m 'cat > f <<EOF\nx\nEOF'",
        "echo 'a << b'",
        "tee -a f.txt <<EOF\nx\nEOF",
    ]
    guides = load_common(raw=True)["pi"]["guide"]
    script = (
        "const [guides, probes] = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
        "console.log(JSON.stringify(probes.map((p) => guides.map((g) =>"
        " new RegExp(g.pattern).test(p) && !(g.unless && new RegExp(g.unless).test(p))))));"
    )
    proc = subprocess.run(
        [node, "-e", script],
        input=json.dumps([guides, probes]),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    js = json.loads(proc.stdout)
    py = [
        [
            bool(re.search(g["pattern"], p)) and not (g.get("unless") and re.search(g["unless"], p))
            for g in guides
        ]
        for p in probes
    ]
    assert py == js


# ─── ~/.pi/agent/settings.json ──────────────────────────────────────


@USERS
def test_pi_settings_owns_only_its_keys(username):
    common = load_common(username)
    existing = {
        "lastChangelogVersion": "1.1.0",
        "defaultModel": "old",
        "enabledModels": ["stale"],
        "theme": "dark",
    }
    out = gen.merge_pi_settings(existing, common)
    assert out["lastChangelogVersion"] == "1.1.0" and out["theme"] == "dark"
    tiers = common["opencode"]["model"]["tier"][common["opencode"]["model"]["provider"]]
    assert out["defaultProvider"] == common["opencode"]["model"]["provider"]
    assert out["defaultModel"] == tiers["default"]
    assert out["skills"] == ["~/.claude/skills"]
    # 持ち物のうち宣言していないものは消す
    assert "enabledModels" not in out


def test_pi_settings_rejects_unknown_keys():
    common = load_common()
    common["pi"]["settings"]["theme"] = "dark"
    with pytest.raises(ValueError, match=r"pi\.settings"):
        gen.merge_pi_settings({}, common)

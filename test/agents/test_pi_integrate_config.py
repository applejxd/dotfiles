"""``[pi.integrate]`` の検証 (生成器) と、judge/protectedrefs.ts の表試験。

足場だけの段なので、どのキーも既定 (無効) のまま挙動は変わらない。
see docs/change/0053-worktree-integration-gate.md
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from agents_common import ROOT, load_common
from test_pi_judge_ts import _node

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen

DRIVER = ROOT / "test" / "agents" / "pi" / "protectedrefs_driver.mjs"
FLOOR = ["main", "master", "develop", "release/*", "hotfix/*"]


def _with_integrate(section):
    common = load_common()
    if section is None:
        common["pi"].pop("integrate", None)
    else:
        common["pi"]["integrate"] = section
    return common


def test_integrate_defaults_when_omitted():
    out = gen.pi_integrate(_with_integrate(None))
    assert out == {
        "enabled": False,
        "target": "develop",
        "protected_refs": FLOOR,
        "risk_paths": [],
        "skip_confirm_in_free_zone": False,
    }


def test_shipped_config_enables_the_free_zone_skip_and_carries_the_floor():
    out = gen.pi_integrate(load_common())
    assert out["enabled"] is False  # 専用操作 (S3) はまだ無い
    assert out["skip_confirm_in_free_zone"] is True  # 自由区の git_commit は確認を省略する (S5b)
    assert out["target"] == "develop"
    assert set(FLOOR) <= set(out["protected_refs"])
    assert out["risk_paths"] and all(isinstance(p, str) for p in out["risk_paths"])


def test_rules_json_carries_integrate_and_confirm_flag():
    judge = gen.build_pi_harness({}, load_common())["judge"]["common"]["pi"]
    assert judge["integrate"]["enabled"] is False  # 専用操作 (S3) はまだ無い
    assert judge["integrate"]["skip_confirm_in_free_zone"] is True  # 自由区の確認省略 (S5b)
    assert judge["confirm"]["integration"] is True  # 統合コマンドの必須確認 (S4b)


def test_integrate_is_not_shared_to_opencode():
    assert not any("integrate" in src for src in gen.PI_SHARED_TO_OPENCODE)
    assert not any("integrate" in dst for dst in gen.PI_SHARED_TO_OPENCODE.values())


@pytest.mark.parametrize(
    "section",
    [
        {"enabled": "yes"},
        {"enabled": 1},
        {"skip_confirm_in_free_zone": "false"},
        {"target": 1},
        {"target": ""},
        {"protected_refs": "main"},
        {"protected_refs": [*FLOOR, 1]},
        {"risk_paths": "AGENTS.md"},
        {"risk_paths": [1]},
    ],
)
def test_integrate_rejects_bad_types(section):
    with pytest.raises(SystemExit):
        gen.pi_integrate(_with_integrate(section))


def test_integrate_rejects_unknown_keys():
    with pytest.raises(ValueError, match="unknown_key"):
        gen.pi_integrate(_with_integrate({"unknown_key": True}))


@pytest.mark.parametrize("missing", FLOOR)
def test_integrate_rejects_a_missing_floor_entry(missing):
    refs = [r for r in FLOOR if r != missing]
    with pytest.raises(SystemExit, match="下限"):
        gen.pi_integrate(_with_integrate({"protected_refs": refs}))


def test_integrate_accepts_extra_protected_refs():
    out = gen.pi_integrate(_with_integrate({"protected_refs": [*FLOOR, "staging", "rc/*"]}))
    assert out["protected_refs"] == [*FLOOR, "staging", "rc/*"]


@pytest.mark.parametrize(
    "bad", ["refs/heads/x", "refs/*", "*", "feat*", "a/*/b", "a/**", "*/x", "/*"]
)
def test_integrate_rejects_bad_ref_shapes(bad):
    with pytest.raises(SystemExit):
        gen.pi_integrate(_with_integrate({"protected_refs": [*FLOOR, bad]}))


def test_integrate_target_must_be_an_exact_protected_ref():
    assert gen.pi_integrate(_with_integrate({"target": "main"}))["target"] == "main"
    for target in ("feature/x", "release/*", "release/1"):
        with pytest.raises(SystemExit, match="target"):
            gen.pi_integrate(_with_integrate({"target": target}))


def _run(**payload):
    node = _node()
    out = subprocess.run(
        [node, str(DRIVER), json.dumps(payload)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(out.stdout)


@pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")
@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("develop", True),
        ("Develop", True),
        ("main", True),
        ("release/1", True),
        ("release/1.0", True),
        ("release", False),
        ("release/", False),
        ("hotfix/x", True),
        ("feature/x", False),
        ("feature/", False),
        ("refs/heads/develop", True),
        ("refs/heads/release/2", True),
        ("refs/remotes/origin/develop", False),
        ("refs/tags/develop", False),
        ("origin/develop", False),
        ("", False),
    ],
)
def test_is_protected_ref(ref, expected):
    assert _run(fn="protected", ref=ref, patterns=FLOOR) is expected


@pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")
@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("feature/x", True),
        ("feature/a/b", True),
        ("refs/heads/feature/x", True),
        ("Feature/X", True),
        ("feature/", False),
        ("feature", False),
        ("develop", False),
        ("refs/remotes/origin/feature/x", False),
        ("", False),
    ],
)
def test_is_feature_source_ref(ref, expected):
    assert _run(fn="feature", ref=ref) is expected

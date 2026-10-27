"""子エージェントのモデルのカタログ (`[pi.model.catalog.<provider>]`。CHG-0043 段 2) の検査の試験。

- 実際の設定 (個人機・制約のある環境の機) が、検査を通り、`rules.json` の `models` に出る
- 階層の既定が、カタログの中の同じ系統の最新でなければ落ちる (古いモデルを残さない)
- 世代は整数の列 (6.9 < 6.10)。重複・typo・無効な値は拒否する
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from agents_common import load_common

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen  # noqa: E402

PERSONAL = load_common("applejxd")
WORK = load_common("worker")


def _mutated(common: dict, change) -> dict:
    c = copy.deepcopy(common)
    provider = c["opencode"]["model"]["provider"]
    change(c["pi"]["model"]["catalog"][provider], provider, c)
    return c


# ─── 実際の設定 ───


@pytest.mark.parametrize("common", [PERSONAL, WORK], ids=["personal", "work"])
def test_the_real_catalogs_are_valid_and_tiers_pass(common) -> None:
    gen.check_pi_tiers_against_catalog(common)  # 落ちなければよい
    cat = gen.pi_catalog(common)
    assert cat is not None
    assert cat["provider"] == common["opencode"]["model"]["provider"]
    assert all(isinstance(m["generation"], list) for m in cat["models"])


def test_the_harness_rules_carry_the_catalog_of_the_active_provider() -> None:
    rules = gen.build_pi_harness({}, PERSONAL)
    assert rules["models"]["provider"] == "github-copilot"
    ids = {m["id"] for m in rules["models"]["models"]}
    assert {"claude-sonnet-5.5", "gpt-6.1-sol", "gpt-6.1-terra"} <= ids
    work = gen.build_pi_harness({}, WORK)
    assert work["models"]["provider"] == "amazon-bedrock"
    assert "us.openai.gpt-6.1-terra" in {m["id"] for m in work["models"]["models"]}


def test_haiku_and_old_generations_are_not_in_the_catalogs() -> None:
    for common in (PERSONAL, WORK):
        for m in gen.pi_catalog(common)["models"]:
            assert "haiku" not in m["id"]
            assert not m["id"].endswith(("gpt-6-sol", "gpt-6-luna", "gpt-6-astra"))


def test_bedrock_is_not_enforced_until_it_is_probed() -> None:
    cat = gen.pi_catalog(WORK)
    assert cat["enforce_verified"] is False
    assert any(not m["verified"] for m in cat["models"])  # 未確認のものを、明示の指示では選べる


# ─── 古いモデルを使う階層は、落ちる ───


def test_a_newer_generation_in_the_catalog_fails_the_tier_that_uses_the_old_one() -> None:
    def add_newer(cat, provider, _c):
        cat["models"].append(
            {
                "id": "claude-sonnet-5.6",
                "family": "claude-sonnet",
                "generation": [5, 6],
                "verified": True,
                "cost": "normal",
            }
        )

    with pytest.raises(SystemExit, match="古い"):
        gen.check_pi_tiers_against_catalog(_mutated(PERSONAL, add_newer))


def test_generation_is_compared_as_integers_so_6_10_is_newer_than_6_9() -> None:
    def to_6_9_and_6_10(cat, provider, c):
        sol = next(m for m in cat["models"] if m["id"] == "gpt-6.1-sol")
        sol["generation"] = [6, 9]
        cat["models"].append(
            {
                "id": "gpt-6.10-sol",
                "family": "gpt-sol",
                "generation": [6, 10],
                "verified": True,
                "cost": "normal",
            }
        )
        c["pi"]["model"]["tier"][provider]["worker"] = "gpt-6.1-sol"  # 6.9 を使う階層

    with pytest.raises(SystemExit, match="古い"):
        gen.check_pi_tiers_against_catalog(_mutated(PERSONAL, to_6_9_and_6_10))


def test_a_tier_model_missing_from_the_catalog_fails() -> None:
    def drop_sonnet(cat, provider, _c):
        cat["models"] = [m for m in cat["models"] if m["id"] != "claude-sonnet-5.5"]

    with pytest.raises(SystemExit, match="カタログに足す"):
        gen.check_pi_tiers_against_catalog(_mutated(PERSONAL, drop_sonnet))


def test_unverified_tier_default_fails_only_where_verification_is_enforced() -> None:
    def unverify_sol(cat, provider, _c):
        next(m for m in cat["models"] if m["id"] == "gpt-6.1-sol")["verified"] = False

    with pytest.raises(SystemExit, match="verified = false"):
        gen.check_pi_tiers_against_catalog(_mutated(PERSONAL, unverify_sol))

    def relax(cat, provider, _c):
        unverify_sol(cat, provider, _c)
        cat["enforce_verified"] = False

    gen.check_pi_tiers_against_catalog(_mutated(PERSONAL, relax))  # 強制しないプロバイダは通る


# ─── 形の検査 ───


@pytest.mark.parametrize(
    ("what", "change", "message"),
    [
        ("duplicate id", lambda c, p, _: c["models"].append(dict(c["models"][0])), "重複"),
        (
            "same family and generation",
            lambda c, p, _: c["models"].append({**c["models"][0], "id": "other-id"}),
            "family と generation",
        ),
        ("family typo", lambda c, p, _: c["models"][0].update(family="claude-sonet"), "family"),
        ("float generation", lambda c, p, _: c["models"][0].update(generation=6.1), "整数の列"),
        (
            "negative generation",
            lambda c, p, _: c["models"][0].update(generation=[6, -1]),
            "整数の列",
        ),
        ("empty generation", lambda c, p, _: c["models"][0].update(generation=[]), "整数の列"),
        (
            "provider prefix in id",
            lambda c, p, _: c["models"][0].update(id="github-copilot/x"),
            "provider/",
        ),
        (
            "effort suffix in id",
            lambda c, p, _: c["models"][0].update(id="claude-sonnet-5.5:high"),
            ":effort",
        ),
        ("bad cost", lambda c, p, _: c["models"][0].update(cost="cheap"), "cost"),
        ("unknown key", lambda c, p, _: c["models"][0].update(price=1), "未知"),
        ("verified not bool", lambda c, p, _: c["models"][0].update(verified="yes"), "verified"),
        ("bad date", lambda c, p, _: c.update(reviewed_on="2026/10/27"), "reviewed_on"),
        ("enforce not bool", lambda c, p, _: c.update(enforce_verified="true"), "enforce_verified"),
        ("no models", lambda c, p, _: c.update(models=[]), "models"),
    ],
)
def test_malformed_catalogs_are_rejected(what, change, message) -> None:
    with pytest.raises((SystemExit, ValueError), match=message):
        gen.pi_catalog(_mutated(PERSONAL, change))


def test_a_provider_without_a_catalog_keeps_the_old_behaviour() -> None:
    c = copy.deepcopy(PERSONAL)
    c["opencode"]["model"]["provider"] = "some-other-provider"
    assert gen.pi_catalog(c) is None

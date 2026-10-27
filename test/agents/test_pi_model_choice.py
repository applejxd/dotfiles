"""`harness/model-choice.ts` (子のモデルと effort の選択。CHG-0043 段 3) の表試験。

``test/agents/pi/model_choice_driver.mjs`` が純粋な関数を動かし、結果を JSON で出す。
node の型除去を使うので、22.18 未満の node では飛ばす。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from test_pi_judge_ts import _node

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DRIVER = HERE / "pi" / "model_choice_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


@pytest.fixture(scope="module")
def t() -> dict:
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1500:]
    return json.loads(proc.stdout)


def test_spec_splitting_keeps_bedrock_version_suffixes(t) -> None:
    s = t["split"]
    assert s["with_level"] == {
        "provider": "github-copilot",
        "id": "claude-sonnet-5.5",
        "level": "medium",
    }
    assert s["bedrock"]["level"] == "low"
    assert "level" not in s["bedrock_version_suffix"]  # `...-v2:0` は id の一部
    assert (
        "level" not in s["not_a_level"]
    )  # 7 段以外は id の一部になり、許可の集合に無いので拒否される


def test_omitting_model_and_effort_uses_the_role_default(t) -> None:
    d = t["defaults"]
    assert (
        d["review"]["source"] == "default" and d["review"]["arg"] == "github-copilot/gpt-6.1-terra"
    )
    assert (
        d["worker_with_level"]["arg"] == "github-copilot/claude-sonnet-5.5:medium"
    )  # 既定の :level を保つ
    assert (
        d["explore_follows_parent"]["model"] == "github-copilot/claude-sonnet-5.5"
    )  # 既定が無ければ親に追従


def test_only_catalog_parent_and_role_defaults_can_be_chosen(t) -> None:
    m = t["model"]
    assert m["catalog_bare"]["model"] == "github-copilot/gpt-6.1-sol"
    assert m["catalog_qualified"]["model"] == "github-copilot/gpt-6.1-sol"
    assert m["parent_exact"]["ok"] is True
    for name in (
        "not_in_catalog",
        "old_generation",
        "haiku",
        "other_provider_spoof",
        "other_provider_same_id",
    ):
        assert m[name]["ok"] is False and "model not allowed" in m[name]["error"], name
    assert m["blank_is_unset"]["source"] == "default"  # 空白は「指定なし」


def test_every_effort_level_is_accepted_and_off_is_not(t) -> None:
    e = t["effort"]
    levels = ("minimal", "low", "medium", "high", "xhigh", "max")
    assert e["every_level"] == {level: level for level in levels}
    for name in ("off", "off_suffix", "bogus", "numeric"):
        assert e[name]["ok"] is False, name
    assert "off" in e["off"]["error"]


def test_empty_values_are_fillers_meaning_unset(t) -> None:
    e = t["effort"]
    assert e["filler_empty"]["source"] == "default" and e["filler_null"]["source"] == "default"


def test_effort_precedence(t) -> None:
    e = t["effort"]
    # 明示の effort > 明示の model の接尾辞 >（同じモデルなら）役割の既定の effort > pi の既定
    assert e["only_effort_on_default"]["arg"] == "github-copilot/gpt-6.1-terra:high"
    assert e["suffix_only"]["effort"] == "low"
    assert e["effort_beats_suffix"]["effort"] == "xhigh"
    assert e["same_model_keeps_default_level"]["effort"] == "medium"
    assert e["other_model_drops_default_level"]["effort"] is None
    assert e["default_level_kept_without_args"]["effort"] == "medium"


def test_a_parent_on_another_provider_is_allowed_only_by_its_full_id(t) -> None:
    p = t["other_provider_parent"]
    assert p["parent_exact"] == "openai/gpt-6.1-sol"  # 親の完全な provider/id は例外として許可
    assert p["catalog"] == "github-copilot/gpt-6.1-sol"  # bare は設定のプロバイダのカタログで解決
    assert p["spoof"].startswith("ERR model not allowed")


def test_without_a_catalog_only_the_parent_and_role_defaults_are_allowed(t) -> None:
    n = t["no_catalog"]
    assert (n["parent"], n["default"], n["omitted"]) == ("faux/spike", "faux/other", "faux/spike")
    assert n["other"].startswith("ERR model not allowed")


def test_unverified_and_high_cost_are_marked_in_the_result_line(t) -> None:
    f = t["flags"]
    assert f["bedrock_unverified"]["unverified"] is True
    assert "UNVERIFIED" in f["bedrock_unverified"]["line"]
    assert f["bedrock_high_cost"]["cost"] == "high"
    assert (
        "HIGH COST" in f["bedrock_high_cost"]["line"]
        and "effort: max" in f["bedrock_high_cost"]["line"]
    )


def test_the_catalog_is_listed_for_the_model_and_says_to_set_it_only_when_asked(t) -> None:
    text = t["catalog_text"]
    assert "github-copilot/gpt-6.1-sol (gpt-sol 6.1, verified)" in text
    assert "only when the user asks" in text and 'Never use "off"' in text
    assert t["catalog_text_none"] == ""

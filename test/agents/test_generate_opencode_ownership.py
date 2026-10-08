"""OpenCode の ``opencode.json`` の所有の規則の test.

生成器が書けるキー・statement のうち、今回宣言していないものを配置済みの設定から消す。
see docs/spec/agent-config-generation.md#配置済みの設定の所有

Run with: ``uv run --with pytest --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import copy
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402
from agents_common import load_common  # noqa: E402

USERS = pytest.mark.parametrize("username", ["applejxd", "worker"], ids=["私用", "会社用"])
# 所有の規則を入れる前のコミット (CHG-0018 段 4 の P の直前)
BEFORE_OWNERSHIP = "d6ea76f"
HAND_POLICY = {"action": "permission", "resource": "shell:dummy-hand *", "effect": "deny"}
OTHER_POLICY = {"action": "mcp.use", "resource": "dummy", "effect": "deny"}


def generated(common: dict, existing: dict | None = None) -> dict:
    return gen.merge_opencode_config(copy.deepcopy(existing or {}), common)


def without_models(common: dict) -> dict:
    out = copy.deepcopy(common)
    del out["opencode"]["model"]
    return out


@pytest.fixture(scope="module")
def before(tmp_path_factory):
    """所有の規則を入れる前の ``generate.py``。

    今の宣言で出力が変わらないことの比較に使う。CHG-0018 段 4 で宣言を変えたら
    出力が変わるので、この比較 (``test_clean_output_matches_the_generator_before``) は外す。
    """
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    result = subprocess.run(
        [git, "show", f"{BEFORE_OWNERSHIP}:scripts/agents/generate.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"{BEFORE_OWNERSHIP} が無い (浅い clone など): {result.stderr.strip()}")
    path = tmp_path_factory.mktemp("before") / "generate_before_ownership.py"
    path.write_text(result.stdout, encoding="utf-8")
    saved = list(sys.path)
    try:
        spec = importlib.util.spec_from_file_location("generate_before_ownership", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved
    return module


def with_hand_edits(config: dict) -> dict:
    """生成物に、手で書いたキーを足す (残るものと消えるものの両方)。"""
    out = copy.deepcopy(config)
    agents = out["agents"]
    agents["mine"] = {"description": "手書きの子", "mode": "subagent", "color": "#111111"}
    agents["plan"]["request"] = {"headers": {"x-dummy": "1"}}
    agents["plan"]["model"] = "dummy/hand-model"
    agents["plan"]["color"] = "#ff0000"
    agents["build"] = {"color": "#222222", "request": {"x": 1}}
    out["agent"]["myv1"] = {"description": "手書きの V1", "mode": "subagent"}
    out["agent"]["bypass"]["color"] = "#00ff00"
    out["agent"]["title"] = {"prompt": "手書き", "temperature": 0.1}
    experimental = out.setdefault("experimental", {})
    experimental["subagent_depth"] = 2
    experimental["policies"] = [HAND_POLICY, OTHER_POLICY, *experimental.get("policies", [])]
    return out


def expected_after_hand_edits(fresh: dict) -> dict:
    """``with_hand_edits`` のうち残るものだけを ``fresh`` に足した期待値。"""
    out = copy.deepcopy(fresh)
    out["agents"]["mine"] = {"description": "手書きの子", "mode": "subagent", "color": "#111111"}
    out["agents"]["plan"]["request"] = {"headers": {"x-dummy": "1"}}
    out["agents"]["plan"]["model"] = "dummy/hand-model"
    out["agents"]["build"] = {"request": {"x": 1}}
    out["agent"]["myv1"] = {"description": "手書きの V1", "mode": "subagent"}
    out["agent"]["title"] = {"temperature": 0.1}
    experimental = out.setdefault("experimental", {})
    experimental["subagent_depth"] = 2
    experimental["policies"] = [OTHER_POLICY, *experimental.get("policies", [])]
    return out


# ---------------------------------------------------------------------------
# 今の宣言では出力が変わらない
# ---------------------------------------------------------------------------


@USERS
@pytest.mark.parametrize("models", [True, False], ids=["models あり", "models 無し"])
def test_clean_output_matches_the_generator_before(before, username, models):
    common = load_common(username)
    if not models:
        common = without_models(common)
    assert generated(common) == before.merge_opencode_config({}, _for_old_generator(common))


def _for_old_generator(common: dict) -> dict:
    """P の直前の生成器が知らない入力を外す。どれも OpenCode の出力には影響しない。

    ``[[mcp]] clis`` の ``pi`` は後から足した生成先で、古い生成器は未知の値として止まる。
    """
    common = copy.deepcopy(common)
    for server in common.get("mcp", []):
        if "clis" in server:
            server["clis"] = [c for c in server["clis"] if c != "pi"]
    return common


@USERS
def test_generated_output_is_a_fixed_point(username):
    common = load_common(username)
    fresh = generated(common)
    assert generated(common, fresh) == fresh


# ---------------------------------------------------------------------------
# 手書きの設定
# ---------------------------------------------------------------------------


@USERS
def test_hand_edits_keep_only_what_the_generator_does_not_write(username):
    """非管理の ID・生成器が書かないキー・ほかの action の policy は残り、ほかは消える。"""
    common = load_common(username)
    fresh = generated(common)
    existing = with_hand_edits(fresh)
    before = copy.deepcopy(existing)
    out = generated(common, existing)
    assert existing == before, "入力を破壊しない"
    assert out == expected_after_hand_edits(fresh)
    assert generated(common, out) == out, "冪等"


def test_hand_permission_policy_is_removed_without_models():
    """``models`` が無くても、生成器が持つ statement は消す。空の ``experimental`` は作らない。"""
    common = without_models(load_common())
    stale = {"action": "provider.use", "resource": "*", "effect": "deny"}
    out = generated(common, {"experimental": {"policies": [HAND_POLICY, OTHER_POLICY, stale]}})
    assert out["experimental"] == {"policies": [OTHER_POLICY]}
    assert "experimental" not in generated(common, {"experimental": {"policies": [HAND_POLICY]}})
    assert "experimental" not in generated(common)
    kept = {"experimental": {"policies": [HAND_POLICY], "flag": True}}
    assert generated(common, kept)["experimental"] == {"flag": True}


def test_undeclared_custom_agents_are_not_removed():
    """宣言から丸ごと消した自作の ID は撤去しない (管理する ID ではなくなる)。"""
    common = load_common()
    deployed = generated(common)
    reduced = copy.deepcopy(common)
    del reduced["opencode"]["agents"]["commit"]
    del reduced["opencode"]["model"]["agents"]["commit"]
    out = generated(reduced, deployed)
    expected = {k: v for k, v in deployed["agents"]["commit"].items() if k != "model"}
    assert out["agents"]["commit"] == expected, "階層のモデルだけは今までどおり外す"


# ---------------------------------------------------------------------------
# 宣言と逆の形式のエントリ
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entry",
    [
        {"description": "x", "mode": "all", "permissions": [], "color": "#000000"},
        {"model": "github-copilot/claude-sonnet-5.5#medium"},
    ],
    ids=["生成器のキーだけ", "階層のモデル"],
)
def test_v2_entry_of_a_v1_agent_is_removed(entry):
    common = load_common("applejxd")
    out = generated(common, {"agents": {"bypass": entry}})
    assert "bypass" not in out["agents"]
    assert out["agent"]["bypass"] == generated(common)["agent"]["bypass"]


def test_v1_entry_of_a_v2_agent_is_removed():
    common = load_common()
    out = generated(common, {"agent": {"plan": {"permission": {"edit": "allow"}, "color": "#0"}}})
    assert "plan" not in out["agent"]


@pytest.mark.parametrize(
    ("existing", "names"),
    [
        ({"agents": {"bypass": {"model": "dummy/hand-model"}}}, ("agents.bypass", "model")),
        ({"agents": {"bypass-worker": {"request": {}}}}, ("agents.bypass-worker", "request")),
        (
            {"agent": {"plan": {"model": "dummy/hand-model", "mode": "primary"}}},
            ("agent.plan", "[opencode.model.agents]"),
        ),
        ({"agent": {"explore": {"temperature": 0.1}}}, ("agent.explore", "temperature")),
    ],
    ids=[
        "V1 宣言の V2 に model",
        "V1 宣言の V2 に request",
        "V2 宣言の V1 に model",
        "V2 宣言の V1 に他",
    ],
)
def test_reverse_entry_with_unowned_keys_stops_apply(existing, names):
    """生成器が書かないキーは黙って消さず、移し方を示して止める。"""
    with pytest.raises(ValueError) as excinfo:
        generated(load_common(), existing)
    for name in names:
        assert name in str(excinfo.value)


def test_v1_declaration_rejects_keys_the_generator_does_not_own():
    common = {"opencode": {"agent": {"x": {"mode": "subagent", "model": "p/m"}}}}
    with pytest.raises(ValueError, match="model"):
        gen.merge_opencode_config({}, common)


# ---------------------------------------------------------------------------
# 往復 (段 4 相当の宣言を当ててから戻す)
# ---------------------------------------------------------------------------


def stage4(common: dict) -> dict:
    """CHG-0018 段 4 相当の宣言 (試験用)。V1 の bypass 系を V2 へ移し、組み込みに規則を付ける。"""
    out = copy.deepcopy(common)
    opencode = out["opencode"]
    for name, agent in opencode.pop("agent").items():
        task = agent["permission"]["task"]
        rules = (
            [{"action": "subagent", "resource": "*", "effect": task}]
            if isinstance(task, str)
            else [{"action": "subagent", "resource": k, "effect": v} for k, v in task.items()]
        )
        opencode["agents"][name] = {
            "description": agent["description"],
            "mode": agent["mode"],
            "bypass": agent["bypass"],
            "permissions": rules,
        }
    for name in ("build", "general", "compaction"):
        opencode["agents"][name] = {
            "description": name,
            "permissions": [{"action": "shell", "resource": "*", "effect": "ask"}],
        }
    opencode["model"]["agents"]["bypass-worker"] = "worker"
    return out


STAGE4_POLICY = {"action": "permission", "resource": "read:.env", "effect": "deny"}


def apply_stage4(common: dict, existing: dict) -> dict:
    """段 4 の生成器の代わり。permission の statement は provider.use の前に書く。"""
    out = generated(stage4(common), existing)
    policies = out["experimental"]["policies"]
    head = [s for s in policies if s.get("action") not in gen.OPENCODE_OWNED_POLICY_ACTIONS]
    tail = [s for s in policies if s.get("action") == "provider.use"]
    out["experimental"]["policies"] = [*head, STAGE4_POLICY, *tail]
    return out


@USERS
def test_reverting_stage4_restores_the_never_applied_config(username):
    common = load_common(username)
    start = with_hand_edits(generated(common))
    applied = apply_stage4(common, start)
    assert "agent" not in applied or not {"bypass", "bypass-worker"} & set(applied["agent"])
    assert applied["agents"]["bypass"]["mode"] == "primary"
    assert applied["agents"]["build"]["permissions"]
    assert applied["agents"]["bypass-worker"]["model"].endswith("#medium")
    assert apply_stage4(common, applied) == applied, "段 4 を 2 回当てても変わらない"
    back = generated(common, applied)
    assert back == generated(common, start)
    assert STAGE4_POLICY not in back["experimental"]["policies"]
    assert "bypass-worker" not in back["agents"]


def test_stage4_stops_on_a_hand_written_key_in_the_old_v1_entry():
    """V2 へ移す ID の V1 に手で書いたキーがあれば、段 4 を当てるときに止まる。"""
    common = load_common()
    existing = generated(common)
    existing["agent"]["bypass"]["temperature"] = 0.1
    with pytest.raises(ValueError, match=r"agent\.bypass"):
        generated(stage4(common), existing)

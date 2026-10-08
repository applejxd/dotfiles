"""OpenCode の guide: 親が bypass の子の、作業ツリーの外の読み取りの確認を allow にする。

生成した rules.json を実際の guide plugin (node) に通して判定する。
``ctx.session.get`` は差し替え、呼ばれた sessionID を記録する。
see docs/spec/agent-config-generation.md#bypass-から呼べる子エージェント

Run with: ``uv run --with pytest --with pyyaml --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402
from agents_common import load_common, node_env  # noqa: E402

COMMON = load_common()
PLUGIN = ROOT / "home/dot_config/opencode/guide-plugin"
CHILDREN = ["explore", "review", "commit"]

# sessions の値: オブジェクトはそのまま返す、"throw" は例外、無ければ undefined。
SCRIPT = """
import plugin from './index.js'
const input = JSON.parse(process.argv[2])
const hooks = {}
const calls = []
const session = {
  async get({ sessionID }) {
    calls.push(sessionID)
    const v = input.sessions[sessionID]
    if (v === "throw") throw new Error("not found")
    return v
  },
}
const ctx = {
  tool: { hook: (n, fn) => { hooks[n] = fn } },
  permission: { hook: (n, fn) => { hooks[n] = fn } },
  shell: { hook() {} },
}
if (input.session === "object") ctx.session = session
else if (input.session === "no-get") ctx.session = {}
await plugin.setup(ctx)
const out = []
for (const [name, e] of input.steps) {
  await hooks[name](e)
  if (name === "evaluate") out.push({ effect: e.effect, calls: calls.splice(0) })
}
console.log(JSON.stringify(out))
"""


def _run(
    tmp_path: Path,
    steps: list[list],
    sessions: dict,
    rules: dict | None = None,
    session: str = "object",
    script: str = SCRIPT,
    **extra,
):
    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い (mise.toml の [tools] に宣言してある)")
    shutil.copy(PLUGIN / "index.js", tmp_path / "index.js")
    rules = rules if rules is not None else gen.build_opencode_guide({}, COMMON)
    (tmp_path / "rules.json").write_text(json.dumps(rules), "utf-8")
    (tmp_path / "run.mjs").write_text(script, "utf-8")
    payload = {"steps": steps, "sessions": sessions, "session": session, **extra}
    done = subprocess.run(
        [node, str(tmp_path / "run.mjs"), json.dumps(payload)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env=node_env(),
    )
    return json.loads(done.stdout)


def _sessions(child: str = "explore", parent: str = "bypass") -> dict:
    return {
        "ses_c": {"id": "ses_c", "parentID": "ses_p", "agent": child},
        "ses_p": {"id": "ses_p", "agent": parent},
    }


def _before(tool: str, id_: str = "call_1", agent: str = "explore") -> list:
    event = {"tool": tool, "id": id_, "agent": agent, "sessionID": "ses_c"}
    if tool == "shell":
        event["input"] = {"command": "ls /etc"}
    return ["execute.before", event]


def _ext(agent: str = "explore", effect: str = "ask", id_: str = "call_1", **extra) -> list:
    event = {
        "sessionID": "ses_c",
        "agent": agent,
        "action": "external_directory",
        "resources": ["/etc/*"],
        "source": {"type": "tool", "messageID": "msg_1", "id": id_},
        "effect": effect,
    }
    event.update(extra)
    return ["evaluate", event]


def _effects(out: list[dict]) -> list[str]:
    return [o["effect"] for o in out]


def test_children_are_listed_in_the_rules():
    assert gen.build_opencode_guide({}, COMMON)["bypass_child_agents"] == sorted(CHILDREN)


@pytest.mark.parametrize("parent", ["bypass", "bypass-worker", "bypass-fleet-worker"])
@pytest.mark.parametrize("tool", ["read", "grep", "glob"])
@pytest.mark.parametrize("child", CHILDREN)
def test_child_read_outside_is_allowed_under_bypass(tmp_path, child, tool, parent):
    out = _run(tmp_path, [_before(tool, agent=child), _ext(child)], _sessions(child, parent))
    assert out == [{"effect": "allow", "calls": ["ses_c", "ses_p"]}]


@pytest.mark.parametrize("parent", ["build", "plan"])
def test_child_read_stays_ask_under_other_parents(tmp_path, parent):
    out = _run(tmp_path, [_before("read"), _ext()], _sessions(parent=parent))
    assert out == [{"effect": "ask", "calls": ["ses_c", "ses_p"]}]


@pytest.mark.parametrize("agent", ["general", "fleet-worker", "build", "plan"])
def test_agents_outside_the_list_are_left_alone(tmp_path, agent):
    """対象外の子・子でない直接のセッションは、session API を呼ばずに ask のまま。"""
    out = _run(tmp_path, [_before("read", agent=agent), _ext(agent)], _sessions(agent))
    assert out == [{"effect": "ask", "calls": []}]


def test_direct_session_of_a_listed_agent_stays_ask(tmp_path):
    """親を持たないセッション (子として起動されていない) は ask のまま。祖先を探さない。"""
    sessions = {"ses_c": {"id": "ses_c", "agent": "explore"}}
    out = _run(tmp_path, [_before("read"), _ext()], sessions)
    assert out == [{"effect": "ask", "calls": ["ses_c"]}]


@pytest.mark.parametrize("action", ["read", "edit", "shell", "subagent", "webfetch"])
def test_other_actions_are_left_alone(tmp_path, action):
    step = _ext(action=action, resources=["/etc/hostname"])
    out = _run(tmp_path, [_before("read"), step], _sessions())
    assert out == [{"effect": "ask", "calls": []}]


@pytest.mark.parametrize("tool", ["shell", "edit", "write", "webfetch"])
def test_external_directory_from_other_tools_stays_ask(tmp_path, tool):
    """shell の workdir や edit 由来の外部ディレクトリは対象外。"""
    out = _run(tmp_path, [_before(tool), _ext()], _sessions())
    assert out == [{"effect": "ask", "calls": []}]


@pytest.mark.parametrize(
    "source",
    [None, {}, {"type": "tool", "id": "other"}],
    ids=["source 無し", "id 無し", "相関の無い id"],
)
def test_uncorrelated_external_directory_stays_ask(tmp_path, source):
    event = _ext()
    if source is None:
        del event[1]["source"]
    else:
        event[1]["source"] = source
    out = _run(tmp_path, [_before("read"), event], _sessions())
    assert out == [{"effect": "ask", "calls": []}]


def test_before_without_id_does_not_match_a_missing_source_id(tmp_path):
    before = _before("read")
    del before[1]["id"]
    event = _ext()
    event[1]["source"] = {"type": "tool"}
    out = _run(tmp_path, [before, event], _sessions())
    assert out == [{"effect": "ask", "calls": []}]


def test_finished_call_is_forgotten(tmp_path):
    """execute.after の後に同じ id が来ても引き上げない。"""
    after = ["execute.after", {"tool": "read", "id": "call_1", "agent": "explore"}]
    out = _run(tmp_path, [_before("read"), after, _ext()], _sessions())
    assert out == [{"effect": "ask", "calls": []}]


@pytest.mark.parametrize("effect", ["allow", "deny"])
def test_allow_and_deny_are_unchanged(tmp_path, effect):
    out = _run(tmp_path, [_before("read"), _ext(effect=effect)], _sessions())
    assert out == [{"effect": effect, "calls": []}]


@pytest.mark.parametrize(
    "sessions",
    [
        {
            "ses_c": {"id": "ses_c", "parentID": "ses_p", "agent": "review"},
            "ses_p": {"agent": "bypass"},
        },
        {"ses_c": {"id": "ses_c", "agent": "explore"}, "ses_p": {"agent": "bypass"}},
        {
            "ses_c": {"id": "ses_c", "parentID": "ses_p", "agent": "explore"},
            "ses_p": {"id": "ses_p"},
        },
        {"ses_c": {"id": "ses_c", "parentID": "ses_p"}, "ses_p": {"agent": "bypass"}},
        {"ses_c": {"id": "ses_c", "parentID": "ses_p", "agent": "explore"}, "ses_p": {"agent": 1}},
        {},
    ],
    ids=[
        "agent 不一致",
        "parentID 無し",
        "親の agent 無し",
        "子の agent 無し",
        "親の agent が文字列でない",
        "子が無い",
    ],
)
def test_inconsistent_sessions_stay_ask(tmp_path, sessions):
    out = _run(tmp_path, [_before("read"), _ext()], sessions)
    assert _effects(out) == ["ask"]


def test_missing_session_id_stays_ask_without_lookup(tmp_path):
    event = _ext()
    del event[1]["sessionID"]
    out = _run(tmp_path, [_before("read"), event], _sessions())
    assert out == [{"effect": "ask", "calls": []}]


@pytest.mark.parametrize(
    ("sessions", "calls"),
    [
        ({"ses_c": "throw", "ses_p": {"agent": "bypass"}}, ["ses_c"]),
        (
            {"ses_c": {"parentID": "ses_p", "agent": "explore"}, "ses_p": "throw"},
            ["ses_c", "ses_p"],
        ),
    ],
    ids=["子の取得で例外", "親の取得で例外"],
)
def test_lookup_failure_stays_ask(tmp_path, sessions, calls):
    out = _run(tmp_path, [_before("read"), _ext()], sessions)
    assert out == [{"effect": "ask", "calls": calls}]


@pytest.mark.parametrize("session", ["none", "no-get"], ids=["ctx.session 無し", "get 無し"])
def test_missing_session_api_stays_ask(tmp_path, session):
    out = _run(tmp_path, [_before("read"), _ext()], _sessions(), session=session)
    assert _effects(out) == ["ask"]


def test_parent_agent_change_is_not_cached(tmp_path):
    """同じ子で、親が bypass → build → bypass と変わったら、その都度引き直す。"""
    steps = []
    for i in range(3):
        steps += [_before("read", id_=f"call_{i}"), _ext(id_=f"call_{i}")]
    # 親の agent を、親が引かれるたびに次の値へ入れ替える
    script = SCRIPT.replace(
        "const v = input.sessions[sessionID]",
        "const v = sessionID === 'ses_p'"
        " ? { agent: input.parents.shift() }"
        " : input.sessions[sessionID]",
    )
    out = _run(tmp_path, steps, _sessions(), script=script, parents=["bypass", "build", "bypass"])
    assert _effects(out) == ["allow", "ask", "allow"]
    assert all(o["calls"] == ["ses_c", "ses_p"] for o in out)


def test_grandparent_is_not_consulted(tmp_path):
    """直接の親が build なら、祖父が bypass でも ask。祖父は取得しない。"""
    sessions = {
        "ses_c": {"id": "ses_c", "parentID": "ses_p", "agent": "explore"},
        "ses_p": {"id": "ses_p", "parentID": "ses_g", "agent": "build"},
        "ses_g": {"id": "ses_g", "agent": "bypass"},
    }
    out = _run(tmp_path, [_before("read"), _ext()], sessions)
    assert out == [{"effect": "ask", "calls": ["ses_c", "ses_p"]}]


_MISSING = object()


def _rules_with_children(value) -> dict:
    rules = gen.build_opencode_guide({}, COMMON)
    if value is _MISSING:
        del rules["bypass_child_agents"]
    else:
        rules["bypass_child_agents"] = value
    return rules


@pytest.mark.parametrize(
    "value",
    [_MISSING, None, "explore", {"explore": True}, [1], ["explore", None], []],
    ids=["無い", "null", "文字列", "オブジェクト", "数値の要素", "null の要素", "空"],
)
def test_unusable_children_list_disables_only_this_upgrade(tmp_path, value):
    """一覧が使えないときは子の引き上げだけを止める。bypass 自身の昇格と誘導は続く。"""
    rules = _rules_with_children(value)
    bypass_ask = {
        "sessionID": "ses_p",
        "agent": "bypass",
        "action": "edit",
        "resources": ["x"],
        "source": {"id": "e"},
        "effect": "ask",
    }
    guided = {
        "agent": "bypass",
        "action": "shell",
        "resources": ["rm -rf .git"],
        "source": {"id": "s"},
        "effect": "ask",
    }
    launch = {
        "agent": "build",
        "action": "subagent",
        "resources": ["bypass-worker"],
        "effect": "allow",
    }
    steps = [
        _before("read"),
        _ext(),
        ["evaluate", bypass_ask],
        ["evaluate", guided],
        ["evaluate", launch],
    ]
    out = _run(tmp_path, steps, _sessions(), rules=rules)
    assert out == [
        {"effect": "ask", "calls": []},
        {"effect": "allow", "calls": []},
        {"effect": "deny", "calls": []},
        {"effect": "deny", "calls": []},
    ]


def test_bypass_upgrade_and_guide_still_work(tmp_path):
    """回帰: 既存の bypass の ask→allow と誘導 deny は session API を使わない。"""
    steps = [
        [
            "evaluate",
            {
                "agent": "bypass",
                "action": "external_directory",
                "resources": ["/etc/*"],
                "source": {"id": "x"},
                "effect": "ask",
            },
        ],
        [
            "evaluate",
            {
                "agent": "bypass",
                "action": "shell",
                "resources": ["rm -rf .git"],
                "source": {"id": "y"},
                "effect": "ask",
            },
        ],
        [
            "evaluate",
            {
                "agent": "build",
                "action": "shell",
                "resources": ["touch x"],
                "source": {"id": "z"},
                "effect": "ask",
            },
        ],
    ]
    out = _run(tmp_path, steps, _sessions())
    assert out == [
        {"effect": "allow", "calls": []},
        {"effect": "deny", "calls": []},
        {"effect": "ask", "calls": []},
    ]


def test_grep_filter_still_applies_to_children(tmp_path):
    """回帰: 引き上げた後も grep の結果から保護対象を落とす。"""
    text = "Found 2 matches\n/home/u/p/.env:\n  Line 1: SECRET=x\n/home/u/p/a.py:\n  Line 2: ok"
    after = {
        "tool": "grep",
        "id": "call_1",
        "agent": "explore",
        "result": {"content": [{"text": text}]},
    }
    script = SCRIPT.replace(
        "console.log(JSON.stringify(out))",
        "console.log(JSON.stringify({ out, after: input.steps.at(-1)[1] }))",
    )
    steps = [_before("grep"), _ext(), ["execute.after", after]]
    result = _run(tmp_path, steps, _sessions(), script=script)
    assert _effects(result["out"]) == ["allow"]
    filtered = result["after"]["result"]["content"][0]["text"]
    assert "SECRET" not in filtered and "a.py" in filtered


# ---------------------------------------------------------------------------
# 生成 (common.toml → rules.json)
# ---------------------------------------------------------------------------


@pytest.fixture(
    params=[("applejxd", False), ("applejxd", True), ("worker", False), ("worker", True)],
    ids=["私用-通常", "私用-ocs", "会社用-通常", "会社用-ocs"],
)
def flavor(request, tmp_path):
    username, isolated = request.param
    common = load_common(username)
    if isolated:
        runtime = tmp_path / "fence"
        runtime.write_text("", "utf-8")
        sandbox = common["opencode"]["sandbox"]
        common["opencode"]["sandbox"] = {**sandbox, "runtime_path": str(runtime)}
    return common, isolated


def test_children_list_reaches_every_flavor(flavor):
    """通常版も ocs も同じ rules.json を読み、plugin が両方に載る。"""
    common, isolated = flavor
    guide = gen.build_opencode_guide({}, common)
    assert guide["bypass_child_agents"] == sorted(CHILDREN)
    if isolated:
        out = gen.opencode_sandbox(common)
        assert out is not None
        assert gen.opencode_guide_plugin_path() in out["plugins"]
    else:
        plugins = gen.merge_opencode_config({}, common)["plugins"]
        assert gen.opencode_guide_plugin_path() in plugins


def test_children_are_a_subset_of_the_bypass_launch_list():
    task = gen.merge_opencode_config({}, COMMON)["agent"]["bypass"]["permission"]["task"]
    allowed = {n for n, effect in task.items() if effect == "allow"}
    children = set(gen.build_opencode_guide({}, COMMON)["bypass_child_agents"])
    assert children <= allowed
    assert not children & set(gen.opencode_bypass_agents(COMMON))


def _common(children, task=None, agents=None) -> dict:
    task = task or {"*": "deny", "explore": "allow", "worker": "allow"}
    return {
        "opencode": {
            "agent": {
                "bypass": {"mode": "primary", "bypass": True, "permission": {"task": task}},
                "worker": {"mode": "subagent", "bypass": True},
            },
            "agents": agents or {},
            "bypass_children": {"agents": children},
        }
    }


def test_missing_children_table_is_an_empty_list():
    common = _common([])
    del common["opencode"]["bypass_children"]
    assert gen.opencode_bypass_child_agents(common) == []


def test_v2_subagent_allow_counts_as_launchable():
    agents = {
        "b2": {
            "description": "x",
            "mode": "primary",
            "bypass": True,
            "permissions": [{"action": "subagent", "resource": "review", "effect": "allow"}],
        }
    }
    assert gen.opencode_bypass_child_agents(_common(["review"], agents=agents)) == ["review"]


def test_children_list_alone_registers_the_plugin():
    common = {
        "opencode": {
            "agent": {
                "bypass": {
                    "mode": "primary",
                    "bypass": True,
                    "permission": {"task": {"explore": "allow"}},
                }
            },
            "bypass_children": {"agents": ["explore"]},
        }
    }
    assert gen.opencode_guide_server_needed(common, tui=False)


@pytest.mark.parametrize(
    ("children", "task", "message"),
    [
        (["general"], None, "起動を許可した子に無い"),
        (["explore", "review"], None, "起動を許可した子に無い"),
        (["*"], {"*": "allow"}, "ワイルドカード"),
        (["exp*"], None, "ワイルドカード"),
        (["worker"], None, "重なる"),
        ("explore", None, "文字列の配列"),
        ([1], None, "文字列の配列"),
        ([""], None, "文字列の配列"),
        (["explore"], {"*": "allow"}, "起動を許可した子に無い"),
    ],
    ids=[
        "許可リストに無い",
        "一部が無い",
        "全部",
        "前方一致",
        "bypass と重複",
        "文字列",
        "数値",
        "空文字",
        "* の allow からは導出しない",
    ],
)
def test_invalid_children_stop_the_generation(children, task, message):
    with pytest.raises(ValueError, match=message):
        gen.build_opencode_guide({}, _common(children, task))

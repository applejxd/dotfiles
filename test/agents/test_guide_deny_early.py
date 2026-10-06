"""OpenCode の guide: 静的 deny の説明付きの前段停止 (``[bash.deny_guide]``)。

V2 は config の静的 deny に当たると plugin の ``permission.evaluate`` を呼ばず、モデルには
``Permission denied: shell`` だけが返る。``rules.json`` の ``deny_guide`` を
``tool.execute.before`` で当てて、説明付きで止める (see test_guide_early_pip.py の pip)。

★最も大事な性質: **前段で止まるのは、静的 deny にも当たるコマンドだけ** (部分集合)。
静的な照合は scanner が分割したセグメントごとに ``cmd`` / ``cmd *`` を当てるので、
それを模擬して、コーパスの全コマンド・全エージェント・通常版/隔離版で確かめる。

Run with: ``uv run --with pytest --with pyyaml --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import copy
import json
import re
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
DENY = [str(c) for c in COMMON["bash"]["deny"]]
GUIDE = COMMON["bash"]["deny_guide"]
ELSEWHERE = [str(c) for c in GUIDE["elsewhere"]]
CLASSIFIED = [c for c in DENY if c not in ELSEWHERE]
USER_MESSAGE = GUIDE["user_message"]

# --- 静的照合の模擬 ----------------------------------------------------------
# OpenCode の照合 (後勝ち・``*`` は空白や ``/`` や改行も含む任意の文字列・末尾の `` *`` は
# 引数なしにも当たる)。scanner の分割は ``&&`` ``||`` ``;`` ``|`` ``&`` 改行と括弧で、
# 引用符の中と ``\`` の直後は分割しない。see docs/research/opencode/permission/allow-list-audit.md


def _glob(pattern: str) -> str:
    return "".join(".*" if c == "*" else re.escape(c) for c in pattern)


def _regex(pattern: str) -> re.Pattern[str]:
    body = _glob(pattern[:-2]) + "( .*)?" if pattern.endswith(" *") else _glob(pattern)
    return re.compile(body, re.DOTALL)


def split_segments(command: str) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    quote = ""
    i = 0
    while i < len(command):
        c = command[i]
        if quote:
            cur.append(c)
            if c == "\\" and quote == '"' and i + 1 < len(command):
                cur.append(command[i + 1])
                i += 1
            elif c == quote:
                quote = ""
        elif c == "\\" and i + 1 < len(command):
            cur += [c, command[i + 1]]
            i += 1
        elif c in "'\"":
            quote = c
            cur.append(c)
        elif c in ";|&\n()`":
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    out.append("".join(cur).strip())
    return [s for s in out if s]


class Static:
    def __init__(self, rules: list[dict]):
        self.rules = [
            (_regex(r["resource"]), r["effect"]) for r in rules if r["action"] in ("shell", "*")
        ]

    def effect(self, segment: str) -> str:
        effect = "ask"
        for regex, eff in self.rules:
            if regex.fullmatch(segment):
                effect = eff
        return effect

    def denies(self, command: str) -> bool:
        return any(self.effect(s) == "deny" for s in split_segments(command))


def agent_rules(name: str) -> list[dict]:
    agent = (COMMON["opencode"].get("agents") or {}).get(name) or {}
    return list(agent.get("permissions") or [])


def static_for(agent: str, isolated: bool) -> Static:
    base = (
        gen.build_opencode_sandbox_permissions(COMMON)
        if isolated
        else gen.build_opencode_permissions(COMMON)
    )
    return Static(base + agent_rules(agent))


# --- plugin (node) -----------------------------------------------------------

SCRIPT = """
import plugin from './index.js'
import { readFileSync } from 'node:fs'
const hooks = {}
const ctx = { tool: { hook: (n, fn) => { hooks[n] = fn } }, permission: { hook() {} },
  shell: { hook() {} } }
await plugin.setup(ctx)
const cases = JSON.parse(readFileSync(process.argv[2], 'utf8'))
const out = []
for (const [cmd, agent, tool] of cases) {
  const e = { tool: tool ?? 'shell', id: 'x', input: { command: cmd } }
  if (agent !== null) e.agent = agent
  try {
    await hooks['execute.before'](e)
    out.push(null)
  } catch (err) {
    out.push(err.message)
  }
}
console.log(JSON.stringify(out))
"""


def _run(
    tmp_path: Path,
    cases: list[tuple],
    *,
    isolated: bool = False,
    rules: dict | str | None = None,
) -> list[str | None]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い (mise.toml の [tools] に宣言してある)")
    shutil.copy(PLUGIN / "index.js", tmp_path / "index.js")
    if rules is None:
        rules = gen.build_opencode_guide({}, COMMON)
    (tmp_path / "rules.json").write_text(
        rules if isinstance(rules, str) else json.dumps(rules), "utf-8"
    )
    (tmp_path / "run.mjs").write_text(SCRIPT, "utf-8")
    (tmp_path / "cases.json").write_text(json.dumps(cases), "utf-8")
    env = node_env(OCS_ISOLATED="1") if isolated else node_env()
    done = subprocess.run(
        [node, str(tmp_path / "run.mjs"), str(tmp_path / "cases.json")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env=env,
        timeout=120,
    )
    return json.loads(done.stdout)


# --- 生成器 ------------------------------------------------------------------


def _common_with(**guide_changes) -> dict:
    common = copy.deepcopy(COMMON)
    common["bash"]["deny_guide"].update(guide_changes)
    return common


def test_every_deny_belongs_to_exactly_one_class():
    """deny の全項目が user_only / alternative / elsewhere のどれか 1 つに属す。"""
    classes = [
        *GUIDE["user_only"],
        *[c for a in GUIDE["alternative"] for c in a["commands"]],
        *GUIDE["elsewhere"],
    ]
    assert sorted(classes) == sorted(DENY)
    assert len(classes) == len(set(classes))


def test_unclassified_deny_stops_generation():
    common = copy.deepcopy(COMMON)
    common["bash"]["deny"].append("some-new-command")
    with pytest.raises(SystemExit, match="some-new-command"):
        gen.build_opencode_guide({}, common)


def test_unknown_command_in_a_class_stops_generation():
    common = _common_with(user_only=[*GUIDE["user_only"], "not-in-deny"])
    with pytest.raises(SystemExit, match="not-in-deny"):
        gen.build_opencode_guide({}, common)


def test_command_in_two_classes_stops_generation():
    common = _common_with(elsewhere=[*GUIDE["elsewhere"], "sudo"])
    with pytest.raises(SystemExit, match="sudo"):
        gen.build_opencode_guide({}, common)


def test_alternative_needs_a_message():
    common = copy.deepcopy(COMMON)
    common["bash"]["deny_guide"]["alternative"][0].pop("message")
    with pytest.raises(SystemExit):
        gen.build_opencode_guide({}, common)


def test_elsewhere_needs_a_real_early_guide_rule():
    common = copy.deepcopy(COMMON)
    for rule in common["opencode"]["shell"]["guide"]:
        rule.pop("early", None)
    with pytest.raises(SystemExit, match="early"):
        gen.build_opencode_guide({}, common)


def test_rules_json_has_early_rules_for_every_classified_deny():
    rules = gen.build_opencode_guide({}, COMMON)["deny_guide"]
    assert rules
    for cmd in CLASSIFIED:
        hits = [r for r in rules if re.search(r["pattern"], f"{cmd} x")]
        assert len(hits) == 1, cmd
        re.compile(hits[0]["pattern"])
        re.compile(hits[0]["unless"])
        assert hits[0]["message"]


def test_deny_guide_is_not_mixed_into_the_evaluate_rules():
    """evaluate の誘導 (``guide``) に混ぜない。混ぜると静的 deny に無い場面 (隔離版・エージェントの
    allow) でも止まる。"""
    out = gen.build_opencode_guide({}, COMMON)
    for rule in out["deny_guide"]:
        assert rule not in out["guide"]
    assert not [r for r in out["guide"] if USER_MESSAGE in r["message"]]


def test_static_deny_list_is_unchanged_by_the_guide():
    """説明のために静的 deny を外していない (plugin が壊れても静的 deny が止める)。"""
    config = gen.merge_opencode_config({}, COMMON)
    denied = {
        r["resource"]
        for r in config["permissions"]
        if r["action"] == "shell" and r["effect"] == "deny"
    }
    for cmd in DENY:
        assert f"{cmd} *" in denied, cmd


def test_ocs_marks_only_the_rules_ocs_drops():
    """隔離版が捨てた deny には ``not_isolated`` が付き、残した deny には付かない。"""
    rules = gen.build_opencode_guide({}, COMMON)["deny_guide"]
    ocs = {
        r["resource"]
        for r in gen.build_opencode_sandbox_permissions(COMMON)
        if r["action"] == "shell" and r["effect"] == "deny"
    }
    normal = {
        r["resource"]
        for r in gen.build_opencode_permissions(COMMON)
        if r["action"] == "shell" and r["effect"] == "deny"
    }
    for cmd in CLASSIFIED:
        (rule,) = [r for r in rules if re.search(r["pattern"], f"{cmd} x")]
        assert f"{cmd} *" in normal
        assert rule.get("not_isolated", False) == (f"{cmd} *" not in ocs), cmd
    # 取り違えていない (どちらの側にも実例がある)
    assert any(f"{c} *" not in ocs for c in CLASSIFIED)
    assert any(f"{c} *" in ocs for c in CLASSIFIED)


def test_no_declared_agent_overrides_a_deny_today():
    """今の宣言で静的 deny を覆すエージェントは無い。

    覆すエージェントを対象外にする仕組みは test_v1_agent_permissions_* が確かめる。
    """
    rules = gen.build_opencode_guide({}, COMMON)["deny_guide"]
    assert not [r for r in rules if r.get("except_agents")]


def test_claude_and_copilot_generation_is_unchanged_by_deny_guide():
    """``[bash.deny_guide]`` は OpenCode 専用。Claude / Copilot の permission に出さない。"""
    without = copy.deepcopy(COMMON)
    without["bash"].pop("deny_guide")
    assert gen.build_claude_permissions(COMMON) == gen.build_claude_permissions(without)
    assert gen.merge_claude_settings({}, COMMON) == gen.merge_claude_settings({}, without)


# --- plugin: 説明が返ること --------------------------------------------------

AGENTS = ["build", "bypass", "bypass-worker", "bypass-fleet-worker", "fleet-worker"]


def test_alternative_and_user_messages_reach_the_model(tmp_path):
    cases = [
        ("npm install -g cowsay", "build", "shell"),
        ("uv self update", "build", "shell"),
        ("chezmoi upgrade", "build", "shell"),
        ("git config --local user.name x", "build", "shell"),
        ("git config core.hooksPath x", "build", "shell"),
        ("docker system prune -af", "build", "shell"),
        ("npm cache clean --force", "build", "shell"),
        ("git push", "build", "shell"),
        ("git push origin main", "build", "shell"),
        ("sudo true", "build", "shell"),
        ("git reset --hard HEAD~1", "build", "shell"),
        ("ls && ssh host", "build", "shell"),
        ("echo a | psql", "build", "shell"),
        ("git stash drop", "build", "shell"),
    ]
    out = _run(tmp_path, cases)
    want = [
        "mise use -g",
        "導入元",
        "導入元",
        "dot_gitconfig.tmpl",
        "dot_gitconfig.tmpl",
        "docker rm",
        "利用者",
        USER_MESSAGE,
        USER_MESSAGE,
        USER_MESSAGE,
        USER_MESSAGE,
        USER_MESSAGE,
        USER_MESSAGE,
        USER_MESSAGE,
    ]
    for (cmd, *_), got, expect in zip(cases, out, want, strict=True):
        assert got and expect in got, f"{cmd!r}: {got!r}"


@pytest.mark.parametrize("agent", AGENTS)
def test_bypass_agents_are_stopped_like_the_others(tmp_path, agent):
    """bypass でも同じ説明で止める (bypass の deny は通常どおり効く定義)。"""
    out = _run(
        tmp_path,
        [
            ("git push", agent, "shell"),
            ("npm install -g x", agent, "shell"),
            ("git push", agent, "grep"),
        ],
    )
    assert out[0] == USER_MESSAGE
    assert out[1] and "mise use -g" in out[1]
    assert out[2] is None, "shell 以外のツールは止めない"


def test_ocs_stops_only_what_ocs_still_denies(tmp_path):
    cases = [
        ("git push", "build", "shell"),  # ocs でも静的 deny が残る
        ("git config --local user.name x", "build", "shell"),
        ("sudo true", "build", "shell"),  # ocs は捨てる (既定 allow)
        ("npm install -g cowsay", "build", "shell"),
        ("git config --global user.name x", "build", "shell"),
        ("docker system prune", "build", "shell"),
        ("ls && systemctl restart x", "build", "shell"),
    ]
    normal = _run(tmp_path, cases)
    ocs = _run(tmp_path, cases, isolated=True)
    assert all(normal), normal
    assert [bool(x) for x in ocs] == [True, True, False, False, False, False, False]


def test_unknown_agent_is_not_stopped(tmp_path):
    """agent が分からなければ止めない (静的 deny に任せる)。"""
    cases = [("git restore a.txt", "build", "shell"), ("git restore a.txt", None, "shell")]
    assert _run(tmp_path, cases) == [USER_MESSAGE, None]


def test_unreadable_rules_stop_nothing(tmp_path):
    cases = [("git push", "build", "shell")]
    assert _run(tmp_path, cases, rules="{ broken") == [None]


def _broken(**changes):
    rules = gen.build_opencode_guide({}, COMMON)
    rules.update(changes)
    return rules


GOOD = {"pattern": "(^|;)git push", "unless": "x", "message": "m"}


@pytest.mark.parametrize(
    "deny_guide",
    [
        [{"message": "x"}],  # pattern 欠落 (new RegExp(undefined) は全一致)
        [{"pattern": "", "unless": "x", "message": "x"}],
        [{"pattern": "git push", "message": "x"}],  # unless 必須
        [{"pattern": "git push", "unless": "", "message": "x"}],
        [{"pattern": "git push", "unless": "x"}],  # message 欠落
        [{"pattern": "git push", "unless": "x", "message": ""}],
        [{"pattern": 1, "unless": "x", "message": "x"}],
        [{"pattern": ".*", "unless": "zzz", "message": "x"}],  # 全一致
        [{"pattern": "(", "unless": "x", "message": "x"}],  # 壊れた正規表現
        [{**GOOD, "not_isolated": "yes"}],
        [{**GOOD, "except_agents": "commit"}],
        [{**GOOD, "except_agents": [1]}],
        [GOOD, "not an object"],
        [GOOD, None],
        "not a list",
        {"pattern": "git push"},
    ],
)
def test_malformed_deny_guide_disables_the_whole_section(tmp_path, deny_guide):
    """1 件でも不正なら節ごと無効 (健全な GOOD も止めない)。全 shell を止める事故を避ける。"""
    cases = [("git push", "build", "shell"), ("ls", "build", "shell"), ("echo", "build", "shell")]
    assert _run(tmp_path, cases, rules=_broken(deny_guide=deny_guide)) == [None] * 3


@pytest.mark.parametrize("agents", [None, "build", [1], {"build": True}])
def test_missing_or_malformed_agent_list_disables_deny_guide(tmp_path, agents):
    rules = _broken()
    if agents is None:
        del rules["deny_guide_agents"]
    else:
        rules["deny_guide_agents"] = agents
    assert _run(tmp_path, [("git push", "build", "shell")], rules=rules) == [None]


def test_deny_guide_absent_is_not_an_error(tmp_path):
    """古い rules.json (deny_guide 無し) は何も止めない。pip の early は動く。"""
    rules = _broken()
    del rules["deny_guide"], rules["deny_guide_agents"]
    out = _run(
        tmp_path, [("git push", "build", "shell"), ("pip install x", "build", "shell")], rules=rules
    )
    assert out[0] is None and out[1]


@pytest.mark.parametrize(
    "guide",
    [
        [{"message": "x", "early": True}],  # pattern 欠落
        [{"pattern": "", "message": "x", "early": True}],
        [{"pattern": "pip", "early": True}],  # message 欠落
        [{"pattern": "pip", "message": "x", "unless": 1, "early": True}],
        [{"pattern": "pip", "message": "x", "early": "yes"}],
        ["not an object"],
    ],
)
def test_malformed_guide_does_not_stop_everything(tmp_path, guide):
    """既存の guide 節にも同じ穴があった (pattern 欠落が全一致になる)。"""
    cases = [("ls", "build", "shell"), ("echo hi", "build", "shell")]
    assert _run(tmp_path, cases, rules=_broken(guide=guide)) == [None, None]


# --- 対象エージェント -------------------------------------------------------


def test_agent_list_has_declared_and_builtin_agents():
    agents = gen.opencode_deny_guide_agents(COMMON)
    for name in (
        "build",
        "plan",
        "general",
        "explore",
        "review",
        "fleet-worker",
        "bypass",
    ):
        assert name in agents, name
    assert "custom-agent" not in agents


def test_unknown_agents_are_left_to_the_static_deny(tmp_path):
    """宣言外 (利用者が opencode.json に直接書いた) や不明な agent では前段で止めない。"""
    cases = [
        ("git push", "custom-agent", "shell"),
        ("git push", None, "shell"),
        ("git push", "title", "shell"),
        *[("git push", a, "shell") for a in ("build", "plan", "general", "explore")],
    ]
    out = _run(tmp_path, cases)
    assert out[:3] == [None, None, None]
    assert all(out[3:])


def _with_v1(permission) -> dict:
    common = copy.deepcopy(COMMON)
    common["opencode"]["agent"]["mine"] = {"mode": "primary", "permission": permission}
    return common


@pytest.mark.parametrize(
    "permission",
    [
        {"bash": {"git push *": "allow"}},
        {"shell": {"git push *": "ask"}},
        {"*": {"*": "allow"}},
        {"bash": "allow"},
        {"*": "allow"},
        "allow",
        {"bash": 5},  # 読めない形は覆しうるものとして扱う
    ],
)
def test_v1_agent_permissions_that_override_a_deny_are_exempt(permission):
    rules = gen.build_opencode_guide({}, _with_v1(permission))["deny_guide"]
    (rule,) = [r for r in rules if re.search(r["pattern"], "git push x")]
    assert "mine" in rule["except_agents"]


@pytest.mark.parametrize(
    "permission",
    [{"task": {"*": "allow"}}, {"bash": {"git push *": "deny"}}, {"bash": {"ls *": "allow"}}, {}],
)
def test_v1_agent_without_an_override_is_not_exempt(permission):
    rules = gen.build_opencode_guide({}, _with_v1(permission))["deny_guide"]
    (rule,) = [r for r in rules if re.search(r["pattern"], "git push x")]
    assert "mine" not in rule.get("except_agents", [])


def test_v1_exempt_agent_is_not_stopped_by_the_plugin(tmp_path):
    rules = gen.build_opencode_guide({}, _with_v1({"bash": {"git push *": "allow"}}))
    out = _run(
        tmp_path, [("git push", "mine", "shell"), ("git push", "build", "shell")], rules=rules
    )
    assert out[0] is None and out[1]


# --- スキルのスクリプトのリダイレクト ------------------------------------------

SKILL_HEADS = gen._skill_script_allow_and_heads(COMMON)[1]
SKILL_MESSAGE = COMMON["opencode"]["skill_scripts"]["redirect_message"]
LINT_DOCS = "python3 ~/.claude/skills/sdd-docs/scripts/lint_docs.py"
CHECKPOINT = "python3 ~/.config/opencode/skills/checkpoint/scripts/checkpoint.py"
CHECK_REFS = "python3 ~/.claude/skills/sdd-docs/scripts/check_refs.py"

SKILL_STOP = [
    f"{LINT_DOCS} 2>&1",
    f"{LINT_DOCS} > out.txt",
    f"{LINT_DOCS} >> out.txt",
    f"{LINT_DOCS} < in.txt",
    f"{LINT_DOCS} >/dev/null",
    f"{LINT_DOCS} 2>&1 | tail -5",
    f"ls && {LINT_DOCS} > out.txt",
    f"{CHECKPOINT} read --session s 2>&1",
    f"{CHECKPOINT} lint x > out.txt",
    LINT_DOCS.replace("~", gen.expand_user("~")) + " > out.txt",
]
SKILL_PASS = [
    LINT_DOCS,
    f"{LINT_DOCS} | tail -5",
    f"{LINT_DOCS}; echo a > out.txt",
    f"{LINT_DOCS} && echo a > out.txt",
    f"{LINT_DOCS}.bak > out.txt",
    f'python3 "{LINT_DOCS[8:]}" > out.txt',
    f"{CHECKPOINT} write x > out.txt",
    f"{CHECKPOINT} lint 'a b' > out.txt",
    f"{CHECK_REFS} --save > out.txt",
    f"{CHECK_REFS} --save",
]


def test_skill_redirect_rules_are_generated():
    rules = [
        r
        for r in gen.build_opencode_guide({}, COMMON)["deny_guide"]
        if r["message"] == SKILL_MESSAGE
    ]
    assert rules
    for head in SKILL_HEADS:
        assert any(re.search(r["pattern"], f"{head} > x") for r in rules), head


def test_skill_redirect_rules_need_a_message():
    common = copy.deepcopy(COMMON)
    del common["opencode"]["skill_scripts"]["redirect_message"]
    with pytest.raises(SystemExit, match="redirect_message"):
        gen.build_opencode_guide({}, common)


def test_skill_redirect_rules_survive_without_bash_deny_guide():
    common = copy.deepcopy(COMMON)
    del common["bash"]["deny_guide"]
    rules = gen.build_opencode_guide({}, common)["deny_guide"]
    assert rules and all(r["message"] == SKILL_MESSAGE for r in rules)


@pytest.mark.parametrize("agent", ["build", "bypass", "fleet-worker"])
def test_skill_redirects_are_explained(tmp_path, agent):
    cases = [(c, agent, "shell") for c in SKILL_STOP + SKILL_PASS]
    out = _run(tmp_path, cases)
    static = static_for(agent, False)
    for cmd, got in zip(SKILL_STOP, out[: len(SKILL_STOP)], strict=True):
        assert static.denies(cmd), f"静的 deny に無い例を置いた: {cmd!r}"
        assert got == SKILL_MESSAGE, f"{cmd!r}: {got!r}"
    for cmd, got in zip(SKILL_PASS, out[len(SKILL_STOP) :], strict=True):
        assert got is None, f"{cmd!r} を前段で止めた: {got!r}"


def test_skill_redirects_are_not_stopped_in_ocs(tmp_path):
    """隔離版は既定 allow でスキルの静的 deny を捨てる。前段も止めない。"""
    out = _run(tmp_path, [(c, "build", "shell") for c in SKILL_STOP], isolated=True)
    static = static_for("build", True)
    for cmd, got in zip(SKILL_STOP, out, strict=True):
        assert got is None or static.denies(cmd), f"{cmd!r} を隔離版で止めた: {got!r}"


# --- 部分集合の性質 ----------------------------------------------------------

SHAPES = [
    "{c}",
    "{c} x",
    "{c} --help",
    "ls && {c} x",
    "ls; {c} x",
    "ls;{c} x",
    "ls | {c} x",
    "ls || {c} x",
    "{c} x; ls",
    "ls\n{c} x",
    "  {c} x",
    "FOO=1 {c} x",
    "echo {c}",
    "echo x; echo {c}",
    'echo "{c} x"',
    "echo '{c} x'",
    'echo "a; {c} x"',
    "echo 'a && {c} x'",
    "echo a # ; {c} x",
    "echo a \\; {c} x",
    "ls \\\n{c} x",
    "echo $({c} x)",
    "echo `{c} x`",
    "({c} x)",
    "{{ {c} x; }}",
    "cat <<EOF\n{c} x\nEOF",
    "{c}\tx",
    "{c}x",
    "{c}-x",
    "{c}.x",
    "ls &&\n{c} x",
    '{c} "q; r"',
    "ls & {c} x",
    "echo a > f; {c} x",
]

EXTRA = [
    "git config --get user.name",
    "git config --list",
    "git config user.name",
    "git config --global user.name 'A B'",
    "git config --global --get user.name",
    "git stash list",
    "git stash push",
    "git stash",
    "git reset HEAD~1",
    "git reset --soft HEAD~1",
    "git checkout main",
    "git checkout -b x",
    "git restore --help",
    "git restore --staged -- a.txt",
    "git restore a.txt",
    "systemctl status x",
    "systemctl show x",
    "docker ps",
    "docker rm abc",
    "docker rmi abc",
    "docker system df",
    'echo "git push"',
    "echo sudo",
    "cat file",
    "atop",
    "at",
    "atq",
    "ls; echo sudo",
    "gh pr view",
    "gh pr merge 1",
    "npm install x",
    "npm install --save-dev x",
    "uv self version",
    "uv sync",
    "sudoedit x",
    "mkfs.btrfs x",
    "ssh-keygen -t ed25519",
    "scp2 x",
    "git pushx",
    "git  push",
    "git -C x push",
    "git commit -m 'sudo x'",
    'git commit -m "git push"',
    "echo a >f; ls",
    "uv pip install x",
    "mise use -g npm:cowsay",
]


def _corpus() -> list[str]:
    seen: dict[str, None] = {}
    for cmd in CLASSIFIED:
        for shape in SHAPES:
            seen[shape.format(c=cmd)] = None
    for cmd in EXTRA + SKILL_STOP + SKILL_PASS:
        seen[cmd] = None
    return list(seen)


PROPERTY_AGENTS = ["build", "fleet-worker", "review"]


@pytest.fixture(scope="module")
def stops(tmp_path_factory):
    """(isolated, agent, command) -> 前段の停止メッセージ (止めなければ None)。"""
    corpus = _corpus()
    out: dict[tuple[bool, str, str], str | None] = {}
    for isolated in (False, True):
        tmp = tmp_path_factory.mktemp("early")
        cases = [(c, a, "shell") for a in PROPERTY_AGENTS for c in corpus]
        results = _run(tmp, cases, isolated=isolated)
        for (c, a, _), got in zip(cases, results, strict=True):
            out[(isolated, a, c)] = got
    return out


def test_early_stop_is_a_subset_of_the_static_deny(stops):
    """★前段で止まる ⇒ 静的にも deny。偽陽性 (静的 deny に無いものを止める) が無いこと。"""
    statics = {(iso, a): static_for(a, iso) for iso in (False, True) for a in PROPERTY_AGENTS}
    bad = [
        (iso, agent, cmd)
        for (iso, agent, cmd), got in stops.items()
        if got and not statics[(iso, agent)].denies(cmd)
    ]
    assert not bad, f"前段が静的 deny に無いコマンドを止めた: {bad[:10]}"


def test_corpus_exercises_both_outcomes(stops):
    """止める例が実際に多数あり、静的 deny なのに止めない例 (引用符など) もある。"""
    stopped = [k for k, v in stops.items() if v]
    assert len(stopped) > 200
    static = static_for("build", False)
    missed = [k for k, v in stops.items() if not v and k[1] == "build" and not k[0]]
    assert any(static.denies(k[2]) for k in missed), "保守側に倒した例が 1 つも無い"


DIRECT = ["{c}", "{c} x", "ls && {c} x", "ls; {c} x", "ls | {c} x", "{c} x; ls", "ls\n{c} x"]


def test_plain_forms_of_every_ocs_kept_deny_are_stopped(stops):
    """引用符などを含まない素直な形は、通常版・隔離版とも残っている deny について必ず止める。"""
    for isolated in (False, True):
        static = static_for("build", isolated)
        for cmd in CLASSIFIED:
            if not static.denies(f"{cmd} x"):
                continue
            for shape in DIRECT:
                command = shape.format(c=cmd)
                assert stops[(isolated, "build", command)], (isolated, command)


@pytest.mark.parametrize(
    "command", [c for c in EXTRA if not c.startswith(("git restore", "git config --global --get"))]
)
def test_commands_outside_the_static_deny_are_not_stopped(stops, command):
    """止めてはいけない例 (読み取り・ask・別コマンド・語境界)。静的 deny でないものは通す。"""
    static = static_for("build", False)
    got = stops[(False, "build", command)]
    if got:
        assert static.denies(command), f"{command!r} を前段で止めた: {got}"
    forbidden = {
        "git config --get user.name",
        "git config --list",
        "git stash list",
        "git stash push",
        "git reset HEAD~1",
        "git checkout main",
        "systemctl status x",
        "docker ps",
        "docker rm abc",
        'echo "git push"',
        "cat file",
        "atop",
        "ls; echo sudo",
        "gh pr view",
        "npm install x",
        "uv self version",
    }
    if command in forbidden:
        assert got is None, command

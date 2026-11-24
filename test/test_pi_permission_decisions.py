"""pi の権限の方針 (stock) を、実際の判定エンジンに通して、(コマンド → 判定) の表と照合する。

- ``pi-permission-policy.json`` を、``@gotgenes/pi-permission-system`` の判定エンジンに直接入れて評価する
  (YOLO は切った状態。bash は複合コマンドの分解とラッパーの床を含む)。
- ``home/dot_cc-safety-net/`` の規則を、``cc-safety-net`` の ``explain`` に通す。
- 表は ``test/agents/pi_stock/permission_cases.json``。規則を変えたら、表に例を足して回す
  (規則の書き間違いと、誤判定 = 通常の作業を止める・危険な形を通す、を開発の段階で見つける)。

pi の package が入っていない環境 (CI など) では skip する。skip は通過ではない。
see docs/spec/agent-config-generation.md#permission-system-の設定
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "home" / ".chezmoitemplates" / "pi-permission-policy.json"
CSN_RULES = ROOT / "home" / "dot_cc-safety-net" / "rules"
DRIVER = ROOT / "test" / "agents" / "pi_stock" / "permission_check.mjs"
CASES = json.loads((ROOT / "test" / "agents" / "pi_stock" / "permission_cases.json").read_text(encoding="utf-8"))


# T3 の MCP ツール (pi では mcp__t3-code__<名前>)。判定表の t3_mcp に無い新しいツールが ask になることも確かめる
T3_FUTURE_TOOL = "a_future_tool_not_in_the_table"
T3_TOOLS = [(t, "allow") for t in CASES["t3_mcp"]["allow"]] + [(t, "ask") for t in [*CASES["t3_mcp"]["ask"], T3_FUTURE_TOOL]]
# mcp.json に宣言されたサーバ (T3 は宣言されない。宣言されないサーバの名前は、最初の ``__`` で分けられる)
MCP_SERVERS = ["agentcore-websearch", "websearch", "webfetch"]

AGENT_DIR = Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent")
NODE_MODULES = AGENT_DIR / "npm" / "node_modules"
PERMISSION_PKG = NODE_MODULES / "@gotgenes" / "pi-permission-system"
JITI = NODE_MODULES / "jiti"
CSN_CLI = NODE_MODULES / "cc-safety-net" / "dist" / "bin" / "cc-safety-net.js"


def _alias_root() -> Path | None:
    """pi 本体の install (``@earendil-works/*`` を含む node_modules)。版を問わず、新しい方を使う。"""
    for base in (AGENT_DIR / "install" / "releases", Path(os.environ.get("PI_MANAGED_INSTALL_ROOT", "")) / "releases"):
        found = sorted(base.glob("*/node_modules/@earendil-works/pi-coding-agent")) if base.is_dir() else []
        if found:
            return found[-1].parents[1]
    return None


ALIAS_ROOT = _alias_root()

needs_engine = pytest.mark.skipif(
    not (shutil.which("node") and PERMISSION_PKG.is_dir() and JITI.is_dir() and ALIAS_ROOT),
    reason="pi-permission-system の package か node が無い (pi を入れた機械でだけ回る)",
)
needs_csn = pytest.mark.skipif(
    not (shutil.which("node") and CSN_CLI.is_file()),
    reason="cc-safety-net の package か node が無い (pi を入れた機械でだけ回る)",
)


def _home(value: str) -> str:
    """表の ``$HOME`` を、この機械のホームへ展開する (規則の ``~`` は規則の側だけが展開され、値は展開されない)。"""
    return value.replace("$HOME", str(Path.home()))


def run_engine(
    tmp_path: Path,
    *,
    bash=(),
    surface=(),
    access=(),
    alias=(),
    mcp_tools=(),
    project=None,
    agents=None,
    agent_bash=(),
    name="in",
) -> dict:
    payload = {
        "pkg": str(PERMISSION_PKG),
        "jiti": str(JITI),
        "aliasRoot": str(ALIAS_ROOT),
        "policy": json.loads(POLICY.read_text(encoding="utf-8")),
        "bash": list(bash),
        "surface": [[s[0], _home(s[1])] for s in surface],
        "access": [_home(c) for c in access],
        "alias": [[a[0], [_home(v) for v in a[1]]] for a in alias],
        "mcpTools": list(mcp_tools),
        "mcpServers": MCP_SERVERS,
    }
    if project is not None:
        payload["project"] = project
    if agents:
        payload["agents"] = agents
        payload["agentBash"] = [list(c) for c in agent_bash]
    src = tmp_path / f"{name}.json"
    src.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    done = subprocess.run(
        ["node", str(DRIVER), str(src)], capture_output=True, text=True, encoding="utf-8", timeout=180, check=False
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


@pytest.fixture(scope="module")
def engine_result(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("perm")
    return run_engine(
        tmp,
        bash=[c["cmd"] for c in CASES["bash"]],
        surface=CASES["surface"],
        access=[c[0] for c in CASES["access"]],
        alias=CASES.get("alias", []),
        mcp_tools=[f"mcp__t3-code__{tool}" for tool, _ in T3_TOOLS],
    )


@needs_engine
def test_bash_decisions_match_the_table(engine_result):
    """表の (コマンド → 判定)。ずれは、規則の書き間違い・通常の作業を止める誤判定・危険な形の見逃しのどれか。"""
    bad = []
    for case, got in zip(CASES["bash"], engine_result["bash"], strict=True):
        if got["state"] != case["perm"]:
            bad.append(f"{case['cmd']!r}: 期待 {case['perm']} / 実際 {got['state']} ({got['pattern']})")
    assert not bad, "\n".join(bad)


@needs_engine
def test_every_bash_rule_is_exercised_by_the_table(engine_result):
    """方針の bash の規則は、表のどれかの例が当たる (当たらない規則は、書き間違いか、表の不足)。"""
    policy_rules = set(json.loads(POLICY.read_text(encoding="utf-8"))["permission"]["bash"]) - {"*"}
    hit = {g["pattern"] for g in engine_result["bash"]}
    assert not (policy_rules - hit), f"表のどの例も当たらない規則: {sorted(policy_rules - hit)}"


def test_external_directory_read_keeps_denies_and_asks_after_every_allow():
    """同じ面では最後に一致した規則が勝ち、値は symlink の実体・``..`` を含む綴りのどれかに一致すればよい。

    deny・ask が allow より前にあると、symlink や ``..`` を含む綴りが、allow に一致して deny・ask を上書きする。
    方針は「allow が前、``..`` を含む綴りの ask が次、deny・ask が最後」を守る (判定表の ``alias`` が実ゲートと同じ評価で確かめる)。
    """
    policy = json.loads(POLICY.read_text(encoding="utf-8"))["permission"]
    rules = policy["external_directory_read"]
    actions = [(v["action"] if isinstance(v, dict) else v) for v in rules.values()]
    first_non_allow = next(i for i, a in enumerate(actions) if a != "allow")
    assert all(a != "allow" for a in actions[first_non_allow:]), "allow が、deny・ask の後ろにある"
    assert list(rules)[first_non_allow : first_non_allow + 2] == ["*/../*", "*/.."], "`..` の ask は、deny・ask の前に置く"
    bare = policy["external_directory"]
    assert bare["*/../*"] == "ask" and bare["*/.."] == "ask"


def test_t3_mcp_allow_list_matches_the_policy():
    """T3 の MCP は、ツールごとに ``t3-code:<名前>`` で allow する (名前単位の規則。引数は区別できない。判定表と一致させる)。

    サーバ単位の ``t3-code`` の allow は、全ツールと将来の追加分まで通すので置かない。
    判定そのものは、``test_t3_mcp_decisions_match_the_table`` が確かめる。
    """
    mcp = json.loads(POLICY.read_text(encoding="utf-8"))["permission"]["mcp"]
    table = CASES["t3_mcp"]
    assert next(iter(mcp)) == "*" and mcp["*"] == "ask", "既定は ask。最後に一致した規則が勝つので、先頭に置く"
    assert "t3-code" not in mcp, "サーバ単位の allow は、全ツールと将来の追加分まで通す"
    t3 = {key.split(":", 1)[1]: value for key, value in mcp.items() if key.startswith("t3-code:")}
    assert set(t3.values()) == {"allow"}, "T3 のツールは、allow だけを足す (ask は既定、deny は理由つきで別に決める)"
    assert set(t3) == set(table["allow"]), "方針の allow と、判定表の allow が食い違っている"
    assert not set(table["allow"]) & set(table["ask"]), "判定表で、同じツールが allow と ask の両方にある"


# pi 組み込みの MCP の資源・スクリプトのツール (拡張の分類は ``mcp`` ではなく「その他の拡張ツール」)。(ツール名, 期待)
# 資源のツールは ``server`` などの引数に関わらず、名前だけで判定される (入力は対象の生成に使われない)。
PI_BUILTIN_MCP_TOOLS = [
    ("list_mcp_resources", "allow"),
    ("list_mcp_resource_templates", "allow"),
    ("read_mcp_resource", "ask"),
    ("codemode", "ask"),
]


@needs_engine
def test_builtin_mcp_resource_tools_are_classified_as_extension_tools(tmp_path):
    """資源ツール 3 本と ``codemode`` は、実ゲートの ``normalizeInput`` で、``mcp`` の面ではなくツール名の面になる。

    ``mcp`` の面になると、サーバ単位の allow (``websearch`` など) が、資源の本文を読むツールにも効いてしまう。
    拡張の更新で分類が変わったら、ここで落ちる。対照として、``mcp__websearch__web_search`` は ``mcp`` の面で allow。
    """
    names = [name for name, _ in PI_BUILTIN_MCP_TOOLS] + ["mcp__websearch__web_search"]
    result = run_engine(tmp_path, mcp_tools=names)["mcpTools"]
    bad = []
    for (name, want), got in zip(PI_BUILTIN_MCP_TOOLS, result, strict=False):
        if (got["surface"], got["values"], got["action"]) != (name, ["*"], want):
            bad.append(f"{name}: 期待 {name}/*/{want} / 実際 {got['surface']}/{got['values']}/{got['action']} ({got['pattern']})")
    assert not bad, "\n".join(bad)
    contrast = result[-1]
    assert contrast["surface"] == "mcp" and contrast["action"] == "allow", contrast


@needs_engine
def test_child_agents_keep_nohup_denied(tmp_path):
    """定義ファイルに bash がある子 (``bg_run`` は持たない) の実際の定義に、グローバルの方針を重ねて判定する。

    実効の道具は settings.json の ``agentOverrides`` が決め、実際に bash を持つのは worker だけ (scout・oracle は外される)。
    ここは定義ファイルを見るので、上書きが外れても方針が崩れないことまで固定する。

    読み取りだけではない ``nohup python x.py > run.log 2>&1 &`` の形が、YOLO を切った状態で deny のままであること。
    ラッパーの床 (``allow`` を ``ask`` に引き上げる) のため、子の frontmatter で allow に上書きしても ``ask`` にしかならない。
    YOLO が入った状態 (床の ``ask`` が自動承認される) と、他の形は固定しない。
    固定するのは方針の判定だけ。子が実際にバックグラウンドで投入できるかは、囲い (pib) の有無で変わり、ここでは固定しない
    (囲いの中では、コマンドの終了でバックグラウンドのジョブも消える。docs/spec/agent-config-generation.md の ``nohup`` の項)。
    """
    import re

    agents = {}
    for md in sorted((ROOT / "home" / "dot_pi" / "agent" / "agents").glob("*.md")):
        text = md.read_text(encoding="utf-8")
        tools = re.search(r"^tools:\s*(.*)$", text, re.M)
        if tools and "bash" in [x.strip() for x in tools.group(1).split(",")]:
            agents[md.stem] = text
    assert {"worker", "scout", "oracle"} <= set(agents), sorted(agents)
    cmd = "nohup python x.py > run.log 2>&1 &"
    result = run_engine(tmp_path, agents=agents, agent_bash=[(name, cmd) for name in agents])
    bad = [
        f"{name}: {cmd!r}: 期待 deny / 実際 {got['state']} ({got['pattern']})"
        for name, got in zip(agents, result["agentBash"], strict=True)
        if got["state"] != "deny"
    ]
    assert not bad, "\n".join(bad)


@needs_engine
def test_surface_decisions_match_the_table(engine_result):
    bad = []
    for case, got in zip(CASES["surface"], engine_result["surface"], strict=True):
        if got["action"] != case[2]:
            bad.append(f"{case[0]} {case[1]!r}: 期待 {case[2]} / 実際 {got['action']} ({got['pattern']})")
    assert not bad, "\n".join(bad)


@needs_engine
def test_sandbox_toggle_protected_paths_are_denied_by_an_explicit_rule(tmp_path):
    """/sandbox (pi-sandbox-toggle) が YOLO を入れる前に問い合わせる保護パスは、**明示の規則**で deny でなければならない。
    規則が無く、既定の規則 (``*``) が答えたものは、write・edit の path ゲートが何もせず通す (上流 describePathGate)。
    拡張の PROTECTED_PATHS を読み、本物の判定エンジンで、配布する方針に対して確かめる。"""
    import re

    src = (ROOT / "home" / "dot_pi" / "agent" / "local-packages" / "pi-sandbox-toggle" / "src" / "index.ts").read_text(
        encoding="utf-8"
    )
    paths = re.findall(r'"([^"]+)"', re.search(r"const PROTECTED_PATHS = \[(.*?)\];", src, re.S).group(1))
    assert paths
    result = run_engine(tmp_path, surface=[("path_write", p.replace("~", "$HOME", 1)) for p in paths])
    bad = [
        f"{p}: {got['action']} ({got['pattern']})"
        for p, got in zip(paths, result["surface"], strict=True)
        if got["action"] != "deny" or got["pattern"] in (None, "*")
    ]
    assert not bad, "\n".join(bad)


@needs_engine
def test_alias_decisions_match_the_table(engine_result):
    """symlink の別名と解決後の実体を合わせた判定 (値のどれかに一致した、設定上で最後の規則が勝つ)。

    別名が allow に一致すれば、実体が既定の ask でも allow になる。実体側が、allow より後ろの ask に一致するときだけ ask に戻る。
    """
    bad = []
    for case, got in zip(CASES.get("alias", []), engine_result["alias"], strict=True):
        if got["action"] != case[2]:
            bad.append(f"{case[0]} {case[1]!r}: 期待 {case[2]} / 実際 {got['action']} ({got['pattern']})")
    assert not bad, "\n".join(bad)


@needs_engine
def test_t3_mcp_decisions_match_the_table(engine_result):
    """T3 の MCP ツールの判定。対象の生成は、手で書かず、実ゲートの ``normalizeInput`` をそのまま通す。

    allow は、意図した規則 (``t3-code:<名前>``) が当たって allow になる。ほかは既定の ask (``*``)。
    表に無い新しいツールも ask になる (サーバ単位の allow が入ると、ここで落ちる)。
    """
    bad = []
    for (tool, want), got in zip(T3_TOOLS, engine_result["mcpTools"], strict=True):
        pattern = f"t3-code:{tool}" if want == "allow" else "*"
        if (got["action"], got["pattern"]) != (want, pattern):
            bad.append(f"{tool}: 期待 {want} ({pattern}) / 実際 {got['action']} ({got['pattern']}) 対象 {got['values']}")
    assert not bad, "\n".join(bad)


@needs_engine
def test_bash_path_effects_match_the_table(engine_result):
    """bash のトークンの向き (read / write / unproven)。commandEffects の宣言と、それを外す旗が、意図どおりに効くこと。

    向きは surface の判定と合わせて読む: unproven は読み取りと書き込みの両方を調べ、厳しい方になる。
    """
    bad = []
    for case, got in zip(CASES["access"], engine_result["access"], strict=True):
        cmd, expected = case
        actual = [[_short(a["path"]), a["effect"]] for a in got]
        if actual != [[e[0], e[1]] for e in expected]:
            bad.append(f"{cmd!r}: 期待 {expected} / 実際 {actual}")
    assert not bad, "\n".join(bad)


def _short(path: str) -> str:
    """ホームを ``$HOME`` に戻して、表と同じ書き方にする。"""
    home = str(Path.home())
    return path.replace(home, "$HOME", 1) if path.startswith(home) else path


@needs_engine
@pytest.mark.parametrize("variant", ["project", "project_deny_write"])
def test_project_config_recipe(tmp_path, variant):
    """docs の「プロジェクト単位でデータセットを読み取り専用にする」の設定が、グローバルの方針と合成されること。"""
    case = CASES[variant]
    got = run_engine(tmp_path, surface=case["surface"], project=case["config"], name=variant)
    bad = [
        f"{s[0]} {s[1]!r}: 期待 {s[2]} / 実際 {g['action']} ({g['pattern']})"
        for s, g in zip(case["surface"], got["surface"], strict=True)
        if g["action"] != s[2]
    ]
    assert not bad, "\n".join(bad)


def _explain(home: Path, workdir: Path, cmd: str) -> tuple[str, str]:
    env = {**os.environ, "CC_SAFETY_NET_HOME": str(home)}
    done = subprocess.run(
        ["node", str(CSN_CLI), "explain", "--json", cmd],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        env=env,
        cwd=workdir,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-1000:]
    data = json.loads(done.stdout)
    return data["result"], data.get("ruleId") or ""


@needs_csn
def test_cc_safety_net_decisions_match_the_table(tmp_path):
    """cc-safety-net (リポジトリの規則つき) が、表の blocked / allowed と一致すること。"""
    home = tmp_path / "csn"
    shutil.copytree(CSN_RULES, home / "rules")
    workdir = tmp_path / "work"
    workdir.mkdir()
    cases = CASES["bash"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda c: _explain(home, workdir, c["cmd"]), cases))
    bad = [
        f"{c['cmd']!r}: 期待 {c['csn']} / 実際 {r[0]} ({r[1]})"
        for c, r in zip(cases, results, strict=True)
        if r[0] != c["csn"]
    ]
    assert not bad, "\n".join(bad)


def test_cc_safety_net_rulebook_files_are_wellformed():
    """配る規則ファイルの形 (cc-safety-net が無くても検査できる範囲)。"""
    rule = json.loads((CSN_RULES / "rule.json").read_text(encoding="utf-8"))
    assert rule["version"] == 1 and rule["rules"] == ["dotfiles-guard"]
    assert {"name": "bg_run", "cwd": "cwd"} in rule["command_tools"]  # bg_run の中身も解析させる
    book = json.loads((CSN_RULES / "dotfiles-guard" / "rulebook.json").read_text(encoding="utf-8"))
    assert book["name"] == "dotfiles-guard" and book["rulebook_version"] == 1
    assert [r["name"] for r in book["rules"]] == ["git-push"]
    assert all(r["command"] in book["allowed_commands"] for r in book["rules"])

"""子の文脈 (AGENTS.md) の抜粋を、ハーネスの子の起動へ配線した結果の試験 (CHG-0059 S4)。

既定 (``inherit``) は今と同一で、``extract`` を明示したときだけ、役割ごとの抜粋が子の system prompt に入る。
正本は ``AGENTS.md`` と ``home/.chezmoitemplates/agent-instructions.md`` の実物。抜粋の期待値は、
``harness/child-context.ts`` の ``resolveContext`` を node で呼んで作る (期待値をここへ写さない)。
契約は docs/change/closed/0059-child-context.md §4.1・§4.2。

子の側の変換は、``PI_HARNESS_CHILD=1`` と契約の環境変数 (``PI_HARNESS_CHILD_AGENT`` / ``PI_HARNESS_CHILD_CONTEXT``)
を付けた pi を直に起動して見る (子の起動を省いた、安い経路)。親が子へ渡す契約は ``guarded_task`` から見る。
"""

from __future__ import annotations

# ruff: noqa: F811  (env はインポートしたフィクスチャ)
import copy
import json
import subprocess
from pathlib import Path

import pytest
from agents_common import ROOT, load_common
from test_pi_child_persist import _prompts
from test_pi_harness import FIXTURES, PI, env, gen, run_pi  # noqa: F401
from test_pi_judge_ts import _node

pytestmark = pytest.mark.skipif(
    PI is None or _node() is None, reason="pi か、型除去に対応した node (22.18 以上) が無い"
)

# 凍結 (ADR-0030): 実物は印なしの平らな文書になったので、印つきの固定サンプル (旧正本の写し) を使う
_FIX = ROOT / "test" / "agents" / "fixtures" / "child_context"
REAL_PROJECT = (_FIX / "repo-instructions.md").read_text(encoding="utf-8")
REAL_GLOBAL = (_FIX / "agent-instructions.md").read_text(encoding="utf-8")
ROLES = ["explore", "review", "plan", "worker"]
HEADING_HEAD = "【親の指示からの抜粋】あなたは子エージェント ("
PARENT_WORDS = ["`ask`", "guarded_action", "コミットの承認"]
ID = "<!-- child-context: v1 -->"
MARK_G = "MARK_GLOBAL_LEGACY_55aa"
MARK_P = "MARK_PROJECT_LEGACY_55aa"


def _expected(text, role):
    """``resolveContext`` (extract) の結果を node で作る。"""
    script = (
        'import { resolveContext } from "'
        + (ROOT / "home/dot_config/pi/harness/child-context.ts").as_uri()
        + '";'
        "const [t, r] = JSON.parse(await new Promise((ok) => { let s = ''; process.stdin.on('data', (d) => (s += d));"
        " process.stdin.on('end', () => ok(s)); }));"
        "console.log(JSON.stringify(resolveContext(t, r, 'extract')));"
    )
    proc = subprocess.run(
        [_node(), "--input-type=module", "-e", script],
        input=json.dumps([text, role]),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _place(env, global_text, project_text):
    (env["proj"] / "AGENTS.md").write_text(project_text, encoding="utf-8")
    (Path(env["env"]["PI_CODING_AGENT_DIR"]) / "AGENTS.md").write_text(
        global_text, encoding="utf-8"
    )


def _child(env, agent, mode, *msgs, global_text=REAL_GLOBAL, project_text=REAL_PROJECT, **extra):
    """契約の環境変数つきの子を直に起動する。(proc, 各ターンの最終 prompt の一覧) を返す。"""
    _place(env, global_text, project_text)
    contract = {"PI_HARNESS_CHILD": "1"}
    if agent is not None:
        contract["PI_HARNESS_CHILD_AGENT"] = agent
    if mode is not None:
        contract["PI_HARNESS_CHILD_CONTEXT"] = mode
    proc = run_pi(env, [], *msgs, mode="json", FAUX_DUMP_PROMPT="1", **contract, **extra)
    return proc, _prompts(proc)


def _src(env, side):
    """文脈ファイルの見出しに出る「出典: <path>」。祖先の AGENTS.md は環境で変わるので、試験が置いた 2 つだけを見る。"""
    base = env["proj"] if side == "project" else Path(env["env"]["PI_CODING_AGENT_DIR"])
    return f"出典: {base / 'AGENTS.md'}"


# --- 2: extract で、役割ごとに抜粋が変わる ---


@pytest.mark.parametrize("agent", ROLES)
def test_extract_puts_the_role_extract_of_both_real_sources_and_no_parent_words(env, agent):
    proc, prompts = _child(env, agent, "extract")
    assert proc.returncode == 0, proc.stderr
    assert len(prompts) == 1
    p = prompts[0]
    for text in (REAL_GLOBAL, REAL_PROJECT):
        ex = _expected(text, agent)
        assert ex["kind"] == "extract" and ex["text"], ex
        assert ex["text"] in p, agent
    assert f"{HEADING_HEAD}{agent}) です。" in p
    assert _src(env, "global") in p and _src(env, "project") in p  # 文脈ファイルごとに 1 行
    assert "AGENTS.md" in p
    # 親向けの語が増えない (本体の案内文にもある語なので、文脈が空同然の基準と個数を比べる。祖先の分は両方に入る)
    _, base = _child(env, agent, "extract", global_text="# g\n", project_text="# p\n")
    for word in PARENT_WORDS:
        assert p.count(word) == base[0].count(word), (agent, word)
        assert (
            word
            not in _expected(REAL_PROJECT, agent)["text"] + _expected(REAL_GLOBAL, agent)["text"]
        )
        assert word in REAL_GLOBAL + REAL_PROJECT  # 全文にはある語を選んでいる
    # 親向けの全文は入らない (抜粋は全文より十分短い)
    assert REAL_PROJECT[:200] not in p


def test_extract_differs_between_explore_and_review_that_share_a_profile(env):
    rules = json.loads((env["harness"] / "rules.json").read_text(encoding="utf-8"))
    assert rules["agents"]["explore"]["profile"] == rules["agents"]["review"]["profile"]
    marker = "新しい試験ファイルは"
    _, ex = _child(env, "explore", "extract")
    _, rv = _child(env, "review", "extract")
    assert marker in rv[0] and marker not in ex[0]
    assert ex[0] != rv[0]


# --- 1: inherit (既定) は今と同一 ---


@pytest.mark.parametrize("mode", [None, "inherit"])
def test_inherit_and_default_keep_the_full_context(env, mode):
    proc, prompts = _child(env, "worker", mode)
    assert proc.returncode == 0, proc.stderr
    p = prompts[0]
    assert HEADING_HEAD not in p
    assert "<!-- child:worker" in p and "<!-- parent -->" in p  # 印つきの全文のまま


def test_inherit_through_the_parent_matches_the_characterization(env):
    # 既定の設定 (環境変数も無い) の親から起動した子の prompt は、特性化の試験 (test_pi_child_prompt.py) と同じ形
    (env["proj"] / "AGENTS.md").write_text("# project\nMARK_X\n", encoding="utf-8")
    dump = env["tmp"] / "d.txt"
    calls = [{"name": "guarded_task", "args": {"agent": "worker", "task": "dump"}}]
    proc = run_pi(
        env,
        calls,
        FAUX_CHILD_DUMP_FILE=str(dump),
        PI_HARNESS_TEST_CHILD_EXT=str(FIXTURES / "faux.ts"),
    )
    assert proc.returncode == 0, proc.stderr
    text = dump.read_text(encoding="utf-8")
    assert "MARK_X" in text and HEADING_HEAD not in text
    assert "文脈: inherit" in proc.stdout


# --- 3: 導入前 (legacy) と混在 ---


def test_unmarked_files_stay_full_even_with_extract(env):
    _, prompts = _child(
        env,
        "worker",
        "extract",
        global_text=f"# g\n- {MARK_G}\n",
        project_text=f"# p\n- {MARK_P}\n",
    )
    p = prompts[0]
    assert MARK_G in p and MARK_P in p
    assert _src(env, "global") not in p and _src(env, "project") not in p


@pytest.mark.parametrize("adopted", ["global", "project"])
def test_mixed_adoption_extracts_only_the_adopted_side(env, adopted):
    legacy_mark = MARK_P if adopted == "global" else MARK_G
    real = REAL_GLOBAL if adopted == "global" else REAL_PROJECT
    legacy = f"# l\n- {legacy_mark}\n"
    kw = (
        {"global_text": real, "project_text": legacy}
        if adopted == "global"
        else {"global_text": legacy, "project_text": real}
    )
    _, prompts = _child(env, "worker", "extract", **kw)
    p = prompts[0]
    assert legacy_mark in p  # 導入前の側は全文
    assert _src(env, adopted) in p  # 導入済みの側だけ抜粋
    other = "project" if adopted == "global" else "global"
    assert _src(env, other) not in p
    assert _expected(real, "worker")["text"] in p


# --- 4: 破損 ---


@pytest.mark.parametrize(
    ("text", "where"),
    [
        (f"{ID}\n<!-- child:worker -->\nX\n", "1 行目|2 行目"),  # 閉じ忘れ
        (f"{ID}\n<!-- child:worker -->\nX\n<!-- /child -->\n未分類の行\n", "5 行目"),
    ],
)
@pytest.mark.parametrize("side", ["global", "project"])
def test_broken_adopted_file_fails_the_child_with_the_cause(env, text, where, side):
    ok = REAL_PROJECT if side == "global" else REAL_GLOBAL
    kw = (
        {"global_text": text, "project_text": ok}
        if side == "global"
        else {"global_text": ok, "project_text": text}
    )
    proc, prompts = _child(env, "worker", "extract", **kw)
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, out
    assert prompts == []  # 抜粋にも全文にもならない
    assert "AGENTS.md" in out
    assert any(w in out for w in where.split("|")), out
    assert "未分類" in out or "閉じていない" in out, out


def test_broken_file_fails_the_child_job_and_the_parent_gets_the_cause(env):
    (env["proj"] / "AGENTS.md").write_text(f"{ID}\n<!-- child:worker -->\nX\n", encoding="utf-8")
    calls = [{"name": "guarded_task", "args": {"agent": "worker", "task": "dump"}}]
    dump = env["tmp"] / "d.txt"
    proc = run_pi(
        env,
        calls,
        FAUX_CHILD_DUMP_FILE=str(dump),
        PI_HARNESS_TEST_CHILD_EXT=str(FIXTURES / "faux.ts"),
        PI_HARNESS_CHILD_CONTEXT="extract",
    )
    out = proc.stdout + proc.stderr
    assert not dump.exists(), out  # 全文でも抜粋でも子は動いていない
    assert "AGENTS.md" in out and "閉じていない" in out, out


# --- A/D1: 導入前のファイルの普通の HTML コメントで子は終了しない ---


PLAIN_COMMENT = "<!-- generated from parent guide -->"


def test_before_adoption_plain_comment_does_not_stop_the_child_and_stays_full(env):
    # 導入前の AGENTS.md の普通の HTML コメント (parent を含む) で、extract の子が終了しない
    legacy = f"# p\n{PLAIN_COMMENT}\n- {MARK_P}\n"
    proc, prompts = _child(
        env, "worker", "extract", global_text=f"# g\n- {MARK_G}\n", project_text=legacy
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert MARK_P in prompts[0] and PLAIN_COMMENT in prompts[0] and MARK_G in prompts[0]
    assert _src(env, "project") not in prompts[0]


def test_adopted_file_with_the_same_comment_outside_blocks_still_fails_the_child(env):
    adopted = f"{ID}\n<!-- child:worker -->\nX\n<!-- /child -->\n{PLAIN_COMMENT}\n"
    proc, prompts = _child(env, "worker", "extract", project_text=adopted)
    assert proc.returncode != 0 and prompts == [], proc.stdout + proc.stderr
    assert "未分類" in proc.stdout + proc.stderr


# --- 5: 毎メッセージ ---


def test_every_message_of_one_child_session_gets_the_extract(env):
    _, prompts = _child(env, "worker", "extract", "one", "two", "three")
    assert len(prompts) == 3
    ex = _expected(REAL_PROJECT, "worker")["text"]
    for p in prompts:
        assert (
            ex in p
            and _src(env, "global") in p
            and _src(env, "project") in p
            and "<!-- parent -->" not in p
        )


# --- C: 別の起動経路 (Windows の subagents 拡張) は、環境変数が残っていても除外 ---


def test_other_launch_path_is_excluded_even_when_the_contract_variables_leak(env):
    _, prompts = _child(env, "worker", "extract", PI_SUBAGENT_CHILD="1")
    assert HEADING_HEAD not in prompts[0] and "<!-- parent -->" in prompts[0]
    # 対照: 同じ入力で PI_SUBAGENT_CHILD が無ければ抜粋になる
    _, prompts = _child(env, "worker", "extract")
    assert f"{HEADING_HEAD}worker) です。" in prompts[0]


# --- B: 子側 hook の入力検査と例外の集約 ---

BREAK = FIXTURES / "break_context.ts"


def _run_broken(env, how, mode="extract"):
    """試験拡張 break_context.ts をハーネスより先に読み込んで、子を直に起動する (run_pi の -e はハーネスの後ろなので使えない)。"""
    _place(env, REAL_GLOBAL, REAL_PROJECT)
    args = [PI, "--no-session", "--model", "faux/spike", "-nbt", "-ne", "-e", "builtin:mcp"]
    args += ["-e", str(BREAK), "-e", str(env["harness"]), "-e", str(FIXTURES / "faux.ts")]
    args += ["--mode", "json", "go"]
    return subprocess.run(
        args,
        cwd=env["proj"],
        env={
            **env["env"],
            "FAUX_TOOL_CALLS": "[]",
            "FAUX_DUMP_PROMPT": "1",
            "PI_HARNESS_CHILD": "1",
            "PI_HARNESS_CHILD_AGENT": "worker",
            "PI_HARNESS_CHILD_CONTEXT": mode,
            "BREAK_CONTEXT": how,
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        check=False,
    )


@pytest.mark.parametrize(
    ("how", "cause"),
    [
        ("not_array", "contextFiles"),
        ("null_item", "要素"),
        ("path_num", "path"),
        ("content_num", "content"),
        ("throw_getter", "getter boom"),
    ],
)
def test_malformed_context_files_fail_the_extract_child_with_the_cause(env, how, cause):
    proc = _run_broken(env, how)
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, out
    # pi 自身の落ち方ではなく、ハーネスの終了処理を通っている
    assert "子の文脈 (AGENTS.md) の抜粋に失敗" in out, out
    assert _prompts(proc) == []  # LLM を呼ばない (黙って全文にもしない)
    assert cause in out, out


def test_empty_context_files_is_normal(env):
    # AGENTS.md がどこにも無い (空の配列) は契約違反ではない
    _place(env, "# g\n", "# p\n")
    (env["proj"] / "AGENTS.md").unlink()
    (Path(env["env"]["PI_CODING_AGENT_DIR"]) / "AGENTS.md").unlink()
    proc = run_pi(
        env, [], mode="json", FAUX_DUMP_PROMPT="1",
        PI_HARNESS_CHILD="1", PI_HARNESS_CHILD_AGENT="worker", PI_HARNESS_CHILD_CONTEXT="extract",
    )  # fmt: skip
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(_prompts(proc)) == 1


def test_long_path_keeps_the_cause_in_the_exit_message(env):
    deep = env["proj"] / ("d" * 120) / ("e" * 120)
    deep.mkdir(parents=True)
    env2 = {**env, "proj": deep}
    bad = f"{ID}\n<!-- child:worker -->\nX\n"  # 閉じ忘れ
    proc, prompts = _child(env2, "worker", "extract", project_text=bad)
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0 and prompts == [], out
    assert "閉じていない" in out, out  # 原因が先頭側にあり、長いパスで切れない
    assert str(deep / "AGENTS.md") not in out  # パスは末尾側に短縮される
    assert ("e" * 40) in out  # 末尾側は残る
    assert "(出典: …" in out, out  # 出典のパスが短縮して添えられる (原因の後ろ)


# --- D5: report の after は、見出しを含む実際に投入する長さ ---


def _u16(s):
    return len(s.encode("utf-16-le")) // 2


def test_report_after_is_the_length_of_what_is_actually_injected_with_the_heading(env):
    report = env["tmp"] / "after.jsonl"
    _, prompts = _child(env, "worker", "extract", PI_HARNESS_CHILD_CONTEXT_REPORT=str(report))
    recs = [json.loads(x) for x in report.read_text(encoding="utf-8").splitlines()]
    for side, text in (("project", REAL_PROJECT), ("global", REAL_GLOBAL)):
        src = _src(env, side).removeprefix("出典: ")
        rec = next(r for r in recs if r["path"] == src)
        head = next(
            ln for ln in prompts[0].splitlines() if ln.startswith(HEADING_HEAD) and src in ln
        )
        ex = _expected(text, "worker")["text"]
        assert rec["after"] == _u16(head) + 2 + _u16(ex), side


# --- 6: 契約の外は変えない ---


def test_parent_without_child_flag_is_not_changed_by_the_env_value(env):
    _place(env, REAL_GLOBAL, REAL_PROJECT)
    proc = run_pi(
        env,
        [],
        mode="json",
        FAUX_DUMP_PROMPT="1",
        PI_HARNESS_CHILD_CONTEXT="extract",
        PI_HARNESS_CHILD_AGENT="worker",
    )
    p = _prompts(proc)[0]
    assert HEADING_HEAD not in p and "<!-- parent -->" in p


def test_child_without_the_agent_contract_is_not_changed(env):
    # Windows の別の拡張が起動する子に相当 (PI_HARNESS_CHILD=1 だけ)
    _, prompts = _child(env, None, "extract")
    assert HEADING_HEAD not in prompts[0] and "<!-- parent -->" in prompts[0]
    _, prompts = _child(env, None, None)
    assert HEADING_HEAD not in prompts[0] and "<!-- parent -->" in prompts[0]


@pytest.mark.parametrize("agent", ["commit", "unknown"])
def test_child_with_a_role_outside_the_child_roles_stays_full(env, agent):
    _, prompts = _child(env, agent, "extract")
    assert HEADING_HEAD not in prompts[0] and "<!-- parent -->" in prompts[0]


def test_child_context_value_other_than_extract_does_nothing(env):
    _, prompts = _child(env, "worker", "inherit")
    assert HEADING_HEAD not in prompts[0]


# --- 観測 (PI_HARNESS_CHILD_CONTEXT_REPORT) ---


def test_report_lists_each_decision_without_the_body(env):
    report = env["tmp"] / "report.jsonl"
    _child(env, "review", "extract", PI_HARNESS_CHILD_CONTEXT_REPORT=str(report))
    recs = [json.loads(x) for x in report.read_text(encoding="utf-8").splitlines()]
    kinds = {r["path"].replace("\\", "/").rsplit("/", 2)[-2:][-1]: r for r in recs}
    assert recs and all(
        r["kind"] == "extract" and r["blocks"] >= 1 for r in recs if r["path"].endswith("AGENTS.md")
    )
    assert all(r["after"] < r["before"] for r in recs if r["kind"] == "extract")
    assert kinds
    assert "新しい試験ファイルは" not in report.read_text(encoding="utf-8")


# --- 7: 親の設定・環境変数・起動契約・見出し ---


def _parent(env, *, setting=None, override=None, agent="worker", **extra):
    rules_path = env["harness"] / "rules.json"
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    if setting is not None:
        rules["child"] = {"context": setting}
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    _place(env, REAL_GLOBAL, REAL_PROJECT)
    dump = env["tmp"] / f"d-{agent}.txt"
    dump.unlink(missing_ok=True)
    calls = [{"name": "guarded_task", "args": {"agent": agent, "task": "dump"}}]
    if override is not None:
        extra["PI_HARNESS_CHILD_CONTEXT"] = override
    proc = run_pi(
        env,
        calls,
        FAUX_CHILD_DUMP_FILE=str(dump),
        PI_HARNESS_TEST_CHILD_EXT=str(FIXTURES / "faux.ts"),
        **extra,
    )
    return proc, (dump.read_text(encoding="utf-8") if dump.exists() else None)


def test_setting_extract_passes_the_contract_to_the_child_and_shows_it_in_the_heading(env):
    proc, text = _parent(env, setting="extract")
    assert proc.returncode == 0, proc.stderr
    assert text is not None and f"{HEADING_HEAD}worker) です。" in text, proc.stdout
    assert "文脈: extract" in proc.stdout


def test_explore_and_review_get_their_own_role_name(env):
    _, ex = _parent(env, setting="extract", agent="explore")
    _, rv = _parent(env, setting="extract", agent="review")
    assert f"{HEADING_HEAD}explore) です。" in ex and f"{HEADING_HEAD}review) です。" in rv


def test_environment_override_beats_the_setting(env):
    proc, text = _parent(env, setting="extract", override="inherit")
    assert HEADING_HEAD not in text and "文脈: inherit" in proc.stdout
    proc, text = _parent(env, setting="inherit", override="extract")
    assert f"{HEADING_HEAD}worker) です。" in text and "文脈: extract" in proc.stdout


def test_unknown_environment_value_fails_the_child_launch_and_says_why(env):
    proc, text = _parent(env, setting="inherit", override="bogus")
    out = proc.stdout + proc.stderr
    assert text is None, out  # 子は起動しない (静かに extract にも inherit にもならない)
    assert "PI_HARNESS_CHILD_CONTEXT" in out and "bogus" in out


def test_commit_agent_is_always_inherit(env):
    proc, text = _parent(env, setting="extract", agent="commit")
    assert text is not None and HEADING_HEAD not in text
    assert "文脈: inherit" in proc.stdout


# --- 8: 設定の検証 (generate.py) ---


def _rules_with(child):
    common = copy.deepcopy(load_common())
    pi = common.setdefault("pi", {})
    if child is None:
        pi.pop("child", None)
    else:
        pi["child"] = child
    return gen.build_pi_harness({}, common)


def test_the_real_config_defaults_to_inherit():
    assert _rules_with(None)["child"] == {"context": "inherit"}
    assert load_common()["pi"]["child"]["context"] == "inherit"


@pytest.mark.parametrize("value", ["inherit", "extract"])
def test_generate_passes_the_allowed_values(value):
    assert _rules_with({"context": value})["child"] == {"context": value}


@pytest.mark.parametrize(
    "child",
    [
        {"context": "full"},
        {"context": ""},
        {"context": 1},
        {"ctx": "extract"},
        {"context": "extract", "x": 1},
        "extract",
    ],
)
def test_generate_rejects_unknown_values_and_keys(child):
    with pytest.raises((SystemExit, ValueError)):
        _rules_with(child)

"""文脈ファイル (contextFiles) の書き換えが保たれる条件の特性化 (CHG-0059 S4 の前提)。

``before_agent_start`` のハンドラが ``event.systemPromptOptions.contextFiles`` を書き換えたとき、
複数ターン・ツールの往復・複数の拡張・返り値 ``{systemPrompt}``・``-nc`` のもとで、最終の prompt がどうなるかを固定する。
測った手順と表は docs/research/agents/child-context-probe.md の「複数ターン・複数拡張・優先関係」。
観測は試験専用の拡張 test/agents/pi/dump_options.ts (呼び出しごとの記録は DUMP_OPTIONS_CALLS_FILE)。
最終の prompt は faux の FAUX_DUMP_PROMPT (--mode json の assistant の本文) で見る。
see docs/change/closed/0059-child-context.md
"""

from __future__ import annotations

# ruff: noqa: F811  (env はインポートしたフィクスチャ)
import json
import shutil

import pytest
from test_pi_harness import FIXTURES, PI, env, run_pi  # noqa: F401

pytestmark = pytest.mark.skipif(PI is None, reason="pi is not installed")

ORIG = "ORIG_PROJ_4b1d"
MUT_A = "MUT_A_4b1d"
MUT_B = "MUT_B_4b1d"
MUT_ADD = "MUT_ADD_4b1d"
RETURNED = "RETURNED_PROMPT_4b1d"
REPLACE_A = f"contextFiles:replace:{MUT_A}"
REPLACE_B = f"contextFiles:replace:{MUT_B}"


def _go(
    env,
    *msgs,
    calls=(),
    two=False,
    dump=True,
    order=("dump_options", "dump_options_b"),
    pre=(),
    **kw,
):
    """pi を --mode json で起動する。(proc, 呼び出しの記録, 各ターンの最終 prompt の一覧) を返す。

    dump_options.ts を ``dump_options_b.ts`` にもコピーし、two のとき ``order`` の順に ``-e`` で 2 つ読む。
    """
    shutil.copy2(FIXTURES / "dump_options.ts", env["tmp"] / "dump_options_b.ts")
    (env["proj"] / "AGENTS.md").write_text(f"# project\n{ORIG}\n", encoding="utf-8")
    log = env["tmp"] / "calls.jsonl"
    log.unlink(missing_ok=True)
    paths = {
        "dump_options": FIXTURES / "dump_options.ts",
        "dump_options_b": env["tmp"] / "dump_options_b.ts",
    }
    exts = []
    for name in order if two else order[:1]:
        exts += ["-e", str(paths[name])]
    proc = run_pi(
        env,
        list(calls),
        *msgs,
        extra=[*pre, *exts],
        mode="json",
        DUMP_OPTIONS_CALLS_FILE=str(log),
        **({"FAUX_DUMP_PROMPT": "1"} if dump else {}),
        **kw,
    )
    assert proc.returncode == 0, proc.stderr
    recs = (
        [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
        if log.exists()
        else []
    )
    return proc, recs, _prompts(proc)


def _prompts(proc):
    """faux (FAUX_DUMP_PROMPT) が assistant の本文として返した system prompt を、ターン順に返す。"""
    out = []
    for line in proc.stdout.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        m = e.get("message") or {}
        if e.get("type") == "message_end" and m.get("role") == "assistant":
            out.append(
                "".join(c.get("text", "") for c in m.get("content", []) if c.get("type") == "text")
            )
    return out


def _of(recs, ev, ext=None):
    return [r for r in recs if r["ev"] == ev and (ext is None or r["ext"] == ext)]


def _proj_file(files):
    """作業先 (試験の proj/) の AGENTS.md の要素。祖先の AGENTS.md は環境で変わるので path の末尾で選ぶ。"""
    return next(f for f in files if f["path"].replace("\\", "/").endswith("/proj/AGENTS.md"))


# --- Q1: 複数のユーザーメッセージ ---


def test_q1_handler_runs_every_message_with_fresh_context_and_rewrite_reaches_every_prompt(env):
    _, recs, prompts = _go(env, "one", "two", "three", DUMP_OPTIONS_MUTATE=REPLACE_A)
    starts = _of(recs, "before_agent_start")
    # メッセージごとに毎回呼ばれ、渡される contextFiles は毎回元の内容 (前回の書き換えは残らない)
    assert [r["seq"] for r in starts] == [1, 2, 3]
    for r in starts:
        assert _proj_file(r["before"])["head"].startswith("# project"), r["before"]
        assert _proj_file(r["after"])["head"] == MUT_A
    # どのメッセージの最終の prompt にも書き換えが反映される
    assert len(prompts) == 3
    for p in prompts:
        assert MUT_A in p and ORIG not in p


# --- Q2: ツールの往復 ---


def test_q2_tool_round_trip_does_not_call_the_handler_again_and_keeps_the_rewrite(env):
    calls = [{"name": "guarded_ls", "args": {"path": "."}}]
    proc, recs, _ = _go(
        env, "one", calls=calls, dump=False, DUMP_OPTIONS_MUTATE=REPLACE_A, DUMP_OPTIONS_WATCH=MUT_A
    )
    # before_agent_start は 1 回だけ。LLM の呼び出し (turn) は 2 回で、どちらの ctx.getSystemPrompt() にも書き換えが残る
    assert len(_of(recs, "before_agent_start")) == 1
    turns = _of(recs, "turn_start")
    assert len(turns) == 2
    assert all(t["watch"] is True for t in turns)
    assert "guarded_ls: isError=false" in proc.stdout  # 往復が実際に起きた


# --- Q3: 2 つの拡張 ---


@pytest.mark.parametrize(
    ("order", "winner", "loser"),
    [
        (("dump_options", "dump_options_b"), MUT_B, MUT_A),
        (("dump_options_b", "dump_options"), MUT_A, MUT_B),
    ],
)
def test_q3_two_extensions_run_in_dash_e_order_and_the_later_one_sees_the_earlier_rewrite(
    env, order, winner, loser
):
    first, second = order
    mutate = {"dump_options": REPLACE_A, "dump_options_b": REPLACE_B}
    _, recs, prompts = _go(
        env,
        "one",
        two=True,
        order=order,
        **{
            f"DUMP_OPTIONS_MUTATE__{first}": mutate[first],
            f"DUMP_OPTIONS_MUTATE__{second}": mutate[second],
        },
    )
    starts = _of(recs, "before_agent_start")
    # (a) 実行の順は -e の順
    assert [r["ext"] for r in starts] == list(order)
    # (b) 後の拡張は、前の拡張の書き換えを見る (元の内容ではない)
    assert _proj_file(starts[0]["before"])["head"].startswith("# project")
    assert _proj_file(starts[1]["before"])["head"] == mutate[first].rsplit(":", 1)[1]
    # (c) 最終の prompt は後の拡張の結果
    assert winner in prompts[0] and loser not in prompts[0] and ORIG not in prompts[0]


# --- Q4: 返り値 {systemPrompt} ---


def test_q4_returned_system_prompt_wins_over_the_context_rewrite_in_the_same_handler(env):
    _, recs, prompts = _go(
        env, "one", DUMP_OPTIONS_MUTATE=REPLACE_A, DUMP_OPTIONS_RETURN_PROMPT=RETURNED
    )
    assert _of(recs, "before_agent_start")[0]["returned"] == "systemPrompt"
    # 書き換えも行ったが、最終の prompt は返り値の文字列そのもの (文脈も既定の本体も含まれない)
    assert prompts == [RETURNED]


# --- Q4b: 2 つの拡張と返り値 ---


@pytest.mark.parametrize("returner", ["dump_options", "dump_options_b"])
def test_q4_returned_system_prompt_of_either_extension_is_final_even_if_a_later_one_rewrites_the_context(
    env, returner
):
    _, _, prompts = _go(
        env,
        "one",
        two=True,
        DUMP_OPTIONS_MUTATE__dump_options=REPLACE_A,
        DUMP_OPTIONS_MUTATE__dump_options_b=REPLACE_B,
        **{f"DUMP_OPTIONS_RETURN_PROMPT__{returner}": RETURNED},
    )
    # 先の拡張が返しても、後の拡張の contextFiles の書き換えは最終の prompt に出ない
    assert prompts == [RETURNED]


# --- Q5: /reload ---


def test_q5_rewrite_takes_effect_in_the_turn_after_reload(env):
    # faux.ts の spike-reload コマンドが ctx.reload() を呼ぶ。拡張は作り直され (seq が 1 に戻る)、次のターンも書き換わる
    _, recs, prompts = _go(env, "one", "/spike-reload", "two", DUMP_OPTIONS_MUTATE=REPLACE_A)
    assert [r["seq"] for r in _of(recs, "before_agent_start")] == [1, 1]
    assert len(prompts) == 2
    assert all(MUT_A in p and ORIG not in p for p in prompts)


# --- Q6: 空の contextFiles に足す ---


def test_q6_added_context_file_reaches_the_prompt_with_and_without_nc(env):
    _, recs, prompts = _go(env, "one", DUMP_OPTIONS_MUTATE=f"contextFiles:add:{MUT_ADD}")
    # 既定: 既存の文脈の末尾に足される
    assert MUT_ADD in prompts[0] and ORIG in prompts[0]
    assert prompts[0].index(ORIG) < prompts[0].index(MUT_ADD)
    # -nc: contextFiles は空で渡され、足した要素だけが出る (抜粋を足す口として使える)
    _, recs, prompts = _go(
        env, "one", pre=("-nc",), DUMP_OPTIONS_MUTATE=f"contextFiles:add:{MUT_ADD}"
    )
    start = _of(recs, "before_agent_start")[0]
    assert start["before"] == [] and [f["head"] for f in start["after"]] == [MUT_ADD]
    assert MUT_ADD in prompts[0] and ORIG not in prompts[0]

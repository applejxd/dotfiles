"""子エージェントが実際に受け取る system prompt の特性化 (CHG-0059 S0)。

今の挙動を固定する。S4 (文脈の受け渡しの配線) で、既定の ``inherit`` のとき同一であることの基準になる。
固定するのは (1) 作業先と agent 置き場の ``AGENTS.md`` が両方入る (2) 前置きと役割の system が並ぶ位置
(3) 役割ごとに前置きで始まる、の 3 つ。測った結果の表は docs/research/agents/child-context-probe.md。
see docs/change/0059-child-context.md
"""

from __future__ import annotations

# ruff: noqa: F811  (env はインポートしたフィクスチャ。引数名で使うので再定義に見える)
import os
from pathlib import Path

import pytest
from agents_common import load_common
from test_pi_harness import (  # noqa: F401  (env はフィクスチャ。使い回す)
    FIXTURES,
    PI,
    env,
    gen,
    run_pi,
)

pytestmark = pytest.mark.skipif(PI is None, reason="pi is not installed")

PREAMBLE_HEAD = "【子エージェントへ】"
MARK_PROJECT = "MARK_PROJECT_AGENTS_7f3a"
MARK_AGENT_DIR = "MARK_AGENTDIR_AGENTS_9c1e"
ROLES = ["explore", "review", "plan", "worker"]


def _child_prompt(env, agent):
    """目印入りの AGENTS.md を 2 か所に置き、``agent`` の子の system prompt の全文を返す。"""
    (env["proj"] / "AGENTS.md").write_text(f"# project\n{MARK_PROJECT}\n", encoding="utf-8")
    (Path(env["env"]["PI_CODING_AGENT_DIR"]) / "AGENTS.md").write_text(
        f"# global\n{MARK_AGENT_DIR}\n", encoding="utf-8"
    )
    dump = env["tmp"] / f"child-prompt-{agent}.txt"
    calls = [{"name": "guarded_task", "args": {"agent": agent, "task": "dump"}}]
    proc = run_pi(
        env,
        calls,
        FAUX_CHILD_DUMP_FILE=str(dump),
        PI_HARNESS_TEST_CHILD_EXT=str(FIXTURES / "faux.ts"),
    )
    assert proc.returncode == 0, proc.stderr
    assert dump.exists(), proc.stdout + proc.stderr
    prompt = dump.read_text(encoding="utf-8")
    # 手で長さを測るとき用 (CHILD_PROMPT_KEEP=<dir>)
    keep = os.environ.get("CHILD_PROMPT_KEEP")
    if keep:
        Path(keep, f"{agent}.txt").write_text(prompt, encoding="utf-8")
    return prompt


@pytest.mark.parametrize("agent", ROLES)
def test_child_prompt_has_both_context_files_and_the_preamble_before_them(env, agent):
    system = gen.build_pi_harness({}, load_common())["agents"][agent]["system"]
    prompt = _child_prompt(env, agent)
    # 今は -nc が無いので、作業先と agent 置き場の AGENTS.md が両方とも全文で届く
    assert prompt.count(MARK_PROJECT) == 1 and prompt.count(MARK_AGENT_DIR) == 1
    # 前置きは 1 つで、役割の system の直前に空行 1 つを挟んで続く
    assert prompt.count(PREAMBLE_HEAD) == 1
    start = prompt.index(PREAMBLE_HEAD)
    assert prompt[start:].split("\n\n", 1)[1].startswith(system[:80]), prompt[start : start + 400]
    assert system in prompt
    # 前置き + 役割の system (--append-system-prompt) は、文脈ファイルより前。文脈は agent 置き場 → 作業先の順
    assert start < prompt.index(MARK_AGENT_DIR) < prompt.index(MARK_PROJECT)
    assert prompt.index(system) < prompt.index(MARK_AGENT_DIR)

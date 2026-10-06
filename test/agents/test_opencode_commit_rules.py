"""OpenCode でのコミットの規則 (親が自分で行う ``git commit`` の確認) の test.

コミットは commit スキルに従って親が行い、``git commit`` の確認が承認の場になる
(通常起動でも隔離起動でも)。OpenCode の照合 (後勝ち・``*`` は空白や ``/`` や改行も含む
任意の文字列・末尾の `` *`` は引数なしにも当たる) をここで再現し、生成した全体の規則を当てる。
照合の性質は実機で確かめた。see docs/research/opencode/commit-review-agents.md の記録 E2
see docs/spec/agent-config-generation.md#コミットの確認

Run with: ``uv run --with pytest --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402
from agents_common import load_common  # noqa: E402

COMMON = load_common("applejxd")


def _glob(pattern: str) -> str:
    return "".join(".*" if c == "*" else re.escape(c) for c in pattern)


def matches(pattern: str, text: str) -> bool:
    regex = _glob(pattern[:-2]) + "( .*)?" if pattern.endswith(" *") else _glob(pattern)
    return re.fullmatch(regex, text, re.DOTALL) is not None


def evaluate(rules: list[dict], command: str) -> str:
    effect = None
    for rule in rules:
        if rule["action"] in ("shell", "*") and matches(rule["resource"], command):
            effect = rule["effect"]
    assert effect is not None, command
    return effect


def normal_global() -> list[dict]:
    return gen.merge_opencode_config({}, COMMON)["permissions"]


def ocs_config(tmp_path: Path) -> dict:
    runtime = tmp_path / "fence"
    runtime.write_text("", "utf-8")
    opencode = COMMON["opencode"]
    common = {
        **COMMON,
        "opencode": {**opencode, "sandbox": {**opencode["sandbox"], "runtime_path": str(runtime)}},
    }
    out = gen.opencode_sandbox(common)
    assert out is not None
    return out


def test_no_commit_agent():
    """コミット用の子エージェントは置かない (CHG-0013 / CHG-0014 を取りやめた)。"""
    config = gen.merge_opencode_config({}, COMMON)
    assert "commit" not in config["agents"]
    assert "commit" not in COMMON["opencode"]["model"]["agents"]


def test_commit_asks_in_the_normal_config():
    assert evaluate(normal_global(), "git commit -m '<件名>' -m '<本文>'") == "ask"


def test_commit_asks_in_ocs(tmp_path):
    """★隔離版も git commit の ask を捨てない (利用者の選択)。"""
    rules = ocs_config(tmp_path)["permissions"]
    assert evaluate(rules, "git commit -m x") == "ask"
    assert evaluate(rules, "git commit -m 'feat: x' -m '- Motivation: a'") == "ask"


@pytest.mark.parametrize("command", ["git status --short", "git diff HEAD"])
def test_global_rules_still_ask_for_plain_status_and_diff(command):
    """全体の allow から git status / git diff を外した判断はそのまま。"""
    assert evaluate(normal_global(), command) == "ask"


def _option_commit_guide() -> dict:
    rules = [r for r in gen.opencode_guide_rules(COMMON) if "git commit の前に" in r["message"]]
    assert len(rules) == 1
    return rules[0]


@pytest.mark.parametrize(
    "command",
    [
        "git -c core.hooksPath=/dev/null commit -m x",
        "git -c a=b -c c=d commit -m x",
        "git -C . commit -m x",
        "git --no-pager commit -m x",
        "ls && git -c x=y commit -m z",
    ],
)
def test_option_before_commit_is_guided(command):
    """★隔離起動はシェルの既定が allow なので、ask に当たらない形を guide で止める。"""
    assert re.search(_option_commit_guide()["pattern"], command), command


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m x",
        "git -C x log --grep commit",
        "git -c color.ui=never log --oneline",
        "git log --oneline",
        "echo git commit",
    ],
)
def test_plain_commit_and_other_subcommands_are_not_guided(command):
    assert not re.search(_option_commit_guide()["pattern"], command), command

"""OpenCode の子エージェント ``commit`` の権限 (``[opencode.agents.commit]``) の test.

素の git の読み取りとパス指定のステージだけを確認なしで通し、``git commit`` は確認に回す。
OpenCode の照合 (後勝ち・``*`` は空白や ``/`` や改行も含む任意の文字列・末尾の `` *`` は
引数なしにも当たる) をここで再現し、生成した全体の規則 + エージェントの規則を当てる。
照合の性質は実機で確かめた。see docs/research/opencode/commit-review-agents.md の記録 E2

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
SKILL = ROOT / "home" / "dot_claude" / "skills" / "commit" / "SKILL.md"
CODEX_SKILL = ROOT / "home" / "dot_codex" / "skills" / "commit" / "SKILL.md"
OVERRIDE = "呼び出し元の指示が `git commit` の権限の確認を承認の場と定めているときは"


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


def normal_rules() -> list[dict]:
    config = gen.merge_opencode_config({}, COMMON)
    return config["permissions"] + config["agents"]["commit"]["permissions"]


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


def ocs_rules(tmp_path: Path) -> list[dict]:
    out = ocs_config(tmp_path)
    return out["permissions"] + out["agents"]["commit"]["permissions"]


def agent() -> dict:
    return gen.merge_opencode_config({}, COMMON)["agents"]["commit"]


# 通常起動でも隔離起動でも同じ判定になるもの
COMMON_CASES = {
    "allow": [
        "git status",
        "git status --short --branch",
        "git diff HEAD",
        "git diff --cached --stat",
        'git diff -- "sub dir/c.txt"',
        "git log --oneline -10",
        "git log -1 --oneline",
        "git branch --show-current",
        'git add -- a.txt "sub dir/c.txt"',
        'git restore --staged -- "sub dir/c.txt"',
    ],
    "ask": [
        "git commit -m x",
        "git commit -m 'a > b'",
        "git commit -m 'feat: x' -m '- Motivation: a\n- Change: b'",
    ],
    "deny": [
        "git status --short > out.txt",
        "git diff HEAD 2>&1",
        "git diff --output=out.txt",
        "git log -p --output=out.txt",
        "git add -- a.txt > /dev/null",
        "git commit --no-verify -m x",
        "git commit -m x --no-verify",
        "git commit -n -m x",
        "git commit -am x",
        "git commit -a -m x",
        "git commit --all -m x",
        "git commit --amend -m x",
        "git commit -m x --amend",
        "git -c x commit -m y",
        "git -c core.hooksPath=/dev/null commit -m x",
        "git -C . commit -m x",
        "git stash",
        "git stash pop",
        "git checkout -b x",
        "git checkout -- a.txt",
        "git restore a.txt",
        "git restore --staged a.txt",
        "git reset HEAD a.txt",
        "git clean -fd",
        "git push",
    ],
}


# エージェントの規則に当たらず、全体の規則 (通常起動は ask、隔離起動は allow) に落ちるもの
FALLTHROUGH = ["git add -A", "git add .", "git branch -v", "git switch -c x", "git rm a.txt"]


def _cases(extra: dict[str, list[str]]) -> list[tuple[str, str]]:
    return [
        (effect, command)
        for table in (COMMON_CASES, extra)
        for effect, commands in table.items()
        for command in commands
    ]


@pytest.mark.parametrize(
    ("effect", "command"),
    _cases({"ask": FALLTHROUGH}),
)
def test_commit_agent_decisions_in_the_normal_config(effect, command):
    """★まとめてのステージなど、エージェントが決めない形は全体の規則 (ask) に落ちる。"""
    assert evaluate(normal_rules(), command) == effect


@pytest.mark.parametrize(
    ("effect", "command"),
    _cases({"allow": FALLTHROUGH}),
)
def test_commit_agent_decisions_in_ocs(effect, command, tmp_path):
    """★隔離版は git commit の ask を全体から捨てているが、エージェントの ask が戻す。"""
    assert evaluate(ocs_rules(tmp_path), command) == effect


def test_ocs_global_rules_do_not_ask_for_git_commit(tmp_path):
    """前提の確認: 隔離版の全体の規則だけでは git commit もオプションを前に置いた形も通る。"""
    rules = ocs_config(tmp_path)["permissions"]
    assert evaluate(rules, "git commit -m x") == "allow"
    assert evaluate(rules, "git -c core.hooksPath=/dev/null commit -m x") == "allow"


@pytest.mark.parametrize("command", ["git status --short", "git diff HEAD"])
def test_global_rules_still_ask_for_plain_status_and_diff(command):
    """全体の allow から git status / git diff を外した判断は、commit の中でだけ例外にする。"""
    assert evaluate(gen.merge_opencode_config({}, COMMON)["permissions"], command) == "ask"


def test_rules_are_ordered_denies_allows_exceptions_ask_then_commit_denies():
    """後勝ちなので、状態を変える git の deny → allow → 例外の deny → ask → commit の deny の順。"""
    shell = [r for r in agent()["permissions"] if r["action"] == "shell"]
    effects = [r["effect"] for r in shell]
    ask = effects.index("ask")
    allows = [i for i, e in enumerate(effects) if e == "allow"]
    assert effects.count("ask") == 1
    assert shell[ask]["resource"] == "git commit *"
    assert all(e == "deny" for e in effects[: allows[0]])
    assert allows == list(range(allows[0], allows[-1] + 1))
    assert {r["resource"] for r in shell[allows[-1] + 1 : ask]} == {"*>*", "*--output*"}
    assert all(e == "deny" for e in effects[allows[-1] + 1 : ask])
    commit_denies = {r["resource"] for r in shell[ask + 1 :]}
    expected = {"* --no-verify*", "git commit -a*", "git commit --amend*", "git -* commit *"}
    assert expected <= commit_denies
    assert all(e == "deny" for e in effects[ask + 1 :])


def test_output_deny_does_not_hit_plain_forms():
    for command in ("git diff --stat HEAD", "git log --oneline -10"):
        assert not matches("*--output*", command)


def test_commit_agent_cannot_edit_ask_or_launch_subagents():
    rules = agent()["permissions"]
    for action in ("edit", "question", "subagent"):
        assert {"action": action, "resource": "*", "effect": "deny"} in rules


def _skill_commands(path: Path) -> list[str]:
    """スキルが教える git の形 (インラインコードとコードブロック)。

    文中で名前だけ挙げたもの (`git add` など引数の無いもの) は除く。
    """
    text = path.read_text("utf-8")
    inline = [c for c in re.findall(r"`(git [^`]+)`", text) if len(c.split()) >= 3]
    blocks = [
        line.strip()
        for block in re.findall(r"```bash\n(.*?)```", text, re.DOTALL)
        for line in block.splitlines()
        if line.strip().startswith("git ")
    ]
    return inline + blocks


def test_skill_forms_are_allowed_or_asked_in_the_commit_agent():
    """commit スキルが教える形は、commit の中で allow (git commit だけ ask) に当たる。

    ポリシーの節に並ぶ禁止の形 (--no-verify や git add . など) は除く。
    """
    rules = normal_rules()
    forbidden = ("--no-verify", "--amend", "commit -a", "--all", "add .", "add -A")
    taught = [c for c in _skill_commands(SKILL) if not any(f in c for f in forbidden)]
    assert "git add -- <対象ファイル...>" in taught
    assert "git restore --staged -- <パス>" in taught
    for command in taught:
        command = re.sub(r"<[^>]+>", "a.txt", command)
        expected = "ask" if command.startswith("git commit") else "allow"
        assert evaluate(rules, command) == expected, command


def test_system_prompt_names_the_approval_and_defers_to_the_skill():
    """system は作法をスキルに任せ、確認が承認の場だと明記し、スキルもその上書きを認める。"""
    system = agent()["system"]
    assert "commit スキル" in system
    assert "承認を求める返答は書かず" in system
    assert "git commit -m '<件名>' -m '<本文>'" in system
    assert evaluate(normal_rules(), "git commit -m '<件名>' -m '<本文>'") == "ask"
    assert not re.search(r"^\s*-?\s*git -c ", system, re.MULTILINE)
    for path in (SKILL, CODEX_SKILL):
        text = re.sub(r"\n\s*", "", path.read_text("utf-8"))
        assert OVERRIDE in text, path
        assert "承認済み" in text and "一字も変えずに使う" in text, path


def test_approved_message_is_used_verbatim():
    """利用者が全文を承認したメッセージは書き直させない (確認画面では切れて読めないことがある)。"""
    assert "一字も変えずに使う" in agent()["system"]
    assert "そのまま使う" in agent()["description"]
    skill = re.sub(r"\n\s*", "", SKILL.read_text("utf-8"))
    assert "任せる前にメッセージ全文をユーザーに示して承認を得て" in skill


def test_system_prompt_steers_reads_and_messages_away_from_the_shell():
    """読むのは read / glob / grep ツール、メッセージは -m を重ねる。"""
    system = agent()["system"]
    assert "read / glob / grep ツール" in system
    assert "ヒアドキュメントと -F は使わない" in system
    rules = normal_rules()
    for command in ("cat a.txt", "ls src", "find . -name x", "echo ---"):
        assert evaluate(rules, command) != "allow", command
    body = "git commit -m 'feat: x' -m '- Motivation: a\n- Change: b' -m '- Impact: c'"
    assert evaluate(rules, body) == "ask"

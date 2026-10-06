"""OpenCode の子エージェント ``commit`` (計画役) の権限と、親が行うコミットの規則の test.

``commit`` は読むだけで、論理単位ごとの対象とメッセージ全文を返す。ステージとコミットは親が
行い、親の ``git commit`` の確認が承認の場になる (通常起動でも隔離起動でも)。
OpenCode の照合 (後勝ち・``*`` は空白や ``/`` や改行も含む任意の文字列・末尾の `` *`` は
引数なしにも当たる) をここで再現し、生成した全体の規則 + エージェントの規則を当てる。
照合の性質は実機で確かめた。see docs/research/opencode/commit-review-agents.md の記録 E2
see docs/change/0013-commit-agent-as-planner.md

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
OVERRIDE = (
    "呼び出し元の指示やエージェントの説明が `git commit` の権限の確認を承認の場と定めているときは"
)


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


def agent() -> dict:
    return gen.merge_opencode_config({}, COMMON)["agents"]["commit"]


def agent_rules(base: list[dict]) -> list[dict]:
    return base + agent()["permissions"]


# --- 子 (計画役): 読むだけ -------------------------------------------------------

READS = [
    "git status",
    "git status --short --branch",
    "git diff HEAD",
    "git diff --cached --stat",
    'git diff -- "sub dir/c.txt"',
    "git log --oneline -10",
    "git log -1 --oneline",
    "git branch --show-current",
    "git rev-parse --show-toplevel",
]

WRITES = [
    'git add -- a.txt "sub dir/c.txt"',
    "git add -A",
    "git add .",
    'git restore --staged -- "sub dir/c.txt"',
    "git commit -m x",
    "git commit -m 'feat: x' -m '- Motivation: a\n- Change: b'",
    "git -c core.hooksPath=/dev/null commit -m x",
    "git stash",
    "git checkout -- a.txt",
    "git reset HEAD a.txt",
    "git clean -fd",
    "git switch -c x",
    "git rm a.txt",
    "git push",
    "git status --short > out.txt",
    "git diff HEAD 2>&1",
    "git diff --output=out.txt",
    "git log -p --output=out.txt",
    "cat a.txt",
    "ls src",
    "echo ---",
]


@pytest.mark.parametrize("command", READS)
def test_planner_can_read(command, tmp_path):
    for base in (normal_global(), ocs_config(tmp_path)["permissions"]):
        assert evaluate(agent_rules(base), command) == "allow", command


@pytest.mark.parametrize("command", WRITES)
def test_planner_cannot_stage_commit_or_write(command, tmp_path):
    """★通常起動でも隔離起動 (シェルの既定が allow) でも、読み取り以外は止まる。"""
    for base in (normal_global(), ocs_config(tmp_path)["permissions"]):
        assert evaluate(agent_rules(base), command) == "deny", command


def test_planner_cannot_edit_ask_or_launch_subagents():
    rules = agent()["permissions"]
    for action in ("edit", "question", "subagent"):
        assert {"action": action, "resource": "*", "effect": "deny"} in rules


def test_planner_rules_are_deny_all_then_reads_then_output_denies():
    """後勝ちなので、shell 全体の deny → 読み取りの allow → 書き出しの deny の順。"""
    shell = [r for r in agent()["permissions"] if r["action"] == "shell"]
    assert shell[0] == {"action": "shell", "resource": "*", "effect": "deny"}
    effects = [r["effect"] for r in shell[1:]]
    first_deny = effects.index("deny")
    assert all(e == "allow" for e in effects[:first_deny])
    assert {r["resource"] for r in shell[1 + first_deny :]} == {"*>*", "*<*", "*--output*"}
    assert "ask" not in effects


def test_output_deny_does_not_hit_plain_forms():
    for command in ("git diff --stat HEAD", "git log --oneline -10"):
        assert not matches("*--output*", command)


# --- 親: git commit の確認が承認の場 ---------------------------------------------


def test_parent_commit_asks_in_the_normal_config():
    assert evaluate(normal_global(), "git commit -m '<件名>' -m '<本文>'") == "ask"


def test_parent_commit_asks_in_ocs(tmp_path):
    """★隔離版も git commit の ask を捨てない (CHG-0013 の段 2。利用者の選択)。"""
    rules = ocs_config(tmp_path)["permissions"]
    assert evaluate(rules, "git commit -m x") == "ask"
    assert evaluate(rules, "git commit -m 'feat: x' -m '- Motivation: a'") == "ask"


@pytest.mark.parametrize("command", ["git status --short", "git diff HEAD"])
def test_global_rules_still_ask_for_plain_status_and_diff(command):
    """全体の allow から git status / git diff を外した判断は、commit の中でだけ例外にする。"""
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


# --- スキルと指示 ---------------------------------------------------------------


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


def test_skill_forms_split_between_planner_and_parent():
    """スキルが教える読み取りの形は子で allow、ステージとコミットは子で deny、親の commit は ask。

    ポリシーの節に並ぶ禁止の形 (--no-verify や git add . など) は除く。
    """
    forbidden = ("--no-verify", "--amend", "commit -a", "--all", "add .", "add -A")
    taught = [c for c in _skill_commands(SKILL) if not any(f in c for f in forbidden)]
    assert "git add -- <対象ファイル...>" in taught
    writes = ("git add", "git commit", "git restore")
    for command in taught:
        command = re.sub(r"<[^>]+>", "a.txt", command)
        expected = "deny" if command.startswith(writes) else "allow"
        assert evaluate(agent_rules(normal_global()), command) == expected, command
    assert evaluate(normal_global(), "git commit -m a.txt -m a.txt") == "ask"


def test_description_tells_the_parent_the_three_steps():
    """親から見える説明に、show → 全文をコードブロックで書く → apply の 3 手を書く (CHG-0014)。"""
    description = agent()["description"]
    assert "ステージもコミットもしない" in description
    assert "commit_plan.py show <ID>" in description
    assert "一字一句変えずに ```text のコードブロック 1 つで返答の文章に書く" in description
    assert "commit_plan.py apply <ID>" in description
    assert "guide plugin が apply を止める (利用者の拒否ではない)" in description
    assert "1 つずつ実行する" in description


SCRIPT_PATH = "~/.claude/skills/commit/scripts/commit_plan.py"


@pytest.mark.parametrize("home", ["~/", None])
def test_planner_can_snapshot_and_save_but_not_apply(home, tmp_path):
    path = SCRIPT_PATH if home else SCRIPT_PATH.replace("~/", gen.expand_user("~/"))
    for base in (normal_global(), ocs_config(tmp_path)["permissions"]):
        rules = agent_rules(base)
        assert evaluate(rules, f"python3 {path} snapshot") == "allow"
        assert evaluate(rules, f"python3 {path} save 20261006-1 '{{\"units\": []}}'") == "allow"
        assert evaluate(rules, f"python3 {path} apply 20261006-1") == "deny"
        assert evaluate(rules, f"python3 {path} save x '{{}}' > out") == "deny"


@pytest.mark.parametrize("home", ["~/", None])
def test_parent_apply_asks_and_show_is_free(home, tmp_path):
    """apply は通常起動でも隔離起動でも確認。show は確認なし (隔離起動は既定 allow)。"""
    path = SCRIPT_PATH if home else SCRIPT_PATH.replace("~/", gen.expand_user("~/"))
    for base in (normal_global(), ocs_config(tmp_path)["permissions"]):
        assert evaluate(base, f"python3 {path} apply 20261006-1") == "ask"
        assert evaluate(base, f"python3 {path} show 20261006-1") == "allow"


def test_parent_chained_commit_asks_once(tmp_path):
    """連結形は 1 回の呼び出し。git commit の区切りが ask (git add は通常で ask、隔離で allow)。"""
    for base in (normal_global(), ocs_config(tmp_path)["permissions"]):
        assert evaluate(base, "git commit -m 'feat: x' -m '- Change: y'") == "ask"
        assert evaluate(base, "git add -- a.txt") in ("ask", "allow")


def test_system_prompt_saves_a_plan_and_defers_to_the_skill():
    system = agent()["system"]
    assert "commit スキル" in system
    assert "commit_plan.py snapshot" in system
    assert "commit_plan.py save <ID> '<JSON>'" in system
    assert "\\u0027" in system and "\\u003e" in system
    assert "ファイル単位" in system
    assert "git add / git commit などで状態を変えない" in system


def test_skills_describe_the_planned_flow():
    for path in (SKILL, CODEX_SKILL):
        text = re.sub(r"\n\s*", "", path.read_text("utf-8"))
        assert OVERRIDE in text, path
        assert "子エージェントとして計画だけを求められた場合を含む" in text, path
        assert "ステージもコミットもしない" in text, path
    skill = re.sub(r"\n\s*", "", SKILL.read_text("utf-8"))
    assert "commit_plan.py show <ID>" in skill
    assert "一字一句変えずに ```text のコードブロック 1 つで" in skill
    assert "commit_plan.py apply <ID>" in skill


def test_system_prompt_keeps_shell_calls_sequential():
    """shell を同じ応答に並べない指示を保持する。

    see docs/research/opencode/commit-review-agents.md の記録 E7
    """
    assert (
        "shell は 1 回の応答で 1 つだけ呼び、完了結果を受け取ってから次を呼ぶ" in agent()["system"]
    )


def test_system_prompt_steers_reads_away_from_the_shell():
    assert "read / glob / grep ツール" in agent()["system"]

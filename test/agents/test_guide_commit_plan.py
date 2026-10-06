"""コミット計画の apply の前段の確かめ (guide plugin の ``commit-plan.js`` と ``index.js``)。

同じターンで ``commit_plan.py show <ID>`` の出力と同じ全文を ```text ブロックで返答に書いて
いなければ、apply を止める。会話の中で全文を読めることを仕組みで担保する。
see docs/change/0014-deterministic-commit-runner.md

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
SCRIPT = "~/.claude/skills/commit/scripts/commit_plan.py"
ID = "20261006-120000-abc123"
PLAN = "コミット計画 x（main、全 1 件）\n\n[1/1] 対象 1 件\n  M a.py\n  ---\n  feat: [1/1] 件名"


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い (mise.toml の [tools] に宣言してある)")
    return node


def user(text: str = "コミットして") -> dict:
    return {"type": "user", "text": text}


def show(output: str = PLAN, plan_id: str = ID, status: str = "completed") -> dict:
    return {
        "type": "tool",
        "name": "shell",
        "state": {
            "status": status,
            "input": {"command": f"python3 {SCRIPT} show {plan_id}"},
            "content": [{"type": "text", "text": output + "\n"}],
        },
    }


def text(body: str) -> dict:
    return {"type": "text", "text": body}


def assistant(*parts: dict) -> dict:
    return {"type": "assistant", "content": list(parts)}


APPLY = f"python3 {SCRIPT} apply {ID}"


@pytest.fixture(scope="module")
def check(tmp_path_factory):
    work = tmp_path_factory.mktemp("commit-plan")
    shutil.copy(PLUGIN / "commit-plan.js", work / "commit-plan.js")
    (work / "run.mjs").write_text(
        "import { checkApply } from './commit-plan.js'\n"
        "const [command, messages] = JSON.parse(process.argv[2])\n"
        "console.log(JSON.stringify(checkApply(command, messages)))\n",
        "utf-8",
    )

    def call(command: str, messages: list[dict]):
        done = subprocess.run(
            [_node(), str(work / "run.mjs"), json.dumps([command, messages])],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return json.loads(done.stdout)

    return call


def test_written_block_passes(check):
    msgs = [user(), assistant(show(), text(f"計画です。\n\n```text\n{PLAN}\n```"))]
    assert check(APPLY, msgs) is None


def test_trailing_spaces_and_crlf_are_ignored(check):
    written = PLAN.replace("\n", "  \r\n")
    msgs = [user(), assistant(show(), text(f"```\n{written}\n\n```"))]
    assert check(APPLY, msgs) is None


@pytest.mark.parametrize(
    ("messages", "word"),
    [
        ([user(), assistant(text(f"```text\n{PLAN}\n```"))], "show がこのターンにありません"),
        ([user(), assistant(show())], "全文が返答に見つかりません"),
        ([user(), assistant(show(), text(PLAN))], "全文が返答に見つかりません"),
        (
            [user(), assistant(show(), text(f"```text\n{PLAN.replace('[1/1]', '1/1')}\n```"))],
            "全文が返答に見つかりません",
        ),
        (
            [user(), assistant(show(), text(f"```text\n{PLAN}\n```")), user("次")],
            "show がこのターンにありません",
        ),
        (
            [
                user(),
                assistant(show(plan_id="20261006-120000-zzzzzz"), text(f"```text\n{PLAN}\n```")),
            ],
            "show がこのターンにありません",
        ),
        (
            [user(), assistant(show(status="running"), text(f"```text\n{PLAN}\n```"))],
            "show がこのターンにありません",
        ),
        ([user(), assistant(show(output=""), text("```text\n\n```"))], "空です"),
    ],
    ids=[
        "no-show",
        "not-written",
        "outside-block",
        "altered",
        "older-turn",
        "other-id",
        "not-finished",
        "empty",
    ],
)
def test_missing_or_altered_plan_is_stopped(check, messages, word):
    reason = check(APPLY, messages)
    assert reason and word in reason
    assert "利用者による拒否ではありません" in reason or "空です" in reason


@pytest.mark.parametrize(
    "command",
    ["git commit -m x", f"python3 {SCRIPT} show {ID}", f"python3 {SCRIPT} snapshot", "ls"],
)
def test_other_commands_are_not_checked(check, command):
    assert check(command, []) is None


def test_quoted_script_path_is_still_checked(check):
    assert check(f'python3 "{SCRIPT}" apply {ID}', [user()])


# --- index.js に組み込んだ形 ---------------------------------------------------

INDEX_SCRIPT = """
import plugin from './index.js'
const [command, messages, contextFails] = JSON.parse(process.argv[2])
const hooks = {}
const ctx = {
  tool: { hook: (n, fn) => { hooks[n] = fn } },
  permission: { hook() {} },
  shell: { hook() {} },
  session: { context: async () => { if (contextFails) throw new Error('boom'); return messages } },
}
await plugin.setup(ctx)
try {
  await hooks['execute.before']({ tool: 'shell', id: 'x', sessionID: 's', agent: 'build',
    input: { command } })
  console.log(JSON.stringify(null))
} catch (err) {
  console.log(JSON.stringify(err.message))
}
"""


def _index(tmp_path: Path, command: str, messages: list[dict], *, fails=False, helper=True):
    for name in ("index.js", "commit-message.js", *(["commit-plan.js"] if helper else [])):
        shutil.copy(PLUGIN / name, tmp_path / name)
    (tmp_path / "rules.json").write_text(json.dumps(gen.build_opencode_guide({}, COMMON)), "utf-8")
    (tmp_path / "run.mjs").write_text(INDEX_SCRIPT, "utf-8")
    done = subprocess.run(
        [_node(), str(tmp_path / "run.mjs"), json.dumps([command, messages, fails])],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env=node_env(),
    )
    return json.loads(done.stdout)


def test_index_passes_a_written_plan(tmp_path):
    msgs = [user(), assistant(show(), text(f"```text\n{PLAN}\n```"))]
    assert _index(tmp_path, APPLY, msgs) is None


def test_index_stops_an_unwritten_plan(tmp_path):
    reason = _index(tmp_path, APPLY, [user(), assistant(show())])
    assert reason and "全文が返答に見つかりません" in reason


def test_index_fails_closed_when_the_context_is_unreadable(tmp_path):
    msgs = [user(), assistant(show(), text(f"```text\n{PLAN}\n```"))]
    reason = _index(tmp_path, APPLY, msgs, fails=True)
    assert reason and "会話の記録を読めない" in reason


def test_index_fails_closed_without_the_helper(tmp_path):
    msgs = [user(), assistant(show(), text(f"```text\n{PLAN}\n```"))]
    reason = _index(tmp_path, APPLY, msgs, helper=False)
    assert reason and "commit-plan.js を読めない" in reason


def test_index_leaves_other_commands_alone(tmp_path):
    assert _index(tmp_path, "git status --short", [], fails=True) is None

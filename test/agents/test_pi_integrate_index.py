"""index.ts の配線の縮小後の姿。実際の pi (faux モデル) に、フルガードを載せて確かめる。

旧い統合経路の撤去 (CHG-0062 の A5) で、git_integrate と非同期承認の配線は消えた。固定するのは次の 3 つ。
- guarded_action の説明・システムプロンプト・bash の説明に git_integrate が出ない (設定の値に関わらず)
- git_integrate を呼ぶと、未知の操作として拒否される
- /pending は、退避したコミットの list / show / drop 用に登録されている (静的に確かめる)
see docs/change/0062-pr-hub-simplify.md
"""

# ruff: noqa: F811
# fixture (env) を他の試験ファイルから import するので、引数名の再定義を許す
from __future__ import annotations

import json
import re

import pytest
from test_pi_harness import HARNESS_SRC, PI, env, run_pi  # noqa: F401

pytestmark = pytest.mark.skipif(PI is None, reason="pi is not installed")

# 旧い配線が使っていたラベル。システムプロンプトには作業ディレクトリ (試験名を含む) が入るので、操作の id ではなくラベルで見る
LABEL = "保護ブランチへの統合 (squash)"


def _tool_descriptions(env) -> dict[str, str]:
    proc = run_pi(env, [], FAUX_DUMP_TOOLS="1")
    assert proc.returncode == 0, proc.stderr
    hit = re.search(r"TOOLDEFS=(\[.*\])", proc.stdout, re.S)
    assert hit, proc.stdout + proc.stderr
    return {d["name"]: d["description"] or "" for d in json.loads(hit.group(1))}


def _system_prompt(env) -> str:
    proc = run_pi(env, [], FAUX_DUMP_PROMPT="1")
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_git_integrate_is_not_advertised(env):
    descs = _tool_descriptions(env)
    assert "guarded_action" in descs  # 承認つきの操作そのものは従来どおり
    for name, text in descs.items():
        assert "git_integrate" not in text, name
    assert "/pending approve" not in descs["guarded_bash"]
    prompt = _system_prompt(env)
    assert LABEL not in prompt
    assert "- guarded_action: " in prompt  # git_commit などの行は残る


def test_git_integrate_is_an_unknown_action(env):
    call = [
        {
            "name": "guarded_action",
            "args": {"action": "git_integrate", "params": {"source": "feature/x", "message": "m"}},
        }
    ]
    proc = run_pi(env, call)
    out = proc.stdout + proc.stderr
    assert "isError=true" in out and "unknown action" in out, out


# --- 配線の有無 (実際の pi では回せない箇所を、ソースで固定する) ---

INDEX = HARNESS_SRC.read_text(encoding="utf-8")


def test_pending_command_is_still_registered():
    assert re.search(r"registerPendingCommand\(pi,", INDEX)
    cmd = (HARNESS_SRC.parent / "pending-command.ts").read_text(encoding="utf-8")
    assert 'pi.registerCommand("pending"' in cmd

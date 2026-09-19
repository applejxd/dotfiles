"""bashrules/tables.toml (Python を書かずに編集できるデータ層) の振る舞い。

利用者が TOML だけを編集したときに何が起きるかを確かめる。
判定そのものの網羅は test_check_bash_decision.py 側にある。

Run with: ``uv run --with pytest --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = ROOT / "home" / "dot_claude" / "hooks" / "executable_check_bash.py"

sys.path.insert(0, str(ROOT / "test" / "agents"))

from agents_common import agents_config_dir  # noqa: E402

AGENTS_DIR = agents_config_dir()


def _run(hook: Path, command: str) -> tuple[str | None, str]:
    """hook を subprocess で動かし (decision, reason) を返す。

    decision は hook が沈黙したとき (= 許可) に None。その場合は CLI 側が
    素通り扱いにするため、stderr を reason として返して切り分けられるようにする。
    """
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(ROOT),
    }
    proc = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "AGENTS_CONFIG_DIR": str(AGENTS_DIR)},
    )
    out = proc.stdout.strip()
    if not out:
        return None, proc.stderr.strip()
    data = json.loads(out)
    return data["permissionDecision"], data.get("permissionDecisionReason", "")


def _run_with_tables(tmp_path: Path, command: str, mutate) -> tuple[str | None, str]:
    """hook 一式を複製し、tables.toml を書き換えてから実行する。

    実ファイルを触らずに「利用者が TOML を編集した状態」を作るためのヘルパ。
    ``mutate`` は TOML 本文を受け取って書き換えた本文を返す。
    """
    hooks = tmp_path / "hooks"
    shutil.copytree(HOOK_PATH.parent, hooks, ignore=shutil.ignore_patterns("__pycache__"))
    tables = hooks / "lib" / "bashrules" / "tables.toml"
    tables.write_text(mutate(tables.read_text(encoding="utf-8")), encoding="utf-8")
    return _run(hooks / HOOK_PATH.name, command)


def test_tables_toml_edit_changes_the_decision(tmp_path):
    """TOML に 1 行足すだけで守れること (Python を書かずに更新できる)。

    これが成り立たないと「データは TOML / ロジックは Python」という建て付けが
    崩れ、利用者が Python を読まないと更新できない状態に戻る。
    """
    target = "cat ./my-company-token.txt"
    assert _run(HOOK_PATH, target)[0] is None, "前提: 未登録の名前は素通りする"

    def add_name(text: str) -> str:
        return text.replace(
            "sensitive_basenames = [\n",
            'sensitive_basenames = [\n  "my-company-token.txt",\n',
            1,
        )

    decision, reason = _run_with_tables(tmp_path, target, add_name)
    assert decision == "deny", f"TOML に足した名前が効いていない (stderr={reason})"
    assert "my-company-token.txt" in reason


def test_broken_tables_toml_does_not_silently_allow(tmp_path):
    """TOML を壊しても素通りせず deny になること (fail-closed)。

    利用者が手で編集する以上、壊れた状態は必ず起きる。import 例外のまま終了
    すると stdout が空・exit 1 となり、CLI 側は「hook 失敗」として素通りさせて
    しまう (agent_compat の Pattern C)。必ず deny を出力してから終わること。
    """
    decision, reason = _run_with_tables(
        tmp_path,
        "cat ~/.ssh/id_rsa",
        lambda text: text + "\nthis is not valid toml [[[\n",
    )
    assert decision == "deny", f"壊れた TOML で素通りした (fail-open): {reason}"
    assert "検査ルールを読み込めませんでした" in reason

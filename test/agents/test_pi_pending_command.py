"""``/pending`` の旧形式 (``home/dot_config/pi/harness/pending-command.ts``)。

``test/agents/pi/pending_command_driver.mjs`` が、偽の pi・偽の ctx・使い捨ての git リポジトリで
``registerPendingCommand`` を動かして結果を JSON で出す (node の型除去を使うので、22.18 未満の node では飛ばす)。
確かめるのは、旧形式 (承認が取れず退避した git commit) の list / show / drop / USAGE が従来の出力のままであることと、
コマンドだけの登録 (ツールは登録しない)。新形式 (承認・巡回・resolve・unlock) の試験は、旧い統合経路の撤去で外した。

see docs/change/closed/0062-pr-hub-simplify.md
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "pending_command_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


@pytest.fixture(scope="module")
def table():
    proc = subprocess.run(
        [_node(), str(RUNNER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1000:]
    return json.loads(proc.stdout)


def test_legacy_list_show_drop_keep_their_original_output(table):
    assert table["legacy_empty"] == "退避したコミットは無い"
    lg = table["legacy"]
    # 一覧の 1 行: <id>  <短い oid>  <件名>  (<ブランチ>)
    assert lg["list"] == f"{lg['id']}  {lg['short']}  feat: a.txt  (refs/heads/main)"
    assert lg["listLevel"] == "info" and lg["showHasMessage"] is True
    assert lg["missing"] == "見つからない (/pending list で ref を確かめる)"
    assert lg["drop"] == (
        f"破棄した: refs/pi/pending/{lg['id']} (到達用の ref を外した。オブジェクトは git gc まで残る)"
    )
    assert lg["dropAgain"] == "破棄できなかった (ref が無い・退避の ref ではない)"
    assert lg["after"] == "退避したコミットは無い"
    assert lg["usage"].startswith("/pending [list | show <id>")
    assert lg["touched"] >= 1  # 操作のたびに不在を解除する


def test_it_registers_a_command_only(table):
    # registerTool は呼ばれない (偽の pi は呼ぶと例外)
    assert table["registration"]["commands"] == ["pending"]

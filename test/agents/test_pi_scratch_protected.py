"""`.tmp` 自体や `.tmp/keep` を丸ごと消す削除を、TS 版の判定器でも ask にする (CHG-0042 U13 の b')。

Python 版 (`test_check_bash_file_ops.py`) と同じ結果になることの確認。配下の個別の削除と、絞り込みのある
`find` は、今までどおり免除 (`[bash] ask` の規則に当たらず、承認を省く。役割の既定の判定に落ちる)。
"""

from __future__ import annotations

import pytest
from test_pi_confirm import _bash, _judge
from test_pi_judge_ts import _node

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

PROTECTED = [
    "rm -rf .tmp",
    "rm -rf ./.tmp",
    "rm -rf .tmp/",
    "rm -rf /work/proj/.tmp",
    "rm -rf .tmp/*",
    "rm -rf .tmp/keep",
    "rm -rf ./.tmp/research",
    "rm -rf .tmp/review-loop",
    "find ./.tmp -delete",
    "find /work/proj/.tmp -delete",
    "find .tmp -maxdepth 1 -delete",
    "find .tmp -exec rm {} +",
    "find .tmp/keep -delete",
]
EXEMPT = [
    "rm -rf .tmp/keep/old.md",
    "rm -rf .tmp/research/topic",
    "rm -rf .tmp/s/abcd1234",
    "rm -f .tmp/a.log .tmp/b.log",
    "rm -rf /work/proj/.tmp/run-1",
    "find ./.tmp -name '*.log' -delete",
    "find .tmp -type f -mtime +7 -delete",
    "find .tmp -type f -exec rm {} +",
    "find .tmp/keep -name '*.tmp' -delete",
]


@pytest.mark.parametrize("command", PROTECTED)
def test_whole_scratch_and_protected_places_ask_by_the_policy(command: str) -> None:
    (verdict,) = _judge([_bash(command)])
    assert verdict["decision"] == "ask", f"{command!r} -> {verdict}"
    assert verdict.get("check") in {"check_policy_ask", "check_find_dangerous"}, (
        f"{command!r} -> {verdict}"
    )


@pytest.mark.parametrize("command", EXEMPT)
def test_individual_deletions_and_filtered_find_stay_exempt(command: str) -> None:
    (verdict,) = _judge([_bash(command)])
    # 免除 = ask の規則に当たらない (役割の既定の判定に落ちる)
    assert verdict.get("check") not in {"check_policy_ask", "check_find_dangerous"}, (
        f"{command!r} -> {verdict}"
    )


def test_the_protected_form_is_a_rule_ask_that_bypass_passes() -> None:
    normal, bypass = _judge([_bash("rm -rf .tmp"), _bash("rm -rf .tmp", bypass=True)])
    assert normal["decision"] == "ask"
    assert bypass["decision"] == "allow" and bypass.get("bypassed") is True

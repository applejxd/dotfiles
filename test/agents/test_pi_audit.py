"""子の完了結果の形式検査 (``home/dot_config/pi/harness/audit.ts``) の表試験。

``test/agents/pi/audit_golden.mjs`` が audit.ts を読んで結果を JSON で出す。node の型除去
(strip-types) を使うので、22.18 未満の node では飛ばす。
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "audit_golden.mjs"

ALL = ["結論", "根拠", "未確認", "次の候補"]

AUDIT = {
    "standard_headings": [],
    "bold_with_colon": [],
    "bold_alone_lines": [],
    "parens_fullwidth": [],
    "parens_ascii": [],
    "review_style": [],
    "quoted_bullets": [],
    "two_only": ["未確認", "次の候補"],
    "mention_not_heading": ALL,
    "empty": ALL,
}
SUMMARY = {
    "none": "none",
    "strip_and_order": "read×2 bash×1",
    "tie_by_name": "bash×2 read×2 write×1",
    "mixed_prefix": "read×2 grep×1",
}


@pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")
def test_audit_matches_the_table():
    proc = subprocess.run(
        [_node(), str(RUNNER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1000:]
    got = json.loads(proc.stdout)
    assert got["audit"] == AUDIT
    assert got["summary"] == SUMMARY

"""同梱の ``[pi.integrate] risk_paths`` が ``.agents/config/pi.json`` の変更を拾うことの試験。

描画後の設定 (生成器の出力) の ``risk_paths`` に、設定ファイルが入っていることを確かめる。
統合の算出 (旧 harness/integrate-plan.ts) へ渡す結合の検査は、旧い統合経路の撤去 (CHG-0062 の A5) で外した。
PR ビューア側は、合成した ``risk_paths`` で試験している (test_pr_viewer_merge_api.py)。
"""

from __future__ import annotations

import sys

from agents_common import ROOT, load_common

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen

PI_JSON = ".agents/config/pi.json"


def test_shipped_risk_paths_list_pi_json():
    assert PI_JSON in gen.pi_integrate(load_common())["risk_paths"]

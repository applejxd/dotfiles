"""同梱の ``[pi.integrate] risk_paths`` が ``.agents/config/pi.json`` の変更を拾うことの試験。

描画後の設定 (生成器の出力) を、統合の算出 (harness/integrate-plan.ts) へそのまま渡す。
"""

from __future__ import annotations

import sys

from agents_common import ROOT, load_common
from test_pi_integrate_plan import _commit, _git, _plan, repo  # noqa: F401  (repo は fixture)

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen

PI_JSON = ".agents/config/pi.json"


def test_shipped_risk_paths_list_pi_json():
    assert PI_JSON in gen.pi_integrate(load_common())["risk_paths"]


def test_plan_flags_pi_json_with_shipped_risk_paths(repo):  # noqa: F811
    risk = gen.pi_integrate(load_common())["risk_paths"]
    _git(repo, "checkout", "-q", "feature/x")
    _commit(repo, PI_JSON, "{}\n")
    _git(repo, "checkout", "-q", "develop")
    plan = _plan(repo, riskPaths=risk)
    assert plan["ok"] is True, plan
    flagged = {r["path"]: r["reason"] for r in plan["risks"]}
    assert PI_JSON in flagged
    assert PI_JSON in flagged[PI_JSON]

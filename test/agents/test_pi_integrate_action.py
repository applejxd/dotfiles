"""git_integrate のアダプタ (harness/integrate-action.ts) の試験。使い捨ての実 git リポジトリで確かめる。

要求側 (capture)・承認側 (plan / recheck / execute)・二重承認・linked worktree で要求して本体で承認する流れを見る。
see docs/change/0055
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_integrate_exec import _hook
from test_pi_integrate_plan import PROTECTED, RISK, _commit, _git
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "integrate_action_driver.mjs"
CFG = {"target": "develop", "protectedRefs": PROTECTED, "riskPaths": RISK}
MSG = "feat: x\n\nbody line"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="hook をシェルスクリプトで作る")


def _run(payload: dict, timeout: int = 120) -> dict:
    node = _node()
    if node is None:
        pytest.skip("node が無い (または古い)")
    out = subprocess.run(
        [node, str(DRIVER)],
        input=json.dumps({"cfg": CFG, **payload}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=timeout,
    )
    return json.loads(out.stdout)


def _values(**kw: str) -> dict:
    return {"source": "feature/x", "message": MSG, **kw}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "main"
    r.mkdir()
    _git(r, "init", "-q", "-b", "develop")
    for k, v in (("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
        _git(r, "config", k, v)
    _commit(r, "a.txt", "1\n2\n3\n", "init")
    _git(r, "checkout", "-q", "-b", "feature/x")
    _commit(r, "b.txt", "new\nfile\n")
    _commit(r, "scripts/run.sh", "echo\n")
    _git(r, "checkout", "-q", "develop")
    _commit(r, "c.txt", "dev\n")
    return r


@pytest.fixture
def feat(repo: Path, tmp_path: Path) -> Path:
    p = tmp_path / "feat"
    _git(repo, "worktree", "add", "-q", str(p), "feature/x")
    return p


def _rev(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", ref).strip()


def test_spec_and_capture_premise(repo: Path) -> None:
    res = _run({"op": "capture", "cwd": str(repo), "values": _values(cleanup="branch")})
    spec = res["spec"]
    assert spec["id"] == "git_integrate" and spec["argv"] == []
    assert (
        spec["fields"]["cleanup"]["optional"] is True and "optional" not in spec["fields"]["source"]
    )
    cap = res["capture"]
    assert cap["ok"] is True, cap
    p = cap["premise"]
    assert p["kind"] == "git_integrate" and p["cleanup"] == "branch"
    assert p["source"] == "refs/heads/feature/x" and p["target"] == "refs/heads/develop"
    assert p["sourceOid"] == _rev(repo, "feature/x") and p["targetOid"] == _rev(repo, "develop")
    assert p["mergeBase"] == _git(repo, "merge-base", "develop", "feature/x").strip()
    assert len(p["resultTree"]) >= 40 and len(p["messageDigest"]) == 64
    assert cap["worktree"] == str(repo)


def test_capture_refusals(repo: Path) -> None:
    def cap(cwd: Path = repo, **kw: str) -> dict:
        return _run({"op": "capture", "cwd": str(cwd), "values": _values(**kw)})["capture"]

    bad = cap(cleanup="rm_rf")
    assert bad["ok"] is False and "cleanup" in bad["reason"]
    _git(repo, "checkout", "-q", "-b", "feature/y", "develop")
    assert "already_merged" in cap(source="feature/y")["reason"]
    _git(repo, "checkout", "-q", "develop")
    _git(repo, "checkout", "-q", "-b", "feature/c1", "develop~1")
    _commit(repo, "c.txt", "conflict\n")
    _git(repo, "checkout", "-q", "develop")
    c = cap(source="feature/c1")
    assert c["ok"] is False and "conflict" in c["reason"] and "c.txt" in c["reason"]


def test_plan_summary_and_changes(repo: Path) -> None:
    res = _run(
        {"op": "flow", "requestCwd": str(repo), "approverCwd": str(repo), "values": _values()}
    )
    assert res["capture"]["ok"] is True
    lines = res["plan"]["summary"].split("\n")
    assert all(sum(2 if ord(ch) > 0x2E80 else 1 for ch in ln) <= 46 for ln in lines), lines
    text = res["plan"]["summary"]
    assert "feature/x → develop (squash)" in text and "衝突: なし" in text
    assert "scripts/run.sh" in text and "要求時から変わった点" not in text
    assert (
        "feat: x" in res["plan"]["view"]
        and "body line" in res["plan"]["view"]
        and "b.txt" in res["plan"]["view"]
    )
    assert res["recheck"] == {"ok": True}


def test_stacked_warning_only_when_stacked(repo: Path) -> None:
    flow = {"op": "flow", "requestCwd": str(repo), "approverCwd": str(repo)}
    plain = _run({**flow, "values": _values()})["plan"]
    assert "含む他の feature" not in plain["summary"] and "含む他の feature" not in plain["view"]
    _git(repo, "branch", "feature/a", "feature/x~1")
    res = _run({**flow, "values": _values()})
    for key in ("summary", "view"):
        assert "含む他の feature (未統合): feature/a" in res["plan"][key], res["plan"][key]
    assert res["recheck"] == {"ok": True}
    assert "stacked" not in res["capture"]["premise"]


def _stacked_flow(repo: Path, saved: list[dict]) -> dict:
    _git(repo, "branch", "feature/a", "feature/x~1")
    return _run(
        {
            "op": "flow",
            "requestCwd": str(repo),
            "approverCwd": str(repo),
            "values": _values(),
            "saved": saved,
        }
    )


def test_stacked_warning_shows_unapproved_pending(repo: Path) -> None:
    res = _stacked_flow(repo, [{"values": _values(source="feature/a")}])
    tail = res["savedIds"][0][-4:]
    for key in ("summary", "view"):
        assert f"feature/a (保留 …{tail} が未承認)" in res["plan"][key], res["plan"][key]
    assert "先にそちらを承認するのが通常の順序" in res["plan"]["view"]
    assert res["recheck"] == {"ok": True}


def test_stacked_warning_without_pending_is_unchanged(repo: Path) -> None:
    res = _stacked_flow(repo, [])
    for key in ("summary", "view"):
        assert "保留" not in res["plan"][key] and "未承認" not in res["plan"][key], res["plan"][key]
        assert "含む他の feature (未統合): feature/a" in res["plan"][key]


def test_stacked_warning_ignores_done_pending(repo: Path) -> None:
    res = _stacked_flow(repo, [{"values": _values(source="feature/a"), "finish": True}])
    for key in ("summary", "view"):
        assert "未承認" not in res["plan"][key] and "保留" not in res["plan"][key], res["plan"][key]


def test_stacked_warning_ignores_unrelated_pending(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "feature/z", "develop~1")
    _commit(repo, "z.txt", "z\n")
    _git(repo, "checkout", "-q", "develop")
    res = _stacked_flow(repo, [{"values": _values(source="feature/z")}])
    for key in ("summary", "view"):
        assert "未承認" not in res["plan"][key] and "feature/z" not in res["plan"][key], res[
            "plan"
        ][key]
    # 無関係な保留があっても、文言は「統合する」のままで、summary は 1 行のまま (保留が見つかったときだけ行を分ける)
    assert "保留" not in res["plan"]["view"], res["plan"]["view"]
    assert "先にそちらを統合するのが通常の順序" in res["plan"]["view"], res["plan"]["view"]
    assert "含む他の feature (未統合): feature/a" in res["plan"]["summary"], res["plan"]["summary"]


def test_target_advanced_after_request(repo: Path) -> None:
    res = _run(
        {
            "op": "flow",
            "requestCwd": str(repo),
            "approverCwd": str(repo),
            "values": _values(),
            "beforePlan": [["commit", "-q", "--allow-empty", "-m", "advance1"]],
            "beforeRecheck": [["commit", "-q", "--allow-empty", "-m", "advance2"]],
        }
    )
    summary = res["plan"]["summary"]
    assert "要求時から変わった点" in summary and "統合先が進んだ" in summary
    assert res["recheck"]["ok"] is False and "統合先が進んだ" in res["recheck"]["reason"]


def test_execute_integrates(repo: Path) -> None:
    old = _rev(repo, "develop")
    res = _run(
        {
            "op": "flow",
            "requestCwd": str(repo),
            "approverCwd": str(repo),
            "values": _values(),
            "execute": True,
        }
    )
    assert res["exec"]["outcome"] == "success", res["exec"]
    assert _rev(repo, "develop~1") == old
    assert _git(repo, "log", "-1", "--format=%B").strip() == MSG
    assert _git(repo, "status", "--porcelain") == ""


def test_hook_changes_commit(repo: Path, tmp_path: Path) -> None:
    _hook(repo, tmp_path, "echo x > extra.txt\ngit add extra.txt")
    res = _run(
        {
            "op": "flow",
            "requestCwd": str(repo),
            "approverCwd": str(repo),
            "values": _values(),
            "execute": True,
        }
    )
    assert res["exec"]["outcome"] == "success", res["exec"]
    assert any("hook が内容を変えた" in e for e in res["exec"]["evidence"]), res["exec"]


def test_double_approval_runs_once(repo: Path) -> None:
    before = _rev(repo, "develop")
    res = _run({"op": "double", "cwd": str(repo), "values": _values(), "before": before})
    assert res["commits"] == 1, res
    assert len(res["sent"]) == 1 and res["sent"][0]["outcome"] == "success", res
    assert sorted(r["level"] for r in res["replies"]) == ["info", "warning"], res
    assert _git(repo, "status", "--porcelain") == ""


def test_request_in_linked_worktree_approve_in_main(repo: Path, feat: Path) -> None:
    res = _run(
        {
            "op": "flow",
            "requestCwd": str(feat),
            "approverCwd": str(repo),
            "values": _values(cleanup="branch_and_worktree"),
            "execute": True,
        }
    )
    assert res["capture"]["ok"] is True and res["capture"]["worktree"] == str(repo), res["capture"]
    assert res["exec"]["outcome"] == "success", res["exec"]
    assert not feat.exists()
    assert _git(repo, "branch", "--list", "feature/x").strip() == ""
    assert (repo / "b.txt").exists()


def test_request_saves_when_target_dirty_but_approval_refuses(repo: Path, feat: Path) -> None:
    """要求側は統合先の dirty を調べず保存できる。承認側の再計画は dirty で拒否し、実行しない。see docs/change/0055"""
    (repo / "a.txt").write_text("dirty\n", encoding="utf-8")
    old = _rev(repo, "develop")
    res = _run(
        {
            "op": "flow",
            "requestCwd": str(feat),
            "approverCwd": str(repo),
            "values": _values(),
            "execute": True,
        }
    )
    assert res["capture"]["ok"] is True and res["capture"]["premise"]["kind"] == "git_integrate", (
        res["capture"]
    )
    assert res["capture"]["worktree"] == str(repo)
    assert res["plan"]["ok"] is False and "dirty_target_worktree" in res["plan"]["reason"], res[
        "plan"
    ]
    assert "exec" not in res and _rev(repo, "develop") == old
    assert (repo / "a.txt").read_text(encoding="utf-8") == "dirty\n"


# --- isTargetWorktree (git の識別で「統合先の作業ツリーの中か」を判定する) と enabled ---

HERE_JS = """
import { pathToFileURL } from "node:url";
import { readFileSync } from "node:fs";
const ia = await import(pathToFileURL(process.env.IA_TS).href);
const req = JSON.parse(readFileSync(0, "utf8"));
const out = {};
const state = { on: req.enabled };
if (req.op === "same") {
	out.same = ia.sameIdentity(req.a, req.b);
} else if (req.op === "here") {
	out.here = ia.isTargetWorktree(req.cwd, req.target, req.env ?? undefined);
} else {
	const cfg = { ...req.cfg, enabled: () => state.on };
	const env = { ...process.env };
	out.capture = await ia.integrateRequestAdapter(cfg).capture({ cwd: req.cwd, values: req.values, env });
	const rec = { action: "git_integrate", params: req.values, premise: {}, request: { id: "x", sessionId: "s", cwd: req.cwd } };
	const ad = ia.integrateApprovalAdapter(cfg);
	out.plan = await ad.plan(rec, { cwd: req.cwd, env, rules: {} });
	if (req.enabledAfterPlan !== undefined) state.on = req.enabledAfterPlan;
	const approved = { plan: { source: { ref: "x", oid: "x" }, message: "m" }, cleanup: "none" };
	out.recheck = await ad.recheck(approved, { cwd: req.cwd, env, rules: {} });
}
process.stdout.write(JSON.stringify(out));
"""


def _js(tmp_path: Path, payload: dict, env_extra: dict | None = None) -> dict:
    node = _node()
    if node is None:
        pytest.skip("node が無い (または古い)")
    script = tmp_path / "here_driver.mjs"
    script.write_text(HERE_JS, encoding="utf-8")
    import os

    env = {
        **os.environ,
        "IA_TS": str(ROOT / "home" / "dot_config" / "pi" / "harness" / "integrate-action.ts"),
        **(env_extra or {}),
    }
    out = subprocess.run(
        [node, str(script)],
        input=json.dumps({"cfg": CFG, **payload}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
        env=env,
    )
    return json.loads(out.stdout)


def _here(tmp_path: Path, cwd: Path | str, target: Path | str, **kw) -> dict:
    return _js(tmp_path, {"op": "here", "cwd": str(cwd), "target": str(target), **kw})["here"]


def test_here_false_for_feature_worktree_under_main(repo: Path, tmp_path: Path) -> None:
    # 反例: feature の worktree は本体の配下にある。パスの配下判定 (素朴な実装) だと true になって誤許可する
    nested = repo / ".tmp" / "worktrees" / "x"
    _git(repo, "worktree", "add", "-q", str(nested), "feature/x")
    assert str(nested).startswith(str(repo) + "/")  # 素朴な「配下か」判定なら here: true になる配置
    assert _here(tmp_path, nested, repo) == {"ok": True, "here": False}
    assert _here(tmp_path, repo, nested) == {"ok": True, "here": False}


def test_here_true_for_root_and_subdir(repo: Path, tmp_path: Path) -> None:
    (repo / "sub" / "deep").mkdir(parents=True)
    assert _here(tmp_path, repo, repo) == {"ok": True, "here": True}
    assert _here(tmp_path, repo / "sub" / "deep", repo) == {"ok": True, "here": True}


def test_here_false_for_sibling_worktree(repo: Path, feat: Path, tmp_path: Path) -> None:
    assert _here(tmp_path, feat, repo) == {"ok": True, "here": False}


def test_here_false_for_nested_other_repo(repo: Path, tmp_path: Path) -> None:
    inner = repo / "vendor" / "inner"
    inner.mkdir(parents=True)
    _git(inner, "init", "-q", "-b", "main")
    assert _here(tmp_path, inner, repo) == {"ok": True, "here": False}


def test_here_true_via_symlink(repo: Path, tmp_path: Path) -> None:
    link = tmp_path / "link"
    link.symlink_to(repo, target_is_directory=True)
    assert _here(tmp_path, link, repo) == {"ok": True, "here": True}
    assert _here(tmp_path, repo, link) == {"ok": True, "here": True}


def test_here_not_ok_for_non_git_or_missing(repo: Path, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    ceil = {
        "GIT_CEILING_DIRECTORIES": str(tmp_path)
    }  # tmp_path が別のリポジトリの中にあっても、そこへは遡らせない
    for bad in (plain, tmp_path / "missing"):
        for a, b in ((bad, repo), (repo, bad)):
            r = _js(tmp_path, {"op": "here", "cwd": str(a), "target": str(b)}, ceil)["here"]
            assert r["ok"] is False and r["reason"], r


def test_here_ignores_inherited_git_env(repo: Path, feat: Path, tmp_path: Path) -> None:
    # GIT_DIR / GIT_WORK_TREE が本体を指していても、feat の実体で判定される
    inherited = {"GIT_DIR": str(repo / ".git"), "GIT_WORK_TREE": str(repo)}
    assert _js(tmp_path, {"op": "here", "cwd": str(feat), "target": str(repo)}, inherited)[
        "here"
    ] == {"ok": True, "here": False}
    assert _js(tmp_path, {"op": "here", "cwd": str(feat), "target": str(repo), "env": inherited})[
        "here"
    ] == {"ok": True, "here": False}
    assert _js(tmp_path, {"op": "here", "cwd": str(repo), "target": str(feat)}, inherited)[
        "here"
    ] == {"ok": True, "here": False}


def test_enabled_false_refuses_all(repo: Path, tmp_path: Path) -> None:
    off = _js(tmp_path, {"op": "adapters", "cwd": str(repo), "values": _values(), "enabled": False})
    assert off["capture"]["ok"] is False and "無効" in off["capture"]["reason"]
    assert off["plan"]["ok"] is False and "無効" in off["plan"]["reason"]
    assert off["recheck"]["ok"] is False and "無効" in off["recheck"]["reason"]
    on = _js(tmp_path, {"op": "adapters", "cwd": str(repo), "values": _values(), "enabled": True})
    assert on["capture"]["ok"] is True and on["plan"]["ok"] is True


def test_here_not_ok_when_target_is_subdir(repo: Path, tmp_path: Path) -> None:
    # 統合先自体が作業ツリーのルートでない (サブディレクトリ) → 拒否。cwd 側のサブディレクトリは従来どおり許す
    (repo / "sub").mkdir()
    r = _here(tmp_path, repo, repo / "sub")
    assert r["ok"] is False and "ルート" in r["reason"], r


def test_here_not_ok_when_target_deleted_and_climbs_to_parent(repo: Path, tmp_path: Path) -> None:
    # 統合先の worktree が消え、同じ場所に空のディレクトリが残ると、git は親 (本体) へ遡る
    gone = repo / ".tmp" / "worktrees" / "gone"
    gone.mkdir(parents=True)
    r = _here(tmp_path, repo, gone)
    assert r["ok"] is False and "ルート" in r["reason"], r


@pytest.mark.parametrize("idx", [0, 1, 2])
def test_same_identity_checks_each_identifier(tmp_path: Path, idx: int) -> None:
    a = ["/r/.git", "/r/.git", "/r"]
    assert _js(tmp_path, {"op": "same", "a": a, "b": list(a)})["same"] is True
    b = list(a)
    b[idx] = "/other"
    assert _js(tmp_path, {"op": "same", "a": a, "b": b})["same"] is False
    assert _js(tmp_path, {"op": "same", "a": a, "b": a[:2]})["same"] is False


def test_enabled_turned_off_between_plan_and_recheck(repo: Path, tmp_path: Path) -> None:
    r = _js(
        tmp_path,
        {
            "op": "adapters",
            "cwd": str(repo),
            "values": _values(),
            "enabled": True,
            "enabledAfterPlan": False,
        },
    )
    assert r["plan"]["ok"] is True
    assert r["recheck"]["ok"] is False and "無効" in r["recheck"]["reason"], r["recheck"]


def test_enabled_omitted_keeps_behavior(repo: Path) -> None:
    # CFG には enabled が無い (従来の呼び出し)。既存の試験と同じく通る
    assert _run({"op": "capture", "cwd": str(repo), "values": _values()})["capture"]["ok"] is True


# --- 承認側アダプターの runsHere・exclusive・execute の戻り値 (実行の核へ接続する契約) ---


def _adapter(cwd: Path, target: Path | str | None) -> dict:
    return _run(
        {
            "op": "adapter",
            "cwd": str(cwd),
            "targetWorktree": None if target is None else str(target),
        }
    )


def test_adapter_runs_here_from_main_and_not_from_nested_feature(repo: Path) -> None:
    nested = repo / ".tmp" / "worktrees" / "x"
    _git(repo, "worktree", "add", "-q", str(nested), "feature/x")
    assert _adapter(repo, repo)["here"] == {"ok": True, "here": True}
    assert _adapter(nested, repo)["here"] == {"ok": True, "here": False}


def test_adapter_runs_here_not_ok_without_target_worktree(repo: Path) -> None:
    res = _adapter(repo, None)
    assert res["here"]["ok"] is False and res["here"]["reason"], res


def test_adapter_is_exclusive(repo: Path) -> None:
    assert _adapter(repo, repo)["exclusive"] is True


def test_adapter_execute_returns_exec_outcome_with_facts(repo: Path) -> None:
    res = _run(
        {
            "op": "flow",
            "requestCwd": str(repo),
            "approverCwd": str(repo),
            "values": _values(),
            "execute": True,
        }
    )
    x = res["execOutcome"]
    assert x["termination"] == "stopped" and x["body"]["outcome"] == "success", x
    assert x["body"]["facts"]["result_commit"] == _rev(repo, "HEAD")

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


def test_execute_does_not_clean_up_a_source_that_became_protected(repo: Path) -> None:
    """承認の後に設定が変わり、統合元が保護ブランチに入っても、後片付けで消さない (承認アダプター経由)。統合の結果は残す。"""
    values = _values(cleanup="branch")
    res = _run(
        {
            "op": "flow",
            "requestCwd": str(repo),
            "approverCwd": str(repo),
            "values": values,
            "execute": True,
            "protectAtExecute": values["source"],
        }
    )
    body = res["exec"]
    assert body["outcome"] == "success", body
    assert any("保護ブランチ" in r for r in body["remainingCleanup"]), body
    assert _git(repo, "branch", "--list", values["source"]).strip() != ""


def test_execute_cleans_up_a_normal_source(repo: Path) -> None:
    """対照: 保護されていない統合元は、従来どおり後片付けで消える。"""
    values = _values(cleanup="branch")
    res = _run(
        {
            "op": "flow",
            "requestCwd": str(repo),
            "approverCwd": str(repo),
            "values": values,
            "execute": True,
        }
    )
    assert res["exec"]["outcome"] == "success", res["exec"]
    assert _git(repo, "branch", "--list", values["source"]).strip() == ""


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


def _summary_of(repo: Path, message: str, **term: int) -> list[str]:
    # term: columns / rows (端末の大きさの注入)。省略は「幅・行数不明」 (従来の固定幅 46)
    res = _run(
        {
            "op": "flow",
            "requestCwd": str(repo),
            "approverCwd": str(repo),
            "values": _values(message=message),
            **term,
        }
    )
    assert res["capture"]["ok"] is True, res["capture"]
    return res["plan"]["summary"].split("\n")


def _cells(line: str) -> int:
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in line)


def _msg_block(lines: list[str]) -> list[str]:
    # 「メッセージ:」から、次の字下げでない行まで (メッセージとその続きの行。残り N 行の行も含む)
    i = next(k for k, ln in enumerate(lines) if ln.startswith("メッセージ:"))
    j = i + 1
    while j < len(lines) and (lines[j].startswith("  ") or lines[j].startswith("… 残り")):
        j += 1
    return lines[i:j]


BODY = "feat: x\n\n" + "\n".join(f"- item {n}" for n in range(1, 13))


def test_summary_shows_every_message_line_not_only_the_subject(repo: Path) -> None:
    # 承認するのは、保護ブランチへ入る内容そのもの (メッセージを含む)。予算内なら空行を除く全行を出す
    lines = _summary_of(repo, MSG)
    assert _msg_block(lines) == ["メッセージ: feat: x", "  body line"], lines
    assert not any("(+1 行)" in ln for ln in lines), (
        lines
    )  # 従来の (+N 行) は、最後の「残り N 行」に置き換わった


def test_summary_budget_is_8_lines_when_rows_unknown_and_marks_the_rest(repo: Path) -> None:
    blk = _msg_block(_summary_of(repo, BODY))
    # 予算 8 行 (メッセージ: の行を含む)。超えた分は最後の 1 行に記す (13 行中 8 行を見せ、残り 5)
    assert blk[:2] == ["メッセージ: feat: x", "  - item 1"], blk
    assert len(blk) == 9 and blk[-1] == "… 残り 5 行 (「全文を見る」で全文)", blk


def test_summary_budget_follows_rows(repo: Path) -> None:
    small = _summary_of(repo, BODY, columns=120, rows=20)
    big = _summary_of(repo, BODY, columns=120, rows=60)
    # rows=60 は上限 24 行。全部 (13 行) が入る。rows=20 は他の行を引いて下限 3 まで絞る
    assert not any(ln.startswith("… 残り") for ln in big) and len(_msg_block(big)) == 13, big
    blk = _msg_block(small)
    assert blk[-1].startswith("… 残り") and 3 <= len(blk) - 1 < 13, blk
    tiny = _msg_block(_summary_of(repo, BODY, columns=120, rows=5))
    assert len(tiny) == 4 and tiny[-1] == "… 残り 10 行 (「全文を見る」で全文)", tiny  # 下限 3


LONG = "feat: " + "abcdefghij " * 8 + "end"


def _subject_text(blk: list[str]) -> str:
    # ラベルと字下げを外してつなぐ (折り返しで文字を落とさないことの確認)
    return blk[0].removeprefix("メッセージ: ") + "".join(ln.removeprefix("  ") for ln in blk[1:])


def test_summary_wide_terminal_wraps_the_long_subject_without_clipping(repo: Path) -> None:
    narrow = _msg_block(_summary_of(repo, LONG))
    wide = _msg_block(_summary_of(repo, LONG, columns=120))
    assert wide == ["メッセージ: " + LONG], wide  # 幅 120 なら 1 行に全部入る
    assert len(narrow) == 3 and all(_cells(ln) <= 46 for ln in narrow), narrow
    assert _subject_text(narrow) == LONG, narrow  # 46 でも 3 行以内に収まる件名は全部見える
    assert narrow[1].startswith("  ") and narrow[2].startswith("  ")  # 2 スペースのぶら下がり


def test_summary_subject_is_shown_in_full_up_to_3_lines_even_with_a_tiny_budget(repo: Path) -> None:
    blk = _msg_block(_summary_of(repo, LONG + "\n" + BODY, rows=5))
    assert _subject_text(blk[:3]) == LONG, blk
    assert blk[-1].startswith("… 残り"), blk
    # 3 行を超える件名は、第 3 行を … で切る (「ほかにある」の印)
    huge = _msg_block(_summary_of(repo, "feat: " + "abcdefghij " * 40))
    assert len(huge) == 3 and huge[2].endswith("…") and all(_cells(ln) <= 46 for ln in huge), huge


def test_ref_names_with_display_control_characters_are_sanitized(repo: Path) -> None:
    """承認画面の統合元・統合先の ref 名に、双方向制御文字・C1 制御文字が生のまま出ない。計画の ref 自体は変えない。"""
    for bad, shown in ("\u202e", "\\u{202e}"), ("\u0085", "\\x85"):
        name = f"feature/a{bad}b"
        _git(repo, "branch", name, "feature/x")
        res = _run(
            {
                "op": "flow",
                "requestCwd": str(repo),
                "approverCwd": str(repo),
                "values": _values(source=name),
            }
        )
        assert res["capture"]["ok"] is True, res["capture"]
        assert res["capture"]["premise"]["source"] == f"refs/heads/{name}"
        for text in (res["plan"]["summary"], res["plan"]["view"]):
            assert bad not in text, text
            assert shown in text, text


def test_summary_message_is_sanitized_at_any_width(repo: Path) -> None:
    for term in ({}, {"columns": 120, "rows": 40}):
        lines = _summary_of(repo, "feat: \x1b[2Jx\n\n\x07body\x1b]0;t\x07", **term)
        text = "\n".join(lines)
        assert "\x1b" not in text and "\x07" not in text, lines
        assert "\\x1b[2Jx" in text and "body" in text, lines


def test_summary_single_line_message_is_one_line_without_a_remainder_mark(repo: Path) -> None:
    lines = _summary_of(repo, "feat: only")
    assert _msg_block(lines) == ["メッセージ: feat: only"], lines


def test_summary_every_line_fits_the_default_width_46_when_the_terminal_is_unknown(
    repo: Path,
) -> None:
    # 回帰: 幅不明は従来の 46 セル (全角は 2)
    lines = _summary_of(repo, "feat: " + "あ" * 60 + "\n\n- a\n- b")
    assert all(_cells(ln) <= 46 for ln in lines), lines
    assert _msg_block(lines)[-2:] == ["  - a", "  - b"], lines


def test_summary_other_lines_widen_with_the_terminal(repo: Path) -> None:
    path_rows = _summary_of(repo, "feat: x", columns=120)
    assert all(_cells(ln) <= 118 for ln in path_rows), path_rows


def test_summary_message_budget_is_capped_at_exactly_24_lines(repo: Path) -> None:
    # rows が十分大きくても、メッセージ部分は 24 行 (メッセージ: の行を含む) で止まる。非空 71 行のうち 47 行が残り
    msg = "feat: x\n\n" + "\n".join(f"- item {n}" for n in range(1, 71))
    blk = _msg_block(_summary_of(repo, msg, columns=120, rows=200))
    assert len(blk) == 24 + 1, blk
    assert (
        blk[0] == "メッセージ: feat: x" and blk[1] == "  - item 1" and blk[23] == "  - item 23"
    ), blk
    assert blk[-1] == "… 残り 47 行 (「全文を見る」で全文)", blk


def test_summary_body_width_is_capped_at_exactly_200_minus_2(repo: Path) -> None:
    # 幅 500 でも本文は 198 セル (200 - 2) まで。メッセージを 450 字にして、上限に届くようにする
    lines = _summary_of(repo, "feat: x\n\n" + "y" * 450, columns=500, rows=200)
    widths = [_cells(ln) for ln in lines]
    assert max(widths) == 198, widths


# --- cwd ごとの設定 (HEAD の .agents/config/pi.json)。保護は全体のまま ---

PI_JSON = ".agents/config/pi.json"
PROFILE_A = {"integrate": {"target": "production", "source_prefixes": ["feat/"]}}
PROFILE_B = {"integrate": {"target": "production", "source_prefixes": ["feat/", "fix/"]}}
PROFILE_C = {"integrate": {"target": "main", "source_prefixes": ["feat/"]}}
NOTE = "プロジェクト設定 (pi.json)"
LINE_A = f"{NOTE}: 統合先 production・統合元の接頭辞 feat/"


def _rules() -> dict:
    integ = {"enabled": True, "protected_refs": ["main", "develop", "production"]}
    return {"judge": {"common": {"pi": {"pending": {"enabled": True}, "integrate": integ}}}}


def _prun(payload: dict) -> dict:
    node = _node()
    if node is None:
        pytest.skip("node が無い (または古い)")
    out = subprocess.run(
        [node, str(DRIVER)],
        input=json.dumps({"rules": _rules(), **payload}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=120,
    )
    return json.loads(out.stdout)


def _put(repo: Path, obj: object | str, msg: str = "pi.json") -> None:
    _commit(repo, PI_JSON, obj if isinstance(obj, str) else json.dumps(obj), msg)


@pytest.fixture
def prof(repo: Path) -> Path:
    """develop の HEAD に pi.json (A)。production・main は develop と同じ位置。feat/y は production から。"""
    _put(repo, PROFILE_A, "pi A")
    _git(repo, "branch", "production")
    _git(repo, "branch", "main")
    for name, obj in (("cfgB", PROFILE_B), ("cfgC", PROFILE_C)):
        _git(repo, "checkout", "-q", "-b", name, "develop")
        _put(repo, obj, name)
    _git(repo, "checkout", "-q", "-b", "feat/y", "production")
    _commit(repo, "y.txt", "y\n")
    _git(repo, "checkout", "-q", "develop")
    return repo


def _pflow(repo: Path, **kw: object) -> dict:
    return _prun(
        {
            "op": "flow",
            "requestCwd": str(repo),
            "approverCwd": str(repo),
            "values": _values(source="feat/y"),
            **kw,
        }
    )


def test_profile_capture_uses_target_prefix_and_blob(prof: Path) -> None:
    res = _prun({"op": "capture", "cwd": str(prof), "values": _values(source="feat/y")})
    cap = res["capture"]
    assert cap["ok"] is True, cap
    p = cap["premise"]
    assert p["target"] == "refs/heads/production" and p["source"] == "refs/heads/feat/y"
    assert p["profileBlob"] == _git(prof, "rev-parse", f"HEAD:{PI_JSON}").strip()
    # 既定の接頭辞 (feature/) はこのリポジトリでは統合元にならない
    bad = _prun({"op": "capture", "cwd": str(prof), "values": _values()})["capture"]
    assert bad["ok"] is False and "bad_source" in bad["reason"], bad


def test_profile_overridden_is_shown(prof: Path) -> None:
    res = _pflow(prof)
    assert res["plan"]["summary"].count(NOTE) == 1 and "統合先 production" in res["plan"]["summary"]
    assert "feat/y → production (squash)" in res["plan"]["summary"]
    assert LINE_A in res["plan"]["view"], res["plan"]["view"]
    assert res["recheck"] == {"ok": True}


def test_without_pi_json_nothing_changes(repo: Path) -> None:
    res = _prun(
        {"op": "flow", "requestCwd": str(repo), "approverCwd": str(repo), "values": _values()}
    )
    assert (
        res["capture"]["ok"] is True and res["capture"]["premise"]["target"] == "refs/heads/develop"
    )
    assert res["capture"]["premise"]["profileBlob"] is None
    for key in ("summary", "view"):
        assert "pi.json" not in res["plan"][key], res["plan"][key]
    assert "要求時から変わった点" not in res["plan"]["summary"]
    assert res["recheck"] == {"ok": True}


def test_profile_that_equals_defaults_is_silent(repo: Path) -> None:
    _put(repo, {"integrate": {"target": "develop", "source_prefixes": ["feature/", "bugfix/"]}})
    res = _prun(
        {"op": "flow", "requestCwd": str(repo), "approverCwd": str(repo), "values": _values()}
    )
    assert res["capture"]["ok"] is True
    for key in ("summary", "view"):
        assert "pi.json" not in res["plan"][key], res["plan"][key]


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ('{"integrate": {"protected_refs": ["x"]}}', "protected_refs_not_allowed"),
        ('{"integrate": {"target": "staging"}}', "bad_target"),
        ('{"integrate": {"colour": 1}}', "unknown_key"),
        ("{not json", "invalid_json"),
    ],
)
def test_invalid_profile_falls_back_with_diagnostic(repo: Path, text: str, code: str) -> None:
    _put(repo, text)
    res = _prun(
        {"op": "flow", "requestCwd": str(repo), "approverCwd": str(repo), "values": _values()}
    )
    assert (
        res["capture"]["ok"] is True and res["capture"]["premise"]["target"] == "refs/heads/develop"
    )
    for key in ("summary", "view"):
        assert f"{NOTE} は無効" in res["plan"][key], res["plan"][key]
        assert f"({code})" in res["plan"][key] and "全体の既定で処理" in res["plan"][key]
    assert f"{NOTE} は無効 ({code})。全体の既定で処理" in res["plan"]["view"]


def test_invalid_profile_does_not_echo_content(repo: Path) -> None:
    secret = "SECRET-TOKEN-0123456789"
    _put(repo, '{"integrate": {"target": "' + secret + '", "' + secret + '": 1')
    res = _prun(
        {"op": "flow", "requestCwd": str(repo), "approverCwd": str(repo), "values": _values()}
    )
    assert secret not in json.dumps(res, ensure_ascii=False)
    assert "無効 (invalid_json)" in res["plan"]["view"]


def test_symlink_profile_is_invalid(repo: Path) -> None:
    link = repo / PI_JSON
    link.parent.mkdir(parents=True)
    link.symlink_to("../../a.txt")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "link")
    res = _prun(
        {"op": "flow", "requestCwd": str(repo), "approverCwd": str(repo), "values": _values()}
    )
    assert res["capture"]["ok"] is True
    assert "無効 (not_regular_file)" in res["plan"]["view"], res["plan"]["view"]


def test_uncommitted_profile_is_ignored(repo: Path) -> None:
    _write_pi = repo / PI_JSON
    _write_pi.parent.mkdir(parents=True)
    _write_pi.write_text(json.dumps(PROFILE_A), encoding="utf-8")
    res = _prun({"op": "capture", "cwd": str(repo), "values": _values()})
    p = res["capture"]["premise"]
    assert p["target"] == "refs/heads/develop" and p["profileBlob"] is None
    # 作業ツリーの A (feat/) は効かない: feat/y は統合元にならない
    _git(repo, "branch", "feat/y", "feature/x")
    bad = _prun({"op": "capture", "cwd": str(repo), "values": _values(source="feat/y")})["capture"]
    assert bad["ok"] is False and "bad_source" in bad["reason"], bad


def test_extra_protected_refs_in_profile_does_not_protect_or_unprotect(repo: Path) -> None:
    _put(repo, {"integrate": {"protected_refs": ["feature/*"]}})
    res = _prun({"op": "capture", "cwd": str(repo), "values": _values()})
    assert res["capture"]["ok"] is True, res["capture"]


def test_profile_change_between_request_and_approval(prof: Path) -> None:
    res = _pflow(prof, beforePlan=[["checkout", "-q", "cfgB"]])
    assert "プロジェクト設定 (pi.json) が要求時と違う" in res["plan"]["summary"]
    assert "プロジェクト設定 (pi.json) が要求時と違う" in res["plan"]["view"]
    assert "統合先が要求時と違う" not in res["plan"]["view"]


def test_target_change_between_request_and_approval(prof: Path) -> None:
    res = _pflow(prof, beforePlan=[["checkout", "-q", "cfgC"]])
    view = res["plan"]["view"]
    assert "統合先が要求時と違う (production→main)" in view, view
    assert "プロジェクト設定 (pi.json) が要求時と違う" in view


def test_recheck_fails_when_profile_blob_changes(prof: Path) -> None:
    res = _pflow(prof, beforeRecheck=[["checkout", "-q", "cfgB"]])
    assert res["recheck"]["ok"] is False, res["recheck"]
    assert "承認した後に" in res["recheck"]["reason"] and "設定" in res["recheck"]["reason"]


def test_recheck_fails_when_target_ref_changes(prof: Path) -> None:
    res = _pflow(prof, beforeRecheck=[["checkout", "-q", "cfgC"]])
    assert res["recheck"]["ok"] is False, res["recheck"]
    assert "承認した後に" in res["recheck"]["reason"] and "統合先" in res["recheck"]["reason"]


def test_old_record_without_profile_blob_shows_no_difference(repo: Path) -> None:
    res = _prun(
        {
            "op": "flow",
            "requestCwd": str(repo),
            "approverCwd": str(repo),
            "values": _values(),
            "dropPremise": ["profileBlob"],
        }
    )
    assert "要求時から変わった点" not in res["plan"]["summary"], res["plan"]["summary"]
    assert "要求時から変わった点: なし" in res["plan"]["view"]
    assert res["recheck"] == {"ok": True}

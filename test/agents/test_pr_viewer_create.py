"""PR ビューア 段 B1 の S（起票: 新しい feature の枝・worktree と依頼文 brief の記録）の試験。

使い捨てのリポジトリ（tmp_path。名前・メールは架空）で node のサーバを `--allow-create` つきで起動し、HTTP で確かめる。
契約: .tmp/keep/prv-app/api-contract-create.md。起票の権限の源は「ブラウザからの POST」だけで、ref・記録は権限として読まない。
反例（パス走査・既存の上書き・巻き戻し・中断の残り・秘密らしい文字列・入口の検査）を先に固定し、正規の POST が通る対照を置く。
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node
from test_pr_viewer_merge_api import no_leak, post
from test_pr_viewer_server import APP, Server, _commit, _git, _init, _pr_key, _web_dir

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

UUID1 = "11111111-1111-4111-8111-111111111111"
UUID2 = "22222222-2222-4222-8222-222222222222"


# ---------------------------------------------------------------- 道具


class W:
    base: Path
    repo: Path
    server: Server
    args: list[str]


def _args(w: W, *, create=True, merge=False, delay_ms=0, fail=None, extra=()) -> list[str]:
    a = [
        "--repo",
        str(w.repo),
        "--port",
        "0",
        "--web-dir",
        str(_web_dir(w.base)) if not (w.base / "web").exists() else str(w.base / "web"),
    ]
    a += ["--rules-file", str(w.base / "rules.json")]
    if create:
        a.append("--allow-create")
    if merge:
        a.append("--allow-merge")
    if delay_ms:
        a += ["--create-test-delay-ms", str(delay_ms)]
    if fail:
        a += ["--create-test-fail", fail]
    return [*a, *extra]


def _start(tmp: Path, *, gitignore=True, default="develop", **kw) -> W:
    w = W()
    w.base = tmp
    w.repo = _init(tmp / "example-app", default)
    _git(w.repo, "config", "user.name", "Example Dev")
    _git(w.repo, "config", "user.email", "you@example.com")
    _git(w.repo, "config", "gc.auto", "0")
    _git(w.repo, "config", "maintenance.auto", "false")
    files = {"README.md": "hello\n", "keep.txt": "keep\n"}
    if gitignore:
        files[".gitignore"] = ".tmp/\n"
    _commit(w.repo, files, "init")
    w.server = Server(_args(w, **kw))
    return w


@pytest.fixture
def make(tmp_path):
    made: list[W] = []

    def build(**kw) -> W:
        d = tmp_path / f"w{len(made)}"
        d.mkdir()
        world = _start(d, **kw)
        made.append(world)
        return world

    yield build
    for world in made:
        world.server.stop()


def restart(w: W, **kw) -> None:
    w.server.stop()
    w.server = Server(_args(w, **kw))


def target_oid(w: W) -> str:
    status, body = w.server.get("/api/repos")
    assert status == 200
    return body["repos"][0]["targetOid"]


def repo_id(w: W) -> str:
    status, body = w.server.get("/api/repos")
    assert status == 200
    return body["repos"][0]["repoId"]


def brief(**over) -> dict:
    b = {
        "title": "起票の試験",
        "goal": "新しい機能を作る。",
        "constraints": "公開できない内容は書かない。",
        "scope": ["apps/**"],
        "acceptance": "試験が通る。",
    }
    b.update(over)
    return b


def body_of(w: W, name="alpha", *, request_id=UUID1, expect=None, **over) -> dict:
    b = {
        "kind": "feature",
        "name": name,
        "requestId": request_id,
        "expect": {"target": expect or target_oid(w)},
        "brief": brief(),
    }
    b.update(over)
    return b


def create(w: W, body=None, **kw):
    return post(
        w, f"/api/repos/{repo_id(w)}/features", body if body is not None else body_of(w), **kw
    )


def snapshot(w: W) -> dict:
    return {
        "refs": _git(w.repo, "for-each-ref"),
        "worktrees": _git(w.repo, "worktree", "list", "--porcelain"),
        "status": _git(w.repo, "status", "--porcelain=v1", "--ignored"),
        "head": _git(w.repo, "rev-parse", "HEAD"),
    }


def wt_path(w: W, name="alpha") -> Path:
    return w.repo / ".tmp" / "worktrees" / name


def wait_for(pred, timeout=30.0, step=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return False


def post_async(w: W, body=None):
    out: dict = {}

    def run():
        try:
            out["r"] = create(w, body)
        except Exception as e:  # 接続が切れた試験で使う
            out["e"] = e

    t = threading.Thread(target=run)
    t.start()
    return t, out


def stop_and_stderr(w: W) -> str:
    proc = w.server.proc
    proc.terminate()
    proc.wait(15)
    text = proc.stderr.read()
    proc.stdout.close()
    proc.stderr.close()
    return text


def review_ref(name: str) -> str:
    return f"refs/pi/review/{_pr_key(f'feature/{name}')}"


def has_ref(w: W, ref: str) -> bool:
    return _git(w.repo, "rev-parse", "--verify", "--quiet", ref, check=False).strip() != ""


def events_of(w: W, name: str) -> list[dict]:
    text = _git(w.repo, "show", f"{review_ref(name)}:events.jsonl")
    return [json.loads(line) for line in text.splitlines()]


# ---------------------------------------------------------------- 入口（旗・Origin・Funnel・形）


def test_create_is_disabled_without_the_flag_even_with_a_forged_record(make):
    w = make(create=False)
    # ref に偽の brief の記録があっても、権限として読まない（正規の POST の対照は別の試験）
    _git(w.repo, "update-ref", review_ref("alpha"), _git(w.repo, "rev-parse", "HEAD").strip())
    before = snapshot(w)
    status, body = create(w)
    assert (status, body["error"]["code"]) == (403, "create_disabled")
    assert snapshot(w) == before
    status, caps = w.server.get("/api/capabilities")
    assert caps["create"] is False and caps["merge"] is False


def test_capabilities_and_repos_expose_create_and_target_oid(make):
    w = make()
    status, caps = w.server.get("/api/capabilities")
    assert status == 200 and caps == {"merge": False, "create": True, "targets": ["develop"]}
    status, repos = w.server.get("/api/repos")
    assert repos["repos"][0]["targetOid"] == _git(w.repo, "rev-parse", "develop").strip()


@pytest.mark.parametrize(
    ("kw", "status", "code"),
    [
        ({"origin": None}, 403, "forbidden_origin"),
        ({"origin": "null"}, 403, "forbidden_origin"),
        ({"origin": "http://evil.example"}, 403, "forbidden_origin"),
        ({"headers": {"Tailscale-Funnel-Request": "?1"}}, 403, "forbidden_funnel"),
        ({"headers": {"X-PRV": None}}, 400, "bad_request"),
        ({"headers": {"Content-Type": "text/plain"}}, 400, "bad_request"),
    ],
)
def test_entry_checks_refuse_before_anything_is_created(make, kw, status, code):
    w = make()
    before = snapshot(w)
    got, body = create(w, **kw)
    assert (got, body["error"]["code"]) == (status, code)
    assert snapshot(w) == before


def test_oversized_and_malformed_bodies_are_refused(make):
    w = make()
    before = snapshot(w)
    big = body_of(w)
    big["brief"]["goal"] = "x" * 70_000
    assert create(w, big)[0] == 413
    assert create(w, raw=b"not json")[1]["error"]["code"] == "bad_json"
    assert snapshot(w) == before


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"extra": 1}, "bad_request"),
        ({"kind": "bugfix"}, "bad_kind"),
        ({"kind": None}, "bad_kind"),
        ({"requestId": "not-a-uuid"}, "bad_request_id"),
        ({"requestId": "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"}, "bad_request_id"),
        ({"expect": {"target": "abc"}}, "bad_expect"),
        ({"expect": {"target": "a" * 40, "x": 1}}, "bad_expect"),
        ({"expect": "x"}, "bad_expect"),
    ],
)
def test_body_shape_is_checked(make, over, code):
    w = make()
    before = snapshot(w)
    status, body = create(w, body_of(w, **over))
    assert (status, body["error"]["code"]) == (400, code)
    assert snapshot(w) == before


def test_unknown_repo_is_404(make):
    w = make()
    assert post(w, "/api/repos/r00000000/features", body_of(w))[0] == 404
    assert post(w, "/api/repos/xyz/features", body_of(w))[0] == 404


def test_stale_develop_is_409_and_creates_nothing(make):
    w = make()
    old = target_oid(w)
    _commit(w.repo, {"later.txt": "x\n"}, "feat: later")
    before = snapshot(w)
    status, body = create(w, body_of(w, expect=old))
    assert (status, body["error"]["code"]) == (409, "stale_view")
    assert snapshot(w) == before


# ---------------------------------------------------------------- 名前


@pytest.mark.parametrize(
    "name",
    [
        "../x",
        "a/b",
        "a\\b",
        "..",
        ".x",
        "x.lock",
        "x.git",
        "x.",
        "con",
        "nul",
        "com1",
        "lpt9",
        "con.txt",
        "a" * 65,
        "",
        "a\x00b",
        "ABC",
        "ｆｏｏ",
        "-x",
        "a b",
        123,
        None,
    ],
)
def test_bad_names_are_400_and_nothing_leaves_the_root(make, name):
    w = make()
    guard = w.base / "guard.txt"
    guard.write_text("g", encoding="utf-8")
    before = snapshot(w)
    status, body = create(w, body_of(w, name=name))
    assert (status, body["error"]["code"]) == (400, "bad_name")
    assert snapshot(w) == before
    assert guard.read_text(encoding="utf-8") == "g"
    assert sorted(p.name for p in w.base.iterdir()) == sorted(
        ["example-app", "guard.txt", "web", "outside.js"]
    )


def test_max_length_name_is_accepted(make):
    w = make()
    name = "a" + "b" * 63
    status, body = create(w, body_of(w, name=name))
    assert status == 201, body
    assert wt_path(w, name).is_dir()


# ---------------------------------------------------------------- 正常


def test_create_makes_branch_worktree_and_record(make):
    w = make(merge=True)
    develop = target_oid(w)
    status, body = create(w)
    assert status == 201, body
    f = body["feature"]
    key = _pr_key("feature/alpha")
    assert f["branch"] == "feature/alpha" and f["prKey"] == key and f["id"] == f"{repo_id(w)}/{key}"
    assert f["base"] == {"branch": "develop", "oid": develop}
    assert f["worktree"] == {"name": "alpha", "rel": ".tmp/worktrees/alpha"}
    assert (
        f["brief"]["rev"] == 1
        and re.fullmatch(r"[0-9a-f]{64}", f["brief"]["digest"])
        and f["brief"]["bytes"] > 0
    )
    assert f["recorded"] is True and f["replay"] is False and f["warnings"] == []
    # 枝・worktree・記録
    assert _git(w.repo, "rev-parse", "feature/alpha").strip() == develop
    listing = _git(w.repo, "worktree", "list", "--porcelain")
    assert str(wt_path(w).resolve()) in listing and "branch refs/heads/feature/alpha" in listing
    assert _git(wt_path(w), "status", "--porcelain=v1", "--ignored") == ""
    meta = json.loads(_git(w.repo, "show", f"{review_ref('alpha')}:meta.json"))
    assert meta["schema"] == 2 and meta["branch"] == "feature/alpha" and meta["target"] == "develop"
    events = events_of(w, "alpha")
    assert [e["t"] for e in events] == ["brief"]
    assert (
        events[0]["by"] == "app"
        and events[0]["d"]["via"] == "viewer"
        and events[0]["d"]["requestId"] == UUID1
    )
    assert events[0]["vs"] == {"source": develop, "target": develop, "base": develop}
    # GET …/review に brief
    status, rev = w.server.get(f"/api/prs/{f['id']}/review")
    assert (
        status == 200
        and rev["brief"]["title"] == "起票の試験"
        and rev["brief"]["digest"] == f["brief"]["digest"]
    )
    assert (
        rev["brief"]["bytes"] == f["brief"]["bytes"]
        and rev["brief"]["rev"] == 1
        and rev["brief"]["scope"] == ["apps/**"]
    )
    # 一覧と詳細に state: empty、統合は計画の段階で成り立たない
    status, prs = w.server.get("/api/prs")
    assert [p["state"] for p in prs["prs"] if p["branch"] == "feature/alpha"] == ["empty"]
    status, detail = w.server.get(f"/api/prs/{f['id']}")
    assert detail["pr"]["state"] == "empty"
    status, plan = post(w, f"/api/prs/{f['id']}/merge-plan", {})
    assert status == 200 and plan["mergeable"] is False


def test_empty_becomes_merged_after_work_is_fast_forwarded(make):
    w = make()
    status, _body = create(w)
    assert status == 201
    _commit(wt_path(w), {"work.txt": "w\n"}, "feat: work")
    _git(w.repo, "merge", "--ff-only", "feature/alpha")
    status, prs = w.server.get("/api/prs")
    # 0 コミットの PR でも、起票時の基点から進んだものは「統合済み」のまま
    assert [p["state"] for p in prs["prs"] if p["branch"] == "feature/alpha"] == ["merged"]


def test_boundary_sizes_are_accepted(make):
    w = make()
    b = brief(
        title="題" * 100, goal="目" * 1500, constraints="条" * 1500, acceptance="完" * 800, scope=[]
    )
    # 合計 3900。scope 1 件 100 字で、ちょうど 4000
    b["scope"] = ["s" * 100]
    status, body = create(w, body_of(w, brief=b))
    assert status == 201, body
    assert body["feature"]["brief"]["bytes"] <= 15000


def test_fields_are_stored_as_given_including_newlines_and_japanese(make):
    w = make()
    b = brief(goal="一行目\r\n二行目\t字下げ", scope=["docs/**", "apps/pr-viewer/*.ts"])
    status, body = create(w, body_of(w, brief=b))
    assert status == 201, body
    d = events_of(w, "alpha")[0]["d"]
    assert d["goal"] == "一行目\n二行目\t字下げ" and d["scope"] == [
        "docs/**",
        "apps/pr-viewer/*.ts",
    ]


# ---------------------------------------------------------------- 既存を上書きしない


def test_existing_branch_is_name_used_and_untouched(make):
    w = make()
    _git(w.repo, "branch", "feature/alpha")
    before = snapshot(w)
    status, body = create(w)
    assert (status, body["error"]["code"]) == (409, "name_used")
    assert snapshot(w) == before


def test_directory_file_conflicts_are_name_used(make):
    w = make()
    _git(w.repo, "branch", "feature")  # 枝 feature があると feature/<名> は作れない（D/F）
    before = snapshot(w)
    assert create(w, body_of(w, name="beta"))[1]["error"]["code"] == "name_used"
    assert snapshot(w) == before
    _git(w.repo, "branch", "-D", "feature")
    _git(w.repo, "branch", "feature/gamma/inner")  # 名前が既存の枝の親になる（D/F の逆）
    before = snapshot(w)
    assert create(w, body_of(w, name="gamma"))[1]["error"]["code"] == "name_used"
    assert snapshot(w) == before


def test_existing_directory_is_name_used_and_keeps_its_contents(make):
    w = make()
    d = wt_path(w)
    d.mkdir(parents=True)
    (d / "mine.txt").write_text("mine", encoding="utf-8")
    before = snapshot(w)
    status, body = create(w)
    assert (status, body["error"]["code"]) == (409, "name_used")
    assert (d / "mine.txt").read_text(encoding="utf-8") == "mine"
    assert snapshot(w) == before
    assert not has_ref(w, "refs/heads/feature/alpha")


def test_existing_review_record_is_name_used(make):
    w = make()
    _git(w.repo, "update-ref", review_ref("alpha"), _git(w.repo, "rev-parse", "HEAD").strip())
    before = snapshot(w)
    status, body = create(w)
    assert (status, body["error"]["code"]) == (409, "name_used")
    assert snapshot(w) == before


def test_registered_but_missing_worktree_is_refused(make):
    w = make()
    path = wt_path(w)
    path.parent.mkdir(parents=True)
    _git(w.repo, "worktree", "add", "--detach", str(path))
    subprocess.run(["rm", "-rf", str(path)], check=True)  # 登録だけが残る（prunable）
    before = snapshot(w)
    status, body = create(w)
    assert (status, body["error"]["code"]) == (409, "worktree_registered")
    assert snapshot(w) == before


# ---------------------------------------------------------------- 配置・設定の検査


def test_unsupported_repo_without_develop(make):
    w = make(default="main")
    before = snapshot(w)
    status, body = create(w, body_of(w))
    assert (status, body["error"]["code"]) == (409, "unsupported_repo")
    assert snapshot(w) == before


def test_not_ignored_tmp_is_bad_layout(make):
    w = make(gitignore=False)
    before = snapshot(w)
    status, body = create(w)
    assert (status, body["error"]["code"]) == (409, "bad_layout")
    assert snapshot(w) == before
    assert not (w.repo / ".tmp").exists()


def test_symlinked_tmp_is_bad_layout(make):
    w = make()
    outside = w.base / "elsewhere"
    outside.mkdir()
    (w.repo / ".tmp").symlink_to(outside)
    before = snapshot(w)
    status, body = create(w)
    assert (status, body["error"]["code"]) == (409, "bad_layout")
    assert snapshot(w) == before
    assert list(outside.iterdir()) == []


def test_gitflow_worktree_path_mismatch_is_bad_layout(make):
    w = make()
    (w.repo / ".gitflow").write_text(
        "[gitflow]\n\tworktreePath = ../elsewhere/{{ branchName }}\n", encoding="utf-8"
    )
    before = snapshot(w)
    status, body = create(w)
    assert (status, body["error"]["code"]) == (409, "bad_layout")
    assert snapshot(w) == before


def test_gitflow_with_the_fixed_worktree_path_is_accepted(make):
    w = make()
    (w.repo / ".gitflow").write_text(
        "[gitflow]\n\tworktreePath = .tmp/worktrees/{{ branchName }}\n", encoding="utf-8"
    )
    assert create(w)[0] == 201


def test_external_code_config_is_refused(make):
    w = make()
    _git(w.repo, "config", "merge.evil.driver", "touch pwned %A")
    before = snapshot(w)
    status, body = create(w)
    assert (status, body["error"]["code"]) == (409, "external_code")
    assert snapshot(w) == before


# ---------------------------------------------------------------- 巻き戻し・記録の順序


def test_add_failure_rolls_the_branch_back(make):
    w = make(fail="add")
    before = snapshot(w)
    status, body = create(w)
    assert (status, body["error"]["code"]) == (500, "create_failed")
    assert snapshot(w) == before
    assert not has_ref(w, "refs/heads/feature/alpha")


def test_record_failure_rolls_branch_and_worktree_back(make):
    w = make(fail="record")
    before = snapshot(w)
    status, body = create(w)
    assert (status, body["error"]["code"]) == (500, "create_failed")
    assert not has_ref(w, "refs/heads/feature/alpha") and not has_ref(w, review_ref("alpha"))
    assert not wt_path(w).exists()
    assert snapshot(w) == before
    # 巻き戻した後は、同じ名前で作り直せる
    restart(w)
    assert create(w)[0] == 201


def test_record_is_not_written_before_the_worktree_is_verified(make):
    w = make(delay_ms=2500)
    t, out = post_async(w)
    assert wait_for(lambda: (wt_path(w) / ".git").exists())
    time.sleep(0.3)
    # 枝と worktree はできているが、記録はまだ無い（記録を先に書かない）
    assert has_ref(w, "refs/heads/feature/alpha")
    assert not has_ref(w, review_ref("alpha"))
    t.join(30)
    assert out["r"][0] == 201
    assert has_ref(w, review_ref("alpha"))


def test_dirty_worktree_blocks_rollback_and_reports_partial(make):
    w = make(delay_ms=2500, fail="record")
    t, out = post_async(w)
    assert wait_for(lambda: (wt_path(w) / ".git").exists())
    time.sleep(0.4)
    (wt_path(w) / "mine.txt").write_text(
        "作業中", encoding="utf-8"
    )  # 巻き戻しの前に作業ツリーを汚す
    t.join(30)
    status, body = out["r"]
    assert (status, body["error"]["code"]) == (500, "create_partial")
    assert "worktree" in body["error"]["message"] and "branch" in body["error"]["message"]
    no_leak(w, body)
    # 何も消さない
    assert (wt_path(w) / "mine.txt").read_text(encoding="utf-8") == "作業中"
    assert has_ref(w, "refs/heads/feature/alpha") and not has_ref(w, review_ref("alpha"))


def test_sigkill_midway_leaves_branch_and_worktree_without_record(make):
    w = make(delay_ms=8000)
    t, out = post_async(w)
    assert wait_for(lambda: (wt_path(w) / ".git").exists())
    time.sleep(0.5)
    w.server.proc.kill()  # SIGKILL 相当の中断
    t.join(30)
    assert "r" not in out or out["r"][0] != 201
    assert (
        has_ref(w, "refs/heads/feature/alpha")
        and wt_path(w).is_dir()
        and not has_ref(w, review_ref("alpha"))
    )
    # 自動では直さない。再起票は name_used で断られる
    w.server.stop()
    w.server = Server(_args(w))
    before = snapshot(w)
    status, body = create(w)
    assert (status, body["error"]["code"]) == (409, "name_used")
    assert snapshot(w) == before


def test_sigterm_waits_for_the_running_create(make):
    w = make(delay_ms=1500)
    t, out = post_async(w)
    assert wait_for(lambda: (wt_path(w) / ".git").exists())
    time.sleep(0.3)
    w.server.proc.terminate()
    t.join(30)
    assert out["r"][0] == 201, out
    assert w.server.proc.wait(20) == 0
    assert has_ref(w, review_ref("alpha"))


def test_second_create_while_one_runs_is_busy(make):
    w = make(delay_ms=1500)
    t, out = post_async(w)
    assert wait_for(lambda: (wt_path(w) / ".git").exists())
    status, body = create(w, body_of(w, name="beta", request_id=UUID2))
    assert (status, body["error"]["code"]) == (409, "busy")
    assert not has_ref(w, "refs/heads/feature/beta")
    t.join(30)
    assert out["r"][0] == 201


# ---------------------------------------------------------------- 冪等


def test_same_request_id_replays_without_creating_again(make):
    w = make()
    first = create(w)
    assert first[0] == 201
    refs = _git(w.repo, "for-each-ref")
    status, again = create(w)
    assert (
        status == 200
        and again["feature"]["replay"] is True
        and again["feature"]["recorded"] is True
    )
    for k in ("branch", "prKey", "id", "base", "worktree", "brief"):
        assert again["feature"][k] == first[1]["feature"][k]
    assert _git(w.repo, "for-each-ref") == refs
    assert len(events_of(w, "alpha")) == 1


def test_replay_survives_a_moved_develop_and_a_restart(make):
    w = make()
    first = create(w)
    _commit(w.repo, {"later.txt": "x\n"}, "feat: later")
    restart(w)
    status, again = create(w, body_of(w, expect=first[1]["feature"]["base"]["oid"]))
    assert status == 200 and again["feature"]["replay"] is True
    assert again["feature"]["base"] == first[1]["feature"]["base"]


def test_different_request_id_or_different_brief_is_name_used(make):
    w = make()
    assert create(w)[0] == 201
    status, body = create(w, body_of(w, request_id=UUID2))
    assert (status, body["error"]["code"]) == (409, "name_used")
    other = body_of(w)
    other["brief"]["goal"] = "別の目的"
    status, body = create(w, other)
    assert (status, body["error"]["code"]) == (409, "name_used")
    assert len(events_of(w, "alpha")) == 1


# ---------------------------------------------------------------- brief の検査


def _secrets() -> dict[str, str]:
    # 試験の文字列自体が秘密検出に当たらないよう、実行時に組み立てる
    return {
        "private_key": "-----BEGIN " + "RSA PRIVATE KEY-----",
        "aws_key": "AK" + "IA" + "ABCDEFGHIJKLMNOP",
        "github_token": "gh" + "p_" + "a" * 36,
        "slack_token": "xo" + "xb-" + "1234567890-abcdefghij",
        "bearer": "Bear" + "er " + "abcdefghijklmnop1234",
        "jwt": "ey" + "J" + "abcdefgh.abcdefgh.abcdefgh",
        "url_userinfo": "https://user:" + "hunter2" + "@example.com/x",
        "password": "pass" + "word=" + "hunter2x",
    }


@pytest.mark.parametrize("kind", list(_secrets()))
@pytest.mark.parametrize("field", ["goal", "title", "constraints", "acceptance", "scope"])
def test_secret_like_strings_are_refused_by_kind_only(make, kind, field):
    w = make()
    secret = _secrets()[kind]
    b = brief()
    b[field] = [secret] if field == "scope" else f"前置き {secret} 後置き"
    if field == "title":
        b[field] = secret
    before = snapshot(w)
    status, body = create(w, body_of(w, brief=b))
    assert (status, body["error"]["code"]) == (400, "secret_like")
    assert kind in body["error"]["message"]
    assert secret not in json.dumps(body, ensure_ascii=False) and "hunter2" not in json.dumps(body)
    assert snapshot(w) == before


def test_ordinary_prose_is_not_secret_like(make):
    w = make()
    b = brief(goal="password の扱いを docs に書く。Bearer 認証は対象外。token の説明も書く。")
    assert create(w, body_of(w, brief=b))[0] == 201


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"title": "t" * 101}, "brief_too_large"),
        ({"goal": "g" * 1501}, "brief_too_large"),
        ({"constraints": "c" * 1501}, "brief_too_large"),
        ({"acceptance": "a" * 801}, "brief_too_large"),
        ({"scope": ["s"] * 21}, "brief_too_large"),
        ({"scope": ["s" * 121]}, "brief_too_large"),
        (
            {
                "goal": "g" * 1500,
                "constraints": "c" * 1500,
                "acceptance": "a" * 800,
                "title": "t" * 100,
                "scope": ["s" * 101],
            },
            "brief_too_large",
        ),
        (
            {
                "goal": "😀" * 1500,
                "constraints": "😀" * 1500,
                "acceptance": "😀" * 800,
                "title": "😀" * 100,
            },
            "brief_too_large",
        ),
        ({"title": ""}, "bad_brief"),
        ({"goal": "   "}, "bad_brief"),
        ({"title": None}, "bad_brief"),
        ({"goal": 5}, "bad_brief"),
        ({"scope": "apps/**"}, "bad_brief"),
        ({"scope": [1]}, "bad_brief"),
        ({"scope": [""]}, "bad_brief"),
        ({"scope": ["/etc/passwd"]}, "bad_brief"),
        ({"scope": ["../x"]}, "bad_brief"),
        ({"scope": ["a/../x"]}, "bad_brief"),
        ({"scope": ["C:\\x"]}, "bad_brief"),
        ({"scope": ["a\nb"]}, "bad_brief"),
        ({"title": "a\nb"}, "bad_brief"),
        ({"goal": "a\x07b"}, "bad_brief"),
        ({"goal": "a\x00b"}, "bad_brief"),
        ({"goal": "a\x1bb"}, "bad_brief"),
        ({"goal": "a\u202eb"}, "bad_brief"),
        ({"goal": "a\u2066b"}, "bad_brief"),
        ({"goal": "a\u200fb"}, "bad_brief"),
        ({"goal": "a\u2028b"}, "bad_brief"),
        ({"goal": "a\x85b"}, "bad_brief"),
        ({"unknown": "x"}, "bad_brief"),
    ],
)
def test_brief_limits_and_characters(make, over, code):
    w = make()
    b = brief()
    b.update(over)
    before = snapshot(w)
    status, body = create(w, body_of(w, brief=b))
    assert (status, body["error"]["code"]) == (400, code)
    assert snapshot(w) == before


def test_lone_surrogates_are_refused(make):
    w = make()
    before = snapshot(w)
    for bad in ('"\\ud800"', '"x\\udc00y"', '"a\\ud83d"'):
        raw = json.dumps(body_of(w)).replace(json.dumps(brief()["goal"]), bad).encode("utf-8")
        status, body = create(w, raw=raw)
        assert (status, body["error"]["code"]) == (400, "bad_brief")
    # 対のサロゲートは 1 字として受け付ける
    ok = (
        json.dumps(body_of(w))
        .replace(json.dumps(brief()["goal"]), '"\\ud83d\\ude00"')
        .encode("utf-8")
    )
    assert create(w, raw=ok)[0] == 201
    assert snapshot(w) != before


def test_brief_missing_is_bad_brief(make):
    w = make()
    body = body_of(w)
    del body["brief"]
    assert create(w, body)[1]["error"]["code"] == "bad_brief"
    body["brief"] = []
    assert create(w, body)[1]["error"]["code"] == "bad_brief"


# ---------------------------------------------------------------- 応答・診断の漏えい


def test_responses_and_diagnostics_do_not_leak_paths_or_text(make):
    w = make()
    marker = "秘匿されるべき本文ABC"
    b = brief(goal=f"目的 {marker}")
    outs = [
        create(w, body_of(w, brief=b)),
        create(w, body_of(w, brief=b)),  # replay
        create(w, body_of(w, request_id=UUID2, brief=b)),  # name_used
        create(w, body_of(w, name="../x", brief=b)),
        create(w, body_of(w, name="beta", brief=brief(goal=_secrets()["github_token"]))),
    ]
    stderr = stop_and_stderr(w)
    no_leak(w, *[o[1] for o in outs], stderr)
    assert marker not in stderr and marker not in "".join(
        json.dumps(o[1], ensure_ascii=False) for o in outs[1:]
    )
    lines = [json.loads(line) for line in stderr.splitlines() if line.startswith("{")]
    creates = [ln for ln in lines if ln.get("t") == "create"]
    assert [c["result"] for c in creates][:3] == ["ok", "replay", "name_used"]
    assert all(set(c) == {"t", "req", "repo", "pr", "result", "recorded"} for c in creates)


# ---------------------------------------------------------------- 既存の経路が壊れない


def test_existing_comments_submit_and_merge_still_work(make):
    w = make(merge=True)
    _git(w.repo, "switch", "-q", "-c", "feature/a", "develop")
    _commit(w.repo, {"a.txt": "a\n"}, "feat: a")
    _git(w.repo, "switch", "-q", "develop")
    status, prs = w.server.get("/api/prs")
    pr = next(p for p in prs["prs"] if p["branch"] == "feature/a")
    assert pr["state"] == "open"
    status, c = post(w, f"/api/prs/{pr['id']}/comments", {"body": "確認"}, origin=None)
    assert status == 201, c
    status, s = post(w, f"/api/prs/{pr['id']}/submit", {"kind": "comment"})
    assert status == 201, s
    status, m = post(
        w,
        f"/api/prs/{pr['id']}/merge",
        {
            "expect": {"source": pr["sourceOid"], "target": pr["targetOid"]},
            "message": "feat: a を統合する\n",
            "cleanup": "none",
        },
    )
    assert status == 200 and m["merge"]["recorded"] is True
    # merge 系は --allow-merge が無いと断る（旗は分かれている）
    w2 = make(create=True, merge=False)
    assert post(w2, f"/api/prs/{pr['id']}/merge-plan", {})[1]["error"]["code"] == "merge_disabled"


def test_create_does_not_enable_merge_and_merge_flag_does_not_enable_create(make):
    w = make(create=False, merge=True)
    assert create(w)[1]["error"]["code"] == "create_disabled"
    w2 = make(create=True, merge=False)
    _status, caps = w2.server.get("/api/capabilities")
    assert caps["merge"] is False and caps["create"] is True


# ---------------------------------------------------------------- brief-cli（読み取り専用）


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_node(), str(APP / "brief-cli.ts"), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )


def test_brief_cli_show_reads_without_writing(make):
    w = make()
    assert create(w)[0] == 201
    before = snapshot(w)
    p = _cli("show", str(w.repo), "feature/alpha")
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert (
        out["ok"] is True
        and out["branch"] == "feature/alpha"
        and out["brief"]["goal"] == "新しい機能を作る。"
    )
    assert out["brief"]["scope"] == ["apps/**"] and re.fullmatch(
        r"[0-9a-f]{64}", out["brief"]["digest"]
    )
    # worktree の root からも読める
    p2 = _cli("show", str(wt_path(w)), "feature/alpha")
    assert p2.returncode == 0 and json.loads(p2.stdout)["brief"]["title"] == "起票の試験"
    assert snapshot(w) == before


@pytest.mark.parametrize(
    "args",
    [
        ["show"],
        ["show", ".", "main"],
        ["show", ".", "feature/../x"],
        ["show", ".", "feature/a", "extra"],
        ["write", ".", "feature/a"],
        ["show", "--repo", "feature/a"],
    ],
)
def test_brief_cli_bad_input_is_exit_2(make, args):
    p = _cli(*args)
    assert p.returncode == 2
    assert json.loads(p.stdout)["ok"] is False


def test_brief_cli_without_record_is_exit_2(make):
    w = make()
    _git(w.repo, "branch", "feature/plain")
    p = _cli("show", str(w.repo), "feature/plain")
    assert p.returncode == 2 and json.loads(p.stdout)["code"] == "no_brief"
    assert str(w.repo) not in p.stdout


# ---------------------------------------------------------------- import 境界（静的）


def _imports(path: Path) -> list[str]:
    return re.findall(r'^import .*? from "([^"]+)"', path.read_text(encoding="utf-8"), flags=re.M)


def test_import_boundaries():
    api = APP / "feature-api.ts"
    create_ts = APP / "feature-create.ts"
    api_src = api.read_text(encoding="utf-8")
    create_src = create_ts.read_text(encoding="utf-8")
    # feature-api は git を直接動かさない
    assert "child_process" not in api_src and "runGit" not in api_src and "spawn" not in api_src
    assert "merge-git" not in "".join(_imports(api))
    # feature-create は merge-git の runGit を使い、新しい実行器・job 系・pis を持たない
    assert "./merge-git.ts" in _imports(create_ts)
    assert "child_process" not in create_src and "spawn(" not in create_src
    for banned in ("job", "pis", "executor", "worker"):
        assert not any(banned in i for i in _imports(create_ts)), banned
    # harness から import してよいのは review-log.ts と review-git.ts だけ
    for src in APP.glob("*.ts"):
        for imp in _imports(src):
            if "harness/" in imp:
                assert imp.rsplit("/", 1)[-1] in ("review-log.ts", "review-git.ts"), (src.name, imp)

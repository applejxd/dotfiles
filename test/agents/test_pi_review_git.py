"""review-git.ts (PR レビュー状態を git の ref に保存する入出力) の試験。

ダミーのリポジトリを tmp_path に作り、node の型除去で `.ts` を直接読む。名前・メールは架空。
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "home" / "dot_config" / "pi" / "harness"

PRELUDE = f"""
import * as L from {json.dumps((HARNESS / "review-log.ts").as_uri())};
import * as G from {json.dumps((HARNESS / "review-git.ts").as_uri())};
import {{ spawn }} from "node:child_process";
import {{ randomUUID }} from "node:crypto";

const cwd = process.argv[2];
const arg = JSON.parse(process.argv[3] || "null");
const out = (x) => process.stdout.write(JSON.stringify(x));
const env = {{ ...process.env, GIT_CONFIG_GLOBAL: "/dev/null", GIT_CONFIG_NOSYSTEM: "1" }};
const git = (argv, opts = {{}}) =>
	new Promise((resolve) => {{
		const p = spawn("git", argv, {{ cwd, env }});
		let so = "", se = "";
		p.stdout.on("data", (d) => (so += d));
		p.stderr.on("data", (d) => (se += d));
		p.on("close", (code) => resolve({{ code, stdout: so, stderr: se }}));
		p.stdin.on("error", () => {{}});
		p.stdin.end(opts.input ?? "");
	}});
const O = (c) => c.repeat(40);
const VS = {{ source: O("a"), target: O("b"), base: O("c") }};
const meta = (branch = "feature/x") => ({{
	schema: 1, pr: L.prKeyOf(branch), branch, target: "develop", createdAt: "2026-01-01T00:00:00Z",
}});
const ev = (t, d, o = {{}}) => ({{
	v: 1, id: o.id ?? randomUUID(), t, by: o.by ?? "pi", at: "2026-01-01T00:00:00Z", vs: o.vs ?? VS, d,
}});
const cm = (body = "x", o = {{}}) => {{
	const id = o.id ?? randomUUID();
	return ev("comment", {{ thread: o.thread ?? id, anchor: null, body }}, {{ ...o, id }});
}};
const KEY = L.prKeyOf("feature/x");
const add = (events, vsOpt) => G.appendEvents(git, KEY, meta(), () => events, vsOpt);
"""


def _node() -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    out = subprocess.run(
        [node, "--version"], capture_output=True, text=True, encoding="utf-8", check=False
    ).stdout
    match = re.match(r"v(\d+)\.(\d+)", out.strip())
    if not match:
        return None
    return node if (int(match.group(1)), int(match.group(2))) >= (22, 18) else None


pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

GENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test User",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test User",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def g(repo, *args, input=None):
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        input=input,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=GENV,
        check=False,
    )
    assert proc.returncode == 0, (args, proc.stderr)
    return proc.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    g(r, "init", "-q", "-b", "main")
    (r / "f.txt").write_text("1\n", encoding="utf-8")
    g(r, "add", ".")
    g(r, "commit", "-q", "-m", "c1")
    return r


@pytest.fixture
def js(tmp_path):
    n = [0]

    def _js(repo, body, arg=None, wait=True):
        n[0] += 1
        script = tmp_path / f"t{n[0]}.mjs"
        script.write_text(
            PRELUDE
            + "\n(async () => {\n"
            + body
            + "\n})().catch((e) => { console.error(e); process.exit(1); });\n",
            encoding="utf-8",
        )
        cmd = [_node(), str(script), str(repo), json.dumps(arg)]
        if not wait:
            return subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8"
            )
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False
        )
        assert proc.returncode == 0, proc.stderr[-3000:]
        return json.loads(proc.stdout)

    return _js


def key(branch="feature/x"):
    import hashlib

    return "p" + hashlib.sha256(f"v1\0refs/heads/{branch}".encode()).hexdigest()[:16]


def refs(repo):
    return g(repo, "for-each-ref", "--format=%(refname) %(objectname)")


def head_oid(repo):
    return g(repo, "rev-parse", "HEAD")


# ─── 往復 ───────────────────────────────────────────────────────────


def test_roundtrip_append_then_read(repo, js):
    r = js(
        repo,
        """
        const none = await G.readPr(git, KEY);
        const a = await add([cm("one")]);
        const b = await add([cm("two")]);
        const got = await G.readPr(git, KEY);
        out({ none, a, b, kind: got.kind, bodies: got.events.map((e) => e.d.body), meta: got.meta, keys: await G.listPrKeys(git) });
        """,
    )
    assert r["none"] == {"kind": "none"}
    assert r["a"]["ok"] is True and r["b"]["ok"] is True
    assert r["kind"] == "ok" and r["bodies"] == ["one", "two"]
    assert r["meta"]["branch"] == "feature/x" and r["keys"] == [key()]
    # tree は 2 つの通常 blob だけ・メッセージと識別子の固定
    ref = f"refs/pi/review/{key()}"
    assert g(repo, "ls-tree", ref).count("100644 blob") == 2
    assert (
        g(repo, "log", "-1", "--format=%s|%an|%ae", ref)
        == "pr-review: comment|pr-review|pr-review@localhost"
    )
    assert len(g(repo, "rev-list", ref).splitlines()) == 2


def test_ref_of_rejects_bad_key(repo, js):
    r = js(
        repo,
        'let e = null; try { G.refOf("../heads/main"); } catch (x) { e = String(x); } out({ e, ok: G.refOf(KEY) });',
    )
    assert r["e"] and r["ok"] == f"refs/pi/review/{key()}"


def test_build_receives_fresh_state_and_null_changes_nothing(repo, js):
    r = js(
        repo,
        """
        await add([cm("one")]);
        const before = (await git(["for-each-ref"])).stdout;
        let seen = -1;
        const n = await G.appendEvents(git, KEY, null, (s) => { seen = s.count; return null; });
        const e = await G.appendEvents(git, KEY, null, () => []);
        const r = await G.appendEvents(git, KEY, null, () => ({ refuse: "nope" }));
        const after = (await git(["for-each-ref"])).stdout;
        out({ seen, n, e, r, same: before === after });
        """,
    )
    assert r["seen"] == 1 and r["same"] is True
    assert r["n"] == {"ok": True, "noop": True} and r["e"] == {"ok": True, "noop": True}
    assert r["r"] == {"ok": False, "refused": "nope"}


def test_new_pr_without_meta_is_refused(repo, js):
    r = js(repo, "out(await G.appendEvents(git, KEY, null, () => [cm()]));")
    assert r == {"ok": False, "refused": "not_found"}
    assert g(repo, "for-each-ref", "refs/pi/") == ""


def test_invalid_event_from_build_is_refused(repo, js):
    r = js(
        repo,
        """
        const bad = ev("receipt", { batchId: randomUUID(), sessionId: "s" });
        out(await add([bad]));
        """,
    )
    assert r == {"ok": False, "refused": "invalid_event"}
    assert g(repo, "for-each-ref", "refs/pi/") == ""


def test_limits_are_enforced_on_append(repo, js):
    r = js(
        repo,
        """
        const big = await add([cm("x".repeat(16384))]);
        await add([cm("seed")]);
        const stale = await G.appendEvents(git, KEY, null, () => [cm("y")]);
        out({ big, stale });
        """,
    )
    assert r["big"] == {"ok": False, "refused": "body_too_large"}
    assert r["stale"]["ok"] is True


def test_too_many_prs_is_refused(repo, js):
    # 200 本の ref を直接作る → 201 本目の作成を断る
    blob = g(repo, "hash-object", "-w", "--stdin", input="x")
    tree = g(repo, "mktree", input=f"100644 blob {blob}\tmeta.json\n")
    commit = g(repo, "commit-tree", tree, "-m", "dummy")
    update = "".join(f"create refs/pi/review/p{i:016x} {commit}\n" for i in range(200))
    g(repo, "update-ref", "--stdin", input=update)
    r = js(repo, "out(await add([cm()]));")
    assert r == {"ok": False, "refused": "too_many_prs"}


# ─── CAS の競合 ─────────────────────────────────────────────────────


def test_cas_conflict_retries_and_keeps_both(repo, js):
    r = js(
        repo,
        """
        await add([cm("base")]);
        let injected = false;
        let calls = 0;
        const racing = async (argv, opts) => {
			if (argv[0] === "update-ref" && !injected) {
				injected = true;
				await add([cm("intruder")]); // 最初の update-ref の直前に別の追記を割り込ませる
			}
			return git(argv, opts);
		};
        const res = await G.appendEvents(racing, KEY, meta(), () => { calls++; return [cm("mine")]; });
        const got = await G.readPr(git, KEY);
        out({ res, calls, bodies: got.events.map((e) => e.d.body) });
        """,
    )
    assert r["res"]["ok"] is True and r["calls"] == 2
    assert r["bodies"] == ["base", "intruder", "mine"]


def test_cas_precondition_is_reevaluated_after_conflict(repo, js):
    # receipt は「その batch の receipt がまだ無いこと」を build が毎回確かめる → 競合後は追記しない
    r = js(
        repo,
        """
        const sub = ev("submit", { batchId: randomUUID(), kind: "comment", items: [], dest: { worktreeId: "w1" } });
        await add([sub]);
        const bid = sub.d.batchId;
        const rc = () => ev("receipt", { batchId: bid, sessionId: "s" });
        const build = (s) => (s.batches.find((b) => b.batchId === bid).received ? null : [rc()]);
        let injected = false;
        const racing = async (argv, opts) => {
            if (argv[0] === "update-ref" && !injected) { injected = true; await G.appendEvents(git, KEY, null, build); }
            return git(argv, opts);
        };
        const res = await G.appendEvents(racing, KEY, null, build);
        const got = await G.readPr(git, KEY);
        out({ res, types: got.events.map((e) => e.t) });
        """,
    )
    assert r["res"] == {"ok": True, "noop": True}
    assert r["types"] == ["submit", "receipt"]


def test_cas_exhausted_after_eight_attempts(repo, js):
    r = js(
        repo,
        """
        await add([cm("base")]);
        let attempts = 0;
        const racing = async (argv, opts) => {
            if (argv[0] === "update-ref") { attempts++; await add([cm("intruder")]); }
            return git(argv, opts);
        };
        const res = await G.appendEvents(racing, KEY, meta(), () => [cm("mine")], { jitterMs: 1 });
        const got = await G.readPr(git, KEY);
        out({ res, attempts, bodies: got.events.map((e) => e.d.body) });
        """,
    )
    assert r["res"] == {"ok": False, "error": "cas_exhausted"}
    assert r["attempts"] == 8
    assert "mine" not in r["bodies"] and len(r["bodies"]) == 9


def test_four_processes_append_forty_events_without_loss(repo, js):
    body = """
        const w = arg;
        for (let i = 0; i < 10; i++) {
            const id = randomUUID();
            const ev1 = cm(`w${w}-${i}`, { id });
            for (;;) {
                const r = await G.appendEvents(git, KEY, meta(), () => [ev1], { jitterMs: 20 });
                if (r.ok) break;
                if (r.error !== "cas_exhausted") throw new Error(JSON.stringify(r));
            }
        }
        out({ done: w });
    """
    procs = [js(repo, body, arg=w, wait=False) for w in range(4)]
    for p in procs:
        _, stderr = p.communicate(timeout=300)
        assert p.returncode == 0, stderr[-2000:]
    r = js(
        repo,
        "const got = await G.readPr(git, KEY); out({ kind: got.kind, bodies: got.events.map((e) => e.d.body) });",
    )
    assert r["kind"] == "ok"
    assert len(r["bodies"]) == 40 and len(set(r["bodies"])) == 40
    assert set(r["bodies"]) == {f"w{w}-{i}" for w in range(4) for i in range(10)}
    # 各プロセスの中の順序は保たれる
    for w in range(4):
        mine = [b for b in r["bodies"] if b.startswith(f"w{w}-")]
        assert mine == [f"w{w}-{i}" for i in range(10)]


# ─── 自己検査 ───────────────────────────────────────────────────────


def _plant(repo, entries, meta=None, events=None):
    """任意の tree の commit を refs/pi/review/<key> に置く。entries: [(mode, type, content or oid, name)]"""
    lines = ""
    for mode, typ, content, name in entries:
        oid = content if typ == "commit" else g(repo, "hash-object", "-w", "--stdin", input=content)
        lines += f"{mode} {typ} {oid}\t{name}\n"
    tree = g(repo, "mktree", input=lines)
    commit = g(repo, "commit-tree", tree, "-m", "planted")
    g(repo, "update-ref", f"refs/pi/review/{key()}", commit)
    return commit


def _good_meta(**kw):
    m = {
        "schema": 1,
        "pr": key(),
        "branch": "feature/x",
        "target": "develop",
        "createdAt": "2026-01-01T00:00:00Z",
    }
    return json.dumps({**m, **kw})


def _read(repo, js):
    return js(repo, "out(await G.readPr(git, KEY));")


def test_selfcheck_accepts_planted_valid_commit(repo, js):
    _plant(
        repo,
        [("100644", "blob", _good_meta(), "meta.json"), ("100644", "blob", "", "events.jsonl")],
    )
    assert _read(repo, js)["kind"] == "ok"


@pytest.mark.parametrize(
    ("name", "entries"),
    [
        (
            "extra_file",
            lambda: [
                ("100644", "blob", _good_meta(), "meta.json"),
                ("100644", "blob", "", "events.jsonl"),
                ("100644", "blob", "x", "evil"),
            ],
        ),
        ("missing_events", lambda: [("100644", "blob", _good_meta(), "meta.json")]),
        (
            "symlink",
            lambda: [
                ("100644", "blob", _good_meta(), "meta.json"),
                ("120000", "blob", "meta.json", "events.jsonl"),
            ],
        ),
        (
            "exec_bit",
            lambda: [
                ("100644", "blob", _good_meta(), "meta.json"),
                ("100755", "blob", "", "events.jsonl"),
            ],
        ),
        (
            "huge_events",
            lambda: [
                ("100644", "blob", _good_meta(), "meta.json"),
                ("100644", "blob", "x" * 524289, "events.jsonl"),
            ],
        ),
        (
            "huge_meta",
            lambda: [
                ("100644", "blob", _good_meta(branch="x" * 5000), "meta.json"),
                ("100644", "blob", "", "events.jsonl"),
            ],
        ),
        (
            "bad_json_events",
            lambda: [
                ("100644", "blob", _good_meta(), "meta.json"),
                ("100644", "blob", "{oops\n", "events.jsonl"),
            ],
        ),
        (
            "bad_json_meta",
            lambda: [
                ("100644", "blob", "{oops", "meta.json"),
                ("100644", "blob", "", "events.jsonl"),
            ],
        ),
        (
            "key_mismatch",
            lambda: [
                ("100644", "blob", _good_meta(branch="feature/other"), "meta.json"),
                ("100644", "blob", "", "events.jsonl"),
            ],
        ),
        (
            "pr_mismatch",
            lambda: [
                ("100644", "blob", _good_meta(pr="p0000000000000000"), "meta.json"),
                ("100644", "blob", "", "events.jsonl"),
            ],
        ),
    ],
)
def test_selfcheck_rejects_and_append_is_refused(repo, js, name, entries):
    commit = _plant(repo, entries())
    r = js(repo, "out({ read: await G.readPr(git, KEY), app: await add([cm()]) });")
    assert r["read"]["kind"] == "bad", (name, r)
    assert r["app"] == {"ok": False, "refused": "bad"}
    # 修復はしない: ref は planted のまま
    assert g(repo, "rev-parse", f"refs/pi/review/{key()}") == commit


def test_selfcheck_rejects_submodule_entry(repo, js):
    sub = "a" * 40
    _plant(
        repo,
        [("100644", "blob", _good_meta(), "meta.json"), ("160000", "commit", sub, "events.jsonl")],
    )
    assert _read(repo, js)["kind"] == "bad"


def test_selfcheck_rejects_invalid_event_log(repo, js):
    bad = json.dumps({"v": 1, "id": "x", "t": "comment"}) + "\n"
    _plant(
        repo,
        [("100644", "blob", _good_meta(), "meta.json"), ("100644", "blob", bad, "events.jsonl")],
    )
    r = _read(repo, js)
    assert r["kind"] == "bad" and "bad_id" in r["reason"]


def test_newer_schema_is_readonly_and_refuses_append(repo, js):
    commit = _plant(
        repo,
        [
            ("100644", "blob", _good_meta(schema=2), "meta.json"),
            ("100644", "blob", '{"future": true}\n', "events.jsonl"),
        ],
    )
    r = js(repo, "out({ read: await G.readPr(git, KEY), app: await add([cm()]) });")
    assert r["read"]["kind"] == "readonly" and r["read"]["meta"]["schema"] == 2
    assert r["app"] == {"ok": False, "refused": "readonly"}
    assert g(repo, "rev-parse", f"refs/pi/review/{key()}") == commit


# ─── 統合済み ───────────────────────────────────────────────────────


def test_merged_pr_refuses_further_appends(repo, js):
    r = js(
        repo,
        """
        const rq = ev("merge_request", {
            requestId: randomUUID(), sourceRef: "refs/heads/feature/x", sourceOid: O("a"),
            targetRef: "refs/heads/develop", targetOid: O("b"), baseOid: O("c"), message: "m", cleanup: "branch_and_worktree",
        });
        const res = ev("merge_result", { requestId: rq.d.requestId, outcome: "success" });
        await add([rq]);
        const failed = await G.appendEvents(git, KEY, null, () => [ev("merge_result", { requestId: rq.d.requestId, outcome: "failed" })]);
        const before = (await git(["rev-parse", "refs/pi/review/" + KEY])).stdout;
        const ok = await add([res]);
        const mid = (await git(["rev-parse", "refs/pi/review/" + KEY])).stdout;
        const after1 = await add([cm("late")]);
        const after2 = await G.appendEvents(git, KEY, null, () => null);
        const end = (await git(["rev-parse", "refs/pi/review/" + KEY])).stdout;
        out({ failed, ok, after1, after2, same: mid === end });
        """,
    )
    assert r["failed"]["ok"] is True  # success 以外の結果は、統合済みにしない
    assert r["ok"]["ok"] is True
    assert r["after1"] == {"ok": False, "refused": "merged"}
    assert r["after2"] == {"ok": False, "refused": "merged"}
    assert r["same"] is True


# ─── 到達可能性・書き込み範囲 ───────────────────────────────────────


def test_old_source_stays_reachable_after_gc(repo, js):
    g(repo, "checkout", "-q", "-b", "feature/x")
    (repo / "f.txt").write_text("2\n", encoding="utf-8")
    g(repo, "commit", "-q", "-am", "feat 1")
    old = head_oid(repo)
    (repo / "f.txt").write_text("3\n", encoding="utf-8")
    g(repo, "commit", "-q", "-am", "feat 2")
    new = head_oid(repo)
    g(repo, "checkout", "-q", "main")
    # source = 旧 feature の先頭 → 同じ source で追記 → 新しい source (実在する commit) で追記
    r = js(
        repo,
        """
        const vsOld = { source: arg.old, target: O("b"), base: O("c") };
        const vsNew = { source: arg.new, target: O("b"), base: O("c") };
        const a = await add([cm("first", { vs: vsOld })]);
        const same = await add([cm("same source", { vs: vsOld })]);
        const b = await add([cm("second", { vs: vsNew })]);
        const parents = (await git(["rev-list", "--parents", "-n", "1", "refs/pi/review/" + KEY])).stdout.trim().split(" ");
        out({ a, same, b, parents });
        """,
        arg={"old": old, "new": new},
    )
    assert r["a"]["ok"] and r["same"]["ok"] and r["b"]["ok"]
    # 記録した source は、その時点の commit の追加の親になる (最初の記録と、source が変わったとき)
    assert old in g(repo, "rev-list", "--parents", "-n", "1", r["a"]["commit"]).split()
    assert len(r["parents"]) == 3 and r["parents"][2] == new
    # source が変わらない追記は、親が直前の ref だけ
    assert len(g(repo, "rev-list", "--parents", "-n", "1", r["same"]["commit"]).split()) == 2
    # ブランチを消して gc しても、どちらの source の commit も読める
    g(repo, "branch", "-D", "feature/x")
    g(repo, "reflog", "expire", "--expire=now", "--all")
    g(repo, "gc", "-q", "--prune=now")
    assert g(repo, "cat-file", "-t", old) == "commit"
    assert g(repo, "cat-file", "-t", new) == "commit"
    assert g(repo, "show", f"{old}:f.txt") == "2"


def test_a_single_recorded_source_stays_reachable_after_gc(repo, js):
    """追記が 1 回だけ (source が変わらない) でも、その source を保持する。branch を消して gc しても読める。"""
    g(repo, "checkout", "-q", "-b", "feature/x")
    (repo / "f.txt").write_text("2\n", encoding="utf-8")
    g(repo, "commit", "-q", "-am", "feat 1")
    src = head_oid(repo)
    g(repo, "checkout", "-q", "main")
    r = js(
        repo,
        """
        const vs = { source: arg.src, target: O("b"), base: O("c") };
        out(await add([cm("only", { vs })]));
        """,
        arg={"src": src},
    )
    assert r["ok"] is True
    g(repo, "branch", "-D", "feature/x")
    g(repo, "reflog", "expire", "--expire=now", "--all")
    g(repo, "gc", "-q", "--prune=now")
    assert g(repo, "cat-file", "-t", src) == "commit", "最後に記録した source が gc で消えた"
    assert g(repo, "show", f"{src}:f.txt") == "2"


def test_a_symbolic_review_ref_never_moves_another_branch(repo, js):
    """review ref を symbolic ref に差し替えても、書き込みは参照先の branch を動かさない。"""
    main_before = g(repo, "rev-parse", "refs/heads/main")
    g(repo, "symbolic-ref", f"refs/pi/review/{key()}", "refs/heads/main")
    r = js(repo, "out(await add([cm('x')]));")
    assert r["ok"] is False  # 自己検査に落ちる (tree が違う) ので書かない
    assert g(repo, "rev-parse", "refs/heads/main") == main_before
    assert head_oid(repo) == main_before


def test_writes_only_under_refs_pi_review(repo, js):
    g(repo, "branch", "other")
    g(repo, "tag", "v1")
    before = [line for line in refs(repo).splitlines() if not line.startswith("refs/pi/review/")]
    js(
        repo,
        """
        await add([cm("a")]);
        await add([cm("b", { vs: { source: O("e"), target: O("b"), base: O("c") } })]);
        await G.appendEvents(git, KEY, null, () => [cm("c")]);
        out(1);
        """,
    )
    now = refs(repo).splitlines()
    assert [line for line in now if not line.startswith("refs/pi/review/")] == before
    assert [line.split()[0] for line in now if line.startswith("refs/pi/review/")] == [
        f"refs/pi/review/{key()}"
    ]
    assert g(repo, "symbolic-ref", "HEAD") == "refs/heads/main"


def test_every_update_ref_targets_review_namespace(repo, js):
    r = js(
        repo,
        """
        const seen = [];
        const spy = async (argv, opts) => { if (argv[0] === "update-ref") seen.push(argv); return git(argv, opts); };
        await G.appendEvents(spy, KEY, meta(), () => [cm("a")]);
        await G.appendEvents(spy, KEY, null, () => [cm("b")]);
        out(seen);
        """,
    )
    assert len(r) == 2
    for argv in r:
        assert (
            argv[:2] == ["update-ref", "--no-deref"]
            and argv[2] == f"refs/pi/review/{key()}"
            and len(argv) == 5
        )
    assert r[0][4] == "0" * 40 and r[1][4] != "0" * 40  # 新規は旧 = 0、2 回目は現在の OID


# ─── 巨大な blob を読まない・新しい PR の meta の検証 ─────────────────────────


@pytest.mark.parametrize("which", ["events", "meta"])
def test_selfcheck_refuses_oversized_blobs_before_reading_them(repo, js, which):
    """巨大な blob は、読む前にサイズで断る (cat-file blob を呼ばない)。検査を外すと、読んでから別の理由で断ることになる。"""
    if which == "events":
        name = "events.jsonl"
        entries = [
            ("100644", "blob", _good_meta(), "meta.json"),
            ("100644", "blob", "x" * 524289, "events.jsonl"),
        ]
    else:
        name = "meta.json"
        entries = [
            ("100644", "blob", _good_meta(branch="x" * 5000), "meta.json"),
            ("100644", "blob", "", "events.jsonl"),
        ]
    _plant(repo, entries)
    big = g(repo, "rev-parse", f"refs/pi/review/{key()}:{name}")
    r = js(
        repo,
        """
        const calls = [];
        const rec = (argv, opts) => { calls.push(argv.join(" ")); return git(argv, opts); };
        const res = await G.readPr(rec, KEY);
        out({ kind: res.kind, readBig: calls.some((c) => c === "cat-file blob " + arg) });
        """,
        arg=big,
    )
    assert r == {"kind": "bad", "readBig": False}


@pytest.mark.parametrize("what", ["pr", "branch", "schema"])
def test_meta_for_a_new_pr_is_validated(repo, js, what):
    r = js(
        repo,
        """
        const m = meta();
        if (arg === "pr") m.pr = "p" + "0".repeat(16);
        if (arg === "branch") m.branch = "feature/other";
        if (arg === "schema") m.schema = 2;
        out(await G.appendEvents(git, KEY, m, () => [cm()]));
        """,
        arg=what,
    )
    assert r == {"ok": False, "refused": "bad_meta"}
    assert g(repo, "for-each-ref", "refs/pi/") == ""

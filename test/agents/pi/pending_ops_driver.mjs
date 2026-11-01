// 非同期承認の保存層 (pending-ops.ts) を、使い捨ての git リポジトリで直接動かして固定する。結果を JSON で標準出力へ出す (照合は test_pi_pending_ops.py)。
//
//   node test/agents/pi/pending_ops_driver.mjs
//
// 競合の試験のため、自分自身を子プロセスとして起動する (--child <操作> <JSON>)。
// see docs/change/0055-async-approval.md
import { execFile, execFileSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const H = resolve(ROOT, "home", "dot_config", "pi", "harness");
const ops = await import(pathToFileURL(resolve(H, "pending-ops.ts")).href);
const store = await import(pathToFileURL(resolve(H, "pending-store.ts")).href);

const ENV = { ...process.env, GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@example.test", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@example.test" };
const git = (cwd, ...args) => execFileSync("git", args, { cwd, env: ENV, encoding: "utf8", input: undefined }).trim();
const gitIn = (cwd, input, ...args) => execFileSync("git", args, { cwd, env: ENV, encoding: "utf8", input }).trim();
const gitOk = (cwd, ...args) => {
	try {
		return git(cwd, ...args);
	} catch {
		return null;
	}
};

const input = (over = {}) => ({
	action: "git_integrate",
	params: { source: "feature/x", message: "メッセージ" },
	premise: { targetOid: "a".repeat(40), files: [1, 2, 3] },
	reason: "timeout",
	request: { id: "req-1", sessionId: "s1", cwd: "/w" },
	createdAt: new Date().toISOString(),
	...over,
});
const owner = (over = {}) => ({ sessionId: "s", runtimeEpoch: "e", pid: process.pid, processStart: "100", host: "h", ...over });

// ---- 子プロセス (競合の試験用) ----
if (process.argv[2] === "--child") {
	const [, , , op, json] = process.argv;
	const a = JSON.parse(json);
	let r;
	if (op === "save") r = ops.saveOp(a.cwd, a.input);
	else if (op === "begin") r = ops.beginApproval(a.cwd, a.id, a.oid, a.owner);
	console.log(JSON.stringify(r));
	process.exit(0);
}

const child = (op, args) =>
	new Promise((res) => {
		execFile(process.execPath, [fileURLToPath(import.meta.url), "--child", op, JSON.stringify(args)], { env: ENV, encoding: "utf8" }, (err, stdout) => {
			res(err ? { crash: String(err.message).slice(0, 200) } : JSON.parse(stdout));
		});
	});

function repo() {
	const dir = mkdtempSync(join(tmpdir(), "pi-ops-"));
	git(dir, "init", "-q", "-b", "main");
	writeFileSync(join(dir, "seed.txt"), "seed\n");
	git(dir, "add", "-A");
	git(dir, "commit", "-q", "-m", "seed");
	return dir;
}
const refs = (cwd, ns = "refs/pi/") => git(cwd, "for-each-ref", "--format=%(refname)", ns).split("\n").filter(Boolean);
const snapshot = (cwd) => ({ head: git(cwd, "rev-parse", "HEAD"), heads: git(cwd, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads"), status: git(cwd, "status", "--porcelain"), index: git(cwd, "ls-files", "-s") });

/** 記録の commit を手で作って、ref に置く (偽造の試験) */
function forge(cwd, id, { files, trailers, parent } = {}) {
	const entries = (files ?? [["record.json", "{}"]])
		.map(([name, text]) => `100644 blob ${gitIn(cwd, text, "hash-object", "-w", "--stdin")}\t${name}`)
		.join("\n");
	const tree = gitIn(cwd, `${entries}\n`, "mktree");
	const msg = `forged\n\n${trailers ?? `Pi-Pending-Kind: action\nPi-Pending-Id: ${id}\nPi-Pending-Request: req-1`}\n`;
	const oid = gitIn(cwd, msg, "commit-tree", tree, ...(parent ? ["-p", parent] : []), "-F", "-");
	git(cwd, "update-ref", `refs/pi/pending/${id}`, oid);
	return oid;
}
const goodRecordText = (over = {}) => {
	const base = { schema: 1, action: "git_integrate", params: { a: "b" }, premise: { x: 1 }, reason: "timeout", request: { id: "req-1", sessionId: "s", cwd: "/w" }, createdAt: new Date().toISOString(), ...over };
	return JSON.stringify({ ...base, digest: over.digest ?? ops.computeDigest(base) });
};

const out = {};
const DAYS = 86400 * 1000;

// 1. 保存・読み出し・一覧・不変性
{
	const cwd = repo();
	const before = snapshot(cwd);
	const r = ops.saveOp(cwd, input());
	const read = ops.readOp(cwd, r.id);
	out.roundtrip = {
		saved: { ok: r.ok, duplicate: r.duplicate, idShape: /^\d{15}$/.test(r.id), ref: r.ref === `refs/pi/pending/${r.id}` },
		readOk: read.ok,
		sameParams: read.ok && JSON.stringify(read.record.params) === JSON.stringify(input().params),
		kind: ops.classifyCommit(cwd, r.oid),
		listed: ops.listOps(cwd).entries.map((e) => ({ state: e.state, kind: e.kind, id: e.id === r.id })),
		count: ops.countPending(cwd),
		keyRefs: refs(cwd, "refs/pi/key/").length,
		untouched: JSON.stringify(snapshot(cwd)) === JSON.stringify(before),
		trailerId: gitOk(cwd, "log", "-1", "--format=%(trailers:key=Pi-Pending-Id,valueonly)", r.oid)?.trim() === r.id,
	};
}

// 2. 偽造・不正な記録を信頼しない
{
	const cwd = repo();
	const cases = {};
	const tryRead = (id) => {
		const r = ops.readOp(cwd, id);
		return { ok: r.ok, reason: r.ok ? "" : r.reason };
	};
	forge(cwd, "000000000000001", { files: [["record.json", goodRecordText()]] });
	cases.baseline = tryRead("000000000000001");
	forge(cwd, "000000000000002", { files: [["record.json", "これは JSON ではない"]] });
	cases.not_json = tryRead("000000000000002");
	forge(cwd, "000000000000003", { files: [["record.json", goodRecordText({ extra: true })]] });
	cases.unknown_key = tryRead("000000000000003");
	forge(cwd, "000000000000004", { files: [["record.json", goodRecordText({ params: { a: 1 } })]] });
	cases.params_not_string = tryRead("000000000000004");
	forge(cwd, "000000000000005", { files: [["record.json", goodRecordText({ digest: "0".repeat(64) })]] });
	cases.digest_mismatch = tryRead("000000000000005");
	forge(cwd, "000000000000006", { files: [["record.json", goodRecordText({ schema: 2 })]] });
	cases.schema_2 = tryRead("000000000000006");
	forge(cwd, "000000000000007", { files: [["record.json", goodRecordText()], ["other.txt", "x"]] });
	cases.extra_file = tryRead("000000000000007");
	forge(cwd, "000000000000008", { files: [["note.json", goodRecordText()]] });
	cases.wrong_file_name = tryRead("000000000000008");
	forge(cwd, "000000000000009", { files: [["record.json", goodRecordText()]], trailers: "Pi-Pending-Id: 000000000000009\nPi-Pending-Request: req-1" });
	cases.no_kind_trailer = tryRead("000000000000009");
	forge(cwd, "000000000000010", { files: [["record.json", goodRecordText()]], trailers: "Pi-Pending-Kind: action\nPi-Pending-Id: 000000000000099\nPi-Pending-Request: req-1" });
	cases.id_mismatch = tryRead("000000000000010");
	forge(cwd, "000000000000011", { files: [["record.json", goodRecordText()]], trailers: "Pi-Pending-Kind: action\nPi-Pending-Id: 000000000000011\nPi-Pending-Request: other" });
	cases.request_mismatch = tryRead("000000000000011");
	forge(cwd, "000000000000012", { files: [["record.json", goodRecordText({ params: { a: "x".repeat(300) } })]] });
	cases.too_large = (() => {
		const r = ops.readOp(cwd, "000000000000012", { ...ops.DEFAULT_LIMITS, maxRecordBytes: 200 });
		return { ok: r.ok, reason: r.ok ? "" : r.reason };
	})();
	// symbolic ref (main を指す)。読めない。main は動かない
	const mainBefore = git(cwd, "rev-parse", "refs/heads/main");
	git(cwd, "symbolic-ref", "refs/pi/pending/000000000000013", "refs/heads/main");
	cases.symbolic_ref = tryRead("000000000000013");
	cases.main_unchanged = git(cwd, "rev-parse", "refs/heads/main") === mainBefore;
	cases.bad_id = tryRead("../../heads/main");
	out.forged = cases;
}

// 3. 種類の判別 (旧形式・新形式・不正な形式)
{
	const cwd = repo();
	const legacyTree = gitIn(cwd, `100644 blob ${gitIn(cwd, "x\n", "hash-object", "-w", "--stdin")}\ta.txt\n100644 blob ${gitIn(cwd, "y\n", "hash-object", "-w", "--stdin")}\tb.txt\n`, "mktree");
	const legacy = gitIn(cwd, "legacy\n\nPi-Pending-Request: r\nPi-Pending-Branch: refs/heads/main\nPi-Pending-Head: (none)\n", "commit-tree", legacyTree, "-F", "-");
	const legacyLie = gitIn(cwd, "legacy\n\nPi-Pending-Kind: action\nPi-Pending-Id: 000000000000001\n", "commit-tree", legacyTree, "-F", "-");
	const recOnlyNoTrailer = forge(cwd, "000000000000002", { files: [["record.json", goodRecordText()]], trailers: "Pi-Pending-Request: r" });
	const action = ops.saveOp(cwd, input()).oid;
	out.classify = { legacy: ops.classifyCommit(cwd, legacy), legacy_claiming_action: ops.classifyCommit(cwd, legacyLie), record_json_without_trailer: ops.classifyCommit(cwd, recOnlyNoTrailer), action: ops.classifyCommit(cwd, action), missing_object: ops.classifyCommit(cwd, "1".repeat(40)) };
	// 旧形式の片付けは、旧形式だけに適用する (古い時刻の名前でも、新形式・不正な形式は消さない)
	const old = ops.saveOp(cwd, input({ params: { source: "feature/old", message: "m" } }), ops.DEFAULT_LIMITS, 1);
	git(cwd, "update-ref", "refs/pi/pending/000000000000003", legacy);
	const dropped = store.reconcilePending(cwd, { now: Date.now() + 40 * DAYS });
	out.legacy_reconcile = { droppedRefs: dropped, newFormatKept: refs(cwd, "refs/pi/pending/").includes(old.ref), invalidKept: refs(cwd, "refs/pi/pending/").includes("refs/pi/pending/000000000000002"), legacyDropped: dropped.includes("refs/pi/pending/000000000000003") };
}

// 4. 重複の抑止
{
	const cwd = repo();
	const a = ops.saveOp(cwd, input());
	const b = ops.saveOp(cwd, input({ request: { id: "req-2", sessionId: "s2", cwd: "/other" }, createdAt: new Date(Date.now() + 1000).toISOString() }));
	const c = ops.saveOp(cwd, input({ params: { source: "feature/y", message: "メッセージ" } }));
	const wt = ops.saveOp(cwd, input({ worktree: "/wt1" }));
	// 決着 (success) したら、同じ要求を新しく作れる。supersedes に前の id が残る
	const begun = ops.beginApproval(cwd, a.id, a.oid, owner());
	const started = ops.markStarted(cwd, a.id, begun.attemptOid);
	ops.finishApproval(cwd, a.id, started.attemptOid, { outcome: "success", phase: "done", confirmedEffects: ["統合した"], remainingCleanup: [], evidence: [] });
	const d = ops.saveOp(cwd, input());
	const dRead = ops.readOp(cwd, d.id);
	// unknown (executor) の間は、同じ要求を作らせない。人が決着させたら作れる
	const begun2 = ops.beginApproval(cwd, d.id, d.oid, owner());
	const started2 = ops.markStarted(cwd, d.id, begun2.attemptOid);
	ops.finishApproval(cwd, d.id, started2.attemptOid, { outcome: "unknown", phase: "started", confirmedEffects: [], remainingCleanup: [], evidence: ["応答が途切れた"] });
	const e = ops.saveOp(cwd, input());
	const resolved = ops.resolveUnknown(cwd, d.id, { kind: "success", evidence: ["確認した"] });
	const f = ops.saveOp(cwd, input());
	out.dedupe = {
		second_is_duplicate: b.ok && b.duplicate && b.id === a.id,
		different_params_new: c.ok && !c.duplicate && c.id !== a.id,
		worktree_is_part_of_key: wt.ok && !wt.duplicate,
		after_done_new: d.ok && !d.duplicate && d.id !== a.id,
		supersedes_plain_rerequest: dRead.ok ? (dRead.record.supersedes ?? null) : "read_failed",
		unknown_blocks: e.ok && e.duplicate && e.id === d.id,
		resolve_unknown_ok: resolved.ok,
		after_resolve_new: f.ok && !f.duplicate && f.id !== d.id,
		keys: refs(cwd, "refs/pi/key/").length,
	};
}

// 5. 競合する保存 (4 プロセスが同時に、同じ要求を保存)
{
	const cwd = repo();
	const rs = await Promise.all([1, 2, 3, 4].map((i) => child("save", { cwd, input: input({ request: { id: `req-${i}`, sessionId: "s", cwd: "/w" } }) })));
	out.concurrent_save = { oks: rs.filter((r) => r.ok).length, created: rs.filter((r) => r.ok && !r.duplicate).length, ids: new Set(rs.filter((r) => r.ok).map((r) => r.id)).size, pendingRefs: refs(cwd, "refs/pi/pending/").length, keys: refs(cwd, "refs/pi/key/").length, crashes: rs.filter((r) => r.crash).length };
}

// 6. 上限
{
	const cwd = repo();
	const lim = { ...ops.DEFAULT_LIMITS, maxPending: 2 };
	const mk = (n) => input({ params: { source: `feature/${n}`, message: "m" } });
	const r1 = ops.saveOp(cwd, mk(1), lim);
	const r2 = ops.saveOp(cwd, mk(2), lim);
	const r3 = ops.saveOp(cwd, mk(3), lim);
	const dupAtLimit = ops.saveOp(cwd, mk(1), lim);
	const big = ops.saveOp(cwd, input({ params: { a: "x".repeat(5000) } }), { ...ops.DEFAULT_LIMITS, maxRecordBytes: 1000 });
	const trunc = ops.saveOp(cwd, mk(9), { ...ops.DEFAULT_LIMITS, maxScan: 1 });
	const listTrunc = ops.listOps(cwd, { ...ops.DEFAULT_LIMITS, maxScan: 1 });
	out.limits = { r1: r1.ok, r2: r2.ok, r3: r3.ok ? "ok" : r3.code, duplicate_at_limit: dupAtLimit.ok && dupAtLimit.duplicate, big: big.ok ? "ok" : big.code, truncated_save: trunc.ok ? "ok" : trunc.code, list_truncated: listTrunc.truncated, list_len: listTrunc.entries.length };
	const bad = ops.saveOp(cwd, input({ action: "Bad Action!" }));
	const badParam = ops.saveOp(cwd, input({ params: { a: 1 } }));
	const badPremise = ops.saveOp(cwd, input({ premise: { a: undefined } }));
	out.invalid_input = { action: bad.ok ? "ok" : bad.code, param: badParam.ok ? "ok" : badParam.code, premise: badPremise.ok ? "ok" : badPremise.code };
}

// 7. 承認の開始 (CAS・排他・symbolic ref の差し替え)
{
	const cwd = repo();
	const a = ops.saveOp(cwd, input());
	const stale = "f".repeat(40);
	const wrongOid = ops.beginApproval(cwd, a.id, stale, owner());
	const first = ops.beginApproval(cwd, a.id, a.oid, owner());
	const second = ops.beginApproval(cwd, a.id, a.oid, owner());
	out.begin = { wrongOid: wrongOid.ok ? "ok" : wrongOid.code, first: first.ok, stage: first.ok ? first.attempt.stage : null, pendingGone: !refs(cwd, "refs/pi/pending/").includes(a.ref), running: refs(cwd, "refs/pi/running/").length, second: second.ok ? "ok" : second.code };
	// 競合 (2 プロセス)
	const b = ops.saveOp(cwd, input({ params: { source: "feature/race", message: "m" } }));
	const rs = await Promise.all([1, 2, 3].map(() => child("begin", { cwd, id: b.id, oid: b.oid, owner: owner() })));
	out.begin_race = { oks: rs.filter((r) => r.ok).length, running: refs(cwd, "refs/pi/running/").filter((r) => r.endsWith(b.id)).length };
	// symbolic ref に差し替えられても、通常のブランチを巻き込まない
	const c = ops.saveOp(cwd, input({ params: { source: "feature/swap", message: "m" } }));
	const mainBefore = git(cwd, "rev-parse", "refs/heads/main");
	git(cwd, "update-ref", "-d", c.ref);
	git(cwd, "symbolic-ref", c.ref, "refs/heads/main");
	const swapped = ops.beginApproval(cwd, c.id, c.oid, owner());
	out.begin_symref_swap = { ok: swapped.ok, mainUnchanged: git(cwd, "rev-parse", "refs/heads/main") === mainBefore, runningCreated: refs(cwd, "refs/pi/running/").some((r) => r.endsWith(c.id)) };
	// 不正な owner・id
	const d = ops.saveOp(cwd, input({ params: { source: "feature/owner", message: "m" } }));
	out.begin_invalid = { owner: ops.beginApproval(cwd, d.id, d.oid, { pid: "x" }).code, id: ops.beginApproval(cwd, "../x", d.oid, owner()).code };
}

// 8. 段階 (reserved → started)・pending へ戻す
{
	const cwd = repo();
	const a = ops.saveOp(cwd, input());
	const b1 = ops.beginApproval(cwd, a.id, a.oid, owner());
	const back = ops.returnToPending(cwd, a.id, b1.attemptOid);
	const sameRecord = ops.readOp(cwd, a.id);
	const afterBack = { pending: refs(cwd, "refs/pi/pending/"), running: refs(cwd, "refs/pi/running/") };
	const again = ops.beginApproval(cwd, a.id, a.oid, owner());
	const s1 = ops.markStarted(cwd, a.id, again.attemptOid);
	const s1b = ops.markStarted(cwd, a.id, again.attemptOid);
	const backStarted = ops.returnToPending(cwd, a.id, s1.attemptOid);
	const s2 = ops.markStarted(cwd, a.id, s1.attemptOid);
	out.stages = { back: back.ok, pendingRestored: sameRecord.ok && afterBack.pending.includes(a.ref), runningCleared: afterBack.running.length === 0, started: s1.ok && s1.attempt.stage === "started", sameAttemptId: s1.ok && s1.attempt.attemptId === again.attempt.attemptId, startedTwice: s1b.ok ? "ok" : s1b.code, returnStarted: backStarted.ok ? "ok" : backStarted.code, startedFromStarted: s2.ok ? "ok" : s2.code };
}

// 9. 結果の記録 (4 値)・鍵・鎖
{
	const cwd = repo();
	const body = (outcome, over = {}) => ({ outcome, phase: "done", confirmedEffects: ["a"], remainingCleanup: [], evidence: ["e"], ...over });
	const run = (n, outcome) => {
		const s = ops.saveOp(cwd, input({ params: { source: `feature/${n}`, message: "m" } }));
		const b = ops.beginApproval(cwd, s.id, s.oid, owner());
		const st = ops.markStarted(cwd, s.id, b.attemptOid);
		const f = ops.finishApproval(cwd, s.id, st.attemptOid, body(outcome));
		return { s, st, f };
	};
	const results = {};
	for (const o of ["success", "failed_confirmed", "not_executed", "unknown"]) {
		const { s, st, f } = run(o, o);
		const r = f.ok ? ops.readResultAt(cwd, s.id, f.doneOid) : null;
		results[o] = { ok: f.ok, done: refs(cwd, "refs/pi/done/").includes(`refs/pi/done/${s.id}`), running: refs(cwd, "refs/pi/running/").includes(`refs/pi/running/${s.id}`), result: r?.ok ? r.result.outcome : null, resolvedBy: r?.ok ? r.result.resolvedBy : null, parentIsAttempt: r?.ok ? r.parent === st.attemptOid : null, keyKept: gitOk(cwd, "rev-parse", "-q", "--verify", `refs/pi/key/${ops.computeDigest({ action: "git_integrate", params: { source: `feature/${o}`, message: "m" }, premise: input().premise })}`) !== null };
	}
	const bad = (() => {
		const s = ops.saveOp(cwd, input({ params: { source: "feature/bad", message: "m" } }));
		const b = ops.beginApproval(cwd, s.id, s.oid, owner());
		return { outcome: ops.finishApproval(cwd, s.id, b.attemptOid, body("weird")).code, list: ops.finishApproval(cwd, s.id, b.attemptOid, { ...body("success"), evidence: "x" }).code, stillRunning: refs(cwd, "refs/pi/running/").includes(`refs/pi/running/${s.id}`) };
	})();
	out.results = { ...results, bad };
}

// 10. 人による決着 (実行者の確認つき)
{
	const cwd = repo();
	const alive = () => ({ state: "alive", reason: "生きている" });
	const gone = () => ({ state: "gone", reason: "止まっている" });
	const unknown = () => ({ state: "unknown", reason: "確認できない" });
	const mk = (n, upto) => {
		const s = ops.saveOp(cwd, input({ params: { source: `feature/r${n}`, message: "m" } }));
		const b = ops.beginApproval(cwd, s.id, s.oid, owner());
		const st = upto === "started" ? ops.markStarted(cwd, s.id, b.attemptOid) : b;
		return { s, oid: st.attemptOid };
	};
	const r = {};
	let x = mk(1, "started");
	r.alive = ops.resolveRunning(cwd, x.s.id, x.oid, { kind: "success" }, { liveness: alive }).code;
	r.unknown_unconfirmed = ops.resolveRunning(cwd, x.s.id, x.oid, { kind: "success" }, { liveness: unknown }).code;
	r.stale_oid = ops.resolveRunning(cwd, x.s.id, "e".repeat(40), { kind: "success" }, { liveness: gone }).code;
	r.stage_mismatch_pending = ops.resolveRunning(cwd, x.s.id, x.oid, { kind: "pending" }, { liveness: gone }).code;
	r.unknown_confirmed = ops.resolveRunning(cwd, x.s.id, x.oid, { kind: "success", evidence: ["ログを見た"] }, { liveness: unknown, userConfirmedStopped: true }).ok;
	const res1 = ops.readResultAt(cwd, x.s.id, git(cwd, "rev-parse", `refs/pi/done/${x.s.id}`));
	r.success_result = res1.ok ? { outcome: res1.result.outcome, by: res1.result.resolvedBy, evidence: res1.result.evidence } : null;
	x = mk(2, "reserved");
	r.reserved_success_refused = ops.resolveRunning(cwd, x.s.id, x.oid, { kind: "success" }, { liveness: gone }).code;
	r.reserved_to_pending = ops.resolveRunning(cwd, x.s.id, x.oid, { kind: "pending" }, { liveness: gone }).ok;
	r.reserved_pending_restored = refs(cwd, "refs/pi/pending/").includes(x.s.ref);
	x = mk(3, "reserved");
	r.reserved_abandon = ops.resolveRunning(cwd, x.s.id, x.oid, { kind: "abandon" }, { liveness: gone }).ok;
	const ab = ops.readResultAt(cwd, x.s.id, git(cwd, "rev-parse", `refs/pi/done/${x.s.id}`));
	r.abandon_outcome = ab.ok ? ab.result.outcome : null;
	x = mk(4, "started");
	r.started_abandon_refused = ops.resolveRunning(cwd, x.s.id, x.oid, { kind: "abandon" }, { liveness: gone }).code;
	r.failed = ops.resolveRunning(cwd, x.s.id, x.oid, { kind: "failed" }, { liveness: gone }).ok;
	const fl = ops.readResultAt(cwd, x.s.id, git(cwd, "rev-parse", `refs/pi/done/${x.s.id}`));
	r.failed_outcome = fl.ok ? fl.result.outcome : null;
	x = mk(5, "started");
	const retry = ops.resolveRunning(cwd, x.s.id, x.oid, { kind: "retry", evidence: ["やり直す"] }, { liveness: gone });
	const newRec = retry.ok && retry.newId ? ops.readOp(cwd, retry.newId) : null;
	r.retry = { ok: retry.ok, newPending: !!newRec?.ok, supersedes: newRec?.ok ? newRec.record.supersedes === x.s.id : null, oldDone: refs(cwd, "refs/pi/done/").includes(`refs/pi/done/${x.s.id}`), oldRunning: refs(cwd, "refs/pi/running/").includes(`refs/pi/running/${x.s.id}`) };
	out.resolve = r;
	const nu = (() => {
		const s = ops.saveOp(cwd, input({ params: { source: "feature/nu", message: "m" } }));
		const b = ops.beginApproval(cwd, s.id, s.oid, owner());
		const st = ops.markStarted(cwd, s.id, b.attemptOid);
		ops.finishApproval(cwd, s.id, st.attemptOid, { outcome: "success", phase: "p", confirmedEffects: [], remainingCleanup: [], evidence: [] });
		return ops.resolveUnknown(cwd, s.id, { kind: "success" }).code;
	})();
	out.resolve_unknown_not_unknown = nu;
}

// 11. 期限
{
	const cwd = repo();
	const a = ops.saveOp(cwd, input({ params: { source: "feature/old", message: "m" } }));
	const b = ops.saveOp(cwd, input({ params: { source: "feature/run", message: "m" } }));
	const runB = ops.beginApproval(cwd, b.id, b.oid, owner());
	const c = ops.saveOp(cwd, input({ params: { source: "feature/done", message: "m" } }));
	const bc = ops.beginApproval(cwd, c.id, c.oid, owner());
	const sc = ops.markStarted(cwd, c.id, bc.attemptOid);
	ops.finishApproval(cwd, c.id, sc.attemptOid, { outcome: "success", phase: "p", confirmedEffects: [], remainingCleanup: [], evidence: [] });
	const legacyTree = gitIn(cwd, `100644 blob ${gitIn(cwd, "x\n", "hash-object", "-w", "--stdin")}\ta.txt\n`, "mktree");
	const legacy = gitIn(cwd, "legacy\n", "commit-tree", legacyTree, "-F", "-");
	git(cwd, "update-ref", "refs/pi/pending/000000000000777", legacy);
	const fresh = ops.reconcileOps(cwd, { retentionDays: 30, resultRetentionDays: 90, now: Date.now() + 1 * DAYS });
	const later = ops.reconcileOps(cwd, { retentionDays: 30, resultRetentionDays: 90, now: Date.now() + 40 * DAYS });
	const much = ops.reconcileOps(cwd, { retentionDays: 30, resultRetentionDays: 90, now: Date.now() + 100 * DAYS });
	out.reconcile = { fresh: fresh.length, later: later.sort(), muchLater: much.sort(), pendingLeft: refs(cwd, "refs/pi/pending/"), runningLeft: refs(cwd, "refs/pi/running/"), doneLeft: refs(cwd, "refs/pi/done/"), keysLeft: refs(cwd, "refs/pi/key/").length, ids: { a: a.id, b: b.id, c: c.id }, runB: runB.ok };
}

// 12. hook を動かさない・HEAD などを変えない・linked worktree
{
	const cwd = repo();
	const hooks = join(cwd, "evil-hooks");
	mkdirSync(hooks);
	const mark = join(cwd, "HOOK-RAN");
	for (const name of ["reference-transaction", "post-commit", "pre-commit"]) {
		writeFileSync(join(hooks, name), `#!/bin/sh\ntouch "${mark}"\n`);
		chmodSync(join(hooks, name), 0o755);
	}
	git(cwd, "config", "core.hooksPath", hooks);
	git(cwd, "config", "commit.gpgsign", "true");
	git(cwd, "config", "gpg.program", "/bin/false");
	const before = snapshot(cwd);
	const a = ops.saveOp(cwd, input());
	const b = ops.beginApproval(cwd, a.id, a.oid, owner());
	const s = ops.markStarted(cwd, a.id, b.attemptOid);
	const f = ops.finishApproval(cwd, a.id, s.attemptOid, { outcome: "success", phase: "p", confirmedEffects: [], remainingCleanup: [], evidence: [] });
	out.safe = { allOk: a.ok && b.ok && s.ok && f.ok, hookRan: existsSync(mark), untouched: JSON.stringify(snapshot(cwd)) === JSON.stringify(before) };
}
{
	const cwd = repo();
	const wt = join(mkdtempSync(join(tmpdir(), "pi-ops-wt-")), "wt");
	git(cwd, "worktree", "add", "-q", "-b", "feature/x", wt);
	const a = ops.saveOp(wt, input());
	const fromMain = ops.readOp(cwd, a.id);
	const b = ops.beginApproval(cwd, a.id, a.oid, owner());
	out.linked = { savedInLinked: a.ok, visibleFromMain: fromMain.ok, beganFromMain: b.ok };
}

// 12. reason の拡張 (inline / request) と、結果の facts
{
	const cwd = repo();
	const reasons = {};
	for (const [i, reason] of ["timeout", "absent", "no_ui", "later", "inline", "request", "bogus"].entries()) {
		const s = ops.saveOp(cwd, input({ reason, params: { source: `feature/rs${i}`, message: "m" } }));
		const back = s.ok ? ops.readOp(cwd, s.id) : null;
		reasons[reason] = { saved: s.ok, code: s.ok ? null : s.code, read: back?.ok ? back.record.reason : null };
	}
	const base = (over = {}) => ({ outcome: "success", phase: "done", confirmedEffects: ["a"], remainingCleanup: ["b"], evidence: ["e"], ...over });
	const ok = (b) => ops.validateResultBody(b);
	const repeat = (n) => Object.fromEntries(Array.from({ length: n }, (_, i) => [`k${i}`, "v"]));
	const facts = { source: "feature/x", target: "develop", result_commit: "a".repeat(40) };
	const valid = {
		no_facts: ok(base()),
		with_facts: ok(base({ facts })),
		empty_facts: ok(base({ facts: {} })),
		sixteen: ok(base({ facts: repeat(16) })),
		value_200: ok(base({ facts: { a: "x".repeat(200) } })),
		key_32: ok(base({ facts: { [`a${"b".repeat(31)}`]: "v" } })),
		multibyte_value: ok(base({ facts: { a: "統合元" } })),
	};
	const invalid = {
		seventeen: ok(base({ facts: repeat(17) })),
		upper_key: ok(base({ facts: { Abc: "v" } })),
		digit_key: ok(base({ facts: { "1a": "v" } })),
		key_33: ok(base({ facts: { [`a${"b".repeat(32)}`]: "v" } })),
		value_201: ok(base({ facts: { a: "x".repeat(201) } })),
		newline: ok(base({ facts: { a: "x\ny" } })),
		cr: ok(base({ facts: { a: "x\ry" } })),
		tab: ok(base({ facts: { a: "x\ty" } })),
		nul: ok(base({ facts: { a: "x\0y" } })),
		del: ok(base({ facts: { a: "x\x7fy" } })),
		number: ok(base({ facts: { a: 1 } })),
		null_value: ok(base({ facts: { a: null } })),
		array_value: ok(base({ facts: { a: ["x"] } })),
		object_value: ok(base({ facts: { a: { b: "x" } } })),
		array_facts: ok(base({ facts: ["x"] })),
		null_facts: ok(base({ facts: null })),
		string_facts: ok(base({ facts: "x" })),
	};
	// 他の項目の検証は不変 (facts が正しくても拒否する)
	const others = {
		outcome: ok(base({ outcome: "weird", facts })),
		phase: ok(base({ phase: "x".repeat(101), facts })),
		confirmedEffects: ok(base({ confirmedEffects: "x", facts })),
		remainingCleanup: ok(base({ remainingCleanup: [1], facts })),
		evidence: ok(base({ evidence: Array.from({ length: 51 }, () => "x"), facts })),
		missing_evidence: ok({ outcome: "success", phase: "p", confirmedEffects: [], remainingCleanup: [] }),
	};
	const run = (n, body) => {
		const s = ops.saveOp(cwd, input({ params: { source: `feature/f${n}`, message: "m" } }));
		const b = ops.beginApproval(cwd, s.id, s.oid, owner());
		const st = ops.markStarted(cwd, s.id, b.attemptOid);
		const f = ops.finishApproval(cwd, s.id, st.attemptOid, body);
		return { s, f, raw: f.ok ? ops.readResultAt(cwd, s.id, f.doneOid) : null };
	};
	const withF = run(1, base({ facts }));
	const withoutF = run(2, base());
	const bad = run(3, base({ facts: { a: "x\ny" } }));
	// facts の無い保存は、出力に facts を含めない
	const rawJson = (r) => git(cwd, "show", `${r.f.doneOid}:result.json`);
	const unk = run(4, base({ outcome: "unknown", facts }));
	const resolved = unk.f.ok ? ops.resolveUnknown(cwd, unk.s.id, { kind: "success" }) : null;
	const afterResolve = resolved?.ok ? ops.readResultAt(cwd, unk.s.id, git(cwd, "rev-parse", `refs/pi/done/${unk.s.id}`)) : null;
	out.facts = {
		reasons,
		valid,
		invalid,
		others,
		roundtrip: withF.raw?.ok ? withF.raw.result.facts : null,
		withoutFactsOk: withoutF.f.ok,
		withoutFactsKey: withoutF.raw?.ok ? "facts" in withoutF.raw.result : null,
		withoutFactsJsonHasFacts: withoutF.f.ok ? rawJson(withoutF).includes("facts") : null,
		badSaveCode: bad.f.ok ? "ok" : bad.f.code,
		badStillRunning: refs(cwd, "refs/pi/running/").includes(`refs/pi/running/${bad.s.id}`),
		resolvedKeepsFacts: afterResolve?.ok ? afterResolve.result.facts : null,
	};
}

out.keys_of_api = Object.keys(ops).sort();
console.log(JSON.stringify(out));

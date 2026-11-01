// 非同期承認の承認する側の「実行の核」(pending-approve.ts の runApproved・resolvePending・unlockPending。CHG-0055 の P8c) を、
// 偽の ctx・偽のアダプタ・本物の統合ロック (exclusive-lock.ts) で直接動かして固定する。結果を JSON で標準出力へ出す。
// 照合は test_pi_approve_core.py。
//
//   node test/agents/pi/approve_core_driver.mjs
//
// see docs/change/0055-async-approval.md#p8c-の決定-v2
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const harness = (name) => pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", name)).href;
const ops = await import(harness("pending-ops.ts"));
const ap = await import(harness("pending-approve.ts"));
const lk = await import(harness("exclusive-lock.ts"));

const ENV = { ...process.env, GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@example.test", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@example.test" };
const git = (cwd, ...args) => execFileSync("git", args, { cwd, env: ENV, encoding: "utf8" }).trim();
const refs = (cwd, ns) => git(cwd, "for-each-ref", "--format=%(refname)", ns).split("\n").filter(Boolean);
const lockRefs = (cwd) => refs(cwd, "refs/pi/lock/");

function repo() {
	const dir = mkdtempSync(join(tmpdir(), "pi-core-"));
	git(dir, "init", "-q", "-b", "main");
	writeFileSync(join(dir, "seed.txt"), "seed\n");
	git(dir, "add", "-A");
	git(dir, "commit", "-q", "-m", "seed");
	return dir;
}

let serial = 0;
const record = (over = {}) => ({
	action: "fake_op",
	params: { mode: "stopped_ok", note: `n${serial++}` },
	premise: { x: 1 },
	reason: "request",
	request: { id: `req-${serial}`, sessionId: "s-req", cwd: "/w" },
	createdAt: new Date().toISOString(),
	...over,
});
const owner = (over = {}) => ({ sessionId: "s-appr", runtimeEpoch: "e", pid: process.pid, processStart: "100", host: "h", ...over });
// セッション名の先頭で、生死を決める (alive-… は生きている、unk-… は確認できない、それ以外は止まっている)
const liveness = (o) => (o.sessionId.startsWith("alive") ? { state: "alive", reason: "生きている" } : o.sessionId.startsWith("unk") ? { state: "unknown", reason: "確認できない" } : { state: "gone", reason: "止まっている" });

const SUCCESS = { outcome: "success", phase: "done", confirmedEffects: ["統合した"], remainingCleanup: [], evidence: ["確認した"] };
const UNKNOWN = { outcome: "unknown", phase: "commit", confirmedEffects: [], remainingCleanup: ["中途の状態の可能性"], evidence: ["git・hook の停止を確認できない。rollback しない"] };

/** 偽のアダプタ。params.mode で、実行の結果を変える */
function adapter(marks, repoDir, over = {}) {
	return {
		action: "fake_op",
		label: "試験の操作",
		plan: async (rec) => ({ ok: true, plan: { mode: rec.params.mode }, summary: "要約の行", view: "全文の本文" }),
		recheck: async () => (over.recheckFails ? { ok: false, reason: "前提が変わった" } : { ok: true }),
		...(over.exclusive === false ? {} : { exclusive: true }),
		...(over.runsHere ? { runsHere: over.runsHere } : {}),
		execute: async (plan) => {
			marks.push(`execute:${plan.mode}`);
			if (plan.mode === "peek") {
				marks.push(`locks:${lockRefs(repoDir).length}`);
				return { body: SUCCESS, termination: "stopped" };
			}
			if (plan.mode === "stopped_ok") return { body: SUCCESS, termination: "stopped" };
			if (plan.mode === "plain") return SUCCESS; // 互換: 旧形式 (ResultBody だけ)
			if (plan.mode === "plain_unknown") return UNKNOWN; // 旧形式で結果不明 (排他の操作では、停止を確かめられない)
			if (plan.mode === "stopped_unknown") return { body: UNKNOWN, termination: "stopped" };
			if (plan.mode === "unconfirmed") return { body: UNKNOWN, termination: "unconfirmed" };
			if (plan.mode === "throw") throw new Error("実行中の例外");
			if (plan.mode === "invalid") return { outcome: "weird" };
			if (plan.mode === "kill_running") {
				// 実行の途中で running の ref が消えた (結果を保存できない状況)
				for (const r of refs(repoDir, "refs/pi/running/")) git(repoDir, "update-ref", "-d", r);
				return { body: SUCCESS, termination: "stopped" };
			}
			return { body: SUCCESS, termination: "stopped" };
		},
	};
}

function ctxOf(cwd, o, selects, answers) {
	return {
		cwd,
		mode: "tui",
		hasUI: true,
		isIdle: () => true,
		ui: {
			select: async (title, options) => {
				selects.push({ title, options });
				const a = answers.shift();
				return typeof a === "function" ? a() : a;
			},
			editor: async () => undefined,
		},
	};
}

function depsOf(cwd, marks, sent, o) {
	return {
		adapters: { fake_op: adapter(marks, cwd, o) },
		enabled: () => true,
		modes: ["tui"],
		rules: {},
		env: ENV,
		dialog: (fn) => fn(),
		bell: () => {},
		owner: () => owner(),
		notify: () => {},
		tellModel: (content, details) => sent.push({ content, details }),
		liveness,
		...(o.authorize ? { authorize: o.authorize } : {}),
	};
}

async function approve(cwd, id, o = {}) {
	const marks = [];
	const sent = [];
	const selects = [];
	const answers = [...(o.answers ?? ["承認して実行"])];
	const reply = await ap.approvePending(id, ctxOf(cwd, o, selects, answers), depsOf(cwd, marks, sent, o));
	return { reply, marks, sent, selects };
}
async function resolveIt(cwd, id, args, o = {}) {
	const marks = [];
	const sent = [];
	return ap.resolvePending(id, args, ctxOf(cwd, o, [], []), depsOf(cwd, marks, sent, o));
}

const save = (cwd, over = {}) => {
	const r = ops.saveOp(cwd, record(over));
	if (!r.ok) throw new Error(`save failed: ${r.reason}`);
	return r;
};
const states = (cwd, id) => ({
	pending: refs(cwd, "refs/pi/pending/").includes(`refs/pi/pending/${id}`),
	running: refs(cwd, "refs/pi/running/").includes(`refs/pi/running/${id}`),
	done: refs(cwd, "refs/pi/done/").includes(`refs/pi/done/${id}`),
});
const resultOf = (cwd, id) => {
	const oid = ops.doneOid(cwd, id);
	const r = oid ? ops.readResultAt(cwd, id, oid) : null;
	return r?.ok ? { outcome: r.result.outcome, by: r.result.resolvedBy, evidence: r.result.evidence } : null;
};

/** 別の承認者 A が、running (reserved か started) とロックを持っている状況を作る */
function otherHolder(cwd, { session, started }) {
	const a = save(cwd, { params: { mode: "stopped_ok", note: `other-${serial++}` } });
	const begin = ops.beginApproval(cwd, a.id, a.oid, owner({ sessionId: session }));
	if (!begin.ok) throw new Error(`begin failed: ${begin.reason}`);
	let attempt = begin.attempt;
	if (started) {
		const st = ops.markStarted(cwd, a.id, begin.attemptOid);
		if (!st.ok) throw new Error(`start failed: ${st.reason}`);
		attempt = st.attempt;
	}
	const got = lk.acquireLock(cwd, { runningId: a.id, attemptId: attempt.attemptId }, { probe: () => ({ attempt: "absent", owner: "unknown" }) });
	if (!got.ok) throw new Error(`lock failed: ${got.reason}`);
	return { id: a.id, handle: got.handle, attemptId: attempt.attemptId };
}

const out = {};

// 1. 排他の操作 (exclusive): 実行中だけロックを持ち、成功したら外す。排他でない操作は、ロックを取らない
{
	const cwd = repo();
	const s = save(cwd, { params: { mode: "peek", note: "peek" } });
	const r = await approve(cwd, s.id);
	const t = save(cwd, { params: { mode: "peek", note: "peek2" } });
	const r2 = await approve(cwd, t.id, { exclusive: false });
	out.lock_scope = { exclusive: { marks: r.marks, level: r.reply.level, afterLocks: lockRefs(cwd).length, result: resultOf(cwd, s.id) }, plain: { marks: r2.marks, afterLocks: lockRefs(cwd).length } };
}

// 2. 旧形式の戻り値 (ResultBody だけ) も、従来どおり受け付ける
{
	const cwd = repo();
	const s = save(cwd, { params: { mode: "plain", note: "plain" } });
	const r = await approve(cwd, s.id);
	out.plain_body = { level: r.reply.level, states: states(cwd, s.id), result: resultOf(cwd, s.id), afterLocks: lockRefs(cwd).length };
}

// 3. D9: 停止を確認できなかった (unconfirmed) → running とロックを残し、結果 (done) を書かない。モデルには固定の文
{
	const cwd = repo();
	const s = save(cwd, { params: { mode: "unconfirmed", note: "u" } });
	const r = await approve(cwd, s.id);
	const lock = lk.readLock(cwd, lk.lockKeyOf(cwd).key);
	out.unconfirmed = {
		level: r.reply.level,
		text: r.reply.text,
		states: states(cwd, s.id),
		result: resultOf(cwd, s.id),
		locks: lockRefs(cwd).length,
		holderIsThisRun: lock.state === "held" && lock.holder.runningId === s.id,
		sent: r.sent.map((m) => m.content),
	};
}

// 4. 実行器が例外 (排他の操作) → 停止を確認できないので、同じく running とロックを残す。排他でない操作は従来どおり unknown を記録する
{
	const cwd = repo();
	const s = save(cwd, { params: { mode: "throw", note: "t" } });
	const r = await approve(cwd, s.id);
	const t = save(cwd, { params: { mode: "throw", note: "t2" } });
	const r2 = await approve(cwd, t.id, { exclusive: false });
	out.thrown = {
		exclusive: { level: r.reply.level, states: states(cwd, s.id), result: resultOf(cwd, s.id), locks: lockRefs(cwd).length },
		plain: { states: states(cwd, t.id), result: resultOf(cwd, t.id) },
	};
}

// 5. 停止は確認できたが結果が不明 (stopped × unknown) → 結果 unknown を記録し、ロックは外す (人が resolve する)
{
	const cwd = repo();
	const s = save(cwd, { params: { mode: "stopped_unknown", note: "su" } });
	const r = await approve(cwd, s.id);
	out.stopped_unknown = { level: r.reply.level, states: states(cwd, s.id), result: resultOf(cwd, s.id), locks: lockRefs(cwd).length };
}

// 6. 結果を保存できなかった (finishApproval の失敗) → ロックを残す (決着前)。外すのは resolve か unlock
{
	const cwd = repo();
	const s = save(cwd, { params: { mode: "kill_running", note: "k" } });
	const r = await approve(cwd, s.id);
	out.finish_failure = { level: r.reply.level, text: r.reply.text, locks: lockRefs(cwd).length };
}

// 7. 別の承認者がロックを持っている: 生きている (alive) → 実行せず pending へ戻す。ロックは A のまま
{
	const cwd = repo();
	const other = otherHolder(cwd, { session: "alive-a", started: true });
	const s = save(cwd, { params: { mode: "stopped_ok", note: "b" } });
	const r = await approve(cwd, s.id);
	const lock = lk.readLock(cwd, lk.lockKeyOf(cwd).key);
	out.held_by_alive = {
		level: r.reply.level,
		text: r.reply.text,
		marks: r.marks,
		states: states(cwd, s.id),
		lockStillOthers: lock.state === "held" && lock.oid === other.handle.oid,
	};
}

// 8. A が reserved のまま止まっている (reserved × gone) → ロックを回復して実行できる。A の running は残る
{
	const cwd = repo();
	const other = otherHolder(cwd, { session: "dead-a", started: false });
	const s = save(cwd, { params: { mode: "stopped_ok", note: "c" } });
	const r = await approve(cwd, s.id);
	out.recovered_reserved = { level: r.reply.level, marks: r.marks, result: resultOf(cwd, s.id), locks: lockRefs(cwd).length, otherRunning: states(cwd, other.id).running };
}

// 9. A が started のまま止まっている (started × gone) → 自動で回復せず、実行しない。ロックは A のまま
{
	const cwd = repo();
	const other = otherHolder(cwd, { session: "dead-a", started: true });
	const s = save(cwd, { params: { mode: "stopped_ok", note: "d" } });
	const r = await approve(cwd, s.id);
	const lock = lk.readLock(cwd, lk.lockKeyOf(cwd).key);
	out.stale_started = { level: r.reply.level, text: r.reply.text, marks: r.marks, states: states(cwd, s.id), lockStillOthers: lock.state === "held" && lock.oid === other.handle.oid };
}

// 10. 承認者の cwd が統合先の中でない (runsHere) → 確認の画面を出す前に断る。観測できない (ok:false) も断る。中なら進む
{
	const cwd = repo();
	const a = save(cwd, { params: { mode: "stopped_ok", note: "h1" } });
	const r1 = await approve(cwd, a.id, { runsHere: () => ({ ok: true, here: false }) });
	const b = save(cwd, { params: { mode: "stopped_ok", note: "h2" } });
	const r2 = await approve(cwd, b.id, { runsHere: () => ({ ok: false, reason: "git で観測できない" }) });
	const c = save(cwd, { params: { mode: "stopped_ok", note: "h3" } });
	const r3 = await approve(cwd, c.id, { runsHere: () => ({ ok: true, here: true }) });
	const d = save(cwd, { params: { mode: "stopped_ok", note: "h4" } });
	const r4 = await approve(cwd, d.id, {
		runsHere: () => {
			throw new Error("例外");
		},
	});
	const view = (r, id) => ({ level: r.reply.level, text: r.reply.text, selects: r.selects.length, marks: r.marks, pending: states(cwd, id).pending });
	out.runs_here = { outside: view(r1, a.id), unobservable: view(r2, b.id), inside: view(r3, c.id), thrown: view(r4, d.id) };
}

// 11. authorize (現在の役割・操作の定義の再判定): 断られたら、計画を作る前に断る
{
	const cwd = repo();
	const a = save(cwd, { params: { mode: "stopped_ok", note: "a1" } });
	const seen = [];
	const r1 = await approve(cwd, a.id, {
		authorize: (rec) => {
			seen.push(rec.action);
			return { ok: false, reason: "この役割では操作できない" };
		},
	});
	const b = save(cwd, { params: { mode: "stopped_ok", note: "a2" } });
	const r2 = await approve(cwd, b.id, { authorize: () => ({ ok: true }) });
	out.authorize = { refused: { level: r1.reply.level, text: r1.reply.text, selects: r1.selects.length, marks: r1.marks, pending: states(cwd, a.id).pending }, seen, allowed: { level: r2.reply.level, marks: r2.marks } };
}

// 11b. authorize が例外を投げたときは、断る (許可に読み替えない)
{
	const cwd = repo();
	const a = save(cwd, { params: { mode: "stopped_ok", note: "at" } });
	const r = await approve(cwd, a.id, {
		authorize: () => {
			throw new Error("例外");
		},
	});
	out.authorize_throw = { level: r.reply.level, marks: r.marks, selects: r.selects.length, pending: states(cwd, a.id).pending };
}

// 3b. 排他の操作の「旧形式で unknown」と「不正な結果」は、停止を確かめられない扱い (running とロックを残す)。排他でない操作は従来どおり
{
	const mk = async (mode, o) => {
		const cwd = repo();
		const s = save(cwd, { params: { mode, note: mode } });
		const r = await approve(cwd, s.id, o);
		return { level: r.reply.level, states: states(cwd, s.id), result: resultOf(cwd, s.id), locks: lockRefs(cwd).length };
	};
	out.fail_closed = { plainUnknown: await mk("plain_unknown", {}), invalid: await mk("invalid", {}), invalidNonExclusive: await mk("invalid", { exclusive: false }) };
}

// 8b. ロックの保持者が名乗る試行の ID が、実際の running の試行と違う (mismatch) → 回復しない
{
	const cwd = repo();
	const a = save(cwd, { params: { mode: "stopped_ok", note: "mm" } });
	const begin = ops.beginApproval(cwd, a.id, a.oid, owner({ sessionId: "dead-a" }));
	if (!begin.ok) throw new Error(begin.reason);
	const got = lk.acquireLock(cwd, { runningId: a.id, attemptId: "99999999-9999-4999-8999-999999999999" }, { probe: () => ({ attempt: "absent", owner: "unknown" }) });
	const s = save(cwd, { params: { mode: "stopped_ok", note: "mm2" } });
	const r = await approve(cwd, s.id);
	const lock = lk.readLock(cwd, lk.lockKeyOf(cwd).key);
	out.mismatch = { level: r.reply.level, marks: r.marks, pending: states(cwd, s.id).pending, lockStillOthers: got.ok && lock.state === "held" && lock.oid === got.handle.oid };
}

// 12. resolve: 排他の操作の started は、実行者が止まっていても、利用者の明示 (--confirm-stopped) が要る。決着したら、その試行のロックを外す
{
	const cwd = repo();
	const other = otherHolder(cwd, { session: "dead-a", started: true });
	const r1 = await resolveIt(cwd, other.id, { kind: "failed", confirmStopped: false });
	const lockBefore = lockRefs(cwd).length;
	const runningBefore = states(cwd, other.id).running;
	const r2 = await resolveIt(cwd, other.id, { kind: "failed", confirmStopped: true });
	out.resolve_exclusive = {
		withoutConfirm: { level: r1.level, text: r1.text, running: runningBefore, locks: lockBefore },
		withConfirm: { level: r2.level, running: states(cwd, other.id).running, done: states(cwd, other.id).done, locks: lockRefs(cwd).length, result: resultOf(cwd, other.id) },
	};
}

// 13. resolve は、別の試行のロックを外さない
{
	const cwd = repo();
	const mine = otherHolder(cwd, { session: "dead-a", started: true });
	const lockOid = lk.readLock(cwd, lk.lockKeyOf(cwd).key).oid;
	// 別の保留 (ロックを持たない) の started を決着させても、ロックは変わらない
	const x = save(cwd, { params: { mode: "stopped_ok", note: "x" } });
	const bx = ops.beginApproval(cwd, x.id, x.oid, owner({ sessionId: "dead-x" }));
	ops.markStarted(cwd, x.id, bx.attemptOid);
	const r1 = await resolveIt(cwd, x.id, { kind: "failed", confirmStopped: true });
	const lockAfter = lk.readLock(cwd, lk.lockKeyOf(cwd).key);
	out.resolve_scope = { level: r1.level, lockUnchanged: lockAfter.state === "held" && lockAfter.oid === lockOid, mineRunning: states(cwd, mine.id).running };
}

// 14. 一覧: ロックがあるときだけ、1 行出る (無いときは、従来と同じ出力)
{
	const cwd = repo();
	const before = ap.listText(cwd, { liveness });
	const other = otherHolder(cwd, { session: "alive-a", started: true });
	const during = ap.listText(cwd, { liveness });
	out.list_lock = { before, during, holder: other.id };
}

// 15. unlock (利用者専用): 孤児のロック (running が無い) だけ、確認のうえで外す。実行中の試行があるときは断る
{
	const cwd = repo();
	// 孤児: running を持たないロック
	const orphan = lk.acquireLock(cwd, { runningId: "000000000000001", attemptId: "11111111-1111-4111-8111-111111111111" }, { probe: () => ({ attempt: "absent", owner: "unknown" }) });
	const selects = [];
	const closed = await ap.unlockPending(ctxOf(cwd, {}, selects, ["閉じる"]), depsOf(cwd, [], [], {}));
	const afterClose = lockRefs(cwd).length;
	const unlocked = await ap.unlockPending(ctxOf(cwd, {}, selects, ["ロックを外す"]), depsOf(cwd, [], [], {}));
	const afterUnlock = lockRefs(cwd).length;
	const none = await ap.unlockPending(ctxOf(cwd, {}, selects, []), depsOf(cwd, [], [], {}));
	// 実行中の試行がある → 断る
	const cwd2 = repo();
	const other = otherHolder(cwd2, { session: "alive-a", started: true });
	const refused = await ap.unlockPending(ctxOf(cwd2, {}, [], ["ロックを外す"]), depsOf(cwd2, [], [], {}));
	out.unlock = {
		orphanOk: orphan.ok,
		closed: closed.text,
		afterClose,
		unlocked: { level: unlocked.level, text: unlocked.text },
		afterUnlock,
		none: none.text,
		refused: { level: refused.level, text: refused.text, locks: lockRefs(cwd2).length, running: states(cwd2, other.id).running },
		dialogOptions: selects[0]?.options,
	};
}

// 16. readRunningStrict と probeHolder: 不存在と、読み取り失敗・symbolic・不正を、別の状態で返す (null に畳まない)
{
	const cwd = repo();
	const [id1, id2, id3, id4] = ["000000000000101", "000000000000102", "000000000000103", "000000000000104"];
	const UU = "99999999-9999-4999-8999-999999999999";
	const s = save(cwd, { params: { mode: "stopped_ok", note: "strict" } });
	const begin = ops.beginApproval(cwd, s.id, s.oid, owner({ sessionId: "alive-s" }));
	if (!begin.ok) throw new Error(begin.reason);
	git(cwd, "symbolic-ref", `refs/pi/running/${id2}`, "refs/pi/nowhere"); // dangling
	git(cwd, "symbolic-ref", `refs/pi/running/${id3}`, `refs/pi/running/${id4}`); // loop
	git(cwd, "symbolic-ref", `refs/pi/running/${id4}`, `refs/pi/running/${id3}`);
	// 壊れた loose ref (列挙から黙って落ちる)、存在しないオブジェクトを指す ref、実在する ref を指す symbolic ref (列挙される)
	const [id5, id6, id7] = ["000000000000105", "000000000000106", "000000000000107"];
	mkdirSync(join(cwd, ".git", "refs", "pi", "running"), { recursive: true });
	writeFileSync(join(cwd, ".git", "refs", "pi", "running", id5), "not-an-oid\n");
	writeFileSync(join(cwd, ".git", "refs", "pi", "running", id6), `${"a".repeat(40)}\n`);
	git(cwd, "symbolic-ref", `refs/pi/running/${id7}`, "refs/heads/main");
	const probe = (runningId, attemptId) => ap.probeHolder(cwd, { runningId, attemptId }, liveness);
	out.strict = {
		absent: ops.readRunningStrict(cwd, id1).state,
		present: { state: ops.readRunningStrict(cwd, s.id).state, matches: ops.readRunningStrict(cwd, s.id).oid === ops.runningOid(cwd, s.id) },
		dangling: ops.readRunningStrict(cwd, id2).state,
		loop: ops.readRunningStrict(cwd, id3).state,
		garbage: ops.readRunningStrict(cwd, id5).state,
		missingObject: ops.readRunningStrict(cwd, id6).state,
		symbolicToExisting: ops.readRunningStrict(cwd, id7).state,
		badId: ops.readRunningStrict(cwd, "not-an-id").state,
		probes: {
			absent: probe(id1, UU),
			dangling: probe(id2, UU),
			loop: probe(id3, UU),
			missingObject: probe(id6, UU),
			mismatch: probe(s.id, UU),
			reserved: probe(s.id, begin.attempt.attemptId),
		},
	};
}

process.stdout.write(JSON.stringify(out));

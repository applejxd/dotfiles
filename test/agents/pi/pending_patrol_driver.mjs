// `/pending approve` の巡回 (CHG-0058 の段 1。pending-command.ts の巡回と pending-approve.ts の planApproval / executeApproval) を、
// 偽の pi・偽の ctx・偽のアダプタ・使い捨ての git リポジトリで動かして固定する。結果を JSON で標準出力へ出す。
// 照合は test_pi_pending_patrol.py。
//
//   node test/agents/pi/pending_patrol_driver.mjs
//
// see docs/change/0058-batch-approval.md
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const harness = (name) => pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", name)).href;
const ops = await import(harness("pending-ops.ts"));
const ap = await import(harness("pending-approve.ts"));
const cmd = await import(harness("pending-command.ts"));

const ENV = { ...process.env, GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@example.test", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@example.test" };
const git = (cwd, ...args) => execFileSync("git", args, { cwd, env: ENV, encoding: "utf8" }).trim();
const refs = (cwd, ns) => git(cwd, "for-each-ref", "--format=%(refname)", ns).split("\n").filter(Boolean);

function repo() {
	const dir = mkdtempSync(join(tmpdir(), "pi-patrol-"));
	git(dir, "init", "-q", "-b", "main");
	writeFileSync(join(dir, "seed.txt"), "seed\n");
	git(dir, "add", "-A");
	git(dir, "commit", "-q", "-m", "seed");
	return dir;
}

const record = (over = {}) => ({
	action: "fake_op",
	params: { mode: "success", tag: "t" },
	premise: { x: 1 },
	reason: "timeout",
	request: { id: "req-1", sessionId: "s-req", cwd: "/w" },
	createdAt: new Date().toISOString(),
	...over,
});
const save = (cwd, mode = "success", tag = mode) => {
	const r = ops.saveOp(cwd, record({ params: { mode, tag } }));
	if (!r.ok) throw new Error(`save failed: ${r.reason}`);
	return r;
};
/** n 件を、古い順に保存する。mode は配列 (足りない分は success) */
const saveMany = (cwd, modes) => modes.map((m, i) => save(cwd, m, `r${i + 1}`));
const states = (cwd, id) => ({
	pending: refs(cwd, "refs/pi/pending/").includes(`refs/pi/pending/${id}`),
	running: refs(cwd, "refs/pi/running/").includes(`refs/pi/running/${id}`),
	done: refs(cwd, "refs/pi/done/").includes(`refs/pi/done/${id}`),
});
const resultOf = (cwd, id) => {
	const oid = ops.doneOid(cwd, id);
	const r = oid ? ops.readResultAt(cwd, id, oid) : null;
	return r?.ok ? { outcome: r.result.outcome, by: r.result.resolvedBy } : null;
};
const body = (outcome, over = {}) => ({ outcome, phase: "done", confirmedEffects: [], remainingCleanup: [], evidence: [], ...over });

/** 偽のアダプタ。mode ごとに結果を変える。実行の印は marks (tag) に残す */
function fakeAdapter(st, opt = {}) {
	return {
		action: "fake_op",
		exclusive: opt.exclusive === true,
		label: "試験の操作",
		plan: async (rec) => (rec.params.mode === "planfail" ? { ok: false, reason: "計画を作れない" } : { ok: true, plan: { mode: rec.params.mode, tag: rec.params.tag, id: rec.params.id }, summary: `要約 ${rec.params.tag}`, view: "全文" }),
		recheck: async () => ({ ok: true }),
		execute: async (plan, env) => {
			st.marks.push(plan.tag);
			st.onExecute?.(plan.tag);
			if (plan.mode === "failed_confirmed") return { body: body("failed_confirmed"), termination: "stopped" };
			if (plan.mode === "unknown_stopped") return { body: body("unknown", { phase: "started", evidence: ["途切れた"] }), termination: "stopped" };
			if (plan.mode === "unconfirmed") return { body: body("unknown", { phase: "started" }), termination: "unconfirmed" };
			if (plan.mode === "not_executed") return { body: body("not_executed"), termination: "stopped" };
			if (plan.mode === "cleanup") return { body: body("success", { remainingCleanup: ["ブランチが残った"] }), termination: "stopped" };
			if (plan.mode === "lockfail") {
				// 排他ロックを別の値に変えて、実行後の解放 (期待値つきの削除) を失敗させる
				for (const r of refs(env.cwd, "refs/pi/lock/")) git(env.cwd, "update-ref", r, "HEAD");
			}
			if (plan.mode === "savefail") {
				for (const r of refs(env.cwd, "refs/pi/running/")) git(env.cwd, "update-ref", "-d", r);
			}
			return { body: body("success", { confirmedEffects: ["実行した"] }), termination: "stopped" };
		},
	};
}

/** 偽の pi と /pending の登録。answers は select の答え (文字列・関数 (title, options) ・undefined・"@first" = 先頭の選択肢・"@throw" = 例外) */
function setup(o = {}) {
	const st = { marks: [], sent: [], notes: [], selects: [], finals: [], onExecute: null, idle: true, throwNotifyAt: 0, inputHandlers: [], subscribed: 0, unsubscribed: 0 };
	const commands = {};
	const pi = { registerCommand: (name, def) => (commands[name] = def), registerTool: () => {} };
	const config = { enabled: o.enabled ?? true, modes: ["tui"] };
	let notifyN = 0;
	st.handle = cmd.registerPendingCommand(pi, {
		settings: () => cmd.pendingSettings(config),
		redact: (t) => t,
		approveDeps: () => ({
			adapters: { fake_op: fakeAdapter(st, { exclusive: o.exclusive }) },
			enabled: () => config.enabled,
			modes: ["tui"],
			rules: {},
			env: ENV,
			dialog: (fn) => fn(),
			bell: () => {},
			owner: () => ({ sessionId: "s", runtimeEpoch: "e", pid: process.pid, processStart: "1", host: "h" }),
			notify: (text, level) => {
				notifyN++;
				if (st.throwNotifyAt && notifyN === st.throwNotifyAt) throw new Error("notify の例外");
				st.notes.push({ text, level, sentSoFar: st.sent.length });
			},
			tellModel: (content, details) => st.sent.push({ content, details, atSelects: st.selects.length }),
			liveness: () => ({ state: "gone", reason: "止まっている" }),
			authorize: o.authorize,
		}),
	});
	/** /pending を 1 回動かす */
	st.run = async (cwd, args, c = {}) => {
		const answers = [...(c.answers ?? [])];
		st.idle = c.idle ?? true;
		const ctx = {
			cwd,
			mode: c.mode ?? "tui",
			hasUI: c.hasUI ?? true,
			isIdle: () => st.idle,
			ui: {
				notify: (text, level) => st.finals.push({ text, level }),
				setStatus: () => {
					if (c.throwStatus) throw new Error("setStatus の例外");
				},
				onTerminalInput: (h) => {
					st.subscribed++;
					st.inputHandlers.push(h);
					return () => {
						st.unsubscribed++;
						st.inputHandlers = st.inputHandlers.filter((x) => x !== h);
					};
				},
				select: async (title, options) => {
					st.selects.push({ title, options });
					const a = answers.shift();
					if (a === "@throw") throw new Error("select の例外");
					if (a === "@first") return options[0];
					return typeof a === "function" ? a(title, options) : a;
				},
				editor: async () => undefined,
			},
		};
		await commands.pending.handler(args, ctx);
		return ctx;
	};
	return st;
}

const out = {};
const lastFinal = (st) => st.finals[st.finals.length - 1] ?? { text: "", level: "" };
const summary = (st, extra = {}) => ({
	selects: st.selects.length,
	titles: st.selects.map((s) => s.title.split("\n")[0]),
	marks: st.marks,
	sent: st.sent.length,
	final: lastFinal(st),
	...extra,
});

// B8: 巡回の画面の先頭は「ここで終える」。先頭を選ぶ (Enter の連打) と、実行せず終わる
{
	const cwd = repo();
	const ids = saveMany(cwd, ["success", "success", "success"]).map((s) => s.id);
	const st = setup();
	await st.run(cwd, "approve", { answers: ["@first", "@first"] });
	out.b8_first = summary(st, { screenOptions: st.selects[1]?.options, pending: ids.map((i) => states(cwd, i).pending) });
	// 1 件だけのときは、従来の画面 (先頭 = 承認して実行)
	const cwd1 = repo();
	saveMany(cwd1, ["success"]);
	const st1 = setup();
	await st1.run(cwd1, "approve", { answers: ["承認して実行"] });
	out.b8_single = summary(st1, { options: st1.selects[0]?.options });
}

// 始まる条件
{
	const cwd = repo();
	const ids = saveMany(cwd, ["success", "success"]).map((s) => s.id);
	const st = setup();
	await st.run(cwd, `approve ${ids[1]}`, { answers: ["承認して実行"] });
	out.start_with_id = summary(st, { options: st.selects[0]?.options, pending: ids.map((i) => states(cwd, i).pending) });

	const cwdH = repo();
	saveMany(cwdH, ["success", "success"]);
	const stH = setup();
	await stH.run(cwdH, "", { answers: ["@first", "@first"] });
	out.start_hub = summary(stH);

	const cwdG = repo();
	saveMany(cwdG, ["success", "success"]);
	const g = {};
	for (const [name, c, en] of [
		["rpc", { mode: "rpc", answers: ["@first"] }, true],
		["busy", { idle: false, answers: ["@first", "@first"] }, true],
		["disabled", { answers: ["@first", "@first"] }, false],
	]) {
		const s = setup({ enabled: en });
		await s.run(cwdG, "approve", c);
		g[name] = summary(s);
	}
	out.start_guards = g;
}

// B10: Esc・error・abort で、次の画面を開かず全体が止まる。「保留のまま次へ」は止まらない
{
	const r = {};
	const cases = {
		esc: ["@first", "承認して実行", undefined],
		error: ["@first", "承認して実行", "@throw"],
		abort: ["@first", "承認して実行", (_t, _o) => (st_abort.handle.abortAll(), "保留のまま次へ")],
		next: ["@first", "保留のまま次へ", "保留のまま次へ", "保留のまま次へ"],
		stop_here: ["@first", "承認して実行", "@first"],
	};
	let st_abort;
	for (const [name, answers] of Object.entries(cases)) {
		const cwd = repo();
		saveMany(cwd, ["success", "success", "success"]);
		const st = setup();
		st_abort = st;
		await st.run(cwd, "approve", { answers });
		r[name] = summary(st);
	}
	out.b10 = r;
}

// B9: 巡回の間はモデルへ通知しない。終わりに溜めた順で通知する。例外・Esc でも通知する。起きていたら止める
{
	const r = {};
	{
		const cwd = repo();
		saveMany(cwd, ["success", "success", "success"]);
		const st = setup();
		await st.run(cwd, "approve", { answers: ["@first", "承認して実行", "承認して実行", "承認して実行"] });
		r.ok = summary(st, { sentAtSelects: st.sent.map((s) => s.atSelects), tags: st.sent.map((s) => s.details.id), noteSent: st.notes.map((n) => n.sentSoFar) });
	}
	{
		const cwd = repo();
		saveMany(cwd, ["success", "success", "success"]);
		const st = setup();
		st.throwNotifyAt = 2; // 2 件目の利用者への通知で例外
		await st.run(cwd, "approve", { answers: ["@first", "承認して実行", "承認して実行", "承認して実行"] });
		r.exception = summary(st, { sentAtSelects: st.sent.map((s) => s.atSelects) });
	}
	{
		const cwd = repo();
		saveMany(cwd, ["success", "success", "success"]);
		const st = setup();
		await st.run(cwd, "approve", { answers: ["@first", "承認して実行", undefined] });
		r.esc = summary(st, { sentAtSelects: st.sent.map((s) => s.atSelects) });
	}
	{
		// 画面の後で、モデルが起きていた (executeApproval の isIdle)
		const cwd = repo();
		saveMany(cwd, ["success", "success"]);
		const st = setup();
		await st.run(cwd, "approve", { answers: ["@first", () => ((st.idle = false), "承認して実行")] });
		r.awake_after_screen = summary(st);
	}
	{
		// 1 件目の実行の最中にモデルが起きた → 2 件目の前 (planApproval の isIdle) で止まる
		const cwd = repo();
		saveMany(cwd, ["success", "success", "success"]);
		const st = setup();
		st.onExecute = () => (st.idle = false);
		await st.run(cwd, "approve", { answers: ["@first", "承認して実行", "承認して実行"] });
		r.awake_before_item = summary(st);
	}
	out.b9 = r;
}

// B4: 2 件目が成功以外・保存の失敗・後片付けあり・計画の拒否 → 3 件目の画面を開かない
{
	const r = {};
	for (const mode of ["failed_confirmed", "unknown_stopped", "unconfirmed", "not_executed", "savefail", "cleanup", "planfail"]) {
		const cwd = repo();
		const ids = saveMany(cwd, ["success", mode, "success"]).map((s) => s.id);
		const st = setup();
		await st.run(cwd, "approve", { answers: ["@first", "承認して実行", "承認して実行", "承認して実行"] });
		r[mode] = summary(st, { third: states(cwd, ids[2]).pending });
	}
	{
		const cwd = repo();
		const ids = saveMany(cwd, ["success", "success", "success"]).map((s) => s.id);
		const st = setup();
		await st.run(cwd, "approve", { answers: ["@first", "承認して実行", "承認して実行", "承認して実行"] });
		r.all_success = summary(st, { results: ids.map((i) => ({ ...states(cwd, i), result: resultOf(cwd, i) })) });
	}
	{
		// 破棄 → 次へ
		const cwd = repo();
		const ids = saveMany(cwd, ["success", "success", "success"]).map((s) => s.id);
		const st = setup();
		await st.run(cwd, "approve", { answers: ["@first", "破棄", "承認して実行", "保留のまま次へ"] });
		r.discard = summary(st, { first: states(cwd, ids[0]), marks: st.marks });
	}
	out.b4 = r;
}

// B11: snapshot は不変。画面の間に記録が変わったら、古い表示を承認しない
{
	const r = {};
	const cwd = repo();
	const [a, b, c] = saveMany(cwd, ["success", "success", "success"]);
	const st = setup();
	const ctx = { cwd, mode: "tui", hasUI: true, isIdle: () => true, ui: { select: async () => undefined, editor: async () => undefined } };
	const deps = {
		adapters: { fake_op: fakeAdapter(st) },
		enabled: () => true,
		modes: ["tui"],
		rules: {},
		env: ENV,
		dialog: (fn) => fn(),
		bell: () => {},
		owner: () => ({ sessionId: "s", runtimeEpoch: "e", pid: process.pid, processStart: "1", host: "h" }),
		notify: () => {},
		tellModel: (content, details) => st.sent.push({ content, details }),
		liveness: () => ({ state: "gone", reason: "" }),
	};
	const pa = await ap.planApproval(a.id, ctx, deps);
	r.plan = { ok: pa.ok, frozen: pa.ok && Object.isFrozen(pa.snapshot), keys: pa.ok ? Object.keys(pa.snapshot).sort() : [], oidIsShown: pa.ok && pa.snapshot.oid === a.oid };
	// 破棄された
	ops.discardOp(cwd, a.id, a.oid);
	const ea = await ap.executeApproval(pa.snapshot, ctx, deps);
	r.discarded = { kind: ea.kind, marks: st.marks.slice() };
	// 別の承認が先に始まった
	const pb = await ap.planApproval(b.id, ctx, deps);
	ops.beginApproval(cwd, b.id, b.oid, deps.owner());
	const eb = await ap.executeApproval(pb.snapshot, ctx, deps);
	r.taken = { kind: eb.kind, marks: st.marks.slice() };
	// 正常: 構造化した結果
	const pc = await ap.planApproval(c.id, ctx, deps);
	const ec = await ap.executeApproval(pc.snapshot, ctx, deps);
	r.executed = { kind: ec.kind, outcome: ec.outcome, termination: ec.termination, saved: ec.saved, cleanup: ec.cleanup, kept: ec.kept, sent: st.sent.length, result: resultOf(cwd, c.id) };
	// 画面の後に、モデルが起きていた
	const d = save(cwd, "success", "d");
	const pd = await ap.planApproval(d.id, ctx, deps);
	const ed = await ap.executeApproval(pd.snapshot, { ...ctx, isIdle: () => false }, deps);
	r.busy = { kind: ed.kind, pending: states(cwd, d.id).pending, marks: st.marks.slice() };
	// 画面の間の破棄 (巡回の中)
	const cwd2 = repo();
	const ids2 = saveMany(cwd2, ["success", "success"]).map((s) => s.id);
	const st2 = setup();
	await st2.run(cwd2, "approve", { answers: ["@first", () => (ops.discardOp(cwd2, ids2[0], ops.readOp(cwd2, ids2[0]).oid), "承認して実行")] });
	r.patrol_discarded = summary(st2);
	// 置換: 破棄して、同じ ID で別の内容を保存し直す (現在の OID は、表示した OID と違う)。古い表示を承認せず、置換後の記録は pending のまま残る
	{
		const cwd3 = repo();
		const T = Date.now() - 100000;
		const s1 = ops.saveOp(cwd3, record({ params: { mode: "success", tag: "old" } }), undefined, T);
		const st3 = setup();
		const deps3 = { ...deps, adapters: { fake_op: fakeAdapter(st3) } };
		const ctx3 = { ...ctx, cwd: cwd3 };
		const p3 = await ap.planApproval(s1.id, ctx3, deps3);
		ops.discardOp(cwd3, s1.id, s1.oid);
		const s2 = ops.saveOp(cwd3, record({ params: { mode: "success", tag: "new" } }), undefined, T);
		const e3 = await ap.executeApproval(p3.snapshot, ctx3, deps3);
		r.replaced = { sameId: s2.ok && s2.id === s1.id, differentOid: s2.ok && s2.oid !== s1.oid, kind: e3.kind, marks: st3.marks.slice(), ...states(cwd3, s1.id) };
	}
	// 構造化した結果 (B11): 実行器の結果ごとに、実行したか・outcome・停止確認・保存・後片付け・残したか
	r.structured = {};
	r.doneOids = {};
	for (const mode of ["unconfirmed", "savefail", "cleanup", "failed_confirmed", "not_executed", "unknown_stopped"]) {
		const cwdS = repo();
		const sS = save(cwdS, mode, mode);
		const stS = setup();
		const depsS = { ...deps, adapters: { fake_op: fakeAdapter(stS) } };
		const ctxS = { ...ctx, cwd: cwdS };
		const pS = await ap.planApproval(sS.id, ctxS, depsS);
		const eS = await ap.executeApproval(pS.snapshot, ctxS, depsS);
		r.doneOids[mode] = eS.doneOid === undefined ? "none" : eS.doneOid === ops.doneOid(cwdS, sS.id) ? "match" : "other";
		r.structured[mode] = { kind: eS.kind, outcome: eS.outcome, termination: eS.termination, saved: eS.saved, cleanup: eS.cleanup, kept: eS.kept };
	}
	// 結果の通知が例外を投げた (開始の後の内部エラー): 成功に見せず、実行の有無を確定できない扱い
	{
		const cwdT = repo();
		const sT = save(cwdT, "success", "throw-tell");
		const stT = setup();
		const depsT = {
			...deps,
			adapters: { fake_op: fakeAdapter(stT) },
			tellModel: () => {
				throw new Error("boom");
			},
		};
		const ctxT = { ...ctx, cwd: cwdT };
		const pT = await ap.planApproval(sT.id, ctxT, depsT);
		const eT = await ap.executeApproval(pT.snapshot, ctxT, depsT);
		r.throwTell = { kind: eT.kind, outcome: eT.outcome, termination: eT.termination, saved: eT.saved, kept: eT.kept, doneOid: eT.doneOid === ops.doneOid(cwdT, sT.id) ? "match" : "other" };
	}
	// 計画と記録は、アダプターが持つ元の参照から切り離して深く固定する (B11)。元の計画を書き換えても、実行するのは表示した計画
	{
		const cwdD = repo();
		const sD = save(cwdD, "success", "deep");
		const stD = setup();
		const adapterD = fakeAdapter(stD);
		let heldPlan;
		const planOf = adapterD.plan;
		adapterD.plan = async (rec) => {
			const p = await planOf(rec);
			heldPlan = p.plan;
			return p;
		};
		const depsD = { ...deps, adapters: { fake_op: adapterD } };
		const ctxD = { ...ctx, cwd: cwdD };
		const pD = await ap.planApproval(sD.id, ctxD, depsD);
		let writeThrows = false;
		try {
			pD.snapshot.plan.tag = "changed";
		} catch {
			writeThrows = true;
		}
		heldPlan.tag = "tampered"; // アダプターが持っている元の計画を書き換える
		const eD = await ap.executeApproval(pD.snapshot, ctxD, depsD);
		r.deep = {
			planFrozen: Object.isFrozen(pD.snapshot.plan),
			recordFrozen: Object.isFrozen(pD.snapshot.record) && Object.isFrozen(pD.snapshot.record.params),
			writeThrows,
			separate: pD.snapshot.plan !== heldPlan,
			marks: stD.marks.slice(),
			kind: eD.kind,
		};
	}
	// 複製できない形 (関数を含む計画) は、画面の前に断る
	{
		const cwdU = repo();
		const sU = save(cwdU, "success", "unclonable");
		const stU = setup();
		const adapterU = fakeAdapter(stU);
		adapterU.plan = async () => ({ ok: true, plan: { tag: "x", fn: () => 1 }, summary: "要約", view: "全文" });
		const pU = await ap.planApproval(sU.id, { ...ctx, cwd: cwdU }, { ...deps, adapters: { fake_op: adapterU } });
		r.unclonable = { ok: pU.ok, text: pU.ok ? "" : pU.reply.text, ...states(cwdU, sU.id), marks: stU.marks.slice() };
	}
	out.b11 = r;
}

// 上限: 9 件あっても 8 件で終わる
{
	const cwd = repo();
	const ids = saveMany(cwd, Array(9).fill("success")).map((s) => s.id);
	const st = setup();
	await st.run(cwd, "approve", { answers: ["@first", ...Array(10).fill("保留のまま次へ")] });
	out.cap = summary(st, { pendingLeft: ids.filter((i) => states(cwd, i).pending).length });
}

// 一貫性: 巡回の各件が、単件と同じ記録・結果を作る
{
	const cwd = repo();
	const [a, b] = saveMany(cwd, ["success", "success"]);
	const st = setup();
	await st.run(cwd, "approve", { answers: ["@first", "承認して実行", "承認して実行"] });
	const cwdS = repo();
	const [s1] = saveMany(cwdS, ["success"]);
	const stS = setup();
	await stS.run(cwdS, `approve ${s1.id}`, { answers: ["承認して実行"] });
	out.consistency = {
		patrol: [a.id, b.id].map((i) => ({ ...states(cwd, i), result: resultOf(cwd, i) })),
		single: { ...states(cwdS, s1.id), result: resultOf(cwdS, s1.id) },
		patrolLocks: refs(cwd, "refs/pi/lock/").length,
		patrolKeys: refs(cwd, "refs/pi/key/").length,
		singleKeys: refs(cwdS, "refs/pi/key/").length,
		sentDetails: st.sent.map((s) => s.details.outcome),
		singleSent: stS.sent.map((s) => s.details.outcome),
	};
}

// B10: 実行中の Esc は実行を止めず、この件の後で巡回を止める (次の画面は開かない)。購読は実行の間だけ
{
	const cwd = repo();
	const [a, b] = [save(cwd, "success", "esc-run"), save(cwd, "success", "second")];
	const st = setup();
	const during = [];
	st.onExecute = (tag) => {
		during.push({ tag, handlers: st.inputHandlers.length });
		if (tag === "esc-run") for (const h of st.inputHandlers) h("\u001b");
	};
	await st.run(cwd, "approve", { answers: ["@first", "承認して実行", "承認して実行"] });
	const stNo = setup();
	stNo.onExecute = () => {
		// Esc ではない入力 (矢印・文字) は無視する
		for (const h of stNo.inputHandlers) {
			h("\u001b[A");
			h("x");
		}
	};
	const cwdNo = repo();
	saveMany(cwdNo, ["success", "success"]);
	await stNo.run(cwdNo, "approve", { answers: ["@first", "承認して実行", "承認して実行"] });
	out.esc_run = {
		...summary(st),
		during,
		subscribed: st.subscribed,
		unsubscribed: st.unsubscribed,
		handlersLeft: st.inputHandlers.length,
		states: [a.id, b.id].map((i) => states(cwd, i)),
		finalText: lastFinal(st).text,
		noEscMarks: stNo.marks.length,
		noEscSelects: stNo.selects.length,
	};
}

// フッターの更新の例外は、巡回とモデルへの通知を妨げない
{
	const cwd = repo();
	saveMany(cwd, ["success", "success"]);
	const st = setup();
	await st.run(cwd, "approve", { answers: ["@first", "承認して実行", "承認して実行"], throwStatus: true });
	out.status_throws = { marks: st.marks.slice(), sent: st.sent.length, sentAtSelects: st.sent.map((s) => s.atSelects), selects: st.selects.length, final: lastFinal(st) };
}

// 排他ロックを外せなかったとき: 成功・保存済みだが後片付けが残る。次の件の画面は開かない
{
	const cwd = repo();
	const [a, b] = [save(cwd, "lockfail", "lockfail"), save(cwd, "success", "after")];
	const st = setup({ exclusive: true });
	await st.run(cwd, "approve", { answers: ["@first", "承認して実行", "承認して実行"] });
	const stOne = setup({ exclusive: true });
	const cwdOne = repo();
	const o = save(cwdOne, "lockfail", "lockfail-one");
	await stOne.run(cwdOne, `approve ${o.id}`, { answers: ["承認して実行"] });
	out.lock_release_fails = { ...summary(st), states: [a.id, b.id].map((i) => states(cwd, i)), results: [a.id, b.id].map((i) => resultOf(cwd, i)), one: lastFinal(stOne).text };
}

console.log(JSON.stringify(out));

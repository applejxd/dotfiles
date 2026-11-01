// `/pending` の ID 省略 (TUI で選ぶ)・Tab 補完・resolve の対話 (pending-pick.ts) を、偽の pi・偽の ctx・使い捨ての git リポジトリで動かして固定する。
// 結果を JSON で標準出力へ出す。照合は test_pi_pending_pick.py。
//
//   node test/agents/pi/pending_pick_driver.mjs
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const harness = (name) => pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", name)).href;
const ops = await import(harness("pending-ops.ts"));
const cmd = await import(harness("pending-command.ts"));
const pick = await import(harness("pending-pick.ts"));
const view = await import(harness("confirm-view.ts"));
const lk = await import(harness("exclusive-lock.ts"));

const ENV = { ...process.env, GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@example.test", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@example.test" };
const git = (cwd, ...args) => execFileSync("git", args, { cwd, env: ENV, encoding: "utf8" }).trim();
const refs = (cwd, ns) => git(cwd, "for-each-ref", "--format=%(refname)", ns).split("\n").filter(Boolean);

function repo() {
	const dir = mkdtempSync(join(tmpdir(), "pi-pick-"));
	git(dir, "init", "-q", "-b", "main");
	writeFileSync(join(dir, "seed.txt"), "seed\n");
	git(dir, "add", "-A");
	git(dir, "commit", "-q", "-m", "seed");
	return dir;
}

let serial = 0;
const record = (over = {}) => ({
	action: "fake_op",
	params: { note: `n${serial++}` },
	premise: { x: 1 },
	reason: "request",
	request: { id: `req-${serial}`, sessionId: "s-req", cwd: "/w" },
	createdAt: new Date().toISOString(),
	...over,
});
const save = (cwd, over = {}) => {
	const r = ops.saveOp(cwd, record(over));
	if (!r.ok) throw new Error(`save failed: ${r.reason}`);
	return r;
};
const owner = (session) => ({ sessionId: session, runtimeEpoch: "e", pid: process.pid, processStart: "100", host: "h" });
const liveness = (o) => (o.sessionId.startsWith("alive") ? { state: "alive", reason: "生きている" } : { state: "gone", reason: "止まっている" });
const UNKNOWN = { outcome: "unknown", phase: "commit", confirmedEffects: [], remainingCleanup: ["中途の状態の可能性"], evidence: ["停止を確認できない"] };
const SUCCESS = { outcome: "success", phase: "done", confirmedEffects: ["実行した"], remainingCleanup: [], evidence: [] };

/** running (reserved か started)。lock = true なら統合ロックも持たせる */
function running(cwd, over, { started, lock } = {}) {
	const a = save(cwd, over);
	const begin = ops.beginApproval(cwd, a.id, a.oid, owner("dead-a"));
	if (!begin.ok) throw new Error(begin.reason);
	let attempt = begin.attempt;
	if (started) {
		const st = ops.markStarted(cwd, a.id, begin.attemptOid);
		if (!st.ok) throw new Error(st.reason);
		attempt = st.attempt;
	}
	if (lock) {
		const got = lk.acquireLock(cwd, { runningId: a.id, attemptId: attempt.attemptId }, { probe: () => ({ attempt: "absent", owner: "unknown" }) });
		if (!got.ok) throw new Error(got.reason);
	}
	return a.id;
}
function doneUnknown(cwd, over) {
	const a = save(cwd, over);
	const begin = ops.beginApproval(cwd, a.id, a.oid, owner("dead-a"));
	const st = ops.markStarted(cwd, a.id, begin.attemptOid);
	const fin = ops.finishApproval(cwd, a.id, st.attemptOid, UNKNOWN);
	if (!fin.ok) throw new Error(fin.reason);
	return a.id;
}
function doneSuccess(cwd, over) {
	const a = save(cwd, over);
	const begin = ops.beginApproval(cwd, a.id, a.oid, owner("dead-a"));
	const st = ops.markStarted(cwd, a.id, begin.attemptOid);
	const fin = ops.finishApproval(cwd, a.id, st.attemptOid, SUCCESS);
	if (!fin.ok) throw new Error(fin.reason);
	return a.id;
}

const adapterOf = (action, marks, over = {}) => ({
	action,
	label: "試験の操作",
	plan: async (rec) => ({ ok: true, plan: {}, summary: "要約の行", view: "全文の本文" }),
	recheck: async () => ({ ok: true }),
	execute: async () => {
		marks.push(`execute:${action}`);
		return { outcome: "success", phase: "done", confirmedEffects: ["操作を実行した"], remainingCleanup: [], evidence: [] };
	},
	...over,
});

const LONG_ACTION = "long_action_name_abcdef";

function setup() {
	const state = { marks: [], throwDeps: false, lastNotes: [] };
	const commands = {};
	const pi = { registerCommand: (name, def) => (commands[name] = def), registerTool: () => { throw new Error("registerTool は呼ばない"); } };
	const adapters = () => ({
		fake_op: adapterOf("fake_op", state.marks),
		excl_op: adapterOf("excl_op", state.marks, { exclusive: true }),
		briefed_op: adapterOf("briefed_op", state.marks, { brief: (rec) => `<<${rec.params.note}>> 日本語の長い要約をここに書く\n二行目\u001b[31m` }),
		[LONG_ACTION]: adapterOf(LONG_ACTION, state.marks, { brief: () => "とても長い日本語の要約文字列をここに並べて幅を超えさせる" }),
	});
	const approveDeps = () => {
		if (state.throwDeps) throw new Error("deps が壊れた");
		return {
			adapters: adapters(),
			enabled: () => true,
			modes: ["tui"],
			rules: {},
			env: ENV,
			dialog: (fn) => fn(),
			bell: () => {},
			owner: () => owner("s-appr"),
			notify: () => {},
			tellModel: () => {},
			liveness,
		};
	};
	cmd.registerPendingCommand(pi, {
		settings: () => cmd.pendingSettings({ enabled: true, modes: ["tui"] }),
		redact: (t) => t,
		approveDeps,
	});
	state.approveDeps = approveDeps;
	state.run = async (cwd, args, c = {}) => {
		const notes = [];
		const selects = [];
		const answers = [...(c.answers ?? [])];
		const ctx = {
			cwd,
			mode: c.mode ?? "tui",
			hasUI: c.hasUI ?? true,
			isIdle: () => true,
			ui: {
				notify: (text, level) => notes.push({ text, level }),
				setStatus: () => {},
				select: async (title, options) => {
					selects.push({ title, options });
					const a = answers.shift();
					return typeof a === "function" ? a(options) : a;
				},
				editor: async () => undefined,
			},
		};
		await commands.pending.handler(args, ctx);
		return { text: notes.map((n) => n.text).join("\n"), level: notes[0]?.level, selects };
	};
	state.commands = commands;
	return state;
}

const stateOf = (cwd, id) => ({
	pending: refs(cwd, "refs/pi/pending/").includes(`refs/pi/pending/${id}`),
	running: refs(cwd, "refs/pi/running/").includes(`refs/pi/running/${id}`),
	done: refs(cwd, "refs/pi/done/").includes(`refs/pi/done/${id}`),
});
const lockCount = (cwd) => refs(cwd, "refs/pi/lock/").length;
const byPrefix = (p) => (options) => options.find((o) => o.startsWith(p));
// eslint 相当の制御文字検査 (改行・タブ・ESC などが 1 つでもあれば true)
const hasControl = (s) => /[\u0000-\u001f\u007f-\u009f]/.test(s);

const out = {};

// 1. 候補: 種類ごとに、何が出るか・順序・ラベルの幅
{
	const cwd = repo();
	const h = setup();
	const p1 = save(cwd, { action: "fake_op", params: { note: "最初の引数の一行目\n二行目" } }).id;
	const p2 = save(cwd, { action: "other_op" }).id; // アダプタ無し
	const p3 = save(cwd, { action: LONG_ACTION }).id;
	const p4 = save(cwd, { action: "briefed_op", params: { note: "ABC" } }).id;
	const p5 = save(cwd, { action: "fake_op", params: { note: "x\u001b[31m赤い制御文字" } }).id;
	const r1 = running(cwd, { action: "excl_op" }, { started: true });
	const d1 = doneUnknown(cwd, { action: "fake_op" });
	const d2 = doneSuccess(cwd, { action: "fake_op" });
	const deps = h.approveDeps({ cwd });
	const c = (kind) => pick.pickCandidates(cwd, kind, deps);
	const tail = (id) => id.slice(-6);
	const labels = Object.fromEntries(["approve", "show", "drop", "resolve"].map((k) => [k, c(k).map((x) => x.label)]));
	const all = Object.values(labels).flat();
	out.cands = {
		ids: { p1, p2, p3, p4, p5, r1, d1, d2 },
		approve: c("approve").map((x) => x.id),
		show: c("show").map((x) => x.id),
		drop: c("drop").map((x) => x.id),
		resolve: c("resolve").map((x) => x.id),
		maxWidth: Math.max(...all.map((l) => view.cellWidth(l))),
		anyControl: all.some(hasControl),
		anyNewline: all.some((l) => l.includes("\n")),
		longLabel: c("approve").find((x) => x.id === p3).label,
		briefLabel: c("approve").find((x) => x.id === p4).label,
		firstArgLabel: c("approve").find((x) => x.id === p1).label,
		ctrlLabel: c("approve").find((x) => x.id === p5).label,
		tails: Object.fromEntries(Object.entries({ p1, p3, p4, p5 }).map(([k, id]) => [k, tail(id)])),
		sortedNewestFirst: c("show").every((x, i, a) => i === 0 || a[i - 1].id > x.id),
	};
}

// 2. 選択 (chooseId): 0 件・1 件・複数・キャンセル。選んだ ID は、ID 指定と同じ経路に進む
{
	const h = setup();
	// 2-0. 0 件
	{
		const cwd = repo();
		const r = {};
		for (const sub of ["approve", "show", "drop"]) {
			const x = await h.run(cwd, sub);
			r[sub] = { text: x.text, selects: x.selects.length };
		}
		out.zero = { ...r, marks: h.marks.length };
	}
	// 2-1. approve 1 件: 選ばずに承認の画面へ。ID 指定と同じ結果
	{
		const a = repo();
		const b = repo();
		const ia = save(a, { params: { note: "same" } }).id;
		const ib = save(b, { params: { note: "same" } }).id;
		const viaPick = await h.run(a, "approve", { answers: ["承認して実行"] });
		const viaId = await h.run(b, `approve ${ib}`, { answers: ["承認して実行"] });
		out.approve_one = {
			pick: { text: viaPick.text.replace(ia, "ID"), level: viaPick.level, selects: viaPick.selects.map((s) => ({ title: s.title.replace(ia, "ID"), options: s.options })), state: stateOf(a, ia) },
			id: { text: viaId.text.replace(ib, "ID"), level: viaId.level, selects: viaId.selects.map((s) => ({ title: s.title.replace(ib, "ID"), options: s.options })), state: stateOf(b, ib) },
		};
	}
	// 2-2. show 1 件
	{
		const a = repo();
		const id = save(a).id;
		const viaPick = await h.run(a, "show");
		const viaId = await h.run(a, `show ${id}`);
		out.show_one = { same: viaPick.text === viaId.text, selects: viaPick.selects.length, hasId: viaPick.text.includes(id) };
	}
	// 2-3. drop 1 件: 選択を出す (やめる / その 1 件)
	{
		const a = repo();
		const id = save(a).id;
		const cancel = await h.run(a, "drop", { answers: [(o) => o.find((x) => x.includes("やめる"))] });
		const escaped = await h.run(a, "drop", { answers: [undefined] });
		const stillThere = stateOf(a, id).pending;
		const done = await h.run(a, "drop", { answers: [(o) => o[0]] });
		out.drop_one = {
			options: cancel.selects[0].options.length,
			firstHasTail: cancel.selects[0].options[0].startsWith("fake_op"),
			cancelText: cancel.text,
			escText: escaped.text,
			stillThere,
			doneText: done.text,
			after: stateOf(a, id).pending,
		};
	}
	// 2-4. 2 件以上: select が出る。title・選択肢 = ラベル (新しい順)。キャンセルで何も起きない。選んだ ID で ID 指定と同じ経路
	{
		const a = repo();
		const i1 = save(a, { params: { note: "older" } }).id;
		const i2 = save(a, { params: { note: "newer" } }).id;
		const marksBefore = h.marks.length;
		const none = await h.run(a, "approve", { answers: [undefined] });
		const noneMarks = h.marks.length - marksBefore;
		const noneStates = [stateOf(a, i1).pending, stateOf(a, i2).pending];
		const labels = pick.pickCandidates(a, "approve", h.approveDeps({ cwd: a })).map((x) => x.label);
		const second = await h.run(a, "approve", { answers: [(o) => o[1], "承認して実行"] });
		out.many = {
			ids: [i1, i2],
			selectCount: none.selects.length,
			title: none.selects[0].title,
			optionsAreLabels: JSON.stringify(none.selects[0].options) === JSON.stringify(labels),
			noneText: none.text,
			noneMarks,
			noneStates,
			secondSelects: second.selects.length,
			secondOptions: second.selects[1]?.options ?? null,
			secondStates: [stateOf(a, i1).pending, stateOf(a, i2).pending],
			secondText: second.text,
		};
	}
	// 2-5. TUI でない: approve は断る・選択を出さない。show / drop も選択を出さない (従来の USAGE)
	{
		const a = repo();
		const i1 = save(a).id;
		save(a);
		const approve = await h.run(a, "approve", { mode: "rpc" });
		const noUi = await h.run(a, "approve", { hasUI: false });
		const show = await h.run(a, "show", { mode: "rpc" });
		const drop = await h.run(a, "drop", { hasUI: false });
		out.non_tui = {
			approve: approve.text,
			noUi: noUi.text,
			selects: approve.selects.length + noUi.selects.length + show.selects.length + drop.selects.length,
			showText: show.text.slice(0, 9),
			dropText: drop.text.slice(0, 9),
			still: stateOf(a, i1).pending,
		};
	}
}

// 3. 補完
{
	const h = setup();
	const cwd = repo();
	const ids = [save(cwd).id, save(cwd, { action: "other_op" }).id, save(cwd).id];
	await h.run(cwd, "list");
	const comp = h.commands.pending.getArgumentCompletions;
	const items = (p) => comp(p);
	const sub = items("");
	const ap = items("ap");
	const approve = items("approve ");
	const prefixed = items(`approve ${ids[2].slice(0, ids[2].length - 1)}`);
	const none = items(`approve ${"9".repeat(15)}`);
	out.completion = {
		isFunction: typeof comp === "function",
		sub: sub?.map((x) => x.value),
		subShape: sub?.every((x) => typeof x.value === "string" && typeof x.label === "string"),
		ap: ap?.map((x) => x.value),
		approveValues: approve?.map((x) => x.value),
		approveIds: ids.filter((i) => i !== ids[1]).reverse().map((i) => `approve ${i}`),
		approveLabels: approve?.map((x) => x.label),
		expectedLabels: pick.pickCandidates(cwd, "approve", h.approveDeps({ cwd })).map((x) => x.label),
		prefixed: prefixed?.map((x) => x.value),
		prefixedExpect: [`approve ${ids[2]}`],
		none,
		show: items("show ")?.map((x) => x.value),
		list: items("list "),
		unknown: items("bogus "),
	};
	h.throwDeps = true;
	out.completion.thrown = items("approve ");
}

// 4. resolve の対話
{
	const h = setup();
	const optionOf = (options, kind) => options.find((o) => o.startsWith(kind));
	// 4-1. reserved の running: pending / abandon だけ
	{
		const cwd = repo();
		const id = running(cwd, { action: "fake_op" }, { started: false });
		const r = await h.run(cwd, "resolve", { answers: [(o) => o[0], (o) => optionOf(o, "pending")] });
		out.reserved = { selects: r.selects.map((s) => s.options), text: r.text, state: stateOf(cwd, id) };
	}
	// 4-2. started (排他でない操作): success / failed / retry。止まった確認は出ない
	{
		const cwd = repo();
		const id = running(cwd, { action: "fake_op" }, { started: true });
		const r = await h.run(cwd, "resolve", { answers: [(o) => o[0], (o) => optionOf(o, "failed")] });
		out.started_plain = { selects: r.selects.map((s) => s.options), text: r.text, state: stateOf(cwd, id) };
	}
	// 4-3. started の排他の操作: 止まった確認が出る。「確かめていない」で断られ、「確かめた」で決着してロックが外れる
	{
		const cwd = repo();
		const id = running(cwd, { action: "excl_op" }, { started: true, lock: true });
		const no = await h.run(cwd, "resolve", { answers: [(o) => o[0], (o) => optionOf(o, "success"), (o) => o.find((x) => x.includes("確かめていない"))] });
		const afterNo = { state: stateOf(cwd, id), locks: lockCount(cwd) };
		const yes = await h.run(cwd, "resolve", { answers: [(o) => o[0], (o) => optionOf(o, "success"), (o) => o.find((x) => x.includes("確かめた") && !x.includes("確かめていない"))] });
		out.exclusive = {
			noSelects: no.selects.map((s) => ({ title: s.title, options: s.options })),
			noText: no.text,
			afterNo,
			yesText: yes.text,
			afterYes: { state: stateOf(cwd, id), locks: lockCount(cwd) },
		};
	}
	// 4-4. executor の unknown (done): success / failed
	{
		const cwd = repo();
		const id = doneUnknown(cwd, { action: "fake_op" });
		const r = await h.run(cwd, "resolve", { answers: [(o) => o[0], (o) => optionOf(o, "success")] });
		out.unknown = { selects: r.selects.map((s) => s.options), text: r.text, resolved: ops.readResultAt(cwd, id, ops.doneOid(cwd, id)).result?.resolvedBy };
	}
	// 4-5. ID だけ (resolve <id>): ID の選択を出さず、結果の種類から
	{
		const cwd = repo();
		const id = running(cwd, { action: "fake_op" }, { started: false });
		const r = await h.run(cwd, `resolve ${id}`, { answers: [(o) => optionOf(o, "abandon")] });
		out.id_only = { selects: r.selects.length, text: r.text, state: stateOf(cwd, id) };
	}
	// 4-6. 従来の resolve <id> <kind>: 選択を出さない。TUI でない対話は断る。キャンセルで何も起きない
	{
		const cwd = repo();
		const id = running(cwd, { action: "fake_op" }, { started: false });
		const rpc = await h.run(cwd, "resolve", { mode: "rpc" });
		const esc = await h.run(cwd, "resolve", { answers: [(o) => o[0], undefined] });
		const old = await h.run(cwd, `resolve ${id} abandon`);
		out.classic = { rpc: rpc.text, rpcSelects: rpc.selects.length, esc: esc.text, escState: null, old: old.text, oldSelects: old.selects.length, state: stateOf(cwd, id) };
	}
}

// 5. 同じ表示の候補は、ラベルの末尾に ID の末尾 4 桁を添えて区別する。ほかは ID を出さない
{
	const cwd = repo();
	const h = setup();
	const d1 = save(cwd, { params: { note: "same" }, premise: { x: 1 } }).id;
	const d2 = save(cwd, { params: { note: "same" }, premise: { x: 2 } }).id;
	const u = save(cwd, { params: { note: "unique" } }).id;
	const c = pick.pickCandidates(cwd, "approve", h.approveDeps({ cwd }));
	const by = (id) => c.find((x) => x.id === id).label;
	out.dup = { d1: by(d1), d2: by(d2), u: by(u), tails: [d1.slice(-4), d2.slice(-4)], maxWidth: Math.max(...c.map((x) => view.cellWidth(x.label))) };
}

// 6. 末尾一致の指定 (数字だけで 15 桁未満)
{
	const h = setup();
	const cwd = repo();
	const a1 = save(cwd).id;
	const a2 = save(cwd).id;
	const r1 = running(cwd, { action: "excl_op" }, { started: true });
	const viaTail = await h.run(cwd, `show ${a1.slice(-4)}`);
	const viaId = await h.run(cwd, `show ${a1}`);
	const full = await h.run(cwd, "show 000000000000000");
	const short2 = await h.run(cwd, `show ${a1.slice(-2)}`);
	const short1 = await h.run(cwd, `drop ${a1.slice(-1)}`);
	const zero = await h.run(cwd, "show 9999999");
	const approveRunning = await h.run(cwd, `approve ${r1.slice(-4)}`);
	const showRunning = await h.run(cwd, `show ${r1.slice(-4)}`);
	const approveTail = await h.run(cwd, `approve ${a2.slice(-4)}`, { answers: ["承認して実行"] });
	out.tail = {
		uniqueSame: viaTail.text === viaId.text && viaTail.text.includes(a1) && viaTail.selects.length === 0,
		full: full.text,
		short2: short2.text,
		short1: short1.text,
		still: stateOf(cwd, a1).pending,
		zero: zero.text,
		approveRunning: approveRunning.text,
		showRunning: showRunning.text.includes(r1),
		approveTail: { text: approveTail.text, state: stateOf(cwd, a2) },
	};
	// 複数: 3 桁の末尾が同じ候補を 2 件以上作る
	const many = repo();
	const lim = { maxPending: 1000, maxRecordBytes: 64 * 1024, maxScan: 1000 };
	const seen = new Map();
	let token = null;
	for (let i = 0; i < 800 && !token; i++) {
		const r = ops.saveOp(many, record(), lim);
		if (!r.ok) throw new Error(r.reason);
		const t = r.id.slice(-3);
		if (seen.has(t)) token = t;
		seen.set(t, [...(seen.get(t) ?? []), r.id]);
	}
	out.tail.found = token !== null;
	if (token) {
		const match = pick.pickCandidates(many, "drop", h.approveDeps({ cwd: many }), Date.now()).filter((x) => x.id.endsWith(token));
		const rpc = await h.run(many, `show ${token}`, { mode: "rpc" });
		const cancel = await h.run(many, `drop ${token}`, { answers: [undefined] });
		const firstStillThere = stateOf(many, match[0].id).pending;
		const chosen = await h.run(many, `drop ${token}`, { answers: [(o) => o[0]] });
		out.tail.many = {
			matches: match.length,
			rpc: rpc.text,
			rpcSelects: rpc.selects.length,
			optionsAreMatches: JSON.stringify(cancel.selects[0].options) === JSON.stringify(match.map((x) => x.label)),
			cancel: cancel.text,
			firstStillThere,
			chosenText: chosen.text,
			firstGone: !stateOf(many, match[0].id).pending,
			secondStillThere: stateOf(many, match[1].id).pending,
		};
	}
}

// 7. 退避 (旧形式) は show の候補には出るが drop の候補には出ない。末尾一致は、末尾でない位置の桁 (部分一致) を拾わない
{
	const h = setup();
	const cwd = repo();
	const a = save(cwd).id;
	const legacyId = "000000000000777";
	git(cwd, "update-ref", `refs/pi/pending/${legacyId}`, "HEAD"); // 旧形式: 名乗りが無く、新形式のファイル 1 つだけの tree でもない
	const deps = h.approveDeps({ cwd });
	const ids = (kind) => pick.pickCandidates(cwd, kind, deps, Date.now()).map((c) => c.id);
	const mid = [a.slice(-8, -4), a.slice(-9, -5), a.slice(-10, -6)].find((t) => ![a, legacyId].some((id) => id.endsWith(t)));
	const viaMiddle = await h.run(cwd, `show ${mid}`);
	out.legacy_and_middle = { a, legacyId, show: ids("show"), drop: ids("drop"), approve: ids("approve"), mid, middleText: viaMiddle.text, middleSelects: viaMiddle.selects.length };
}

console.log(JSON.stringify(out));

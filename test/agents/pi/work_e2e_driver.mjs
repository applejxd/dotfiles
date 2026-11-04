// 作業台帳の端から端まで (store → core → adapt → sched・digest) の統合試験用 driver。照合は test_work_e2e.py。
//
//   node test/agents/pi/work_e2e_driver.mjs replay <root> [stage]   シナリオを store へ永続し、別の store で読み直して畳み、メモリ上の畳み込みと比べる
//   node test/agents/pi/work_e2e_driver.mjs child <root>            lease を取ってシナリオ (ready まで) を永続し、note を ack 付きで追記し続ける (kill -9 の標的)
//   node test/agents/pi/work_e2e_driver.mjs recover <root>          読み直して畳み、不変条件と ack の欠落を調べる
//   node test/agents/pi/work_e2e_driver.mjs sched <variant>         メモリ上のシナリオから schedStateOf → next() し、start を reduce へ当てる
//   node test/agents/pi/work_e2e_driver.mjs digest                  完了した run から digestInputOf → makeDigest → toModelText
//   node test/agents/pi/work_e2e_driver.mjs forge <root>            利用者専用イベントの偽装を試す
// see docs/spec/work/ledger.md#接続と統合試験
import { writeSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const WORK = join(ROOT, "home", "dot_config", "pi", "harness", "work");
const load = (f) => import(pathToFileURL(join(WORK, f)).href);
const [store, ev, rd, inv, pj, ad, sc, dg] = await Promise.all(
	["store.ts", "events.ts", "reduce.ts", "invariants.ts", "project.ts", "adapt.ts", "sched.ts", "digest.ts"].map(load),
);

const out = (s) => writeSync(1, s);
const H = "holder-A";
const BIG = { usd: 100, tokens: 10_000_000, ms: 10_000_000_000 };
const EST = { usd: 1, tokens: 1000, ms: 1000 };

/** シナリオの段: planned (承認前) → ready (承認と task の追加まで) → full (run・検査・予算の調整まで) */
export function scenario(stage = "full", opts = {}) {
	const E = ev.makeEvent;
	const budget = opts.budget ?? BIG;
	const tasks = opts.tasks ?? [
		["T1", ["src/a/**"], [], "worker", "S"],
		["T2", ["src/a/x.ts"], [], "worker", "S"],
		["T3", ["docs/**"], [], "worker", "M"],
		["T4", ["lib/**"], ["T1", "T3"], "worker", "S"],
	];
	const evs = [
		[E("goal.created", "G", { title: "統合試験の goal", budget }, "system")],
		[E("plan.proposed", "G", { hash: "h1" }, "model")],
		[E("lease.acquired", "G", { holder: H, pid: process.pid }, "system")],
	];
	if (stage === "planned") return evs.flat();
	const h = (type, node, data, source = "system") => E(type, node, data, source, { holder: H });
	evs.push([h("plan.approved", "G", { hash: "h1" }, "user")]);
	for (const [id, writes, after, role, size] of tasks) {
		evs.push([h("node.added", id, { node: { kind: "task", parent: "G", title: `task ${id}`, writes, after, attrs: { role, size } } }, "model")]);
	}
	if (stage === "ready") return evs.flat();
	evs.push(
		[h("run.reserved", "R1", { task: "T1", est: EST }), h("run.started", "R1", { pid: 4242 })],
		[h("note.appended", "R1", { by: "run:R1", text: "## 結論\nsrc/a を直した。試験は全部通った。" }, "model")],
		[h("run.usage", "R1", { usage: { usd: 0.2, tokens: 300, ms: 400 } })],
		[h("run.ended", "R1", { status: "done", usage: { usd: 0.3, tokens: 500, ms: 700 }, digestId: "d1" })],
		[h("check.result", "T1", { name: "pytest", ok: true })],
		[h("note.appended", "T3", { by: "user", text: "docs は後でよい" }, "user")],
		[h("note.appended", "T3", { by: "llm", text: "docs は T1 の後で着手する" }, "model")],
		[h("budget.adjusted", "G", { budget: { usd: 200, tokens: 20_000_000, ms: 20_000_000_000 } }, "user")],
	);
	return evs.flat();
}

/** イベント列を seq・ts 付きでメモリ上へ畳む (store を通さない基準) */
export function foldMemory(newEvents) {
	const evs = newEvents.map((e, i) => ({ ...e, seq: i + 1, ts: 1000 + i }));
	return { events: evs, state: rd.fold(evs) };
}

const ser = (s) => JSON.stringify(rd.serialize(s));
const canon = (x) => JSON.stringify(x, (_k, v) => (v && typeof v === "object" && !Array.isArray(v) ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => (a < b ? -1 : 1))) : v));
const viol = (s) => inv.check(s).map((v) => `${v.inv}:${v.node ?? ""}:${v.message}`);
const readyIds = (s) => pj.ready(s).map((n) => n.id);

async function persist(root, newEvents, { pid = process.pid } = {}) {
	const st = store.createStore({ root, pid });
	const lease = await st.acquireLease(H, pid);
	if (!lease) throw new Error("lease が取れない");
	const acks = [];
	for (const e of newEvents) acks.push(await st.append(e));
	return { st, acks };
}

async function replay(root, stage) {
	const evs = scenario(stage);
	const { acks } = await persist(root, evs);
	// メモリ上の基準: store を通さないで (seq・ts を ack と同じにして) 直接畳む
	const mem = { state: rd.fold(evs.map((e, i) => ({ ...e, seq: i + 1, ts: acks[i].ts }))) };
	const st2 = store.createStore({ root });
	const res = await st2.load();
	const state = rd.fold(res.events);
	out(
		`${JSON.stringify({
			n: evs.length,
			sameState: ser(state) === ser(mem.state),
			sameEvents: canon(res.events) === canon(acks),
			seqs: res.events.map((e) => e.seq),
			sources: res.events.map((e) => e.source ?? null),
			holders: res.events.map((e) => e.holder ?? null),
			expectSources: evs.map((e) => e.source ?? null),
			expectHolders: evs.map((e) => e.holder ?? null),
			violations: viol(state),
			violationsMem: viol(mem.state),
			readyMem: readyIds(mem.state),
			readyLoaded: readyIds(state),
			nodes: [...state.nodes.keys()],
			owner: state.nodes.get("G")?.owner ?? null,
			recovered: res.recovered ?? false,
			degraded: res.degraded ?? null,
		})}\n`,
	);
}

async function child(root) {
	const evs = scenario("ready");
	const st = store.createStore({ root });
	const lease = await st.acquireLease(H, process.pid);
	if (!lease) {
		out("nolease\n");
		return;
	}
	for (const e of evs) await st.append(e);
	out("ready\n");
	for (let i = 0; ; i++) {
		const pad = "y".repeat((i * 37) % 250);
		const a = await st.append(ev.makeEvent("note.appended", "T3", { by: "llm", text: `n${i} ${pad}` }, "model", { holder: H }));
		out(`ack ${a.seq} ${i}\n`);
	}
}

async function recover(root) {
	const st = store.createStore({ root });
	const res = await st.load();
	const state = rd.fold(res.events);
	out(
		`${JSON.stringify({
			count: res.events.length,
			seqs: res.events.map((e) => e.seq),
			notes: res.events.filter((e) => e.type === "note.appended").map((e) => ({ seq: e.seq, text: e.data.text })),
			violations: viol(state),
			recovered: res.recovered ?? false,
			degraded: res.degraded ?? null,
			ready: readyIds(state),
		})}\n`,
	);
}

const RES = { slots: 4, hot: [] };

function schedCase(variant) {
	const T = (id, writes, after = []) => [id, writes, after, "worker", "S"];
	switch (variant) {
		case "basic":
			return { tasks: undefined };
		case "tinybudget":
			return { budget: { usd: 0.0001, tokens: 1, ms: 1 } };
		case "slots1":
			return { tasks: [T("T1", ["a/**"]), T("T2", ["b/**"]), T("T3", ["c/**"])], slots: 1 };
		case "disjoint":
			return { tasks: [T("T1", ["a/**"]), T("T2", ["b/**"]), T("T3", ["c/**"])] };
		case "named":
			// 名指しの writes。スケジューラが同時に start した task は、台帳の門 (run.reserved) も通らなければならない
			return { tasks: [T("T1", ["scripts/verify.py"]), T("T2", ["*.py"]), T("T3", ["src/**/*.ts"]), T("T4", ["src/a.ts"])] };
		default:
			throw new Error(`unknown variant ${variant}`);
	}
}

function sched(variant) {
	const c = schedCase(variant);
	const { state } = foldMemory(scenario("ready", { tasks: c.tasks, budget: c.budget }));
	const res = { ...RES, slots: c.slots ?? RES.slots };
	const ss = ad.schedStateOf(state, { now: 5000, resources: res });
	const acts = sc.next(ss, res, 5000);
	const starts = acts.filter((a) => a.kind === "start");
	// start を台帳へ当てる (run.reserved)。門で拒否されたら、スケジューラと台帳の食い違い
	let s = state;
	const rejected = [];
	starts.forEach((a, i) => {
		const e = { ...ev.makeEvent("run.reserved", `RS${i}`, { task: a.task, est: a.reserve }, "system", { holder: H }), seq: s.seq + 1, ts: 9000 + i };
		try {
			s = rd.reduce(s, e);
		} catch (err) {
			rejected.push(`${a.task}: ${String(err.message)}`);
		}
	});
	out(
		`${JSON.stringify({
			actions: acts.map((a) => a.kind),
			starts: starts.map((a) => a.task),
			reserves: starts.map((a) => a.reserve),
			ready: readyIds(state),
			schedTasks: ss.tasks.map((t) => `${t.id}:${t.state}`),
			schedBudget: ss.budget ?? null,
			rejected,
			violations: viol(s),
		})}\n`,
	);
}

function digest() {
	const { state } = foldMemory(scenario("full"));
	const input = ad.digestInputOf(state, "R1");
	const d = dg.makeDigest(input);
	const text = dg.toModelText(d);
	out(
		`${JSON.stringify({
			input: { ...input },
			status: d.status,
			text,
			textLen: [...text].length,
			line: dg.toLine(d),
			nonRun: ad.digestInputOf(state, "T1"),
			unknown: ad.digestInputOf(state, "nope"),
			live: (() => {
				const m = foldMemory(scenario("full").slice(0, scenario("full").findIndex((e) => e.type === "run.ended")));
				return ad.digestInputOf(m.state, "R1");
			})(),
		})}\n`,
	);
}

async function forge(root) {
	const res = {};
	const tryMake = (name, fn) => {
		try {
			const e = fn();
			res[name] = { ok: true, event: e };
		} catch (err) {
			res[name] = { ok: false, name: err.name, message: String(err.message) };
		}
	};
	tryMake("approved_data_user", () => ev.makeEvent("plan.approved", "G", { hash: "h1", source: "user" }, "model"));
	tryMake("approved_system", () => ev.makeEvent("plan.approved", "G", { hash: "h1" }, "system"));
	tryMake("budget_model", () => ev.makeEvent("budget.adjusted", "G", { budget: BIG, source: "user" }, "model"));
	tryMake("resolved_user_model", () => ev.makeEvent("wait.resolved", "T1", { ref: "x", by: "user" }, "model"));
	tryMake("holder_in_data", () => ev.makeEvent("note.appended", "T1", { by: "llm", text: "x", holder: "evil", source: "user" }, "model"));
	// 検証を通らない生のイベント (store は検証しない) を永続し、再生で reducer が拒否するか
	const evs = scenario("planned");
	const { st } = await persist(root, evs);
	await st.append({ type: "plan.approved", node: "G", data: { hash: "h1", source: "user" }, source: "model", holder: H });
	await st.append({ type: "plan.approved", node: "G", data: { hash: "h1", source: "user" }, holder: H });
	const st2 = store.createStore({ root });
	const loaded = await st2.load();
	try {
		rd.fold(loaded.events);
		res.replayStrict = { ok: true };
	} catch (err) {
		res.replayStrict = { ok: false, name: err.name, message: String(err.message) };
	}
	let s = rd.emptyState();
	const errs = [];
	for (const e of loaded.events) {
		try {
			s = rd.reduce(s, e);
		} catch (err) {
			errs.push(`${e.seq}:${e.type}`);
		}
	}
	res.replayTolerant = { rejected: errs, goalState: s.nodes.get("G")?.state, violations: viol(s), sources: loaded.events.map((e) => e.source ?? null) };
	out(`${JSON.stringify(res)}\n`);
}

const [, , cmd, ...args] = process.argv;
if (cmd === "replay") await replay(args[0], args[1] ?? "full");
else if (cmd === "child") await child(args[0]);
else if (cmd === "recover") await recover(args[0]);
else if (cmd === "sched") sched(args[0]);
else if (cmd === "digest") digest();
else if (cmd === "forge") await forge(args[0]);
else {
	process.stderr.write(`unknown command: ${cmd}\n`);
	process.exit(2);
}

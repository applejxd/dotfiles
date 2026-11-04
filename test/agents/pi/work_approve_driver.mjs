// 承認の時点の task だけをスケジューラが自動起動する (Node.approved) の試験用 driver。照合は test_work_approve.py。
//   node test/agents/pi/work_approve_driver.mjs   全シナリオを実行し、結果を JSON で標準出力へ出す
// see docs/spec/work/ledger.md#設計上の判断
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const W = resolve(ROOT, "home", "dot_config", "pi", "harness", "work");
const load = (f) => import(pathToFileURL(resolve(W, f)).href);
const [rd, ev, ad, sc, inv, tool, store, pj] = await Promise.all(
	["reduce.ts", "events.ts", "adapt.ts", "sched.ts", "invariants.ts", "tool.ts", "store.ts", "project.ts"].map(load),
);

const BIG = { usd: 100, tokens: 10_000_000, ms: 10_000_000_000 };
const RES = { slots: 6, hot: [] };
const CTX = { now: 5000, holder: "h1" };

/** 状態に対する手順を組み立てる小さな補助 */
const mk = () => ({ st: rd.emptyState(), log: [] });
const push = (m, type, node, data, source = "system") => {
	const e = { ...ev.makeEvent(type, node, data, source), seq: m.st.seq + 1, ts: 1000 + m.st.seq };
	m.st = rd.reduce(m.st, e);
	m.log.push(e);
};
const addTask = (m, id, parent = "G", writes = [], after = []) =>
	push(m, "node.added", id, { node: { kind: "task", parent, title: `task ${id}`, writes, after, attrs: { role: "worker", size: "S" } } }, "model");
const planned = (m) => {
	push(m, "goal.created", "G", { title: "g", budget: BIG });
	push(m, "plan.proposed", "G", { hash: "h1" }, "model");
};
const approve = (m, hash = "h1") => push(m, "plan.approved", "G", { hash }, "user");
const reprop = (m, hash) => push(m, "plan.proposed", "G", { hash }, "model");

const ids = (xs) => xs.map((n) => n.id);
const startsOf = (m) => {
	const s = ad.schedStateOf(m.st, { now: 1_000_000, resources: RES });
	return sc.next(s, RES, 1_000_000).filter((a) => a.kind === "start").map((a) => a.task ?? a.id);
};
const schedStates = (m) => Object.fromEntries(ad.schedStateOf(m.st, { now: 1_000_000, resources: RES }).tasks.map((t) => [t.id, t.state]));
const viol = (m) => inv.check(m.st).map((v) => `${v.inv}:${v.message}`);
const appr = (m, id) => m.st.nodes.get(id)?.approved ?? null;
const ser = (s) => JSON.stringify(rd.serialize(s));
const tryReduce = (m, type, node, data, source) => {
	try {
		push(m, type, node, data, source);
		return null;
	} catch (e) {
		return String(e.message);
	}
};
const call = (m, args) => {
	const r = tool.handleWork(m.st, args, CTX);
	if (r.ok) for (const e of r.events) push(m, e.type, e.node, e.data, e.source ?? "model");
	return r;
};

const out = {};

// a) 承認で現存の task に approved が立つ
{
	const m = mk();
	planned(m);
	addTask(m, "T1", "G", ["a/**"]);
	addTask(m, "T2", "G", ["b/**"]);
	const before = { T1: appr(m, "T1"), state: m.st.nodes.get("T1").state };
	approve(m);
	out.approve = { before, T1: appr(m, "T1"), T2: appr(m, "T2"), G: appr(m, "G"), s1: m.st.nodes.get("T1").state, viol: viol(m), startsOf: startsOf(m).sort() };
}

// b) 承認 → work add → 候補に出ない
{
	const m = mk();
	planned(m);
	addTask(m, "T1", "G", ["a/**"]);
	approve(m);
	const r = call(m, { op: "add", title: "後から", writes: ["c/**"] });
	const id = r.details.id;
	out.late = {
		ok: r.ok,
		text: r.text,
		state: m.st.nodes.get(id).state,
		approved: appr(m, id),
		readyIds: ids(ad.readyOf(m.st)),
		projectReady: ids(pj.ready(m.st)),
		starts: startsOf(m),
		sched: schedStates(m),
		viol: viol(m),
		id,
	};
	// c) モデルが set で進める (従来どおり)
	const s1 = call(m, { op: "set", id, status: "in_progress" });
	const s2 = call(m, { op: "set", id, status: "done" });
	out.lateSet = { s1: s1.ok, s2: s2.ok, state: m.st.nodes.get(id).state, approved: appr(m, id), viol: viol(m) };
	// d) active な goal への再承認は遷移表が拒否する (追加分を後から承認する経路は今は無い)
	const e1 = tryReduce(m, "plan.proposed", "G", { hash: "h2" }, "model");
	const e2 = tryReduce(m, "plan.approved", "G", { hash: "h1" }, "user");
	const r2 = call(m, { op: "add", title: "もう一つ", writes: ["d/**"] });
	const id2 = r2.details.id;
	out.reapprove = { id2, e1, e2, approved: appr(m, id2), starts: startsOf(m), readyIds: ids(ad.readyOf(m.st)), viol: viol(m) };
}

// e) 承認前の task は候補にならない
{
	const m = mk();
	planned(m);
	addTask(m, "T1");
	out.beforeApprove = { starts: startsOf(m), state: m.st.nodes.get("T1").state, approved: appr(m, "T1"), ready: ids(ad.readyOf(m.st)) };
}

// f) approved を持つ task が終端になる / 終端の task には立てない
{
	const m = mk();
	planned(m);
	addTask(m, "T1", "G", ["a/**"]);
	addTask(m, "T2", "G", ["b/**"]);
	addTask(m, "T3", "G", ["c/**"]);
	approve(m);
	call(m, { op: "set", id: "T1", status: "in_progress" });
	call(m, { op: "set", id: "T1", status: "done" });
	call(m, { op: "cancel", id: "T2" });
	const afterEnd = { T1: appr(m, "T1"), T2: appr(m, "T2"), s1: m.st.nodes.get("T1").state, s2: m.st.nodes.get("T2").state };
	out.terminal = { afterEnd, T3: appr(m, "T3"), viol: viol(m), sched: schedStates(m) };
}

// g) モデル出所の plan.approved は従来どおり拒否 (I10)
{
	const m = mk();
	planned(m);
	addTask(m, "T1");
	const err = tryReduce(m, "plan.approved", "G", { hash: "h1" }, "model");
	const bad = (() => {
		try {
			const g = ev.makeEvent("plan.approved", "G", { hash: "h1" }, "model");
			rd.reduce(m.st, { ...g, seq: m.st.seq + 1, ts: 9 });
			return null;
		} catch (e) {
			return String(e.message);
		}
	})();
	out.forged = { err, bad, approved: appr(m, "T1"), gState: m.st.nodes.get("G").state };
}

// h) 永続 → 再生で approved が保たれる
{
	const m = mk();
	planned(m);
	addTask(m, "T1", "G", ["a/**"]);
	approve(m);
	call(m, { op: "add", title: "後から", writes: ["c/**"] });
	const lines = m.log.map((e) => JSON.parse(store.encodeLine(e).toString("utf8").trim().split("\t")[0]));
	const re = rd.fold(lines);
	out.replay = { same: ser(re) === ser(m.st), T1: re.nodes.get("T1").approved ?? null, late: re.nodes.get("n1")?.approved ?? null, ids: [...re.nodes.keys()], ser: ser(m.st).includes("approved") };
}

// i) add の注記: active のときだけ。出力の上限も守る
{
	const notes = {};
	for (const stage of ["draft", "planned", "active", "paused"]) {
		const m = mk();
		push(m, "goal.created", "G", { title: "g", budget: BIG });
		if (stage !== "draft") {
			reprop(m, "h1");
		}
		if (stage === "active" || stage === "paused") approve(m);
		if (stage === "paused") push(m, "goal.paused", "G", { reason: "x" }, "system");
		const r = call(m, { op: "add", title: "T".repeat(150) });
		notes[stage] = { ok: r.ok, text: r.text, state: m.st.nodes.get(r.details.id)?.state, len: [...r.text].length };
	}
	out.notes = notes;
	// 承認後にもう一度 plan.approved したあとに add した task が task の子でも同じ
	const m = mk();
	planned(m);
	addTask(m, "T1");
	approve(m);
	const r = call(m, { op: "add", title: "子", parent: "T1" });
	out.childNote = { text: r.text, approved: appr(m, r.details.id) };
}

// j) 乱数列の性質試験: plan.proposed / plan.approved / node.added / task の遷移を混ぜても I1〜I10 と「未承認は起動しない」が保たれる
{
	let seed = 12345;
	const rnd = (n) => {
		seed = (Math.imul(seed, 1103515245) + 12345) >>> 0;
		return (seed >>> 8) % n;
	};
	const runs = [];
	for (let i = 0; i < 40; i++) {
		const m = mk();
		planned(m);
		let hash = "h1";
		let n = 0;
		let bad = null;
		let unapprovedStart = null;
		for (let k = 0; k < 40 && bad === null; k++) {
			const g = m.st.nodes.get("G");
			const op = rnd(6);
			try {
				if (op === 0 && g.state === "planned") approve(m, hash);
				else if (op === 1) {
					// active への再承認・再提案は拒否される (拒否されても状態は変わらない)
					tryReduce(m, "plan.approved", "G", { hash }, "user");
				} else if (op <= 3) addTask(m, `T${++n}`, "G", [`d${n}/**`]);
				else {
					const ts = [...m.st.nodes.values()].filter((x) => x.kind === "task");
					if (ts.length > 0) {
						const t = ts[rnd(ts.length)];
						const r = call(m, { op: "set", id: t.id, status: ["in_progress", "done", "pending"][rnd(3)] });
						void r;
					}
				}
			} catch (e) {
				void e;
			}
			const v = viol(m);
			if (v.length > 0) bad = v;
			const st = ad.schedStateOf(m.st, { now: 1_000_000, resources: RES });
			for (const a of sc.next(st, RES, 1_000_000)) {
				if (a.kind !== "start") continue;
				const tid = a.task ?? a.id;
				if (m.st.nodes.get(tid)?.approved !== true) unapprovedStart = tid;
			}
			for (const x of ad.readyOf(m.st)) if (x.approved !== true) unapprovedStart = x.id;
		}
		runs.push({ bad, unapprovedStart, tasks: n });
	}
	out.fuzz = { runs: runs.length, bad: runs.filter((r) => r.bad !== null), unapproved: runs.filter((r) => r.unapprovedStart !== null), withTasks: runs.filter((r) => r.tasks > 0).length };
}

process.stdout.write(`${JSON.stringify(out)}\n`);

// 作業台帳の核 (home/dot_config/pi/harness/work/*.ts) の純関数の試験用 driver。標準入力の JSON を実行し、結果を JSON で標準出力へ出す。照合は test_work_core.py。
//
//   {"scenario":{"events":[{"type":..,"node":..,"data":{..},"source":"user"|"model"|"system"}, ...],"tolerant":false}}
//        イベント列を畳む (seq・ts は driver が付ける)。tolerant なら、拒否されたイベントを飛ばして理由を返す。各 step 後の不変条件の違反も返す
//   {"calls":[{"fn":"ready","events":[..],"args":[..]}, ...]}              関数を呼ぶ (events があれば畳んだ state を、state (serialize 形式) があればそれを第 1 引数に渡す)
//   {"cells":true}                                                           遷移表の全セルを、表の引き当てと実際の reduce の両方で評価する
//   {"fuzz":{"seed":1,"runs":40,"steps":300}}                                乱数列のイベント列で不変条件・決定性・不変性・スナップショットを検査する
//   {"overlap":{"seed":1,"samples":150000}}                                  globsMayOverlap を合成ファイル木で総当たりし、偽陰性を数える
// see docs/spec/work/ledger.md
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const W = resolve(ROOT, "home", "dot_config", "pi", "harness", "work");
const load = (f) => import(pathToFileURL(resolve(W, f)).href);
const [ev, tr, rd, inv, pj, gl] = await Promise.all(["events.ts", "transitions.ts", "reduce.ts", "invariants.ts", "project.ts", "globs.ts"].map(load));

const USER_ONLY = new Set(["plan.approved", "budget.adjusted", "goal.resumed"]);
const Z = { usd: 0, tokens: 0, ms: 0 };
const mkEvent = (e, seq) => {
	const source = e.source ?? (USER_ONLY.has(e.type) || (e.type === "wait.resolved" && e.data?.by === "user") ? "user" : "system");
	return { ts: seq * 1000, seq: e.seq ?? seq, type: e.type, ...(e.node !== undefined ? { node: e.node } : {}), data: { ...(e.data ?? {}), source }, ...(e.aux ? { aux: true } : {}) };
};

const plain = (s) => ({ ...rd.serialize(s), nodes: Object.fromEntries(s.nodes) });
const json = (s) => JSON.stringify(rd.serialize(s));

const deepFreeze = (x) => {
	if (x && typeof x === "object" && !Object.isFrozen(x)) {
		Object.freeze(x);
		for (const v of x instanceof Map ? [...x.values()] : Object.values(x)) deepFreeze(v);
	}
	return x;
};

// 乱数 (mulberry32)。seed 固定で再現できる
const rng = (seed) => () => {
	seed = (seed + 0x6d2b79f5) | 0;
	let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
	t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
	return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

/** 1 件を適用する。拒否されたら { error } */
const tryApply = (state, e) => {
	const full = mkEvent(e, state.seq + 1);
	try {
		return { state: rd.reduce(state, full), event: full };
	} catch (err) {
		return { error: `${err.name}: ${err.message}`, event: full };
	}
};

// ── 遷移表の全セル ──
const Zero = () => ({ ...Z });
const baseState = () => {
	let s = rd.emptyState();
	const E = (type, node, data, source) => ({ type, node, data, source });
	for (const e of [
		E("goal.created", "G", { title: "G" }),
		E("plan.proposed", "G", { hash: "h" }),
		E("plan.approved", "G", { hash: "h" }, "user"),
		E("node.added", "T", { node: { kind: "task", parent: "G", title: "T", writes: [] } }),
		E("node.added", "T2", { node: { kind: "task", parent: "G", title: "T2", writes: [] } }),
		E("run.reserved", "R", { task: "T", est: Zero() }),
		E("run.started", "R", {}),
	]) {
		const r = tryApply(s, e);
		if (r.error) throw new Error(`基準の状態が作れない: ${r.error}`);
		s = r.state;
	}
	return s;
};

const cellEvent = (kind, on, variant) => {
	const node = kind === "goal" ? "G" : kind === "task" ? "T" : "R";
	const big = { usd: 100, tokens: 1e6, ms: 1e9 };
	switch (on) {
		case "plan.proposed": return { type: on, node: "G", data: { hash: "h" } };
		case "plan.approved": return { type: on, node: "G", data: { hash: "h" }, source: "user" };
		case "goal.paused": return { type: on, node, data: { reason: "x" } };
		case "goal.resumed": return { type: on, node, data: {}, source: "user" };
		case "goal.done": return { type: on, node, data: {} };
		case "verdict": return { type: on, node, data: { verdict: variant, reason: "r" } };
		case "note.appended": return { type: on, node, data: { by: "llm", text: "n" } };
		case "budget.adjusted": return { type: on, node, data: { budget: big }, source: "user" };
		case "lease.acquired": return { type: on, node, data: { holder: "A", pid: 1 } };
		case "lease.released":
		case "lease.expired": return { type: on, node, data: { holder: "A" } };
		case "wait.opened": return { type: on, node, data: { wait: { on: "user", ref: "w9", since: 1, auto: false, prompt: "p" } } };
		case "wait.resolved": return { type: on, node, data: { ref: "w1", by: "user" }, source: "user" };
		case "run.reserved": return { type: on, node: "R2", data: { task: "T", est: Zero() } };
		case "run.started": return { type: on, node, data: {} };
		case "run.usage": return { type: on, node, data: { usage: Zero() } };
		case "run.ended": return { type: on, node: "R", data: { status: variant } };
		case "check.result": return { type: on, node, data: { name: "c", ok: variant === "pass" } };
		case "edge.added": return { type: on, node, data: { from: node, to: "T2" } };
		case "edge.rejected": return { type: on, node, data: { from: node, to: "T2", reason: "cycle" } };
		default: throw new Error(`cellEvent 未対応: ${on}`);
	}
};

const evalCell = (cell) => {
	const { kind, from, on, variant } = cell;
	const rule = tr.lookup(kind, from, on, variant);
	if ((kind === "goal" || kind === "run") && on === "run.reserved") return { ...cell, applicable: false };
	const s = structuredClone(baseState());
	const G = s.nodes.get("G");
	const T = s.nodes.get("T");
	const R = s.nodes.get("R");
	const wait = (ref) => ({ on: "user", ref, since: 1, auto: false, prompt: "p" });
	if (kind === "goal") {
		G.state = from;
		G.attrs.planHash = "h";
		G.evidence = ["verdict:1:done"];
		T.state = "done";
		T.evidence = ["check:1"];
		R.state = "done";
		s.nodes.get("T2").state = "done";
		if (on === "lease.released" || on === "lease.expired") G.owner = { holder: "A", pid: 1, startedAt: 0, heartbeat: 0 };
		if (on === "wait.resolved") G.waits = variant === "remain" ? [wait("w1"), wait("w2")] : [wait("w1")];
	} else if (kind === "task") {
		T.state = from;
		if (on === "plan.approved") G.state = "planned";
		G.attrs.planHash = "h";
		R.state = on === "run.reserved" ? "done" : on === "wait.resolved" ? (variant === "live" ? "started" : "done") : on === "run.ended" || from === "running" || from === "waiting" ? "started" : "done";
		if (on === "wait.resolved") T.waits = variant === "remain" ? [wait("w1"), wait("w2")] : [wait("w1")];
	} else {
		R.state = from;
	}
	const full = mkEvent(cellEvent(kind, on, variant), s.seq + 1);
	let actual;
	try {
		const n = rd.reduce(s, full);
		actual = n.nodes.get(kind === "goal" ? "G" : kind === "task" ? "T" : "R").state;
	} catch (err) {
		actual = null;
		cell.error = `${err.name}: ${err.message}`;
	}
	return { ...cell, applicable: true, table: rule ? rule.to : null, actual, ...(cell.error ? { error: cell.error } : {}) };
};

// ── 乱数列のイベント列 (性質試験) ──
const WRITES = [[], [], ["a/**"], ["a/x.ts"], ["b/*.ts"], ["docs/"], ["**/*.md"], ["c/d/e.ts"], ["*.json"]];
const quarter = (R, max) => ({ usd: Math.floor(R() * (max + 1)) * 0.25, tokens: Math.floor(R() * (max + 1)) * 100, ms: Math.floor(R() * (max + 1)) * 1000 });
const bigBudget = (R) => ({ usd: 5 + Math.floor(R() * 40), tokens: 5000 + Math.floor(R() * 50000), ms: 1e6 + Math.floor(R() * 1e7) });
const smallBudget = (R) => ({ usd: 1 + Math.floor(R() * 6), tokens: 500 + Math.floor(R() * 3000), ms: 5000 + Math.floor(R() * 20000) });
const remaining = (n) => ({ usd: n.reserved.usd - n.spent.usd, tokens: n.reserved.tokens - n.spent.tokens, ms: n.reserved.ms - n.spent.ms });
const within = (R, rem) => ({
	usd: Math.min(rem.usd, Math.floor(R() * (rem.usd / 0.25 + 1)) * 0.25),
	tokens: Math.min(rem.tokens, Math.floor(R() * (rem.tokens / 100 + 1)) * 100),
	ms: Math.min(rem.ms, Math.floor(R() * (rem.ms / 1000 + 1)) * 1000),
});

const ACTIONS = [
	..."G".repeat(1), ..."P".repeat(2), ..."A".repeat(3), ..."Z".repeat(1), ..."U".repeat(2), ..."V".repeat(2), ..."D".repeat(2),
	..."N".repeat(8), ..."E".repeat(2), ..."r".repeat(7), ..."s".repeat(6), ..."u".repeat(4), ..."e".repeat(6), ..."c".repeat(5),
	..."w".repeat(3), ..."x".repeat(4), ..."t".repeat(3), ..."b".repeat(1), ..."v".repeat(3), ..."l".repeat(2), ..."X".repeat(1),
];

const gen = (state, R, c) => {
	const pick = (a) => a[Math.floor(R() * a.length)];
	const nodes = [...state.nodes.values()];
	const goals = nodes.filter((n) => n.kind === "goal");
	const tasks = nodes.filter((n) => n.kind !== "goal" && n.kind !== "run");
	const runs = nodes.filter((n) => n.kind === "run");
	const src = (p = 0.9) => (R() < p ? "user" : pick(["model", "system"]));
	const a = pick(ACTIONS);
	switch (a) {
		case "G":
			return goals.length < 3 ? { type: "goal.created", node: `g${++c.g}`, data: { title: "g", ...(R() < 0.8 ? { budget: bigBudget(R) } : {}) } } : null;
		case "P": {
			const g = goals.filter((n) => n.state === "draft" || n.state === "planned");
			return g.length ? { type: "plan.proposed", node: pick(g).id, data: { hash: pick(["h1", "h2"]) } } : null;
		}
		case "A": {
			const g = goals.filter((n) => n.state === "planned");
			if (!g.length) return null;
			const n = pick(g);
			return { type: "plan.approved", node: n.id, data: { hash: R() < 0.9 ? n.attrs.planHash : "zz" }, source: src() };
		}
		case "Z": {
			const g = goals.filter((n) => n.state === "active" || n.state === "paused");
			if (!g.length) return null;
			const n = pick(g);
			return n.state === "active" ? { type: "goal.paused", node: n.id, data: { reason: "p" } } : { type: "goal.resumed", node: n.id, data: {}, source: src(0.8) };
		}
		case "U": {
			const g = goals.filter((n) => n.state === "active");
			return g.length ? { type: "verdict", node: pick(g).id, data: { verdict: pick(["done", "done", "continue", "cancel"]), reason: "r" } } : null;
		}
		case "V": {
			const g = goals.filter((n) => n.state === "active");
			return g.length ? { type: "goal.done", node: pick(g).id, data: {} } : null;
		}
		case "D": {
			// 決着を促す: 終わっていない task を取り消す・飛ばす
			const t = tasks.filter((n) => ["proposed", "ready", "failed", "blocked"].includes(n.state));
			return t.length ? { type: "verdict", node: pick(t).id, data: { verdict: pick(["cancel", "skip", "retry", "block"]), reason: "r" } } : null;
		}
		case "N": {
			const p = goals.filter((n) => !["done", "cancelled"].includes(n.state));
			if (!p.length) return null;
			const par = R() < 0.25 && tasks.length ? pick(tasks) : pick(p);
			const gid = rd.rootGoalId(state.nodes, par.id);
			const same = tasks.filter((n) => rd.rootGoalId(state.nodes, n.id) === gid);
			const after = R() < 0.5 ? [] : [pick(same.length ? same : [{ id: "nope" }]).id, ...(R() < 0.3 ? [pick(same.length ? same : [{ id: "nope" }]).id] : [])];
			return {
				type: "node.added",
				node: `t${++c.t}`,
				data: { node: { kind: pick(["task", "task", "task", "task", "check", "integrate"]), parent: par.id, title: "t", after, writes: pick(WRITES), ...(R() < 0.15 ? { budget: smallBudget(R) } : {}) } },
			};
		}
		case "E": {
			if (tasks.length < 2) return null;
			const f = pick(tasks);
			return { type: "edge.added", node: f.id, data: { from: f.id, to: pick(tasks).id } };
		}
		case "r": {
			const t = tasks.filter((n) => n.state === "ready");
			return t.length ? { type: "run.reserved", node: `r${++c.r}`, data: { task: pick(t).id, est: quarter(R, 6) } } : null;
		}
		case "s": {
			const r = runs.filter((n) => n.state === "reserved");
			return r.length ? { type: "run.started", node: pick(r).id, data: {} } : null;
		}
		case "u": {
			const r = runs.filter((n) => n.state === "started");
			if (!r.length) return null;
			const n = pick(r);
			return { type: "run.usage", node: n.id, data: { usage: within(R, remaining(n)) } };
		}
		case "e": {
			const r = runs.filter((n) => n.state === "started" || n.state === "reserved");
			if (!r.length) return null;
			const n = pick(r);
			const status = pick(n.state === "started" ? ["done", "done", "done", "blocked", "failed", "limit", "aborted", "lost"] : ["failed", "limit", "aborted", "lost"]);
			return { type: "run.ended", node: n.id, data: { status, ...(R() < 0.5 && n.state === "started" ? { usage: within(R, remaining(n)) } : {}) } };
		}
		case "c": {
			const t = tasks.filter((n) => n.state === "checking");
			return t.length ? { type: "check.result", node: pick(t).id, data: { name: "c", ok: R() < 0.75 } } : null;
		}
		case "w": {
			const t = [...tasks.filter((n) => ["running", "waiting", "blocked", "failed"].includes(n.state)), ...goals.filter((n) => !["done", "cancelled"].includes(n.state))];
			if (!t.length) return null;
			const on = pick(["user", "user", "run", "job", "merge", "time"]);
			return { type: "wait.opened", node: pick(t).id, data: { wait: { on, ref: `w${++c.w}`, since: c.w, auto: on !== "user", ...(on === "user" ? { prompt: "確認" } : {}) } } };
		}
		case "x": {
			const t = nodes.filter((n) => n.waits.length > 0);
			if (!t.length) return null;
			const n = pick(t);
			const w = pick(n.waits);
			const by = w.on === "user" ? (R() < 0.7 ? "user" : pick(["run", "job"])) : R() < 0.7 ? w.on : R() < 0.5 ? "user" : "merge";
			return { type: "wait.resolved", node: n.id, data: { ref: w.ref, by }, source: by === "user" ? src(0.85) : "system" };
		}
		case "t": {
			if (!nodes.length) return null;
			const n = pick(nodes);
			const holder = R() < 0.2 ? { holder: pick(["A", "B"]) } : {};
			return { type: "note.appended", node: n.id, data: { by: pick(["user", "llm", "run:r1"]), text: R() < 0.03 ? "x".repeat(301) : "メモ" + c.t, ...holder } };
		}
		case "b": {
			const t = [...goals, ...tasks.filter((n) => n.kind === "task")];
			return t.length ? { type: "budget.adjusted", node: pick(t).id, data: { budget: R() < 0.6 ? bigBudget(R) : smallBudget(R) }, source: src() } : null;
		}
		case "v": {
			const t = tasks.filter((n) => ["failed", "blocked", "running", "waiting", "checking"].includes(n.state));
			return t.length ? { type: "verdict", node: pick(t).id, data: { verdict: pick(["retry", "retry", "block", "cancel"]), reason: "r" } } : null;
		}
		case "l": {
			if (!goals.length) return null;
			const g = pick(goals);
			const holder = pick(["A", "B"]);
			const t = pick(["lease.acquired", "lease.acquired", "lease.released", "lease.expired"]);
			return { type: t, node: g.id, data: t === "lease.acquired" ? { holder, pid: 100 + c.t } : { holder: g.owner?.holder ?? holder } };
		}
		default:
			return { type: "notice", data: { text: "aux" }, aux: true, node: undefined };
	}
};

const fuzz = ({ seed, runs, steps }) => {
	const out = { attempts: 0, applied: 0, rejected: 0, byType: {}, rejectedByType: {}, violations: [], nondeterministic: [], mutated: [], prefixMismatch: [], rejectedUserOnlyFromModel: 0 };
	const R = rng(seed);
	for (let run = 0; run < runs; run++) {
		const c = { g: 0, t: 0, r: 0, w: 0 };
		let state = rd.emptyState();
		const applied = [];
		// 序盤は goal を作って承認まで進める (性質が働く状態に早く入る)
		const warm = [
			{ type: "goal.created", node: `g${++c.g}`, data: { title: "g", budget: bigBudget(R) } },
			{ type: "plan.proposed", node: "g1", data: { hash: "h0" } },
			{ type: "plan.approved", node: "g1", data: { hash: "h0" }, source: "user" },
		];
		for (let i = 0; i < steps; i++) {
			let e = i < warm.length ? warm[i] : null;
			for (let k = 0; !e && k < 6; k++) e = gen(state, R, c);
			if (!e) e = { type: "notice", data: {}, aux: true };
			const before = json(state);
			const frozen = deepFreeze(structuredClone(state));
			const r = tryApply(frozen, e);
			out.attempts++;
			if (json(frozen) !== before) out.mutated.push(`run ${run} step ${i}: 入力の state が変わった (${e.type})`);
			if (r.error) {
				out.rejected++;
				out.rejectedByType[e.type] = (out.rejectedByType[e.type] ?? 0) + 1;
				if (e.source === "model" && USER_ONLY.has(e.type)) out.rejectedUserOnlyFromModel++;
				if (state.seq !== frozen.seq) out.mutated.push(`run ${run} step ${i}: 拒否したのに state が進んだ`);
				continue;
			}
			// 決定性: 同じ入力から同じ出力
			const again = rd.reduce(structuredClone(state), r.event);
			if (json(again) !== json(r.state)) out.nondeterministic.push(`run ${run} step ${i}: 2 回の結果が違う (${e.type})`);
			const v = inv.check(r.state, state);
			if (v.length) out.violations.push(...v.slice(0, 3).map((x) => ({ run, step: i, type: e.type, ...x })));
			out.applied++;
			out.byType[e.type] = (out.byType[e.type] ?? 0) + 1;
			applied.push(r.event);
			state = r.state;
		}
		// fold(log) == fold(prefix) + tail (スナップショットは JSON を往復させる)
		const whole = rd.fold(applied);
		if (json(whole) !== json(state)) out.prefixMismatch.push(`run ${run}: fold(全体) が逐次の結果と違う`);
		for (const cut of [0, Math.floor(applied.length / 3), Math.floor(applied.length / 2), applied.length - 1, applied.length]) {
			const snap = rd.deserialize(JSON.parse(JSON.stringify(rd.serialize(rd.fold(applied.slice(0, cut))))));
			if (json(rd.fold(applied.slice(cut), snap)) !== json(whole)) out.prefixMismatch.push(`run ${run} cut ${cut}: snapshot + tail が fold(全体) と違う`);
		}
	}
	out.violations = out.violations.slice(0, 20);
	return out;
};

// ── globsMayOverlap の総当たり ──
const overlap = ({ seed, samples }) => {
	const R = rng(seed);
	const names = ["a", "b", "x.ts", "y.md", "ab"];
	const files = [];
	const walk = (prefix, d) => {
		for (const n of names) {
			const f = [...prefix, n];
			files.push(f);
			if (d < 3) walk(f, d + 1);
		}
	};
	walk([], 1);
	const pool = ["a", "b", "*", "**", "?", "x.ts", "*.ts", "a*", "*b", "y.md"];
	const pats = [];
	const gen = (prefix, d) => {
		for (const s of pool) {
			const p = [...prefix, s];
			pats.push(p.join("/"), `${p.join("/")}/`);
			if (d < 3) gen(p, d + 1);
		}
	};
	gen([], 1);
	// 独立の判定器: パターンが、ファイルかその祖先ディレクトリに合致するか (ディレクトリへの書き込みは配下に及ぶ)
	const segRe = (s) => new RegExp(`^${s.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, "[^/]*").replace(/\?/g, "[^/]")}$`);
	const norm = (g) => {
		const dir = g.endsWith("/");
		const segs = g.replace(/^(\.\/)+/, "").split("/").filter((s) => s);
		if (dir) segs.push("**");
		if (segs.length === 1 && !dir) segs.unshift("**");
		return segs;
	};
	const m = (p, i, f, j) => {
		if (i === p.length) return true;
		if (p[i] === "**") {
			for (let k = j; k <= f.length; k++) if (m(p, i + 1, f, k)) return true;
			return false;
		}
		return j < f.length && segRe(p[i]).test(f[j]) && m(p, i + 1, f, j + 1);
	};
	const sets = pats.map((p) => {
		const segs = norm(p);
		const bits = new Uint32Array(Math.ceil(files.length / 32));
		files.forEach((f, idx) => {
			if (m(segs, 0, f, 0)) bits[idx >> 5] |= 1 << (idx & 31);
		});
		return bits;
	});
	const truth = (i, j) => sets[i].some((w, k) => (w & sets[j][k]) !== 0);
	const out = { patterns: pats.length, files: files.length, pairs: 0, trueOverlap: 0, misses: [], exactDisjoint: 0, falseOverlap: 0 };
	const test = (i, j) => {
		out.pairs++;
		const t = truth(i, j);
		const g = gl.globsMayOverlap(pats[i], pats[j]);
		if (t) out.trueOverlap++;
		if (t && !g && out.misses.length < 20) out.misses.push([pats[i], pats[j]]);
		if (!t && !g) out.exactDisjoint++;
		if (!t && g) out.falseOverlap++;
	};
	const short = pats.map((p, i) => (p.replace(/\/$/, "").split("/").length <= 2 ? i : -1)).filter((i) => i >= 0);
	for (const i of short) for (const j of short) test(i, j);
	for (let k = 0; k < samples; k++) test(Math.floor(R() * pats.length), Math.floor(R() * pats.length));
	return out;
};

// ── 入口 ──
const input = JSON.parse(readFileSync(0, "utf-8"));
if (input.scenario) {
	let state = rd.emptyState();
	const steps = [];
	for (const e of input.scenario.events) {
		const r = tryApply(state, e);
		if (r.error) {
			if (!input.scenario.tolerant) {
				steps.push({ error: r.error });
				break;
			}
			steps.push({ error: r.error });
			continue;
		}
		const v = inv.check(r.state, state);
		steps.push({ violations: v });
		state = r.state;
	}
	console.log(JSON.stringify({ state: plain(state), steps, violations: inv.check(state) }));
} else if (input.calls) {
	const mods = { ...ev, ...tr, ...rd, ...inv, ...pj, ...gl };
	const results = input.calls.map((c) => {
		try {
			// {"$state": serialize 形式} の引数は、台帳の状態へ戻して渡す (check の prev など)
			const args = structuredClone(c.args ?? []).map((x) => (x && typeof x === "object" && x.$state ? rd.deserialize(x.$state) : x));
			const a = c.state ? [rd.deserialize(c.state), ...args] : c.events ? [rd.fold(c.events.map((e, i) => mkEvent(e, i + 1))), ...args] : args;
			const r = mods[c.fn](...a.map((x) => deepFreeze(x)));
			return { ok: r instanceof Map ? Object.fromEntries(r) : r && r.nodes instanceof Map ? plain(r) : r };
		} catch (err) {
			return { error: `${err.name}: ${err.message}` };
		}
	});
	console.log(JSON.stringify({ results }));
} else if (input.cells) {
	const cells = tr.allCells().map(evalCell);
	console.log(JSON.stringify({ cells }));
} else if (input.fuzz) {
	console.log(JSON.stringify(fuzz(input.fuzz)));
} else if (input.overlap) {
	console.log(JSON.stringify(overlap(input.overlap)));
}

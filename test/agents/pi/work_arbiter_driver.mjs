// 継続の調停 (home/dot_config/pi/harness/work/arbiter.ts) の純関数の試験用 driver。標準入力の JSON を実行し、結果を JSON で標準出力へ出す。照合は test_work_arbiter.py。
//
//   {"settle":{"facts":{..}}}                                  提案者を全部呼んで調停する。{facts, proposals, decision} を返す
//   {"arbitrate":{"facts":{..},"proposals":[..]}}              与えた提案で調停する (入力を deepFreeze して渡す)
//   {"grid":{"base":{..},"axes":[["a.b",[v1,v2]],..]}}         base に axes の直積 (最後の軸が最速) を当てて settle し、行ごとの要約を返す
//   {"fuzz":{"seed":1,"runs":2000}}                            乱数の事実で性質 (entries≤1・決定性・入力の不変・安全側・wake の置き場) を検査し、違反を返す
// see docs/spec/work/arbiter.md
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const W = resolve(ROOT, "home", "dot_config", "pi", "harness", "work");
const arb = await import(pathToFileURL(resolve(W, "arbiter.ts")).href);
const nt = await import(pathToFileURL(resolve(W, "notices.ts")).href);

const deepFreeze = (x) => {
	if (x && typeof x === "object" && !Object.isFrozen(x)) {
		Object.freeze(x);
		for (const v of Object.values(x)) deepFreeze(v);
	}
	return x;
};
const clone = (x) => JSON.parse(JSON.stringify(x));
const setPath = (o, path, v) => {
	const ks = path.split(".");
	let c = o;
	for (const k of ks.slice(0, -1)) c = c[k];
	c[ks.at(-1)] = v;
};

const rng = (seed) => () => {
	seed = (seed + 0x6d2b79f5) | 0;
	let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
	t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
	return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

const summary = (d) => [
	d.continue ? 1 : 0,
	d.row,
	d.entries.length,
	d.effects.filter((e) => e.kind === "wake").length,
	d.entries[0]?.content.length ?? 0,
	d.effects.some((e) => e.kind === "checkpoint" && e.action === "compact") ? 1 : 0,
	d.effects.some((e) => e.kind === "checkpoint" && e.action === "cancel") ? 1 : 0,
];

const run = (facts) => {
	const f = deepFreeze(clone(facts));
	const proposals = arb.propose(f);
	return { proposals, decision: arb.arbitrate(f, proposals) };
};

function fuzz({ seed, runs }) {
	const r = rng(seed);
	const pick = (xs) => xs[Math.floor(r() * xs.length)];
	const bool = () => r() < 0.5;
	const labels = () => Array.from({ length: Math.floor(r() * 4) }, (_, i) => `#${i + 1} 項目`);
	const bad = [];
	const note = (name, facts, extra = "") => bad.length < 20 && bad.push({ name, extra, facts });
	const stats = { runs, continued: 0, wakes: 0, rows: {} };
	for (let i = 0; i < runs; i++) {
		const facts = {
			trigger: pick(["settle", "settle", "resume"]),
			mode: r() < 0.9 ? "interactive" : pick(["print", "json"]),
			child: r() < 0.05,
			outcome: pick(["completed", "completed", "aborted", "error"]),
			phase: pick(["idle", "saving", "compacting", "goal", "plan"]),
			compacting: r() < 0.1,
			userInput: r() < 0.2,
			streak: Math.floor(r() * 12),
			maxStreak: 10,
			budgetExhausted: r() < 0.2,
			checkpoint: { percent: r() < 0.1 ? null : Math.floor(r() * 100), threshold: 80, cooldown: r() < 0.3, llmStep: bool(), disabled: r() < 0.1, prompt: "保存してください" },
			todo: { disabled: r() < 0.1, doing: labels(), blocked: labels(), queued: labels(), nudged: bool(), nudgedWaiting: bool() },
			goal: { active: bool(), claim: bool(), stall: bool(), unapproved: Math.floor(r() * 4) },
			children: { failed: Math.floor(r() * 3), parentStep: bool(), newUserWait: bool() },
		};
		const before = JSON.stringify(facts);
		const frozen = deepFreeze(clone(facts));
		let d;
		let props;
		try {
			props = arb.propose(frozen);
			d = arb.arbitrate(frozen, props);
		} catch (e) {
			note("throw", facts, String(e));
			continue;
		}
		const d2 = arb.arbitrate(clone(facts), clone(props));
		if (JSON.stringify(d) !== JSON.stringify(d2)) note("決定性", facts);
		if (JSON.stringify(frozen) !== before) note("入力の不変", facts);
		if (d.entries.length > 1) note("entries≤1", facts);
		if (d.continue !== (d.entries.length === 1)) note("continue と entries の対応", facts);
		const wakes = d.effects.filter((e) => e.kind === "wake");
		if (wakes.length > 1) note("wake は高々 1 つ", facts);
		if (wakes.length > 0 && (d.continue || d.entries.length > 0)) note("wake と continue は排他", facts);
		if (wakes.length > 0 && facts.trigger !== "resume") note("wake は resume だけ", facts);
		if (d.entries.some((e) => JSON.stringify(e).includes('"wake"') && e.kind === "wake")) note("entries に wake", facts);
		if (d.continue && facts.trigger !== "settle") note("resume で continue", facts);
		if (d.continue || wakes.length > 0) {
			if (facts.outcome !== "completed") note("中断・エラーで継続", facts);
			if (facts.compacting || facts.phase === "compacting") note("圧縮中に継続", facts);
			if (facts.userInput) note("利用者の入力で継続", facts);
			if (facts.child || facts.mode !== "interactive") note("子・print・json で継続", facts);
			if (facts.streak >= facts.maxStreak) note("連続上限で継続", facts);
			if (facts.budgetExhausted && d.row !== 4 && d.row !== 5) note("予算超過で継続", facts);
		}
		for (const e of d.effects) {
			if (e.kind === "notify") {
				const s = nt.select(e.event, props.flatMap((p) => p.effects).find((x) => x.kind === "notify" && x.event === e.event)?.ctx ?? {});
				if (s.show !== e.show && e.event !== "run.failed" && e.event !== "goal.stopped") note("notify の show が select と違う", facts, e.event);
			}
		}
		stats.continued += d.continue ? 1 : 0;
		stats.wakes += wakes.length;
		stats.rows[d.row] = (stats.rows[d.row] ?? 0) + 1;
	}
	return { bad, stats };
}

function grid({ base, axes }) {
	const rows = [];
	const idx = axes.map(() => 0);
	const total = axes.reduce((n, [, vs]) => n * vs.length, 1);
	for (let n = 0; n < total; n++) {
		const f = clone(base);
		axes.forEach(([p, vs], k) => setPath(f, p, vs[idx[k]]));
		rows.push(summary(arb.settle(deepFreeze(f))));
		for (let k = axes.length - 1; k >= 0; k--) {
			if (++idx[k] < axes[k][1].length) break;
			idx[k] = 0;
		}
	}
	return { rows };
}

const req = JSON.parse(readFileSync(0, "utf8"));
let out;
if (req.settle) out = run(req.settle.facts);
else if (req.arbitrate) out = { decision: arb.arbitrate(deepFreeze(clone(req.arbitrate.facts)), deepFreeze(clone(req.arbitrate.proposals))) };
else if (req.grid) out = grid(req.grid);
else if (req.fuzz) out = fuzz(req.fuzz);
else if (req.batch) out = { results: req.batch.map((c) => (c.arbitrate ? { decision: arb.arbitrate(clone(c.arbitrate.facts), clone(c.arbitrate.proposals)) } : run(c.settle.facts))) };
else throw new Error("未知の要求");
process.stdout.write(JSON.stringify(out));

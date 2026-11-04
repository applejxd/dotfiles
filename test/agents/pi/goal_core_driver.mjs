// goal-core.ts の純関数の試験用 driver。標準入力の JSON を実行し、結果を JSON で標準出力へ出す。照合は test_pi_goal_core.py。
//
//   {"calls":[{"fn":"parseClaim","args":["..."]}, ...]}                 関数を順に呼ぶ (引数は deep freeze して渡す = 状態を変更したら失敗する)
//   {"chain":{"state":{...},"steps":[{"op":"settle","facts":{...},"cfg":{...}}|{"op":"verdict","v":null|{...},"now":1,"f":{...}}
//                                    |{"op":"resume","now":1}|{"op":"pause","reason":"user","now":1}|{"op":"budget","budget":{...},"now":1}]}}
//                                                                         状態を引き回して、各 step の {decision,next} を返す
//   {"fuzz":{"seed":1,"runs":50,"steps":60}}                              乱数列 (seed 固定) の遷移で不変条件を検査し、違反を返す
// see docs/spec/guard/pi-extensions.md (配線の後に書く)
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const mod = await import(pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "goal-core.ts")).href);

const deepFreeze = (x) => {
	if (x && typeof x === "object" && !Object.isFrozen(x)) {
		Object.freeze(x);
		for (const v of Object.values(x)) deepFreeze(v);
	}
	return x;
};

const step = (state, st) => {
	switch (st.op) {
		case "settle":
			return mod.decideSettle(state, st.facts, st.cfg ?? { evalMode: "claim" });
		case "verdict":
			return mod.applyVerdict(state, st.v, st.now ?? 0, st.f ?? { auditSeen: false });
		case "resume":
			return { decision: { kind: "resume" }, next: mod.resumeGoal(state, st.now ?? 0) };
		case "pause":
			return { decision: { kind: "pause", reason: st.reason }, next: mod.pauseGoal(state, st.reason, st.now ?? 0, st.detail) };
		case "budget": {
			const r = mod.setBudget(state, st.budget, st.now ?? 0);
			return "error" in r ? { decision: { kind: "error", message: r.error }, next: state } : { decision: { kind: "budget" }, next: r };
		}
		default:
			throw new Error(`unknown op ${st.op}`);
	}
};

// 乱数 (mulberry32)。seed 固定で再現できる
const rng = (seed) => () => {
	seed = (seed + 0x6d2b79f5) | 0;
	let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
	t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
	return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

const fuzz = ({ seed, runs, steps }) => {
	const bad = [];
	const R = rng(seed);
	const pick = (a) => a[Math.floor(R() * a.length)];
	for (let run = 0; run < runs; run++) {
		let s = mod.newGoal("目標", { rounds: 1 + Math.floor(R() * 30), minutes: 1 + Math.floor(R() * 100), ...(R() < 0.3 ? { tokens: 1000 + Math.floor(R() * 50000) } : {}) }, 0, { audit: R() < 0.3 });
		let now = 0;
		let prevUsed = 0;
		let prevLife = { rounds: 0, tokens: 0, evalCalls: 0, evalTokens: 0, resumes: 0 };
		let prevResumes = 0;
		for (let i = 0; i < steps; i++) {
			now += 1000;
			const kind = pick(["settle", "settle", "settle", "verdict", "verdict", "resume", "pause", "budget"]);
			let st;
			if (kind === "settle") {
				const text = pick(["", "a", "b", "同じ", "完了\nGOAL_STATUS: complete", "x\nGOAL_STATUS: blocked: 理由"]);
				st = {
					op: "settle",
					cfg: { evalMode: pick(["claim", "claim", "every"]) },
					facts: {
						mode: pick(["tui", "tui", "tui", "rpc", "print"]),
						outcome: pick(["completed", "completed", "completed", "completed", "error", "aborted"]),
						compacting: R() < 0.1,
						planMode: R() < 0.05,
						pending: R() < 0.05,
						bgBusy: R() < 0.1 ? 1 : 0,
						runMs: Math.floor(R() * 600000),
						now,
						run: { toolCalls: pick([0, 0, 1, 3]), unapproved: pick([0, 0, 0, 1]), text, tokens: Math.floor(R() * 5000), claim: mod.parseClaim(text) },
					},
				};
			} else if (kind === "verdict") {
				st = {
					op: "verdict",
					now,
					v: pick([null, { verdict: "done", reason: "ok" }, { verdict: "continue", reason: pick(["r1", "r2"]) }, { verdict: "blocked", reason: "b" }]),
					f: { auditSeen: R() < 0.5, why: pick(["claim", "stall"]), evalTokens: Math.floor(R() * 3000) },
				};
			} else if (kind === "resume") st = { op: "resume", now };
			else if (kind === "pause") st = { op: "pause", reason: pick(["user", "input", "interrupted"]), now };
			else st = { op: "budget", budget: { rounds: 1 + Math.floor(R() * 40) }, now };
			const before = JSON.stringify(s);
			const { next } = step(deepFreeze(s), st);
			if (JSON.stringify(s) !== before) bad.push(`run ${run} step ${i}: 入力が変わった`);
			const nu = next.used.rounds;
			if (st.op !== "resume" && st.op !== "budget" && nu < prevUsed) bad.push(`run ${run} step ${i}: used.rounds が減った ${prevUsed}->${nu}`);
			if (st.op === "resume" && s.status !== "done") {
				if (next.used.rounds !== 0 || next.used.tokens !== 0 || next.used.runMs !== 0) bad.push(`run ${run} step ${i}: resume で used が 0 にならない`);
			}
			for (const k of Object.keys(prevLife)) if (next.lifetime[k] < prevLife[k]) bad.push(`run ${run} step ${i}: lifetime.${k} が減った`);
			if (next.lifetime.resumes < prevResumes) bad.push(`run ${run} step ${i}: resumes が減った`);
			if (s.status === "done" && next.status !== "done") bad.push(`run ${run} step ${i}: done から戻った`);
			if (st.op !== "resume") {
				for (const k of ["rounds", "runMs", "tokens", "evalCalls", "evalTokens"]) {
					if (next.used[k] < s.used[k]) bad.push(`run ${run} step ${i}: used.${k} が減った (${st.op})`);
				}
			}
			prevUsed = next.used.rounds;
			prevLife = { ...next.lifetime };
			prevResumes = next.lifetime.resumes;
			s = next;
		}
	}
	return bad;
};

const input = JSON.parse(readFileSync(0, "utf-8"));
if (input.calls) {
	const results = input.calls.map((c) => mod[c.fn](...deepFreeze(structuredClone(c.args ?? []))));
	console.log(JSON.stringify({ results }));
} else if (input.chain) {
	let state = input.chain.state;
	const out = [];
	for (const st of input.chain.steps) {
		const r = step(deepFreeze(structuredClone(state)), st);
		out.push(r);
		state = r.next;
	}
	console.log(JSON.stringify({ steps: out }));
} else if (input.fuzz) {
	console.log(JSON.stringify({ bad: fuzz(input.fuzz) }));
}

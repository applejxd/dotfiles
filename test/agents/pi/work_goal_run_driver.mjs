// work/goal-run.ts の試験用 driver。標準入力の JSON (シナリオ) を偽の pi・偽の ctx で実行し、結果を JSON で標準出力へ出す。照合は test_work_goal_run.py。
//
//   {dir, env?, child?, off?, steps: [...]}   off: runtime を無効 (mode off) にして、書き込みが拒否されることを見る
//   step: {ev: "session_start"|"session_shutdown"}
//       | {goal: "<引数>", ui?: bool, confirm?: bool}   (スラッシュコマンド /goal)
//       | {input: "<本文>", source?: "interactive"|"extension"}
//       | {tool: <引数>}                                (ツール work。env に PI_WORK_TOOL=1 のときだけ)
//       | {model: [{type,node,data}...]}                (モデル出所のイベントを runtime へ直接出す)
//       | {facts: true}                                 (settle への goal の事実)
//       | {diff: ["<引数>", ...]}                       (goal-core 直接と台帳経由の突き合わせ)
//   結果: {registered:{tools,commands,handlers}, results:[...], notices:[...], handle: bool}。各結果に snap (goal・task の要約) が付く
// see docs/spec/work/goal-run.md
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const H = resolve(ROOT, "home", "dot_config", "pi", "harness");
const load = (f) => import(pathToFileURL(resolve(H, f)).href);
const [gr, reg, gl, core, ev] = await Promise.all(["work/goal-run.ts", "work/register.ts", "work/goal.ts", "goal-core.ts", "work/events.ts"].map(load));

const sc = JSON.parse(readFileSync(0, "utf-8"));
const env = sc.env ?? { PI_WORK_GOAL: "1" };
const handlers = new Map();
const tools = new Map();
const commands = new Map();
const pi = {
	on: (name, fn) => {
		if (!handlers.has(name)) handlers.set(name, []);
		handlers.get(name).push(fn);
	},
	registerTool: (t) => tools.set(t.name, t),
	registerCommand: (name, c) => commands.set(name, c),
};
const notices = [];
const confirms = [];
const opt = { root: join(sc.dir, ".tmp", "work"), timers: { setInterval: () => 0, clearInterval: () => {} }, ...(sc.off ? { enabled: false } : {}) };
const journal = { emit: () => {} };
delete globalThis.__piWorkRuntime;
const regOpts = { child: sc.child === true, env, journal, runtime: opt };
reg.registerWork(pi, regOpts);
// sc.redact: 題の伏字化の注入の試験 (この語を [R] に替える)
const handle = gr.registerGoal(pi, sc.redact ? { ...regOpts, redact: (t) => t.split(sc.redact).join("[R]") } : regOpts);

const mkCtx = (s) => ({
	cwd: sc.dir,
	hasUI: s.ui !== false,
	sessionManager: { getSessionId: () => "sess-goal" },
	ui: {
		setWidget: () => {},
		notify: (message, level) => notices.push({ message, level }),
		confirm: async (title, body) => {
			confirms.push({ title, body });
			// during: 確認の最中 (Promise が未解決の間) にモデルが work を呼ぶ
			for (const a of s.during ?? []) await tools.get("work").execute("id", a, undefined, undefined, mkCtx({}));
			return s.confirm !== false;
		},
	},
});

const snap = () => {
	const rt = handle?.runtime() ?? globalThis.__piWorkRuntime?.();
	if (!rt) return null;
	const st = rt.state();
	return {
		mode: rt.mode,
		goals: st.goals.map((id) => {
			const n = st.nodes.get(id);
			return { id, state: n.state, title: n.title, budget: n.budget ?? null, pauseReason: n.pauseReason ?? null };
		}),
		tasks: [...st.nodes.values()].filter((n) => n.kind === "task").map((n) => ({ title: n.title, state: n.state, approved: n.approved === true })),
	};
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fire = async (name, event, ctx) => {
	const out = [];
	for (const fn of handlers.get(name) ?? []) out.push((await fn(event, ctx)) ?? null);
	return out;
};

const results = [];
for (const s of sc.steps) {
	const ctx = mkCtx(s);
	const r = {};
	try {
		if (s.ev) {
			r.ret = await fire(s.ev, { reason: "startup" }, ctx);
		} else if (s.goal !== undefined) {
			await commands.get("goal").handler(s.goal, ctx);
			await sleep(3);
		} else if (s.input !== undefined) {
			r.ret = await fire("input", { text: s.input, source: s.source ?? "interactive" }, ctx);
		} else if (s.tool !== undefined) {
			const t = tools.get("work");
			r.tool = t ? (await t.execute("id", s.tool, undefined, undefined, ctx)).content[0].text : null;
		} else if (s.model) {
			const rt = handle.runtime();
			const out = [];
			for (const e of s.model) {
				const node = e.node ?? snap().goals.at(-1)?.id;
				// data 内の "$GOAL" は現在の goal の id に置き換える (台帳へ直接足す task の parent に使う)
				const gid = snap().goals.at(-1)?.id ?? "";
				const data = JSON.parse(JSON.stringify(e.data ?? {}).replaceAll("$GOAL", gid));
				let made = true;
				try {
					ev.makeEvent(e.type, node, data, e.source ?? "model");
				} catch {
					made = false; // 作る段階で拒否される
				}
				// 作る段階を迫る生のイベントを runtime へ直接出し、runtime 側でも拒否されることを見る
				const submitted = await rt.submit([{ type: e.type, node, data, source: e.source ?? "model" }]);
				out.push({ ok: submitted.ok, error: submitted.error ?? null, made });
			}
			r.model = out;
		} else if (s.facts) {
			r.facts = globalThis.__piGoalSnapshot ? (globalThis.__piGoalSnapshot() ?? null) : "none";
		} else if (s.diff) {
			const rt = handle.runtime();
			let exp = null;
			const mism = [];
			for (const a of s.diff) {
				const cmd = core.parseGoalArgs(a);
				const now = Date.now();
				if (cmd.kind === "set") {
					if (!exp) {
						const g = core.newGoal(cmd.text, cmd.budget, now, { audit: cmd.audit });
						if (!("error" in g)) exp = g;
					}
				} else if (cmd.kind === "pause") {
					if (exp?.status === "active") exp = core.pauseGoal(exp, "user", now);
				} else if (cmd.kind === "resume") {
					if (exp?.status === "paused") exp = core.resumeGoal(exp, now);
				} else if (cmd.kind === "budget") {
					if (exp) {
						const b = core.setBudget(exp, cmd.budget, now);
						if (!("error" in b)) exp = b;
					}
				} else if (cmd.kind === "clear") exp = null;
				await commands.get("goal").handler(a, ctx);
				await sleep(3);
				const got = gl.goalStateOf(rt.state());
				const pick = (g) => (g ? { status: g.status, budget: g.budget, text: g.text, audit: g.audit, pause: g.pause?.reason ?? null } : null);
				const e = pick(exp);
				if (e && e.pause === "user") e.pause = "user";
				if (JSON.stringify(pick(got)) !== JSON.stringify(e)) mism.push({ a, got: pick(got), exp: e });
			}
			r.mismatches = mism;
		}
	} catch (e) {
		r.threw = String(e);
	}
	r.snap = snap();
	r.notices = notices.length;
	results.push(r);
}
const lastTool = tools.get("work");
console.log(
	JSON.stringify({
		registered: { tools: [...tools.keys()], commands: [...commands.keys()], handlers: [...handlers.keys()] },
		handle: !!handle,
		hasTool: !!lastTool,
		results,
		notices,
		confirms,
	}),
);
await Promise.all(
	(handlers.get("session_shutdown") ?? []).map((fn) => fn({}, mkCtx({}))),
);
process.exit(0);

// 調停の配線 (autocheckpoint.ts・todo 拡張・work/settle.ts を同じ偽の pi に登録する) の試験用 driver。照合は test_work_settle_wire.py。
//
//   node work_settle_wire_driver.mjs <todo の index.ts>   (標準入力の JSON を実行し、結果を JSON で標準出力へ出す)
//   {"mode":"wire","flag":bool,"todos":[{id,text,status}],"steps":[{"outcome","percent","pending","finish"}]}
//       旗 (PI_WORK_ARBITER) の有無で 3 者を登録し、handlers (イベント名 → 個数)・各 settle の結果を返す
//   {"mode":"snap","cases":[SnapshotInput..]}   buildSnapshot の結果を返す
// see docs/spec/work/settle.md
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const H = resolve(ROOT, "home", "dot_config", "pi", "harness");
const imp = (p) => import(pathToFileURL(p).href);
const req = JSON.parse(readFileSync(0, "utf-8"));
const todoPath = process.argv[2];

if (req.mode === "wire") {
	if (req.flag) process.env.PI_WORK_ARBITER = "1";
	else delete process.env.PI_WORK_ARBITER;
	delete process.env.PI_AUTOCHECKPOINT;
	const ac = await imp(resolve(H, "autocheckpoint.ts"));
	const st = await imp(resolve(H, "work", "settle.ts"));
	const sn = await imp(resolve(H, "work", "settle-snapshot.ts"));
	const todoMod = await imp(todoPath);
	const handlers = {};
	const wakes = [];
	const resumes = [];
	const compacts = [];
	const notes = [];
	const sent = [];
	const pi = {
		on: (n, f) => (handlers[n] ??= []).push(f),
		registerTool: () => {},
		registerCommand: () => {},
		appendEntry: () => {},
		sendUserMessage: (t) => sent.push(t),
	};
	let clock = 0;
	let cur = { percent: null, finish: undefined };
	ac.registerAutoCheckpoint(pi, { child: false, compactInstructions: "I", env: process.env, now: () => clock, resume: (t) => resumes.push(t), resumeDelayMs: 5 });
	todoMod.default(pi);
	let registered = null;
	if (req.flag) {
		const deps = sn.makeSettleDeps({
			checkpointSnapshot: ac.checkpointSnapshot,
			checkpointExec: ac.checkpointExec,
			todoSnapshot: () => globalThis.__piTodoSnapshot?.(),
			wake: (p) => wakes.push(p),
		});
		registered = st.registerSettle(pi, deps, { enabled: true, child: false }).registered;
	}
	const branch = [{ type: "custom", customType: "todo-state", data: { nextId: 99, todos: req.todos ?? [] } }];
	const ctx = {
		mode: "tui",
		hasUI: false,
		ui: { notify: (m) => notes.push(m), setStatus: () => {} },
		sessionManager: { getBranch: () => branch },
		hasPendingMessages: () => cur.pending === true,
		isCompacting: () => false,
		getContextUsage: () => ({ percent: cur.percent }),
		compact: (o) => {
			compacts.push(o);
			if (cur.finish === "complete") o.onComplete?.({});
		},
	};
	for (const f of handlers.session_start ?? []) await f({}, ctx);
	const out = [];
	for (const step of req.steps ?? []) {
		cur = step;
		clock = step.at ?? clock;
		for (const f of handlers.before_agent_start ?? []) await f({ messageType: step.userTurn === false ? "x" : "user" }, ctx);
		const nc = compacts.length;
		const nw = wakes.length;
		// pi 本体の合成規則: entries は後勝ち、continue も後勝ち。event.entries に前の結果が入る
		let entries = [];
		let cont = false;
		for (const h of handlers.agent_before_settle ?? []) {
			const r = await h({ type: "agent_before_settle", outcome: step.outcome ?? "completed", entries, continue: cont }, ctx);
			if (r?.entries !== undefined) entries = r.entries;
			if (r?.continue !== undefined) cont = r.continue;
		}
		out.push({
			types: entries.map((x) => x.customType),
			cont,
			compacts: compacts.length - nc,
			wakes: wakes.length - nw,
			phase: ac.checkpointSnapshot().phase,
		});
	}
	await new Promise((r) => setTimeout(r, 30));
	process.stdout.write(
		JSON.stringify({
			registered,
			handlers: Object.fromEntries(Object.entries(handlers).map(([k, v]) => [k, v.length])),
			steps: out,
			resumes,
			wakes,
			sent,
			todoSnapshot: globalThis.__piTodoSnapshot ? JSON.parse(JSON.stringify(globalThis.__piTodoSnapshot())) : null,
		}),
	);
} else if (req.mode === "snap") {
	const sn = await imp(resolve(H, "work", "settle-snapshot.ts"));
	process.stdout.write(JSON.stringify({ results: req.cases.map((c) => sn.buildSnapshot(c === "__undefined__" ? undefined : c)) }));
} else throw new Error("未知の要求");

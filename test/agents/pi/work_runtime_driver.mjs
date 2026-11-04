// work/runtime.ts の試験の道具。親 (test_work_runtime.py) が実 fs の root を渡して呼ぶ。
//
//   node test/agents/pi/work_runtime_driver.mjs run                      標準入力の操作列 (JSON) を実行し、結果の配列を JSON で出す
//   node test/agents/pi/work_runtime_driver.mjs child-submit <root> <n>  runtime を開き、note を 1 件ずつ submit。ack を 1 行ずつ出す
//
// see docs/spec/work/runtime.md
import { readFileSync, writeSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const WORK = join(ROOT, "home", "dot_config", "pi", "harness", "work");
const { createRuntime } = await import(pathToFileURL(join(WORK, "runtime.ts")).href);
const { createStore } = await import(pathToFileURL(join(WORK, "store.ts")).href);

const out = (s) => writeSync(1, s);

const plain = (state) => ({
	seq: state.seq,
	goals: [...state.goals],
	nodes: Object.fromEntries([...state.nodes.entries()]),
	anomalies: state.anomalies,
});

async function run() {
	const ops = JSON.parse(readFileSync(0, "utf8"));
	let clock = 1_000_000;
	const dead = new Set();
	const faults = {};
	const rts = {};
	const log = {};
	const results = [];
	for (const op of ops) {
		try {
			switch (op.op) {
				case "clock":
					clock = op.t;
					results.push({ ok: true });
					break;
				case "deadpids":
					for (const p of op.pids) dead.add(p);
					results.push({ ok: true });
					break;
				case "open": {
					const name = op.name;
					const l = { alerts: [], changes: [], timers: { fn: null, ms: null, set: 0, cleared: 0 } };
					log[name] = l;
					rts[name] = createRuntime({
						cwd: op.cwd ?? ROOT,
						sessionId: `s-${name}`,
						holder: op.holder ?? name,
						pid: op.pid ?? 111,
						now: () => clock,
						env: op.env ?? {},
						enabled: op.enabled,
						autoLease: op.autoLease,
						root: op.root,
						gitCommonDir: op.gitCommonDir,
						timers: {
							setInterval: (fn, ms) => {
								l.timers.fn = fn;
								l.timers.ms = ms;
								l.timers.set++;
								return "h";
							},
							clearInterval: () => {
								l.timers.cleared++;
							},
						},
						onChange: (s, applied) => {
							l.changes.push({ seq: s.seq, types: applied.map((e) => e.type), n: applied.length });
						},
						onAlert: (m) => l.alerts.push(m),
						storeOptions: {
							isPidAlive: (p) => !dead.has(p),
							beforeWrite: (p) => {
								const code = faults[name];
								if (code) {
									const e = new Error(`${code}: 注入された障害 (${p})`);
									e.code = code;
									throw e;
								}
							},
							...(op.storeOptions ?? {}),
						},
					});
					results.push({ ok: true });
					break;
				}
				case "start":
					await rts[op.name].start();
					results.push({ ok: true, mode: rts[op.name].mode, reason: rts[op.name].readonlyReason });
					break;
				case "submit": {
					const r = await rts[op.name].submit(op.events);
					results.push({ ...r, mode: rts[op.name].mode });
					break;
				}
				case "submitMany": {
					// 並行呼び出し (直列化の確認)
					const rs = await Promise.all(op.batches.map((b) => rts[op.name].submit(b)));
					results.push({ ok: true, value: rs });
					break;
				}
				case "state":
					results.push({ ok: true, value: plain(rts[op.name].state()), mode: rts[op.name].mode });
					break;
				case "mode":
					results.push({ ok: true, mode: rts[op.name].mode, reason: rts[op.name].readonlyReason });
					break;
				case "mutate": {
					// 状態を書き換えようとする。全部が失敗 (例外か無視) し、次の state() が変わらないこと
					const s = rts[op.name].state();
					const tried = [];
					const attempt = (label, fn) => {
						try {
							fn();
							tried.push({ label, threw: false });
						} catch {
							tried.push({ label, threw: true });
						}
					};
					attempt("seq", () => {
						"use strict";
						s.seq = 999;
					});
					attempt("nodes.set", () => s.nodes.set("zzz", {}));
					attempt("nodes.delete", () => s.nodes.clear());
					attempt("goals.push", () => s.goals.push("zzz"));
					const first = [...s.nodes.values()][0];
					if (first) attempt("node.title", () => {
						first.title = "書き換え";
					});
					results.push({ ok: true, value: tried, frozen: Object.isFrozen(s) });
					break;
				}
				case "fault":
					faults[op.name] = op.code;
					results.push({ ok: true });
					break;
				case "tick": {
					const t = log[op.name].timers;
					if (!t.fn) throw new Error("timer が無い");
					t.fn();
					await rts[op.name].heartbeatNow();
					results.push({ ok: true, mode: rts[op.name].mode });
					break;
				}
				case "log":
					results.push({ ok: true, value: log[op.name] });
					break;
				case "close":
					await rts[op.name].close();
					results.push({ ok: true, mode: rts[op.name].mode });
					break;
				case "raw": {
					// runtime を通さず store へ直接追記する (不変条件を破る台帳・壊れた台帳の用意)
					const st = createStore({ root: op.root, now: () => clock, pid: op.pid ?? 999, isPidAlive: () => true });
					const lease = await st.acquireLease("raw", op.pid ?? 999);
					if (!lease) throw new Error("raw: lease が取れない");
					for (const e of op.events) await st.append(e);
					await st.releaseLease();
					results.push({ ok: true });
					break;
				}
				default:
					throw new Error(`未知の op: ${op.op}`);
			}
		} catch (e) {
			results.push({ ok: false, error: String(e?.message ?? e), code: e?.code });
		}
	}
	out(`${JSON.stringify(results)}\n`);
}

async function childSubmit(root, n) {
	const rt = createRuntime({ cwd: ROOT, sessionId: "child", holder: "child", pid: process.pid, root, env: {} });
	await rt.start();
	if (rt.mode !== "driver") {
		out(`mode ${rt.mode}\n`);
		return;
	}
	const first = await rt.submit([{ type: "goal.created", node: "g1", data: { title: "g" }, source: "system" }]);
	out(`ack ${first.applied[0].seq}\n`);
	for (let i = 0; i < Number(n); i++) {
		const r = await rt.submit([{ type: "note.appended", node: "g1", data: { by: "llm", text: `n${i}` }, source: "model" }]);
		if (!r.ok) {
			out(`err ${r.error}\n`);
			return;
		}
		out(`ack ${r.applied[0].seq}\n`);
	}
	// 終わらずに待つ (親が kill -9 する)
	await new Promise((r) => setTimeout(r, 60_000));
}

const cmd = process.argv[2];
if (cmd === "run") await run();
else if (cmd === "child-submit") await childSubmit(process.argv[3], process.argv[4]);
else {
	process.stderr.write("usage: run | child-submit <root> <n>\n");
	process.exit(2);
}

// work/store.ts・work/root.ts の試験の道具。親 (test_work_store.py) が実 fs の root を渡して呼ぶ。
//
//   node test/agents/pi/work_store_driver.mjs run            標準入力の操作列 (JSON) を実行し、結果の配列を JSON で出す
//   node test/agents/pi/work_store_driver.mjs child-append <root> <n> <seed>   ack を 1 件ごとに標準出力へ出しながら追記し続ける
//   node test/agents/pi/work_store_driver.mjs child-hold <root> <ms>           lease を取って 1 件追記し、ms だけ保持して終える
//   node test/agents/pi/work_store_driver.mjs child-try <root> <holder>        lease を取って追記を試み、結果を JSON で出す
//   node test/agents/pi/work_store_driver.mjs child-race <root> <holder> <startAt>   startAt (epoch ms) まで待って acquireLease を試す
//
// see docs/spec/work/store.md
import { readFileSync, writeSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const WORK = join(ROOT, "home", "dot_config", "pi", "harness", "work");
const { createStore, crc32 } = await import(pathToFileURL(join(WORK, "store.ts")).href);
const { resolveStoreRoot } = await import(pathToFileURL(join(WORK, "root.ts")).href);

const out = (s) => writeSync(1, s);

function errInfo(e) {
	return { ok: false, code: e?.code ?? "?", name: e?.name ?? "?", message: String(e?.message ?? e) };
}

async function run() {
	const ops = JSON.parse(readFileSync(0, "utf8"));
	let clock = 1_000_000;
	const dead = new Set();
	const faults = {};
	const stores = {};
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
					stores[name] = createStore({
						root: op.root,
						now: () => clock,
						pid: op.pid ?? process.pid,
						segmentSize: op.segmentSize,
						snapshotEvery: op.snapshotEvery,
						isPidAlive: op.realPids ? undefined : (p) => !dead.has(p),
						beforeWrite: (p) => {
							const code = faults[name];
							if (code) {
								const e = new Error(`${code}: 注入された障害 (${p})`);
								e.code = code;
								throw e;
							}
						},
					});
					results.push({ ok: true });
					break;
				}
				case "fault":
					faults[op.name] = op.code;
					results.push({ ok: true });
					break;
				case "acquire":
					results.push({ ok: true, value: await stores[op.name].acquireLease(op.holder, op.pid ?? process.pid) });
					break;
				case "append":
					results.push({ ok: true, value: await stores[op.name].append({ type: op.type ?? "notice", node: op.node, data: op.data ?? {}, aux: op.aux, source: op.source, holder: op.holder }) });
					break;
				case "appendN": {
					let last = null;
					for (let i = 0; i < op.n; i++) last = await stores[op.name].append({ type: "notice", data: { i } });
					results.push({ ok: true, value: last });
					break;
				}
				case "load":
					results.push({ ok: true, value: await stores[op.name].load() });
					break;
				case "loadSince":
					results.push({ ok: true, value: await stores[op.name].loadSince(op.seq) });
					break;
				case "heartbeat":
					await stores[op.name].heartbeat();
					results.push({ ok: true });
					break;
				case "release":
					await stores[op.name].releaseLease();
					results.push({ ok: true });
					break;
				case "saveSnapshot":
					await stores[op.name].saveSnapshot(op.seq, op.json);
					results.push({ ok: true });
					break;
				case "loadSnapshot":
					results.push({ ok: true, value: await stores[op.name].loadSnapshot() });
					break;
				case "snapshotDue":
					results.push({ ok: true, value: stores[op.name].snapshotDue(op.seq) });
					break;
				case "readonlyReason":
					results.push({ ok: true, value: stores[op.name].readonlyReason });
					break;
				case "currentLease":
					results.push({ ok: true, value: stores[op.name].currentLease() });
					break;
				case "crc32":
					results.push({ ok: true, value: crc32(Buffer.from(op.text, "utf8")) });
					break;
				case "resolveRoot": {
					const allow = new Set(op.writable);
					results.push({ ok: true, value: resolveStoreRoot({ gitCommonDir: op.gitCommonDir, cwd: op.cwd, canWrite: (p) => allow.has(p) }) });
					break;
				}
				default:
					results.push({ ok: false, code: "BAD_OP", message: String(op.op) });
			}
		} catch (e) {
			results.push(errInfo(e));
		}
	}
	out(`${JSON.stringify(results)}\n`);
}

async function childAppend(root, n, seed) {
	const st = createStore({ root });
	const lease = await st.acquireLease("child", process.pid);
	if (!lease) {
		out("nolease\n");
		return;
	}
	out("ready\n");
	// seed 固定の大きさのペイロードで、追記の境界 (行の途中) を kill のタイミングごとにずらす
	let s = Number(seed) >>> 0;
	for (let i = 0; i < Number(n); i++) {
		s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
		const pad = "x".repeat(s % 700);
		const ev = await st.append({ type: "notice", data: { i, pad } });
		out(`ack ${ev.seq}\n`);
	}
	out("done\n");
}

async function childHold(root, ms) {
	const st = createStore({ root });
	const lease = await st.acquireLease("holder", process.pid);
	if (!lease) {
		out("nolease\n");
		return;
	}
	await st.append({ type: "notice", data: { who: "holder" } });
	out("ready\n");
	await new Promise((r) => setTimeout(r, Number(ms)));
}

async function childTry(root, holder) {
	const st = createStore({ root });
	const lease = await st.acquireLease(holder, process.pid);
	let append;
	try {
		const ev = await st.append({ type: "notice", data: { who: holder } });
		append = { ok: true, seq: ev.seq };
	} catch (e) {
		append = errInfo(e);
	}
	out(`${JSON.stringify({ lease: lease !== null, append })}\n`);
}

async function childRace(root, holder, startAt) {
	const st = createStore({ root });
	while (Date.now() < Number(startAt)) {
		/* 同時に始めるための忙しい待ち */
	}
	const lease = await st.acquireLease(holder, process.pid);
	out(`${JSON.stringify({ holder, got: lease !== null })}\n`);
}

const [, , cmd, ...args] = process.argv;
if (cmd === "run") await run();
else if (cmd === "child-append") await childAppend(...args);
else if (cmd === "child-hold") await childHold(...args);
else if (cmd === "child-try") await childTry(...args);
else if (cmd === "child-race") await childRace(...args);
else {
	process.stderr.write(`unknown command: ${cmd}\n`);
	process.exit(2);
}

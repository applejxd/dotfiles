// work/journal.ts の試験用 driver。標準入力の JSON (シナリオ) を実行し、結果を JSON で標準出力へ出す。照合は test_work_journal.py。
//
//   mode "register": {mode, dir, env?, child?, steps:[{at, event, payload, ctx?}]} → {registered, returns, lines, files}
//   mode "create":   {mode, dir, events:[{type, data}], sessionId?} → {lines, lastError, path}
// see docs/spec/work/journal.md
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const mod = await import(pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "work", "journal.ts")).href);

const sc = JSON.parse(readFileSync(0, "utf-8"));
let clock = 0;
const now = () => clock;

const readLines = (dir) => {
	const out = [];
	let files = [];
	try {
		files = readdirSync(dir)
			.filter((f) => f.endsWith(".jsonl"))
			.sort();
	} catch {
		return { files: [], lines: [] };
	}
	for (const f of files) for (const l of readFileSync(join(dir, f), "utf-8").split("\n")) if (l !== "") out.push(l);
	return { files, lines: out };
};

if (sc.mode === "create") {
	const j = mod.createJournal({ dir: sc.dir, sessionId: sc.sessionId ?? "s1", now });
	for (const e of sc.events) {
		clock += 1;
		j.emit(e.type, e.data, e.node);
	}
	const r = readLines(sc.dir);
	console.log(JSON.stringify({ lines: r.lines, files: r.files, lastError: j.lastError ?? null, path: j.path }));
} else {
	const handlers = new Map();
	const pi = {
		on: (name, fn) => {
			if (!handlers.has(name)) handlers.set(name, []);
			handlers.get(name).push(fn);
		},
	};
	mod.registerJournal(pi, { child: sc.child === true, env: sc.env ?? {}, now, dir: sc.dir });
	const returns = [];
	for (const s of sc.steps) {
		clock = s.at ?? clock;
		for (const fn of handlers.get(s.event) ?? []) {
			try {
				returns.push(await fn(s.payload, s.ctx ?? { cwd: sc.dir, sessionManager: { getSessionId: () => "sess1" } }));
			} catch (e) {
				returns.push({ threw: String(e) });
			}
		}
	}
	const r = readLines(sc.dir);
	console.log(JSON.stringify({ registered: handlers.size > 0, handlerNames: [...handlers.keys()], returns, lines: r.lines, files: r.files }));
}

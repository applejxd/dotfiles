// work/register.ts の試験用 driver。標準入力の JSON (シナリオ) を偽の pi・偽の ctx で実行し、結果を JSON で標準出力へ出す。照合は test_work_register.py。
//
//   {dir, env?, child?, pis?: ["a", ...], steps: [...]}
//   step: {pi?, ev: "session_start"|"session_shutdown", sid?, ui?: bool}
//       | {pi?, tool: <引数>, ui?: bool}     (ツール work を呼ぶ)
//       | {pi?, cmd: "work", ui?: bool}      (スラッシュコマンド)
//       | {arm: N}                           (log/ への追記を N 件通した後、失敗させる)
//   結果: {registered:{<pi>:{tools,commands,handlers}}, results:[...], widgets:[...], notices:[...], lease: bool, journal:[...]}
// see docs/spec/work/register.md
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const W = resolve(ROOT, "home", "dot_config", "pi", "harness", "work");
const reg = await import(pathToFileURL(resolve(W, "register.ts")).href);

const sc = JSON.parse(readFileSync(0, "utf-8"));
const env = sc.env ?? { PI_WORK_TOOL: "1" };
const names = sc.pis ?? ["a"];
const pis = {};
const widgets = [];
const notices = [];
const journal = [];
let clock = 1_700_000_000_000;
// 追記の障害注入: {arm: N} の step の後、台帳ログ (log/) への追記を N 件だけ通し、次から失敗させる
let budget = null;
const beforeWrite = (p) => {
	if (budget === null || !String(p).replace(/\\/g, "/").includes("/log/")) return;
	if (budget <= 0) {
		const e = new Error(`EIO: 注入された障害 (${p})`);
		e.code = "EIO";
		throw e;
	}
	budget--;
};

for (const n of names) {
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
	reg.registerWork(pi, {
		child: sc.child === true,
		env,
		pid: n === "a" ? process.pid : process.ppid,
		journal: { emit: (type, data) => journal.push({ pi: n, type, data }) },
		runtime: { root: join(sc.dir, ".tmp", "work"), now: () => clock++, timers: { setInterval: () => 0, clearInterval: () => {} }, storeOptions: { beforeWrite } },
	});
	pis[n] = { handlers, tools, commands };
}

const mkCtx = (n, s) => ({
	cwd: sc.dir,
	hasUI: s.ui !== false,
	sessionManager: { getSessionId: () => s.sid ?? `sess-${n}` },
	ui: {
		setWidget: (key, lines) => widgets.push({ pi: n, key, lines: lines ?? null }),
		notify: (message, level) => notices.push({ pi: n, message, level }),
	},
});

const results = [];
for (const s of sc.steps) {
	const n = s.pi ?? "a";
	const p = pis[n];
	const ctx = mkCtx(n, s);
	try {
		if (s.arm !== undefined) {
			budget = s.arm;
		} else if (s.ev) {
			for (const fn of p.handlers.get(s.ev) ?? []) results.push({ ret: (await fn({ reason: s.reason ?? "startup" }, ctx)) ?? null });
			if (!(p.handlers.get(s.ev) ?? []).length) results.push({ none: true });
		} else if (s.tool !== undefined) {
			const t = p.tools.get("work");
			if (!t) results.push({ none: true });
			else results.push(await t.execute("id", s.tool, undefined, undefined, ctx));
		} else if (s.cmd) {
			const c = p.commands.get(s.cmd);
			if (!c) results.push({ none: true });
			else results.push({ ret: (await c.handler("", ctx)) ?? null });
		}
	} catch (e) {
		results.push({ threw: String(e) });
	}
}

const registered = {};
for (const [n, p] of Object.entries(pis)) {
	const t = p.tools.get("work");
	registered[n] = {
		tools: [...p.tools.keys()],
		commands: [...p.commands.keys()],
		handlers: [...p.handlers.keys()],
		parameters: t ? t.parameters : null,
	};
}
const lease = existsSync(join(sc.dir, ".tmp", "work", "lease", "owner.json"));
const files = existsSync(join(sc.dir, ".tmp", "work")) ? readdirSync(join(sc.dir, ".tmp", "work")).sort() : [];
console.log(JSON.stringify({ registered, results, widgets, notices, lease, files, journal }));

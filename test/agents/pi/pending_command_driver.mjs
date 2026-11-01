// `/pending` (pending-command.ts。CHG-0055 の P5b) を、偽の pi・偽の ctx・使い捨ての git リポジトリで動かして固定する。結果を JSON で標準出力へ出す。
// 照合は test_pi_pending_command.py。
//
//   node test/agents/pi/pending_command_driver.mjs
//
// see docs/change/0055-async-approval.md
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const harness = (name) => pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", name)).href;
const ops = await import(harness("pending-ops.ts"));
const store = await import(harness("pending-store.ts"));
const cmd = await import(harness("pending-command.ts"));
const adapters = await import(harness("pending-adapters.ts"));

const ENV = { ...process.env, GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@example.test", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@example.test" };
const git = (cwd, ...args) => execFileSync("git", args, { cwd, env: ENV, encoding: "utf8" }).trim();

function repo() {
	const dir = mkdtempSync(join(tmpdir(), "pi-pcmd-"));
	git(dir, "init", "-q", "-b", "main");
	writeFileSync(join(dir, "seed.txt"), "seed\n");
	git(dir, "add", "-A");
	git(dir, "commit", "-q", "-m", "seed");
	return dir;
}

/** 旧形式の退避を 1 件作る (ステージして tree を確定し、保存する) */
function legacy(cwd, name) {
	writeFileSync(join(cwd, name), `${name}\n`);
	git(cwd, "add", name);
	const snap = store.snapshotStaged(cwd, `feat: ${name}`, `req-${name}`);
	const saved = store.savePendingSnapshot(cwd, snap);
	git(cwd, "reset", "-q");
	return saved;
}

const record = (over = {}) => ({
	action: "fake_op",
	params: { mode: "success" },
	premise: { x: 1 },
	reason: "timeout",
	request: { id: "req-1", sessionId: "s-req", cwd: "/w" },
	createdAt: new Date().toISOString(),
	...over,
});
const save = (cwd, over = {}) => {
	const r = ops.saveOp(cwd, record(over));
	if (!r.ok) throw new Error(`save failed: ${r.reason}`);
	return r;
};

const fakeAdapter = (marks) => ({
	action: "fake_op",
	label: "試験の操作",
	plan: async (rec) => ({ ok: true, plan: { mode: rec.params.mode }, summary: "要約", view: "全文" }),
	recheck: async () => ({ ok: true }),
	execute: async () => {
		marks.push("execute");
		return { outcome: "success", phase: "done", confirmedEffects: ["操作を実行した"], remainingCleanup: [], evidence: [] };
	},
});

/** 偽の pi と、/pending の登録。config は [pi.pending] の生の値 (呼ぶたびに読まれる) */
function setup(o = {}) {
	const state = { config: { enabled: o.enabled ?? false, modes: ["tui"] }, marks: [], sent: [], touched: 0 };
	const commands = {};
	const pi = {
		registerCommand: (name, def) => {
			commands[name] = def;
		},
		registerTool: () => {
			throw new Error("registerTool は呼ばない");
		},
	};
	const handle = cmd.registerPendingCommand(pi, {
		settings: () => cmd.pendingSettings(state.config),
		redact: (t) => t,
		touch: () => state.touched++,
		approveDeps: () => ({
			adapters: { fake_op: fakeAdapter(state.marks) },
			enabled: () => cmd.pendingSettings(state.config).enabled,
			modes: cmd.pendingSettings(state.config).modes,
			rules: {},
			env: ENV,
			dialog: (fn) => fn(),
			bell: () => {},
			owner: () => ({ sessionId: "s", runtimeEpoch: "e", pid: process.pid, processStart: "1", host: "h" }),
			notify: () => {},
			tellModel: (content, details) => state.sent.push({ content, details }),
			liveness: () => ({ state: "gone", reason: "止まっている" }),
		}),
	});
	/** /pending を 1 回動かす。notify と setStatus の記録を返す */
	state.run = async (cwd, args, c = {}) => {
		const notes = [];
		const status = [];
		const answers = [...(c.answers ?? ["承認して実行"])];
		const ctx = {
			cwd,
			mode: c.mode ?? "tui",
			hasUI: c.hasUI ?? true,
			isIdle: () => c.idle ?? true,
			ui: {
				notify: (text, level) => notes.push({ text, level }),
				setStatus: (key, text) => status.push({ key, text }),
				select: async () => answers.shift(),
				editor: async () => undefined,
			},
		};
		await commands.pending.handler(args, ctx);
		return { text: notes.map((n) => n.text).join("\n"), level: notes[0]?.level, status };
	};
	state.commands = commands;
	state.handle = handle;
	return state;
}

const out = {};

// 1. 旧形式: 一覧・表示・破棄 (従来の出力)
{
	const cwd = repo();
	const h = setup();
	out.legacy_empty = (await h.run(cwd, "")).text;
	const s = legacy(cwd, "a.txt");
	const id = s.ref.slice("refs/pi/pending/".length);
	const list = await h.run(cwd, "list");
	const show = await h.run(cwd, `show ${id}`);
	const missing = await h.run(cwd, "show 000000000000000");
	const drop = await h.run(cwd, `drop ${id}`);
	const dropAgain = await h.run(cwd, `drop ${id}`);
	out.legacy = {
		id,
		short: s.short,
		list: list.text,
		listLevel: list.level,
		showHasMessage: show.text.includes("feat: a.txt") && show.text.includes("a.txt"),
		missing: missing.text,
		drop: drop.text,
		dropAgain: dropAgain.text,
		after: (await h.run(cwd, "list")).text,
		usage: (await h.run(cwd, "bogus")).text,
		touched: h.touched,
	};
}

// 2. 新形式: 一覧・表示・ログ。旧形式と一緒に出る
{
	const cwd = repo();
	const h = setup();
	const l = legacy(cwd, "b.txt");
	const s = save(cwd);
	const list = await h.run(cwd, "list");
	const show = await h.run(cwd, `show ${s.id}`);
	const log = await h.run(cwd, "log");
	out.modern = {
		id: s.id,
		legacyId: l.ref.slice("refs/pi/pending/".length),
		list: list.text,
		show: show.text,
		log: log.text,
		listStatus: list.status,
	};
}

// 3. 無効 (enabled = false): 承認と resolve の承認は断り、一覧・表示・破棄は動く
{
	const cwd = repo();
	const h = setup({ enabled: false });
	const s = save(cwd);
	const approve = await h.run(cwd, `approve ${s.id}`);
	const resolve = await h.run(cwd, `resolve ${s.id} success`);
	const list = await h.run(cwd, "list");
	const drop = await h.run(cwd, `drop ${s.id}`);
	out.disabled = {
		approve: approve.text,
		approveLevel: approve.level,
		resolve: resolve.text,
		listHasId: list.text.includes(s.id),
		drop: drop.text,
		pendingAfterDrop: ops.countPending(cwd),
		executed: h.marks.length,
		dropStatus: drop.status,
	};
}

// 4. 有効 + 偽のアダプタ: 承認して実行し、モデルへ固定のテンプレートで 1 回通知する。フッターが更新される
{
	const cwd = repo();
	const h = setup({ enabled: true });
	const s = save(cwd);
	const before = await h.run(cwd, "list");
	const r = await h.run(cwd, `approve ${s.id}`);
	out.approve = {
		text: r.text,
		level: r.level,
		marks: h.marks,
		sent: h.sent.length,
		content: h.sent[0]?.content ?? "",
		details: h.sent[0]?.details ?? null,
		beforeStatus: before.status,
		afterStatus: r.status,
		pendingLeft: ops.countPending(cwd),
		log: (await h.run(cwd, "log")).text,
	};
}

// 5. 断る条件: 非 TUI・モデルの実行中・UI なし。何も実行しない
{
	const cwd = repo();
	const h = setup({ enabled: true });
	h.config.modes = ["tui", "rpc"];
	const s = save(cwd);
	const rpc = await h.run(cwd, `approve ${s.id}`, { mode: "rpc" });
	const busy = await h.run(cwd, `approve ${s.id}`, { idle: false });
	const noUi = await h.run(cwd, `approve ${s.id}`, { hasUI: false });
	out.refusals = { rpc: rpc.text, busy: busy.text, noUi: noUi.text, marks: h.marks, sent: h.sent.length, pending: ops.countPending(cwd), noUiStatus: noUi.status };
}

// 6. 登録: コマンドだけ (ツールは登録しない)。アダプタの表は今は空。abortAll で待機中の承認を止められる
{
	const h = setup();
	out.registration = {
		commands: Object.keys(h.commands),
		pendingAdapters: Object.keys(adapters.PENDING_ADAPTERS),
		approvalAdapters: Object.keys(adapters.APPROVAL_ADAPTERS),
	};
	const cwd = repo();
	const h2 = setup({ enabled: true });
	const s = save(cwd);
	// 承認の画面で待たせ、abortAll で止める (signal が中断されると、画面は undefined を返して保留のまま閉じる)
	let release;
	const waiting = new Promise((res) => (release = res));
	const run = h2.commands.pending.handler(`approve ${s.id}`, {
		cwd,
		mode: "tui",
		hasUI: true,
		isIdle: () => true,
		ui: { notify: () => {}, setStatus: () => {}, select: async (_t, _o, opts) => (release(), new Promise((res) => opts?.signal?.addEventListener("abort", () => res(undefined), { once: true }))) },
	});
	await waiting;
	h2.handle.abortAll();
	const finished = await Promise.race([run.then(() => true), new Promise((res) => setTimeout(() => res(false), 3000))]);
	out.abort = { finished, pending: ops.countPending(cwd), marks: h2.marks };
}

// 7. resolve: 引数の検査 (有効・無効に関わらず復旧は残る)
{
	const cwd = repo();
	const h = setup({ enabled: false });
	out.resolve = { badKind: (await h.run(cwd, "resolve 000000000000001 maybe")).text, nothing: (await h.run(cwd, "resolve 000000000000001 success")).text };
}

// 8. unlock: ロックが無いときは無いと言う (対話の pi だけ。有効・無効に関わらず復旧は残る)。USAGE に載る
{
	const cwd = repo();
	const h = setup({ enabled: false });
	const none = await h.run(cwd, "unlock");
	const rpc = await h.run(cwd, "unlock", { mode: "rpc" });
	const usage = await h.run(cwd, "bogus");
	out.unlock = { none: none.text, noneLevel: none.level, rpc: rpc.text, usage: usage.text };
}

console.log(JSON.stringify(out));

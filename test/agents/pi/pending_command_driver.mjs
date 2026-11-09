// `/pending` (pending-command.ts) の旧形式 (list / show / drop / USAGE) を、偽の pi・偽の ctx・使い捨ての git リポジトリで動かして固定する。
// 結果を JSON で標準出力へ出す。照合は test_pi_pending_command.py。
// 新形式 (承認・巡回・resolve・unlock) の試験は、旧い統合経路の撤去 (CHG-0062 の A5) で外した。
//
//   node test/agents/pi/pending_command_driver.mjs
//
// see docs/change/closed/0062-pr-hub-simplify.md
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const harness = (name) => pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", name)).href;
const store = await import(harness("pending-store.ts"));
const cmd = await import(harness("pending-command.ts"));

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

/** 偽の pi と、/pending の登録 */
function setup() {
	const state = { touched: 0 };
	const commands = {};
	const pi = {
		registerCommand: (name, def) => {
			commands[name] = def;
		},
		registerTool: () => {
			throw new Error("registerTool は呼ばない");
		},
	};
	cmd.registerPendingCommand(pi, {
		redact: (t) => t,
		touch: () => state.touched++,
	});
	/** /pending を 1 回動かす。notify の記録を返す */
	state.run = async (cwd, args) => {
		const notes = [];
		const ctx = {
			cwd,
			mode: "tui",
			hasUI: true,
			isIdle: () => true,
			ui: {
				notify: (text, level) => notes.push({ text, level }),
				setStatus: () => {},
				select: async () => undefined,
				editor: async () => undefined,
			},
		};
		await commands.pending.handler(args, ctx);
		return { text: notes.map((n) => n.text).join("\n"), level: notes[0]?.level };
	};
	state.commands = commands;
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

// 2. 登録: コマンドだけ (ツールは登録しない)
{
	const h = setup();
	out.registration = { commands: Object.keys(h.commands) };
}

console.log(JSON.stringify(out));

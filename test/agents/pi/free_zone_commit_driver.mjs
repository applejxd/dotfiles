// git_commit の確認の省略 (自由区) を、偽の ctx で executeAction を直接動かして確かめる実行器。標準入力の JSON を読み、結果を JSON で出す。
//
//   {"cwd": "...", "target": "コミットが進むはずのリポジトリ", "message": "...", "dir": "..."?, "hasUI": true,
//    "rules": {...}?, "answers": ["承認して実行"]?, "flip": false?, "child": false?}
//
// flip を真にすると、自由区の判定の 2 回目 (実行直前の再判定) だけ free でなくする。
// see docs/change/0053-worktree-integration-gate.md
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const harness = (name) => pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", name)).href;
const { executeAction } = await import(harness("actions.ts"));
const { classifyFreeZone } = await import(harness("freezone.ts"));

const COMMIT = {
	id: "git_commit",
	label: "コミット",
	argv: ["git", "commit", "-F", "{message_file}"],
	fields: { message: { type: "text", file: true, content: true, max_chars: 1200 }, dir: { type: "dir", optional: true } },
	replaces: ["git commit"],
	preview: "git_staged",
};
const ENV = { ...process.env, GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@example.test", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@example.test" };
const git = (cwd, ...args) => execFileSync("git", args, { cwd, env: ENV, encoding: "utf8" }).trim();

const req = JSON.parse(readFileSync(0, "utf8"));
const answers = [...(req.answers ?? [])];
const calls = { select: [], progress: [] };
const ctx = {
	cwd: req.cwd,
	hasUI: req.hasUI,
	mode: "tui",
	ui: {
		select: async (title, options) => {
			calls.select.push({ title, options });
			return answers.shift();
		},
		editor: async () => undefined,
		input: async () => "",
	},
};
let zoneCalls = 0;
const deps = {
	actions: [COMMIT],
	rules: req.rules ?? {},
	child: req.child === true,
	env: ENV,
	redact: (s) => s,
	judge: () => null,
	dialog: (fn) => fn(),
	bell: () => {},
	progress: (text) => {
		calls.progress.push(text);
		return true;
	},
	...(req.flip
		? {
				freeZone: (cwd, refs) => {
					zoneCalls++;
					return zoneCalls === 1 ? classifyFreeZone(cwd, refs, { env: ENV }) : { free: false, reason: "差し替え" };
				},
			}
		: {}),
};
const before = git(req.target, "rev-parse", "HEAD");
let result;
try {
	const params = { message: req.message, ...(req.dir ? { dir: req.dir } : {}) };
	const r = await executeAction(deps, { action: "git_commit", params }, undefined, ctx);
	result = { ok: true, text: r.content[0].text, details: r.details };
} catch (e) {
	result = { ok: false, text: String(e.message) };
}
process.stdout.write(
	JSON.stringify({ result, calls, advanced: git(req.target, "rev-parse", "HEAD") !== before, subject: git(req.target, "log", "-1", "--format=%s"), zoneCalls }),
);

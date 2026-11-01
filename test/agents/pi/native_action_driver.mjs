// executeAction 経由の保存専用の操作 (native-action.ts。CHG-0055 の P8c) を、偽の ctx で動かして固定する。結果を JSON で出す。
// 照合は test_pi_native_action.py。
//
//   node test/agents/pi/native_action_driver.mjs
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
const { executeAction } = await import(harness("actions.ts"));
const ops = await import(harness("pending-ops.ts"));

const ENV = { ...process.env, GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@example.test", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@example.test" };
const git = (cwd, ...args) => execFileSync("git", args, { cwd, env: ENV, encoding: "utf8" }).trim();
const INTEGRATE = {
	id: "git_integrate",
	label: "統合",
	argv: [],
	fields: { source: { type: "line", content: true, max_chars: 300 } },
	replaces: [],
	preview: "none",
};
const EMPTY = { ...INTEGRATE, id: "empty_op", label: "argv が空の操作" };

function repo() {
	const dir = mkdtempSync(join(tmpdir(), "pi-native-"));
	git(dir, "init", "-q", "-b", "main");
	writeFileSync(join(dir, "seed.txt"), "seed\n");
	git(dir, "add", "-A");
	git(dir, "commit", "-q", "-m", "seed");
	return dir;
}
const pendingRefs = (cwd) => git(cwd, "for-each-ref", "--format=%(refname)", "refs/pi/pending/").split("\n").filter(Boolean);

async function run(o = {}) {
	const cwd = o.cwd ?? repo();
	const headBefore = git(cwd, "rev-parse", "HEAD");
	const selects = [];
	const saved = [];
	let captures = 0;
	const ctx = {
		cwd,
		hasUI: true,
		mode: o.mode ?? "tui",
		ui: {
			select: async (title, options) => {
				selects.push(options);
				return "承認して実行";
			},
			editor: async () => undefined,
			input: async () => "",
		},
		sessionManager: { getSessionId: () => "session-1" },
	};
	const adapters = {
		git_integrate: {
			capture: async ({ values }) => {
				captures++;
				if (o.captureFails) return { ok: false, reason: "前提を取れない" };
				return { ok: true, premise: { source: values.source }, worktree: cwd };
			},
		},
	};
	const deps = {
		actions: [INTEGRATE, EMPTY],
		rules: {},
		child: o.child === true,
		env: ENV,
		redact: (s) => s,
		judge: () => null,
		dialog: (fn) => fn(),
		bell: () => {},
		progress: () => true,
		pending: { enabled: o.enabled ?? true, modes: ["tui"], adapters, onSaved: (i) => saved.push({ action: i.action, reason: i.reason, duplicate: i.duplicate }) },
	};
	let result;
	try {
		const r = await executeAction(deps, { action: o.action ?? "git_integrate", params: { source: "feature/x" } }, undefined, ctx);
		result = { ok: true, text: r.content[0].text };
	} catch (e) {
		result = { ok: false, text: String(e.message) };
	}
	const refs = pendingRefs(cwd);
	const reasons = refs.map((r) => {
		const x = ops.readOp(cwd, r.slice("refs/pi/pending/".length));
		return x.ok ? x.record.reason : "invalid";
	});
	return { result, selects, saved, captures, refs: refs.length, reasons, id: refs[0]?.slice("refs/pi/pending/".length) ?? null, headSame: git(cwd, "rev-parse", "HEAD") === headBefore };
}

const out = {};
out.ok = await run();
{
	const cwd = repo();
	await run({ cwd });
	out.dup = await run({ cwd });
}
out.child = await run({ child: true });
out.disabled = await run({ enabled: false });
out.mode = await run({ mode: "print" });
out.captureFails = await run({ captureFails: true });
out.empty = await run({ action: "empty_op" });
console.log(JSON.stringify(out));

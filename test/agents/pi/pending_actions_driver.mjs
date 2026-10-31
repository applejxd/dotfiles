// 非同期承認の保留への接続 (actions.ts の executeAction。CHG-0055 の P4) を、偽の ctx で直接動かして固定する。結果を JSON で標準出力へ出す。
// 照合は test_pi_pending_actions.py。
//
//   node test/agents/pi/pending_actions_driver.mjs
//
// see docs/change/0055-async-approval.md
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, writeFileSync } from "node:fs";
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
const FAKE = {
	id: "fake_op",
	label: "試験の操作",
	argv: ["sh", "-c", 'touch "$1"', "sh", "{target}"],
	fields: { target: { type: "line", content: true, max_chars: 300 } },
	replaces: [],
	preview: "none",
};
const COMMIT = {
	id: "git_commit",
	label: "コミット",
	argv: ["git", "commit", "-F", "{message_file}"],
	fields: { message: { type: "text", file: true, content: true, max_chars: 1200 }, dir: { type: "dir", optional: true } },
	replaces: ["git commit"],
	preview: "git_staged",
};
const APPROVE = "承認して実行";
const LATER = "あとで (保留)";
const RULES_1S = { judge: { common: { pi: { confirm: { timeout_seconds: 1 } } } } };

function repo() {
	const dir = mkdtempSync(join(tmpdir(), "pi-defer-"));
	git(dir, "init", "-q", "-b", "main");
	writeFileSync(join(dir, "seed.txt"), "seed\n");
	git(dir, "add", "-A");
	git(dir, "commit", "-q", "-m", "seed");
	return dir;
}
const pendingRefs = (cwd) => git(cwd, "for-each-ref", "--format=%(refname)", "refs/pi/pending/").split("\n").filter(Boolean);

/** 1 回の executeAction を動かして、結果と観測を返す */
async function run(o = {}) {
	const cwd = o.cwd ?? repo();
	const mark = join(mkdtempSync(join(tmpdir(), "pi-defer-mark-")), "MARK");
	const answers = [...(o.answers ?? [])];
	const calls = { select: [], progress: [] };
	const saved = [];
	const absence = o.absence ?? { absent: false, gen: 0 };
	const ctx = {
		cwd,
		hasUI: o.hasUI ?? true,
		mode: o.mode ?? "tui",
		ui: {
			select: async (title, options, opts) => {
				calls.select.push({ options });
				const a = answers.shift();
				if (a === "WAIT") return new Promise((res) => opts.signal.addEventListener("abort", () => res(undefined), { once: true }));
				return a;
			},
			editor: async () => undefined,
			input: async () => "",
		},
		sessionManager: { getSessionId: () => "session-1" },
	};
	const adapters =
		o.adapters ??
		{
			fake_op: {
				capture: async ({ values }) =>
					o.captureFails ? { ok: false, reason: "前提を取れない" } : o.captureThrows ? Promise.reject(new Error("取得の例外")) : { ok: true, premise: { target: values.target, head: git(cwd, "rev-parse", "HEAD") } },
			},
		};
	const deps = {
		actions: [FAKE, COMMIT],
		rules: o.rules ?? RULES_1S,
		child: o.child === true,
		env: ENV,
		redact: (s) => s,
		judge: () => null,
		dialog: (fn) => fn(),
		bell: () => {},
		progress: () => true,
		absence,
		...(o.noPending ? {} : { pending: { enabled: o.enabled ?? true, modes: o.modes ?? ["tui"], adapters, onSaved: (i) => saved.push(i), ...(o.save ? { save: o.save } : {}) } }),
	};
	let result;
	try {
		const r = await executeAction(deps, { action: o.action ?? "fake_op", params: o.params ?? { target: mark } }, undefined, ctx);
		result = { ok: true, text: r.content[0].text };
	} catch (e) {
		result = { ok: false, text: String(e.message) };
	}
	const refs = pendingRefs(cwd);
	const records = refs.map((r) => {
		const id = r.slice("refs/pi/pending/".length);
		const x = ops.readOp(cwd, id);
		return x.ok ? { reason: x.record.reason, action: x.record.action, params: x.record.params, premiseKeys: Object.keys(x.record.premise).sort(), session: x.record.request.sessionId, cwd: x.record.request.cwd === cwd } : { invalid: x.reason };
	});
	return { cwd, mark, result, selects: calls.select.map((c) => c.options), executed: existsSync(mark), refs: refs.length, records, saved: saved.map((s) => ({ action: s.action, reason: s.reason, duplicate: s.duplicate })), absent: absence.absent };
}

const out = {};
const slim = (r) => ({ ok: r.result.ok, text: r.result.text, selects: r.selects, executed: r.executed, refs: r.refs, records: r.records, saved: r.saved, absent: r.absent });

out.later = slim(await run({ answers: [LATER] }));
out.approve = slim(await run({ answers: [APPROVE] }));
out.timeout = slim(await run({ answers: ["WAIT"] }));
out.absent = slim(await run({ absence: { absent: true, gen: 0 }, answers: ["WAIT"] }));
out.no_ui = slim(await run({ hasUI: false }));
out.reject = slim(await run({ answers: ["拒否"] }));

// 保留に対応しない形 (従来どおり。「あとで」も出さない)
out.no_adapter = slim(await run({ adapters: {}, answers: ["WAIT"] }));
out.disabled = slim(await run({ enabled: false, answers: ["WAIT"] }));
out.no_pending_deps = slim(await run({ noPending: true, answers: ["WAIT"] }));
out.mode_not_listed = slim(await run({ mode: "rpc", answers: ["WAIT"] }));
out.capture_fails = slim(await run({ captureFails: true, answers: ["WAIT"] }));
out.capture_throws = slim(await run({ captureThrows: true, answers: ["WAIT"] }));
out.no_ui_without_adapter = slim(await run({ adapters: {}, hasUI: false }));

// 同じ要求の重複・保存の失敗
{
	const cwd = repo();
	const params = { target: join(mkdtempSync(join(tmpdir(), "pi-defer-dup-")), "MARK") };
	const a = await run({ cwd, params, answers: [LATER] });
	const b = await run({ cwd, params, answers: [LATER] });
	out.duplicate = { first: slim(a).text, second: slim(b).text, refs: b.refs, savedSecond: b.saved };
}
out.save_fails = slim(await run({ answers: [LATER], save: () => ({ ok: false, code: "limit", reason: "保留が上限に達している" }) }));
out.child = slim(await run({ child: true, answers: [LATER] }));

// 従来の git_commit の退避 (snap) には影響しない
{
	const cwd = repo();
	writeFileSync(join(cwd, "new.txt"), "x\n");
	git(cwd, "add", "-A");
	const r = await run({ cwd, action: "git_commit", params: { message: "docs: 試験" }, answers: ["WAIT"] });
	const refs = pendingRefs(cwd);
	out.git_commit_unchanged = { ok: r.result.ok, text: r.result.text, refs: refs.length, kind: refs.length ? ops.classifyCommit(cwd, git(cwd, "rev-parse", refs[0])) : null, pendingRecords: r.saved.length, selects: r.selects };
}

console.log(JSON.stringify(out));

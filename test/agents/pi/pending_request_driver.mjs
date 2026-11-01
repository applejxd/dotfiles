// 要求側の保存 (pending-request.ts の requestApproval。CHG-0055 の P8c) を、使い捨てのリポジトリで動かして固定する。結果を JSON で出す。
// 照合は test_pi_pending_request.py。
//
//   node test/agents/pi/pending_request_driver.mjs
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
const { requestApproval } = await import(harness("pending-request.ts"));
const ops = await import(harness("pending-ops.ts"));

const ENV = { ...process.env, GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@example.test", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@example.test" };
const git = (cwd, ...args) => execFileSync("git", args, { cwd, env: ENV, encoding: "utf8" }).trim();

function repo() {
	const dir = mkdtempSync(join(tmpdir(), "pi-request-"));
	git(dir, "init", "-q", "-b", "main");
	writeFileSync(join(dir, "seed.txt"), "seed\n");
	git(dir, "add", "-A");
	git(dir, "commit", "-q", "-m", "seed");
	return dir;
}
const pendingRefs = (cwd) => git(cwd, "for-each-ref", "--format=%(refname)", "refs/pi/pending/").split("\n").filter(Boolean);
const state = (cwd) => ({ head: git(cwd, "rev-parse", "HEAD"), branch: git(cwd, "branch", "--show-current"), status: git(cwd, "status", "--porcelain") });

async function run(o = {}) {
	const cwd = o.cwd ?? repo();
	const before = state(cwd);
	let captures = 0;
	let saves = 0;
	const adapters = o.adapters ?? {
		git_integrate: {
			capture: async ({ values }) => {
				captures++;
				if (o.captureThrows) throw new Error("取得の例外");
				if (o.captureFails) return { ok: false, reason: "前提を取れない" };
				return { ok: true, premise: { source: values.source, head: git(cwd, "rev-parse", "HEAD") }, worktree: cwd, host: "host-1" };
			},
		},
	};
	const ac = new AbortController();
	if (o.aborted) ac.abort();
	const deps = {
		adapters,
		enabled: o.enabled ?? true,
		modes: o.modes ?? ["tui"],
		mode: o.mode ?? "tui",
		child: o.child === true,
		env: ENV,
		signal: ac.signal,
		...(o.saveFails ? { save: () => ((saves++), { ok: false, reason: "保存の失敗" }) } : {}),
	};
	const result = await requestApproval({ action: o.action ?? "git_integrate", cwd, sessionId: "session-1", values: o.values ?? { source: "feature/x" } }, deps);
	const refs = pendingRefs(cwd);
	const records = refs.map((r) => {
		const x = ops.readOp(cwd, r.slice("refs/pi/pending/".length));
		return x.ok ? { reason: x.record.reason, action: x.record.action, params: x.record.params, session: x.record.request.sessionId, cwd: x.record.request.cwd === cwd, worktree: x.record.worktree === cwd, host: x.record.host } : { invalid: x.reason };
	});
	return { result, captures, saves, refs: refs.length, records, unchanged: JSON.stringify(state(cwd)) === JSON.stringify(before) };
}

const out = {};
out.ok = await run();
// 同じ要求の重複
{
	const cwd = repo();
	const first = await run({ cwd });
	const second = await run({ cwd });
	out.dup = { first: first.result, second: second.result, refs: second.refs };
}
out.child = await run({ child: true });
out.disabled = await run({ enabled: false });
out.mode = await run({ mode: "print" });
out.unsupported = await run({ action: "other_op" });
out.aborted = await run({ aborted: true });
out.captureFails = await run({ captureFails: true });
out.captureThrows = await run({ captureThrows: true });
out.saveFails = await run({ saveFails: true });
console.log(JSON.stringify(out));

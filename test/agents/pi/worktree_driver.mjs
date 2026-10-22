// worktree.ts の試験用の実行器。引数の JSON `{op, ...}` を読み、結果か `{error: {code, detail}}` を標準出力へ JSON で出す
// (照合は test_pi_worktree.py)。
//
//   node test/agents/pi/worktree_driver.mjs '{"op":"create","repo":"...","jobId":"job-0123abcd","readDeny":{"globs":[],"exceptions":[]}}'
//
// see docs/change/0029-worktree-isolation.md#w1-の実装計画
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const W = await import(
	pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "worktree.ts")).href
);

const args = JSON.parse(process.argv[2] ?? "{}");
const limits = { ...W.DEFAULT_LIMITS, ...(args.limits ?? {}) };
const readDeny = args.readDeny ?? { globs: [], exceptions: [] };

function run() {
	switch (args.op) {
		case "create":
			return W.createIsolation(args.repo, args.jobId, readDeny, limits);
		case "preflight":
			return W.preflight(args.repo, readDeny, limits, new W.Budget(limits.totalMs), args.jobId);
		case "collect":
			return W.collect(args.repo, args.jobId, args.patchName, readDeny, limits);
		case "settle_create": {
			const rec = W.readRecord(args.repo, args.jobId);
			return W.settleFailedCreate(args.repo, rec, args.stage ?? "worktree-add", new W.WorktreeError("git_failed", "injected", {}), limits);
		}
		case "discard":
			return W.discard(args.repo, args.jobId, limits);
		case "clear_stale_lock":
			return W.clearStaleLock(args.repo);
		case "list":
			return W.listRecords(args.repo);
		case "reconcile":
			return W.reconcile(args.repo, args.liveJobIds ?? [], limits);
		case "validate":
			return { id: W.validateJobId(args.id) };
		case "budget0":
			return W.runGit(["rev-parse", "--git-dir"], { cwd: args.repo, budget: new W.Budget(0) });
		case "gitenv":
			return W.gitEnv();
		default:
			throw new Error(`unknown op: ${args.op}`);
	}
}

try {
	console.log(JSON.stringify(run()));
} catch (e) {
	if (e instanceof W.WorktreeError) {
		console.log(JSON.stringify({ error: { code: e.code, detail: e.detail, message: e.message } }));
	} else {
		console.error(e?.stack ?? String(e));
		process.exit(1);
	}
}

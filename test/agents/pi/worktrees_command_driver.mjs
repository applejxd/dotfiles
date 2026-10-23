// worktrees-command.ts の試験用の実行器。引数の JSON `{op, ...}` を読み、結果を標準出力へ JSON で出す
// (照合は test_pi_worktrees_command.py)。
//
//   node test/agents/pi/worktrees_command_driver.mjs '{"op":"run","repo":"...","args":"show job-0123abcd","live":[],"confirm":true}'
//
// confirm: true / false = 確認の答え、省略か null = 確認できない環境 (UI なし)。
// see docs/change/0029-worktree-isolation.md#w1-の実装計画
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const HARNESS = resolve(ROOT, "home", "dot_config", "pi", "harness");
const C = await import(pathToFileURL(resolve(HARNESS, "worktrees-command.ts")).href);

const args = JSON.parse(process.argv[2] ?? "{}");

async function run() {
	switch (args.op) {
		case "run": {
			const confirmCalls = [];
			const confirm =
				args.confirm === true || args.confirm === false
					? async (title, body) => {
							confirmCalls.push({ title, body });
							return args.confirm;
						}
					: null;
			const res = await C.runWorktreesCommand(args.args ?? "", {
				repoRoot: args.repo ?? null,
				liveJobIds: args.live ?? [],
				readDeny: () => args.readDeny ?? { globs: ["**/.env"], exceptions: [] },
				confirm,
			});
			return { ...res, confirmCalls };
		}
		case "startup":
			return { msg: C.startupReconcile(args.repo, args.live ?? []) };
		case "trace_root":
			return { root: C.isolationTraceRoot(args.cwd) };
		case "find_root":
			return { root: C.findRepoRoot(args.cwd, args.limits ? { ...C.STARTUP_LIMITS, ...args.limits } : undefined) };
		default:
			throw new Error(`unknown op: ${args.op}`);
	}
}

try {
	console.log(JSON.stringify(await run()));
} catch (e) {
	console.error(e?.stack ?? String(e));
	process.exit(1);
}

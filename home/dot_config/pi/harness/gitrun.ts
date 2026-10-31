// 判定用の git の同期実行。失敗しても例外を投げず、理由つきで返す。
// see docs/change/0053-worktree-integration-gate.md
import { execFileSync } from "node:child_process";
import { repoTargetEnv } from "./pending-store.ts";

/** `code` は git の終了コード (起動できなかった・時間切れのときは無い) */
export type GitSync = { ok: true; stdout: string } | { ok: false; reason: string; code?: number };

export function gitSync(args: string[], cwd: string, opts: { timeoutMs?: number; env?: NodeJS.ProcessEnv } = {}): GitSync {
	// 対象のリポジトリを選ぶ環境変数は落とす (cwd のリポジトリを見る)
	const env = { ...repoTargetEnv(opts.env ?? process.env), GIT_OPTIONAL_LOCKS: "0", GIT_TERMINAL_PROMPT: "0" };
	try {
		const stdout = execFileSync("git", ["-c", "core.fsmonitor=false", ...args], {
			cwd,
			encoding: "utf8",
			timeout: opts.timeoutMs ?? 3000,
			stdio: ["ignore", "pipe", "pipe"],
			env,
		});
		return { ok: true, stdout };
	} catch (e) {
		const err = e as { code?: unknown; status?: unknown };
		if (err.code === "ENOENT") return { ok: false, reason: "git を起動できない (git か作業ディレクトリが無い)" };
		if (err.code === "ETIMEDOUT") return { ok: false, reason: "git が時間内に終わらなかった" };
		if (typeof err.status === "number") return { ok: false, reason: `git が失敗した (終了コード ${err.status})`, code: err.status };
		return { ok: false, reason: "git を実行できなかった" };
	}
}

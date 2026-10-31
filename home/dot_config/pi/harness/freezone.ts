// 自由区の判定: feature の linked worktree の中だけ free。迷ったら free:false (呼ぶ側は従来どおり確認する)。
// see docs/change/0053-worktree-integration-gate.md
import { realpathSync } from "node:fs";
import { gitSync } from "./gitrun.ts";
import { isFeatureSourceRef, isProtectedRef } from "./judge/protectedrefs.ts";

export type FreeZone = { free: boolean; reason: string; branch?: string; linked?: boolean };

/** 下限。実運用では設定の値を渡す */
export const DEFAULT_PROTECTED: readonly string[] = ["main", "master", "develop", "release/*", "hotfix/*"];

function canon(p: string): string {
	const real = realpathSync(p);
	return process.platform === "win32" ? real.replace(/\\/g, "/").toLowerCase() : real;
}

export function classifyFreeZone(
	cwd: string,
	protectedRefs: readonly string[] = DEFAULT_PROTECTED,
	opts: { env?: NodeJS.ProcessEnv; timeoutMs?: number } = {},
): FreeZone {
	const run = { env: opts.env, timeoutMs: opts.timeoutMs };
	const top = gitSync(["rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir", "--show-toplevel", "--show-superproject-working-tree"], cwd, run);
	if (!top.ok) return { free: false, reason: `リポジトリを判定できない: ${top.reason}` };
	// 行: git-dir / common-dir / toplevel / (submodule のときだけ) superproject
	const lines = top.stdout.split("\n").map((l) => l.replace(/\r$/, ""));
	while (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();
	if (lines.length < 3 || lines.length > 4 || lines.slice(0, 3).some((l) => l === "")) {
		return { free: false, reason: "git の出力が想定外" };
	}
	if (lines.length === 4 && lines[3] !== "") return { free: false, reason: "submodule の中" };
	let linked: boolean;
	try {
		linked = canon(lines[0]) !== canon(lines[1]);
	} catch {
		return { free: false, reason: "git ディレクトリの実体を確かめられない" };
	}
	if (!linked) return { free: false, reason: "主 worktree (linked worktree ではない)", linked: false };
	const head = gitSync(["symbolic-ref", "-q", "HEAD"], cwd, run);
	if (!head.ok) {
		if (head.code === 1) return { free: false, reason: "detached HEAD", linked: true };
		return { free: false, reason: `ブランチを判定できない: ${head.reason}`, linked: true };
	}
	const ref = head.stdout.trim();
	if (!isFeatureSourceRef(ref)) return { free: false, reason: "feature/ ブランチではない", branch: ref, linked: true };
	if (isProtectedRef(ref, protectedRefs)) return { free: false, reason: "保護ブランチ", branch: ref, linked: true };
	return { free: true, reason: "feature の linked worktree", branch: ref, linked: true };
}

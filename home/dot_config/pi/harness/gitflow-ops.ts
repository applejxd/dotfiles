// git flow の操作 (guarded_action の gitflow_*) の preview と事前の検査。git の読み取りだけ (書き込まない)。
// 実効設定が安全プロファイルに合わなければ、操作の前に止める。see docs/change/0047-gitflow.md
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { checkSafeProfile, parseConfigLines, validateFeatureName } from "./gitflow.ts";

export type GitflowPreview = { branch: string; head: string; indexId: string; stat: string };

function git(cwd: string, args: string[]): { ok: boolean; out: string } {
	// 判定や確認の前に走るので、hook も外のコードも動かさない設定で読む
	const r = spawnSync("git", ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.quotepath=false", ...args], {
		cwd,
		encoding: "utf8",
		timeout: 15000,
		env: { ...process.env, GIT_OPTIONAL_LOCKS: "0", GIT_TERMINAL_PROMPT: "0" },
	});
	return { ok: r.status === 0, out: String(r.stdout ?? "").replace(/\n+$/, "") };
}

function sha(...parts: string[]): string {
	return createHash("sha256").update(parts.join("\0")).digest("hex");
}

/** 実効設定を検査し、リポジトリのルートと設定の文字列を返す。合わなければ throw */
function safeContext(cwd: string): { root: string; config: string } {
	const top = git(cwd, ["rev-parse", "--show-toplevel"]);
	if (!top.ok || !top.out) throw new Error("git のリポジトリではない");
	const cfg = git(cwd, ["config", "--get-regexp", "^gitflow\\."]);
	if (!cfg.ok || !cfg.out) throw new Error("このリポジトリは git flow を使っていない (.gitflow が無い、または未設定)。利用者が `git flow init` を行う");
	const profile = checkSafeProfile(parseConfigLines(cfg.out), top.out);
	if (!profile.ok) throw new Error(`git flow の設定が、安全な構成 (main / develop / feature、squash) に合わない:\n${profile.problems.map((p) => `- ${p}`).join("\n")}`);
	return { root: top.out, config: cfg.out };
}

function oid(cwd: string, ref: string): string | null {
	const r = git(cwd, ["rev-parse", "-q", "--verify", `${ref}^{commit}`]);
	return r.ok && r.out ? r.out : null;
}

function featureWorktree(cwd: string, name: string): string | null {
	const r = git(cwd, ["worktree", "list", "--porcelain"]);
	if (!r.ok) return null;
	let path = "";
	for (const line of r.out.split("\n")) {
		if (line.startsWith("worktree ")) path = line.slice("worktree ".length);
		else if (line === `branch refs/heads/feature/${name}`) return path;
	}
	return null;
}

function nameOf(values: Record<string, string>): string {
	const bad = validateFeatureName(values.name);
	if (bad) throw new Error(`name: ${bad}`);
	return values.name;
}

/** 起票の preview: feature/<name> を develop から作る。名前の衝突・develop と main の欠落を止める */
export function gitflowStartPreview(cwd: string, values: Record<string, string>): GitflowPreview {
	const name = nameOf(values);
	const { root, config } = safeContext(cwd);
	const develop = oid(cwd, "refs/heads/develop");
	if (!develop || !oid(cwd, "refs/heads/main")) throw new Error("develop と main のブランチが要る");
	if (oid(cwd, `refs/heads/feature/${name}`)) throw new Error(`feature/${name} は、すでにある`);
	if (existsSync(join(root, ".tmp", "worktrees", name))) throw new Error(`.tmp/worktrees/${name} は、すでにある`);
	const current = git(cwd, ["symbolic-ref", "--short", "-q", "HEAD"]).out || "(detached)";
	return {
		branch: current,
		head: develop,
		indexId: sha(config, develop, name),
		stat: `feature/${name} を develop (${develop.slice(0, 7)}) から作り、.tmp/worktrees/${name} に worktree を作る (ネットワークは使わない)`,
	};
}

/** クローズの preview: feature/<name> を develop へ squash する。develop が checked out の本体で行う。worktree がクリーンで、先のコミットがあること */
export function gitflowFinishPreview(cwd: string, values: Record<string, string>): GitflowPreview {
	const name = nameOf(values);
	const { root, config } = safeContext(cwd);
	const current = git(cwd, ["symbolic-ref", "--short", "-q", "HEAD"]).out;
	if (current !== "develop") throw new Error(`finish は、develop が checked out の本体で行う (今のブランチ: ${current || "(detached)"})`);
	const top = git(cwd, ["rev-parse", "--show-toplevel"]).out;
	const common = git(cwd, ["rev-parse", "--path-format=absolute", "--git-common-dir"]).out;
	if (top !== root || (common && common !== join(root, ".git"))) throw new Error("finish は、本体の作業ツリーで行う (linked worktree からは行わない)");
	const develop = oid(cwd, "refs/heads/develop");
	const feature = oid(cwd, `refs/heads/feature/${name}`);
	if (!develop) throw new Error("develop のブランチが無い");
	if (!feature) throw new Error(`feature/${name} が無い`);
	const ahead = Number(git(cwd, ["rev-list", "--count", `develop..feature/${name}`]).out);
	if (!(ahead >= 1)) throw new Error(`feature/${name} に、develop より先のコミットが無い`);
	const wt = featureWorktree(cwd, name);
	if (wt) {
		const st = git(wt, ["status", "--porcelain"]);
		if (!st.ok) throw new Error(`worktree ${wt} の状態を調べられない`);
		if (st.out) throw new Error(`worktree ${wt} に、コミットしていない変更がある。コミットするか、利用者が扱う`);
	}
	const stat = git(cwd, ["diff", "--stat", "--no-ext-diff", `develop...feature/${name}`]).out;
	return {
		branch: "develop",
		head: develop,
		indexId: sha(config, develop, feature, name),
		stat: `feature/${name} (${feature.slice(0, 7)}、develop より ${ahead} コミット先) を develop へ squash する。リモートには触れない\n${stat}`,
	};
}

/** finish のあとに worktree が残っていれば、その旨 (サンドボックスの内側では、由来が記録できず detached で残る) */
export function leftoverWorktreeHint(cwd: string, name: string): string | null {
	const r = git(cwd, ["worktree", "list", "--porcelain"]);
	if (!r.ok) return null;
	const top = git(cwd, ["rev-parse", "--show-toplevel"]).out;
	const want = join(top, ".tmp", "worktrees", name);
	return r.out.split("\n").some((l) => l === `worktree ${want}`)
		? `worktree ${want} が残っている (サンドボックスの内側では、git flow が由来を記録できず、detached HEAD で残る)。利用者が \`git worktree remove .tmp/worktrees/${name}\` で片付ける`
		: null;
}

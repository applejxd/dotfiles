// git flow の操作 (guarded_action の gitflow_*) の preview と事前の検査。git の読み取りだけ (書き込まない)。
// 実効設定が安全プロファイルに合わなければ、操作の前に止める。see docs/change/0047-gitflow.md
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, realpathSync } from "node:fs";
import { dirname, join, resolve, sep } from "node:path";
import { checkSafeProfile, parseConfigLines, validateFeatureName } from "./gitflow.ts";
import { matchesReadDeny } from "./judge/policy.ts";

export type GitflowPreview = { branch: string; head: string; indexId: string; stat: string };

function git(cwd: string, args: string[]): { ok: boolean; out: string; status: number } {
	// 判定や確認の前に走るので、hook も外のコードも動かさない設定で読む
	const r = spawnSync("git", ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.quotepath=false", ...args], {
		cwd,
		encoding: "utf8",
		timeout: 15000,
		env: { ...process.env, GIT_OPTIONAL_LOCKS: "0", GIT_TERMINAL_PROMPT: "0" },
	});
	return { ok: r.status === 0, out: String(r.stdout ?? "").replace(/\n+$/, ""), status: r.status ?? -1 };
}

function sha(...parts: string[]): string {
	return createHash("sha256").update(parts.join("\0")).digest("hex");
}

/** 実効設定を検査し、リポジトリのルートと設定の文字列を返す。合わなければ throw */
function safeContext(cwd: string): { root: string; config: string } {
	const top = git(cwd, ["rev-parse", "--show-toplevel"]);
	if (!top.ok || !top.out) throw new Error("git のリポジトリではない");
	const cfg = git(cwd, ["config", "--get-regexp", "^gitflow\\."]);
	if (!cfg.ok || !cfg.out || !/^gitflow\.initialized /m.test(cfg.out)) {
		throw new Error("このリポジトリは git flow を使っていない (.gitflow が無い、または未設定)。利用者が `git flow init` を行う");
	}
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
	// squash が衝突で止まると、develop の作業ツリーが衝突状態で残り、git flow の --abort も squash では動かない (v2.1.0 で実測)。
	// 始める前に、作業ツリーを触らない merge-tree で衝突を見つけて断る (git 2.38 未満ではこの検査を飛ばす)
	const mt = git(cwd, ["merge-tree", "--write-tree", "--no-messages", "develop", `feature/${name}`]);
	if (mt.status === 1) {
		throw new Error(
			`feature/${name} は develop と衝突する。feature の worktree で develop を取り込んで (git merge develop)、衝突を解決してコミットしてから、もう一度 finish する (このままだと squash が途中で止まり、develop が衝突状態で残る)`,
		);
	}
	// develop の本体にステージ済み (コミットしていない) の変更があると、squash のコミットに混ざる (実機で発生)。追跡ファイルの変更があれば断る
	const mainStatus = git(cwd, ["status", "--porcelain", "--untracked-files=no"]);
	if (!mainStatus.ok) throw new Error("develop の本体の作業ツリーの状態を調べられない");
	if (mainStatus.out) {
		throw new Error(
			"develop の本体の作業ツリーに、コミットしていない変更がある (squash のコミットに混ざる)。先にコミットするか、利用者が扱う",
		);
	}
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

/**
 * 破棄 (discard) の preview: feature/<name> を、ブランチと worktree ごと捨てる。develop が checked out の本体で行う。
 * develop に入っていないコミットは失われる (reflog にだけ残る) ので、確認の画面に件数と差分の統計を見せる。未コミットの変更がある worktree は断る (git flow も --force-worktree が無いと拒否する)
 */
export function gitflowDiscardPreview(cwd: string, values: Record<string, string>): GitflowPreview {
	const name = nameOf(values);
	const { root, config } = safeContext(cwd);
	const current = git(cwd, ["symbolic-ref", "--short", "-q", "HEAD"]).out;
	if (current !== "develop") throw new Error(`discard は、develop が checked out の本体で行う (今のブランチ: ${current || "(detached)"})`);
	const top = git(cwd, ["rev-parse", "--show-toplevel"]).out;
	const common = git(cwd, ["rev-parse", "--path-format=absolute", "--git-common-dir"]).out;
	if (top !== root || (common && common !== join(root, ".git"))) throw new Error("discard は、本体の作業ツリーで行う (linked worktree からは行わない)");
	const develop = oid(cwd, "refs/heads/develop");
	const feature = oid(cwd, `refs/heads/feature/${name}`);
	if (!develop) throw new Error("develop のブランチが無い");
	if (!feature) throw new Error(`feature/${name} が無い`);
	const ahead = Number(git(cwd, ["rev-list", "--count", `develop..feature/${name}`]).out);
	const wt = featureWorktree(cwd, name);
	if (wt) {
		const st = git(wt, ["status", "--porcelain"]);
		if (!st.ok) throw new Error(`worktree ${wt} の状態を調べられない`);
		if (st.out) throw new Error(`worktree ${wt} に、コミットしていない変更がある。コミットするか、利用者が扱う (捨てると失われる)`);
	}
	const stat = git(cwd, ["diff", "--stat", "--no-ext-diff", `develop...feature/${name}`]).out;
	return {
		branch: "develop",
		head: develop,
		indexId: sha(config, develop, feature, name, "discard"),
		stat:
			`feature/${name} (${feature.slice(0, 7)}) を、ブランチ${wt ? "と worktree" : ""}ごと捨てる。` +
			`develop に入っていないコミット ${ahead} 件は失われる (reflog にだけ残る。元に戻すのは利用者)。リモートには触れない\n${stat}`,
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

/** feature の worktree の中での git commit か (WIP コミットの確認を省く条件。CHG-0047 の (b))。
 *  実効設定が安全・現在のブランチが feature/<名前>・linked worktree (本体ではない) の中・実行場所がその feature の worktree そのもの。
 *  main・develop は、ブランチ名で除かれる */
export function isFeatureWorktreeCommit(cwd: string): boolean {
	try {
		safeContext(cwd);
	} catch {
		return false;
	}
	const branch = git(cwd, ["symbolic-ref", "--short", "-q", "HEAD"]).out;
	const m = /^feature\/(.+)$/.exec(branch);
	if (!m || validateFeatureName(m[1]) !== null) return false;
	const gitDir = git(cwd, ["rev-parse", "--path-format=absolute", "--git-dir"]).out;
	const common = git(cwd, ["rev-parse", "--path-format=absolute", "--git-common-dir"]).out;
	if (!gitDir || !common || gitDir === common) return false;
	const top = git(cwd, ["rev-parse", "--show-toplevel"]).out;
	const wt = featureWorktree(cwd, m[1]);
	return wt !== null && wt === top;
}

/** WIP コミットの対象の worktree。feature/<name> が checked out の、本体の .tmp/worktrees/ の下の linked worktree だけ
 *  (シンボリックリンクを辿らない。ほかの worktree や、手で作った場所は拒否) */
export function resolveFeatureWorktree(cwd: string, name: string): string {
	const bad = validateFeatureName(name);
	if (bad) throw new Error(`name: ${bad}`);
	const common = git(cwd, ["rev-parse", "--path-format=absolute", "--git-common-dir"]);
	if (!common.ok || !common.out) throw new Error("git のリポジトリではない");
	const root = dirname(common.out); // 本体の作業ツリー (.git の親)
	const wt = featureWorktree(cwd, name);
	if (!wt) throw new Error(`feature/${name} の worktree が無い (gitflow_feature_start で起票する)`);
	const base = join(root, ".tmp", "worktrees") + sep;
	let real: string;
	try {
		real = realpathSync(wt);
	} catch {
		throw new Error(`worktree ${wt} を調べられない`);
	}
	if (real !== resolve(wt) || !real.startsWith(base)) throw new Error(`worktree ${wt} は、本体の .tmp/worktrees/ の下の、リンクでない場所ではない`);
	return real;
}

export type ReadDenyLike = { globs: string[]; exceptions: any[] };

/** WIP コミットの preview: 実効設定・feature の worktree の条件・保護対象のパスを検査してから、`git add -A` で全部をステージする。
 *  ステージ済みが空なら止める。**ステージする (書き込む) のは、検査を通ったあとだけ** */
export function gitflowCommitPreview(cwd: string, values: Record<string, string>, readDeny: ReadDenyLike | null): GitflowPreview {
	nameOf(values);
	if (!isFeatureWorktreeCommit(cwd)) throw new Error("feature の worktree の中で、実効設定が安全なときだけ、WIP コミットできる");
	if (!readDeny || readDeny.globs.length === 0) throw new Error("保護対象のパスの一覧が無いので、まとめてステージできない");
	// これからステージされるもの = 未追跡 (ignored を除く) + 追跡済みの変更
	const nul = (s: string) => s.split("\0").filter(Boolean);
	const untracked = git(cwd, ["ls-files", "-z", "--others", "--exclude-standard"]);
	const tracked = git(cwd, ["diff-index", "--name-only", "--no-renames", "-z", "HEAD"]);
	if (!untracked.ok || !tracked.ok) throw new Error("変更の一覧を取れない");
	const raw = (a: { out: string }) => a.out;
	const all = [...new Set([...nul(raw(untracked)), ...nul(raw(tracked))])];
	const hits = all.filter((rel) => matchesReadDeny(rel, readDeny.globs, readDeny.exceptions) ?? matchesReadDeny(join(cwd, rel), readDeny.globs, readDeny.exceptions));
	if (hits.length > 0) throw new Error(`保護対象のパスが変更に含まれるので、まとめてステージしない (内容は読んでいない): ${hits.slice(0, 5).join(", ")}`);
	const add = git(cwd, ["add", "-A"]);
	if (!add.ok) throw new Error("ステージに失敗した");
	const stat = git(cwd, ["diff", "--cached", "--stat", "--no-ext-diff"]).out;
	if (!stat) throw new Error("コミットする変更が無い");
	const branch = git(cwd, ["symbolic-ref", "--short", "-q", "HEAD"]).out;
	const head = git(cwd, ["rev-parse", "HEAD"]).out;
	const idx = git(cwd, ["ls-files", "-s"]).out;
	return { branch, head, indexId: sha(idx, head), stat };
}

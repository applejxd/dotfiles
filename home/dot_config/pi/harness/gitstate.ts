// git の状態の収集 (CHG-0049): パスを所有する worktree・ブランチ・リポジトリの運用モデルを読む。
//
// 判定 (judge/gitflow_gate.ts) とは分ける。ここは git を起動する (読み取りだけ)。
// - 判定ごとに createProbe() で作り直す。結果の記憶はその判定の間だけ (ブランチの変化を次の判定へ持ち越さない)
// - status / check-ignore は使わない (.git/config の core.fsmonitor を起動しうる)。HEAD の直読みもしない
// - 継承された GIT_* は落とす。hook と fsmonitor は無効、時間と出力に上限を付ける
// - 読めなければ unknown。許可の側へ倒さない
// see docs/spec/guard/pi-gitflow-guard.md
import { spawnSync } from "node:child_process";
import { existsSync, realpathSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { checkSafeProfile, identifyModel, parseConfigLines } from "./gitflow.ts";
import type { Facts, Head, ModelFact, Owner } from "./judge/gitflow_gate.ts";

export const GIT_TIMEOUT_MS = 3000;
export const GIT_MAX_BYTES = 64 * 1024;

export type GitResult = { ok: boolean; status: number; out: string; failed: boolean };
export type GitRunner = (cwd: string, args: string[]) => GitResult;

export type ProbeOptions = {
	/** 試験用: git を差し替える */
	run?: GitRunner;
	/** 試験用: 親を辿る上限 (GIT_CEILING_DIRECTORIES と同じ意味。実リポジトリを拾わないため) */
	ceiling?: string[];
	home?: string;
};

/** 継承された GIT_* (GIT_DIR・GIT_WORK_TREE など、調べる対象を変えるもの) を落として git を読み取りで起動する */
export function runGit(cwd: string, args: string[], ceiling: string[] = []): GitResult {
	const env: NodeJS.ProcessEnv = {};
	for (const [k, v] of Object.entries(process.env)) if (v !== undefined && !k.startsWith("GIT_")) env[k] = v;
	Object.assign(env, { GIT_OPTIONAL_LOCKS: "0", GIT_TERMINAL_PROMPT: "0", LC_ALL: "C" });
	if (ceiling.length > 0) env.GIT_CEILING_DIRECTORIES = ceiling.join(":");
	const r = spawnSync("git", ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "core.quotepath=false", ...args], {
		cwd,
		encoding: "utf8",
		timeout: GIT_TIMEOUT_MS,
		maxBuffer: GIT_MAX_BYTES,
		env,
	});
	// 起動できない・時間切れ・出力が上限を超えた は status が null (failed)。許可の根拠にしない
	return { ok: r.status === 0, status: r.status ?? -1, out: String(r.stdout ?? "").replace(/\n+$/, ""), failed: r.status === null || r.error !== undefined };
}

/** 存在する最寄りの親を実体解決し、存在しない末尾を連結する (新規ファイルの所属を決めるため) */
export function realPathOf(path: string): string {
	let cur = resolve(path);
	const rest: string[] = [];
	for (;;) {
		try {
			const real = realpathSync(cur);
			return rest.length === 0 ? real : join(real, ...rest.reverse());
		} catch {
			const parent = dirname(cur);
			if (parent === cur) return resolve(path);
			rest.push(basename(cur));
			cur = parent;
		}
	}
}

function nearestDir(real: string): string {
	let cur = real;
	for (;;) {
		try {
			if (statSync(cur).isDirectory()) return cur;
		} catch {
			// 存在しない
		}
		const parent = dirname(cur);
		if (parent === cur) return cur;
		cur = parent;
	}
}

/** dir から上へ、.git (ファイルでもディレクトリでも) を探す。ceiling に当たったら止める */
function hasGitAncestor(dir: string, ceiling: string[]): boolean {
	let cur = dir;
	for (;;) {
		if (existsSync(join(cur, ".git"))) return true;
		if (ceiling.includes(cur)) return false;
		const parent = dirname(cur);
		if (parent === cur) return false;
		cur = parent;
	}
}

export function createProbe(o: ProbeOptions = {}): Facts {
	const ceiling = (o.ceiling ?? []).map((c) => realPathOf(c));
	const run: GitRunner = o.run ?? ((cwd, args) => runGit(cwd, args, ceiling));
	const owners = new Map<string, Owner>();
	const models = new Map<string, ModelFact>();

	function readOwner(real: string): Owner {
		const dir = nearestDir(real);
		if (!hasGitAncestor(dir, ceiling)) return { kind: "no-repo" };
		const a = run(dir, ["rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir", "--is-inside-git-dir", "--is-bare-repository"]);
		if (!a.ok) return { kind: "unknown", why: a.failed ? "git を実行できない・時間切れ" : `rev-parse が失敗 (${a.status})` };
		const lines = a.out.split("\n");
		if (lines.length !== 4) return { kind: "unknown", why: "rev-parse の出力が想定外" };
		const [gitDir, commonDir, insideGitDir, bare] = lines;
		if (insideGitDir === "true" || bare === "true") return { kind: "git-dir", commonDir: realPathOf(commonDir) };
		const t = run(dir, ["rev-parse", "--path-format=absolute", "--show-toplevel"]);
		if (!t.ok || !t.out) return { kind: "unknown", why: "作業ツリーの根を読めない" };
		const h = run(dir, ["symbolic-ref", "-q", "HEAD"]);
		// symbolic-ref -q は、detached のとき終了コード 1 (出力なし)。それ以外の失敗は読めなかった
		const head: Head = h.ok && h.out ? { kind: "branch", ref: h.out } : h.status === 1 && !h.failed ? { kind: "detached" } : { kind: "unreadable" };
		return { kind: "worktree", top: realPathOf(t.out), commonDir: realPathOf(commonDir), primary: realPathOf(gitDir) === realPathOf(commonDir), head };
	}

	function readModel(commonDir: string): ModelFact {
		// 作業コピーの .gitflow ではなく、develop (無ければ main) にコミットされた内容で識別する。
		// 作業コピーを消す・書き換えるだけで、規約の強制が外れないようにするため
		for (const ref of ["refs/heads/develop", "refs/heads/main"]) {
			const blob = run(commonDir, [`--git-dir=${commonDir}`, "rev-parse", "-q", "--verify", `${ref}:.gitflow`]);
			if (blob.status === 1 && !blob.failed) continue; // ref か .gitflow が無い
			if (!blob.ok || !blob.out) return "unknown";
			const cfg = run(commonDir, [`--git-dir=${commonDir}`, "config", "--blob", blob.out, "--get-regexp", "^gitflow\\."]);
			if (cfg.status === 1 && !cfg.failed) return "other";
			if (!cfg.ok) return "unknown";
			return identifyModel(parseConfigLines(cfg.out));
		}
		return "none";
	}

	return {
		home: o.home ?? homedir(),
		realPath: realPathOf,
		ownerOf(real) {
			const key = nearestDir(real);
			let v = owners.get(key);
			if (!v) owners.set(key, (v = readOwner(real)));
			return v;
		},
		modelOf(commonDir) {
			let v = models.get(commonDir);
			if (!v) models.set(commonDir, (v = readModel(commonDir)));
			return v;
		},
		actionReady(top) {
			const cfg = run(top, ["config", "--get-regexp", "^gitflow\\."]);
			return cfg.ok && checkSafeProfile(parseConfigLines(cfg.out), top).ok;
		},
	};
}

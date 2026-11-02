// 保護ブランチへの統合 (git flow feature finish --squash 相当) の結果を、承認の前に算出する部品。
// ref・インデックス・作業ツリーは変えない (merge-tree がオブジェクトを書くだけ)。外部コードを動かさない。
// see docs/change/0055 (P7/P8)
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { repoTargetEnv } from "./pending-store.ts";
import { DEFAULT_SOURCE_PREFIXES } from "./judge/integrateprofile.ts";
import { isProtectedRef } from "./judge/protectedrefs.ts";

/** プロジェクト設定 (pi.json) の情報。表示と、承認後の再検査 (blob ID) に使う。入力の本文は含めない */
export type PlanProfile = { blob: string | null; overridden: boolean; diagnostics: { code: string; key?: string }[] };
const NO_PROFILE: PlanProfile = { blob: null, overridden: false, diagnostics: [] };

export type IntegrateInput = {
	cwd: string;
	source: string;
	target: string;
	message: string;
	protectedRefs: readonly string[];
	/** 統合元の接頭辞 (末尾は /)。省略時は feature/ と bugfix/ */
	sourcePrefixes?: readonly string[];
	/** 計画に載せるプロジェクト設定の情報 (計算には使わない) */
	profile?: PlanProfile;
	riskPaths: readonly string[];
	env?: NodeJS.ProcessEnv;
	/** false なら統合先 worktree の状態 (進行中の操作・未コミット) を調べない。既定 true */
	checkTargetWorktree?: boolean;
};
export type IntegratePlan = {
	ok: true;
	source: { ref: string; oid: string };
	target: { ref: string; oid: string };
	targetWorktree: string | null;
	mergeBase: string;
	resultTree: string;
	targetTree: string;
	method: "squash";
	message: string;
	stats: { commits: number; files: number; additions: number; deletions: number };
	files: { path: string; add: number | null; del: number | null; status: string }[];
	risks: { path: string; reason: string }[];
	targetAhead: number;
	/** 統合元に含まれる、未統合の他の feature/bugfix の ref (表示だけの情報。承認の判断・再検査には使わない) */
	stacked: string[];
	/** 計画を作ったときのプロジェクト設定 (.agents/config/pi.json) の情報 */
	profile: PlanProfile;
	/** 計画の統合元の判定に使った接頭辞 (表示用) */
	sourcePrefixes: string[];
};
export type IntegrateRefusal = { ok: false; code: string; reason: string; files?: string[] };

type R = { ok: true; out: string } | { ok: false; code?: number; reason: string; out?: string };

// 落とす環境変数 (外部コマンドを起動し得るもの)
const DROP_ENV = ["GIT_EXTERNAL_DIFF", "GIT_PAGER", "GIT_SSH_COMMAND", "GIT_SSH", "GIT_ASKPASS", "SSH_ASKPASS", "GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "GIT_PROXY_COMMAND", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT"];
const SAFE_CONFIG = ["core.hooksPath=/dev/null", "core.fsmonitor=false", "core.quotepath=false", "diff.external=", "core.pager=cat"];

function safeGit(args: string[], cwd: string, baseEnv?: NodeJS.ProcessEnv): R {
	const env: NodeJS.ProcessEnv = { ...repoTargetEnv(baseEnv ?? process.env), GIT_OPTIONAL_LOCKS: "0", GIT_TERMINAL_PROMPT: "0" };
	for (const k of DROP_ENV) delete env[k];
	const full = SAFE_CONFIG.flatMap((c) => ["-c", c]).concat(args);
	try {
		const out = execFileSync("git", full, { cwd, encoding: "utf8", timeout: 5000, stdio: ["ignore", "pipe", "pipe"], env, maxBuffer: 64 * 1024 * 1024 });
		return { ok: true, out };
	} catch (e) {
		const err = e as { code?: unknown; status?: unknown; stdout?: unknown; stderr?: unknown };
		if (err.code === "ENOENT") return { ok: false, reason: "git を起動できない" };
		if (err.code === "ETIMEDOUT") return { ok: false, reason: "git が時間内に終わらなかった" };
		if (typeof err.status === "number") {
			const out = typeof err.stdout === "string" ? err.stdout : "";
			const se = typeof err.stderr === "string" ? err.stderr : "";
			return { ok: false, code: err.status, reason: `git が失敗した (終了コード ${err.status})`, out: out + (se ? `\n${se}` : "") };
		}
		return { ok: false, reason: "git を実行できなかった" };
	}
}

const refuse = (code: string, reason: string, files?: string[]): IntegrateRefusal =>
	files ? { ok: false, code, reason, files } : { ok: false, code, reason };

// biome-ignore lint/suspicious/noControlCharactersInRegex: 制御文字の検出が目的
const CTRL = /[\u0000-\u001f\u007f]/;
const BAD_NAME = /[\s~^:?*[\\]/;

function badRefName(name: string): boolean {
	return name.includes("..") || BAD_NAME.test(name) || CTRL.test(name) || name.endsWith("/") || name.endsWith(".lock") || name.includes("//");
}

function fullRef(name: string): string {
	return name.startsWith("refs/heads/") ? name : `refs/heads/${name}`;
}

/** `**` は任意の深さ、`*` は / 以外、`?` は 1 文字 */
function globToRegExp(glob: string): RegExp {
	let re = "";
	for (let i = 0; i < glob.length; i++) {
		const c = glob[i];
		if (c === "*") {
			if (glob[i + 1] === "*") {
				i++;
				if (glob[i + 1] === "/") {
					i++;
					re += "(?:.*/)?";
				} else re += ".*";
			} else re += "[^/]*";
		} else if (c === "?") re += "[^/]";
		else re += c.replace(/[.+^${}()|[\]\\]/g, "\\$&");
	}
	return new RegExp(`^${re}$`);
}

function targetWorktreeOf(cwd: string, ref: string, env?: NodeJS.ProcessEnv): string | null {
	const r = safeGit(["worktree", "list", "--porcelain"], cwd, env);
	if (!r.ok) return null;
	let cur: string | null = null;
	for (const line of r.out.split("\n")) {
		if (line.startsWith("worktree ")) cur = line.slice(9);
		else if (line === `branch ${ref}` && cur) return cur;
	}
	return null;
}

const MAX_STACKED = 10;

/** 統合元に含まれる未統合の他ブランチ。失敗は空 (表示だけの情報なので、計画を失敗させない) */
function stackedOf(
	cwd: string,
	sourceRef: string,
	sourceOid: string,
	targetOid: string,
	targetTree: string,
	sourcePrefixes: readonly string[],
	env?: NodeJS.ProcessEnv,
): string[] {
	const patterns = sourcePrefixes.map((p) => `refs/heads/${p.replace(/\/+$/, "")}`);
	if (patterns.length === 0) return [];
	const l = safeGit(["for-each-ref", "--format=%(refname)", "--merged", sourceOid, "--no-merged", targetOid, ...patterns], cwd, env);
	if (!l.ok) return [];
	const out: string[] = [];
	for (const ref of l.out.split("\n").map((x) => x.trim())) {
		if (ref === "" || ref === sourceRef || CTRL.test(ref)) continue;
		const oid = safeGit(["rev-parse", "--verify", "--quiet", `${ref}^{commit}`], cwd, env);
		if (!oid.ok) continue;
		// 純粋な変更がすでに統合先にあるもの (squash 統合済みで残っているブランチ) は除く
		const mt = safeGit(["merge-tree", "--write-tree", "--no-messages", targetOid, oid.out.trim()], cwd, env);
		if (mt.ok && mt.out.split("\n")[0]?.trim() === targetTree) continue;
		out.push(ref);
		if (out.length >= MAX_STACKED) break;
	}
	return out;
}

const OPS = ["MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "BISECT_LOG"];

export function computeIntegrationPlan(input: IntegrateInput): IntegratePlan | IntegrateRefusal {
	const { cwd, env } = input;
	const message = input.message;
	if (message.trim() === "" || message.length > 1200 || message.includes("\0")) {
		return refuse("bad_message", "統合のメッセージが空か長すぎるか、NUL を含む。");
	}

	const sourceRef = fullRef(input.source);
	const targetRef = fullRef(input.target);
	const exactProtected = input.protectedRefs.filter((p) => !/[*?[]/.test(p)).map(fullRef);
	const prefixes = input.sourcePrefixes ?? DEFAULT_SOURCE_PREFIXES;
	const fromPrefix = prefixes.some((p) => p !== "" && sourceRef.startsWith(`refs/heads/${p}`) && sourceRef.length > `refs/heads/${p}`.length);
	if (badRefName(input.source) || !fromPrefix || isProtectedRef(sourceRef, input.protectedRefs) || sourceRef === targetRef) {
		return refuse("bad_source", "統合元は設定された接頭辞 (既定 feature/ か bugfix/) のブランチで、保護ブランチでないものでなければならない。");
	}
	if (badRefName(input.target) || !exactProtected.includes(targetRef)) {
		return refuse("bad_target", "統合先は保護ブランチの完全一致でなければならない。");
	}

	for (const [ref, code] of [[sourceRef, "bad_source"], [targetRef, "bad_target"]] as const) {
		if (safeGit(["symbolic-ref", "-q", ref], cwd, env).ok) return refuse(code, "symbolic ref は統合に使えない。");
	}
	const oidOf = (ref: string): R => safeGit(["rev-parse", "--verify", "--quiet", `${ref}^{commit}`], cwd, env);
	const s = oidOf(sourceRef);
	if (!s.ok) return s.code === 1 ? refuse("missing_ref", `ref が存在しない: ${sourceRef}`) : refuse("git_failed", s.reason);
	const t = oidOf(targetRef);
	if (!t.ok) return t.code === 1 ? refuse("missing_ref", `ref が存在しない: ${targetRef}`) : refuse("git_failed", t.reason);
	const sourceOid = s.out.trim();
	const targetOid = t.out.trim();

	const anc = safeGit(["merge-base", "--is-ancestor", sourceRef, targetRef], cwd, env);
	if (anc.ok) return refuse("already_merged", "統合元はすでに統合先に含まれている。");
	if (anc.code !== 1) return refuse("git_failed", anc.reason);

	const drv = safeGit(["config", "--get-regexp", "^merge\\..*\\.driver$"], cwd, env);
	if (drv.ok && drv.out.trim() !== "") return refuse("external_driver", "外部の merge driver が設定されているため、算出しない。");
	if (!drv.ok && drv.code !== 1) return refuse("git_failed", drv.reason);
	const flt = safeGit(["config", "--get-regexp", "^filter\\..*\\.(clean|smudge|process)$"], cwd, env);
	if (flt.ok && flt.out.trim() !== "") return refuse("external_filter", "外部の filter が設定されているため、算出しない (初版の対象外)。");
	if (!flt.ok && flt.code !== 1) return refuse("git_failed", flt.reason);

	const wt = targetWorktreeOf(cwd, targetRef, env);
	if (wt && input.checkTargetWorktree !== false) {
		for (const op of OPS) {
			const p = safeGit(["rev-parse", "--git-path", op], wt, env);
			if (p.ok && existsSync(resolve(wt, p.out.trim()))) {
				return refuse("operation_in_progress", `統合先の worktree で ${op} が進行中。`);
			}
		}
		const st = safeGit(["status", "--porcelain=v1", "-z", "--untracked-files=normal"], wt, env);
		if (!st.ok) return refuse("git_failed", st.reason);
		if (st.out !== "") return refuse("dirty_target_worktree", "統合先の worktree に未コミットの変更か追跡外のファイルがある。");
	}

	const mb = safeGit(["merge-base", targetRef, sourceRef], cwd, env);
	if (!mb.ok) return refuse("git_failed", mb.reason);

	const mt = safeGit(["merge-tree", "--write-tree", "--name-only", "--no-messages", targetOid, sourceOid], cwd, env);
	if (!mt.ok) {
		if (mt.code === 1 && mt.out) {
			const lines = mt.out.split("\n").filter((l) => l !== "");
			const files = [...new Set(lines.slice(1))].slice(0, 20);
			if (files.some((f) => CTRL.test(f))) return refuse("unsafe_path", "パスに制御文字がある。");
			return refuse("conflict", "統合すると衝突する。", files);
		}
		if (mt.code === 129 || /unknown option|usage:/i.test(mt.out ?? "")) {
			return refuse("git_too_old", "git が古く merge-tree --write-tree を使えない (2.38 以上が要る)。");
		}
		return refuse("git_failed", mt.reason);
	}
	const resultTree = mt.out.split("\n")[0]?.trim() ?? "";
	if (!/^[0-9a-f]{40,64}$/.test(resultTree)) return refuse("git_failed", "merge-tree の出力を読めなかった。");

	const tt = safeGit(["rev-parse", `${targetOid}^{tree}`], cwd, env);
	if (!tt.ok) return refuse("git_failed", tt.reason);
	const targetTree = tt.out.trim();
	if (targetTree === resultTree) return refuse("no_change", "統合しても統合先の内容が変わらない。");

	const diffArgs = ["--no-ext-diff", "--no-textconv", "--no-renames", "-z"];
	const raw = safeGit(["diff", "--raw", ...diffArgs, targetTree, resultTree], cwd, env);
	const num = safeGit(["diff", "--numstat", ...diffArgs, targetTree, resultTree], cwd, env);
	if (!raw.ok) return refuse("git_failed", raw.reason);
	if (!num.ok) return refuse("git_failed", num.reason);

	const status = new Map<string, string>();
	const symlinks = new Set<string>();
	const rt = raw.out.split("\0");
	for (let i = 0; i + 1 < rt.length; i += 2) {
		const m = /^:(\d+) (\d+) \S+ \S+ (\w)/.exec(rt[i]);
		if (!m) continue;
		status.set(rt[i + 1], m[3]);
		if (m[1] === "120000" || m[2] === "120000") symlinks.add(rt[i + 1]);
	}
	const files: IntegratePlan["files"] = [];
	for (const rec of num.out.split("\0")) {
		if (rec === "") continue;
		const m = /^(\S+)\t(\S+)\t(.*)$/s.exec(rec);
		if (!m) continue;
		const bin = m[1] === "-";
		files.push({ path: m[3], add: bin ? null : Number(m[1]), del: bin ? null : Number(m[2]), status: status.get(m[3]) ?? "M" });
	}
	for (const p of status.keys()) if (CTRL.test(p)) return refuse("unsafe_path", "変更されるパスに制御文字がある。");
	for (const f of files) if (CTRL.test(f.path)) return refuse("unsafe_path", "変更されるパスに制御文字がある。");

	const size = (f: { add: number | null; del: number | null }) => (f.add === null || f.del === null ? Number.MAX_SAFE_INTEGER : f.add + f.del);
	const sorted = [...files].sort((a, b) => size(b) - size(a));
	const stats = {
		commits: 0,
		files: files.length,
		additions: files.reduce((n, f) => n + (f.add ?? 0), 0),
		deletions: files.reduce((n, f) => n + (f.del ?? 0), 0),
	};

	const count = (range: string): number | null => {
		const r = safeGit(["rev-list", "--count", range], cwd, env);
		return r.ok ? Number(r.out.trim()) : null;
	};
	const commits = count(`${targetOid}..${sourceOid}`);
	const ahead = count(`${sourceOid}..${targetOid}`);
	if (commits === null || ahead === null) return refuse("git_failed", "コミット数を数えられなかった。");
	stats.commits = commits;

	const risks: IntegratePlan["risks"] = [];
	const globs = input.riskPaths.map((g) => [g, globToRegExp(g)] as const);
	for (const p of status.keys()) {
		const hit = globs.find(([, re]) => re.test(p));
		if (hit) risks.push({ path: p, reason: `リスクの高いパス (${hit[0]})` });
		else if (symlinks.has(p)) risks.push({ path: p, reason: "シンボリックリンクの変更" });
	}

	return {
		ok: true,
		source: { ref: sourceRef, oid: sourceOid },
		target: { ref: targetRef, oid: targetOid },
		targetWorktree: wt,
		mergeBase: mb.out.trim(),
		resultTree,
		targetTree,
		method: "squash",
		message,
		stats,
		files: sorted.slice(0, 200),
		risks: risks.slice(0, 50),
		targetAhead: ahead,
		stacked: stackedOf(cwd, sourceRef, sourceOid, targetOid, targetTree, prefixes, env),
		profile: input.profile ? structuredClone(input.profile) : { ...NO_PROFILE, diagnostics: [] },
		sourcePrefixes: [...prefixes],
	};
}

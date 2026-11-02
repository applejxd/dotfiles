// 自由区の判定: feature の linked worktree の中だけ free。迷ったら free:false (呼ぶ側は従来どおり確認する)。
// see docs/change/0053-worktree-integration-gate.md
import { realpathSync } from "node:fs";
import { gitSync } from "./gitrun.ts";
import { isProtectedRef } from "./judge/protectedrefs.ts";
import { loadProfile, type Git } from "./integrate-profile-load.ts";
import { DEFAULT_FREE_ZONE_PREFIXES, DEFAULT_SOURCE_PREFIXES, type ProfileDefaults } from "./judge/integrateprofile.ts";

/** profile は pi.json を読んだ結果の観測用の添え書き (既定以外・診断があるときだけ付く)。確認の省略の判定には、free だけを使う */
export type FreeZone = { free: boolean; reason: string; branch?: string; linked?: boolean; profile?: { overridden: boolean; diagnostics: { code: string }[] } };

export function profileDefaults(protectedRefs: readonly string[], target = "develop"): ProfileDefaults {
	return { protectedRefs, target, sourcePrefixes: DEFAULT_SOURCE_PREFIXES, freeZonePrefixes: DEFAULT_FREE_ZONE_PREFIXES };
}

/** `refs/heads/` を外して小文字 (isProtectedRef と同じ流儀)。他の `refs/` は null */
function branchName(ref: string): string | null {
	const lower = ref.trim().toLowerCase();
	if (lower.startsWith("refs/heads/")) return lower.slice("refs/heads/".length);
	if (lower.startsWith("refs/")) return null;
	return lower;
}

function hasPrefix(ref: string, prefixes: readonly string[]): boolean {
	const name = branchName(ref);
	if (name === null) return false;
	return prefixes.some((p) => name.startsWith(p.toLowerCase()) && name.length > p.length);
}

type Run = { env?: NodeJS.ProcessEnv; timeoutMs?: number };

/** common dir (= 主 worktree) を指す git 実行器。設定はここの HEAD からだけ読む (feature 自身の HEAD は信じない) */
export function gitInCommonDir(commonDir: string, run: Run = {}): Git {
	return (args, c) => gitSync(["--git-dir", commonDir, ...args], c, run);
}

/** cwd のリポジトリの common dir (絶対パス)。分からないときは null */
export function commonDirOf(cwd: string, run: Run = {}): string | null {
	const r = gitSync(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd, run);
	const dir = r.ok ? r.stdout.trim() : "";
	return dir === "" ? null : dir;
}

const PREVIEW_CHANGED = "このプロジェクトは pi.json で統合先か統合元の接頭辞を変えているため、実際の統合先と食い違いうる。統合の内容は確認できない";
const PREVIEW_UNREADABLE = "pi.json を読めないため、実際の統合先を確かめられない。統合の内容は確認できない";

/**
 * raw `git flow … finish` のプレビューを止める理由。統合先か統合元の接頭辞が全体の既定と違うときだけ (自由区だけの変更では null)。
 * cwd の HEAD と、common dir (主 worktree) の HEAD の両方の pi.json を読み、どちらかが変えている・読めないときは止める (fail closed)。
 */
export function previewBlocked(cwd: string, protectedRefs: readonly string[], target: string, deps: { git?: Git; commonGit?: Git } = {}): string | null {
	const defaults = profileDefaults(protectedRefs, target);
	let commonGit = deps.commonGit;
	if (!commonGit) {
		const dir = commonDirOf(cwd);
		if (dir === null) return PREVIEW_UNREADABLE;
		commonGit = gitInCommonDir(dir);
	}
	for (const loaded of [loadProfile(cwd, defaults, { git: deps.git }), loadProfile(cwd, defaults, { git: commonGit })]) {
		if (loaded.readFailed) return PREVIEW_UNREADABLE;
		const p = loaded.profile;
		const same = p.sourcePrefixes.length === defaults.sourcePrefixes.length && p.sourcePrefixes.every((v, i) => v === defaults.sourcePrefixes[i]);
		if (p.target !== defaults.target || !same) return PREVIEW_CHANGED;
	}
	return null;
}

/** rules.json の judge.common.pi.integrate から、確認省略の設定 (skip_confirm_in_free_zone) と保護 ref を読む。無い・形が違うときは省略しない (下限の保護 ref) */
export function freeZoneSettings(rules: any): { skip: boolean; protectedRefs: readonly string[] } {
	const integrate = rules?.judge?.common?.pi?.integrate;
	const refs = integrate?.protected_refs;
	const list = Array.isArray(refs) && refs.length > 0 && refs.every((r: unknown) => typeof r === "string") ? (refs as string[]) : DEFAULT_PROTECTED;
	return { skip: integrate?.skip_confirm_in_free_zone === true, protectedRefs: list };
}

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
	let adminUnderCommon: boolean;
	try {
		const gitDir = canon(lines[0]);
		const commonDir = canon(lines[1]);
		linked = gitDir !== commonDir;
		// 本物の linked worktree の管理ディレクトリは <common dir>/worktrees/<id>。.git ファイルを書き換えた偽の worktree (別の場所の管理ディレクトリ) を自由区にしない
		adminUnderCommon = gitDir.startsWith(`${commonDir}/worktrees/`);
	} catch {
		return { free: false, reason: "git ディレクトリの実体を確かめられない" };
	}
	if (!linked) return { free: false, reason: "主 worktree (linked worktree ではない)", linked: false };
	if (!adminUnderCommon) return { free: false, reason: "linked worktree の管理ディレクトリが common dir の worktrees/ の下にない", linked: true };
	const head = gitSync(["symbolic-ref", "-q", "HEAD"], cwd, run);
	if (!head.ok) {
		if (head.code === 1) return { free: false, reason: "detached HEAD", linked: true };
		return { free: false, reason: `ブランチを判定できない: ${head.reason}`, linked: true };
	}
	const ref = head.stdout.trim();
	// 自由区の接頭辞は、common dir (= 主 worktree) の HEAD の pi.json だけから読む。feature 自身の HEAD は信じない (エージェントが自分で広げられる)
	const loaded = loadProfile(cwd, profileDefaults(protectedRefs), { git: gitInCommonDir(lines[1], run) });
	const note = loaded.overridden || loaded.diagnostics.length > 0 ? { profile: { overridden: loaded.overridden, diagnostics: loaded.diagnostics.map((d) => ({ code: d.code })) } } : {};
	// fail closed: 設定を読めないときは、狭めている設定を見落とすかもしれないので自由区にしない
	if (loaded.readFailed) return { free: false, reason: "プロジェクト設定を読めない (確認する)", branch: ref, linked: true };
	// 主 HEAD が「承認された統合を経た」状態 (保護ブランチ上) であることを、設定の有無にかかわらず要求する。
	// 設定が無いときだけ省くと、主 HEAD を設定の無いブランチへ切り替えて設定を隠す偽装 (狭めた設定を消して既定の feature/ を復活させる) と区別できない。
	// C2 の例外: 設定が無いリポジトリでも、主 worktree が detached・非保護ブランチなら自由区は効かない (確認が増える側)。
	// feature の worktree から `update-ref --no-deref main-worktree/HEAD` で主 HEAD を広い設定のコミットへ向けられる。理由には入力の値を含めない
	const mainHead = gitSync(["--git-dir", lines[1], "symbolic-ref", "-q", "HEAD"], cwd, run);
	if (!mainHead.ok) {
		const reason = mainHead.code === 1 ? "主 worktree の HEAD が detached (設定元として信頼できない)" : "主 worktree のブランチを判定できない";
		return { free: false, reason, branch: ref, linked: true, ...note };
	}
	if (!isProtectedRef(mainHead.stdout.trim(), protectedRefs)) {
		return { free: false, reason: "主 worktree のブランチが保護ブランチではない (設定元として信頼できない)", branch: ref, linked: true, ...note };
	}
	const prefixes = loaded.profile.freeZonePrefixes;
	if (!hasPrefix(ref, prefixes)) {
		const isDefault = prefixes.length === DEFAULT_FREE_ZONE_PREFIXES.length && prefixes.every((v, i) => v === DEFAULT_FREE_ZONE_PREFIXES[i]);
		const reason = isDefault ? "feature/ ブランチではない" : `自由区の接頭辞 (${prefixes.join(" ")}) のブランチではない`;
		return { free: false, reason, branch: ref, linked: true, ...note };
	}
	if (isProtectedRef(ref, protectedRefs)) return { free: false, reason: "保護ブランチ", branch: ref, linked: true, ...note };
	return { free: true, reason: "feature の linked worktree", branch: ref, linked: true, ...note };
}

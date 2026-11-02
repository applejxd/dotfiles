// HEAD の `.agents/config/pi.json` (blob) だけを git から読み、実効の設定にする。作業ツリーのファイルは読まない。
// キャッシュは blob ID (と全体の既定の値) が鍵。git は注入できる。
// see docs/change/0057-per-project-integrate.md
import { gitSync } from "./gitrun.ts";
import { defaultResult, effectiveProfile, MAX_FILE_BYTES, type ProfileDefaults, type ProfileResult } from "./judge/integrateprofile.ts";

export type Git = (args: string[], cwd: string) => { ok: true; stdout: string } | { ok: false; reason: string; code?: number };
export type LoadedProfile = ProfileResult & { blob: string | null };

export const PROFILE_PATH = ".agents/config/pi.json";
const CACHE_LIMIT = 32;
const cache = new Map<string, ProfileResult>();

const defaultGit: Git = (args, cwd) => gitSync(args, cwd, { timeoutMs: 2000 });

function cached(key: string, make: () => ProfileResult): ProfileResult {
	const hit = cache.get(key);
	if (hit) return structuredClone(hit);
	const value = make();
	if (cache.size >= CACHE_LIMIT) {
		const oldest = cache.keys().next();
		if (!oldest.done) cache.delete(oldest.value);
	}
	cache.set(key, value);
	return structuredClone(value);
}

/** cwd のリポジトリの HEAD から設定を読む。無い・HEAD が無い・git の失敗は「設定なし」(全体の既定・診断なし)。 */
export function loadProfile(cwd: string, defaults: ProfileDefaults, deps: { git?: Git } = {}): LoadedProfile {
	const git = deps.git ?? defaultGit;
	const none = (): LoadedProfile => ({ ...defaultResult(defaults), blob: null });

	const ls = git(["ls-tree", "-l", "--full-tree", "HEAD", "--", PROFILE_PATH], cwd);
	if (!ls.ok) return none();
	const line = ls.stdout.split("\n").find((l) => l.length > 0);
	if (line === undefined) return none();
	// "<mode> <type> <oid> <size>\t<path>" (size は空白で右詰め。blob 以外は "-")
	const m = /^(\d{6}) (\S+) ([0-9a-f]{40,64}) +(\d+|-)\t(.*)$/.exec(line);
	if (!m || m[5] !== PROFILE_PATH) return { ...defaultResult(defaults, [{ code: "ls_tree_unparsed" }]), blob: null };
	const [, mode, kind, oid, size] = m;
	if ((mode !== "100644" && mode !== "100755") || kind !== "blob") {
		return { ...defaultResult(defaults, [{ code: "not_regular_file" }]), blob: oid };
	}
	if (Number(size) > MAX_FILE_BYTES) return { ...defaultResult(defaults, [{ code: "too_large" }]), blob: oid };

	const key = JSON.stringify([oid, defaults.target, defaults.protectedRefs, defaults.sourcePrefixes, defaults.freeZonePrefixes]);
	const hit = cache.get(key);
	if (hit) return { ...structuredClone(hit), blob: oid };
	const blob = git(["cat-file", "blob", oid], cwd);
	if (!blob.ok) return { ...defaultResult(defaults, [{ code: "read_failed" }]), blob: oid };
	return { ...cached(key, () => effectiveProfile(defaults, blob.stdout)), blob: oid };
}

/** 試験用: キャッシュを空にする。 */
export function clearProfileCache(): void {
	cache.clear();
}

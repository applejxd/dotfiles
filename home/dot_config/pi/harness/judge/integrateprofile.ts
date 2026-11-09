// プロジェクト内の `.agents/config/pi.json` の解析・検査・実効の設定 (純関数。ファイル・git・時刻に触れない)。
// 保護ブランチは全体設定のまま。ここで受けるのは統合先と接頭辞だけで、保護と交差する値は拒否する。
// 診断は固定のコードとキー名だけ (入力の本文・値・生の例外は入れない)。
// see docs/change/closed/0057-per-project-integrate.md

export type ProfileDefaults = {
	protectedRefs: readonly string[];
	target: string;
	sourcePrefixes: readonly string[];
	freeZonePrefixes: readonly string[];
};
export type Profile = { target: string; sourcePrefixes: string[]; freeZonePrefixes: string[]; source: "default" | "project" };
export type Diagnostic = { code: string; key?: string };
export type ProfileResult = { profile: Profile; diagnostics: Diagnostic[]; overridden: boolean };

export const DEFAULT_SOURCE_PREFIXES: readonly string[] = ["feature/", "bugfix/"];
export const DEFAULT_FREE_ZONE_PREFIXES: readonly string[] = ["feature/"];

export const MAX_FILE_BYTES = 4096;
const MAX_ITEMS = 8;
const MAX_STRING = 64;
const MAX_TARGET = 128;
const INTEGRATE_KEYS = ["target", "source_prefixes", "free_zone_prefixes"] as const;

function sameList(a: readonly string[], b: readonly string[]): boolean {
	return a.length === b.length && a.every((v, i) => v === b[i]);
}

/** 全体の既定のまま (source: "default") の結果。診断は固定のコードだけ。 */
export function defaultResult(defaults: ProfileDefaults, diagnostics: Diagnostic[] = []): ProfileResult {
	return {
		profile: {
			target: defaults.target,
			sourcePrefixes: [...defaults.sourcePrefixes],
			freeZonePrefixes: [...defaults.freeZonePrefixes],
			source: "default",
		},
		diagnostics,
		overridden: false,
	};
}

/** キー名を診断に出せる形にする。先頭 32 字が小文字と `_` だけのときだけ（綴り違いを直す手がかり）。大文字・数字・記号を含むものは、トークンに見えるので `?`。 */
function safeKey(key: string): string {
	const head = key.slice(0, 32);
	return head.length > 0 && /^[a-z_]+$/.test(head) ? head : "?";
}

function unknownKeyDiag(key: string): Diagnostic {
	if (key === "extra_protected_refs" || key === "protected_refs") return { code: "protected_refs_not_allowed", key };
	return { code: "unknown_key", key: safeKey(key) };
}

/** isProtectedRef (judge/protectedrefs.ts) と同じ正規化: `refs/heads/` を外して小文字。他の `refs/` は null。 */
function branchName(ref: string): string | null {
	const lower = ref.trim().toLowerCase();
	if (lower.startsWith("refs/heads/")) return lower.slice("refs/heads/".length);
	if (lower.startsWith("refs/")) return null;
	return lower;
}

/** 接頭辞 P が、保護 (完全一致か末尾 `/*`) の許すブランチ名と交差するか。 */
function overlapsProtected(prefix: string, protectedRefs: readonly string[]): boolean {
	const p = prefix.toLowerCase();
	for (const raw of protectedRefs) {
		const q = branchName(raw);
		if (q === null || q === "") continue;
		if (q.endsWith("/*")) {
			const base = q.slice(0, -1); // "B/"
			if (base.startsWith(p) || p.startsWith(base)) return true;
		} else if (q.startsWith(p)) {
			return true;
		}
	}
	return false;
}

function validPrefixShape(p: string): boolean {
	if (p === "" || !p.endsWith("/") || p.startsWith("/")) return false;
	if (/[*?[\\~^:\s\x00-\x1f\x7f]/.test(p)) return false;
	if (p.includes("..") || p.includes("//") || p.includes("@{")) return false;
	if (p.toLowerCase().startsWith("refs/")) return false;
	return true;
}

type Checked<T> = { ok: true; value: T } | { ok: false; diag: Diagnostic };

function checkPrefixes(key: string, raw: unknown, protectedRefs: readonly string[]): Checked<string[]> {
	if (!Array.isArray(raw)) return { ok: false, diag: { code: "bad_type", key } };
	if (raw.length > MAX_ITEMS) return { ok: false, diag: { code: "too_many", key } };
	const out: string[] = [];
	for (const item of raw) {
		if (typeof item !== "string") return { ok: false, diag: { code: "bad_type", key } };
		if (item.length > MAX_STRING) return { ok: false, diag: { code: "too_large", key } };
		if (!validPrefixShape(item)) return { ok: false, diag: { code: "bad_prefix", key } };
		if (overlapsProtected(item, protectedRefs)) return { ok: false, diag: { code: "prefix_overlaps_protected", key } };
		if (!out.includes(item)) out.push(item);
	}
	return { ok: true, value: out };
}

function checkTarget(raw: unknown, protectedRefs: readonly string[]): Checked<string> {
	const key = "target";
	if (typeof raw !== "string") return { ok: false, diag: { code: "bad_type", key } };
	if (raw.length > MAX_TARGET) return { ok: false, diag: { code: "too_large", key } };
	if (raw === "" || /[*?[]/.test(raw) || !protectedRefs.includes(raw)) return { ok: false, diag: { code: "bad_target", key } };
	return { ok: true, value: raw };
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
	return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** 全体の既定 + プロジェクトの設定 (HEAD の内容。null は設定なし) から、実効の設定を作る。落ちたら全体の既定 + 診断。 */
export function effectiveProfile(defaults: ProfileDefaults, projectText: string | null): ProfileResult {
	if (projectText === null) return defaultResult(defaults);
	if (Buffer.byteLength(projectText, "utf8") > MAX_FILE_BYTES) return defaultResult(defaults, [{ code: "too_large" }]);
	const text = projectText.replace(/^\uFEFF/, "");
	if (text.trim() === "") return defaultResult(defaults);

	let parsed: unknown;
	try {
		parsed = JSON.parse(text);
	} catch {
		return defaultResult(defaults, [{ code: "invalid_json" }]);
	}
	if (!isPlainObject(parsed)) return defaultResult(defaults, [{ code: "not_object" }]);

	const diags: Diagnostic[] = [];
	for (const k of Object.keys(parsed)) if (k !== "integrate") diags.push(unknownKeyDiag(k));
	const section = Object.hasOwn(parsed, "integrate") ? parsed.integrate : {};
	if (!isPlainObject(section)) {
		diags.push({ code: "bad_type", key: "integrate" });
		return defaultResult(defaults, diags);
	}
	for (const k of Object.keys(section)) if (!(INTEGRATE_KEYS as readonly string[]).includes(k)) diags.push(unknownKeyDiag(k));

	let target = defaults.target;
	let sourcePrefixes = [...defaults.sourcePrefixes];
	let freeZonePrefixes = [...defaults.freeZonePrefixes];
	if (Object.hasOwn(section, "target")) {
		const r = checkTarget(section.target, defaults.protectedRefs);
		if (r.ok) target = r.value;
		else diags.push(r.diag);
	}
	if (Object.hasOwn(section, "source_prefixes")) {
		const r = checkPrefixes("source_prefixes", section.source_prefixes, defaults.protectedRefs);
		if (r.ok) sourcePrefixes = r.value;
		else diags.push(r.diag);
	}
	if (Object.hasOwn(section, "free_zone_prefixes")) {
		const r = checkPrefixes("free_zone_prefixes", section.free_zone_prefixes, defaults.protectedRefs);
		if (r.ok) freeZonePrefixes = r.value;
		else diags.push(r.diag);
	}
	if (diags.length > 0) return defaultResult(defaults, diags);

	const overridden =
		target !== defaults.target || !sameList(sourcePrefixes, defaults.sourcePrefixes) || !sameList(freeZonePrefixes, defaults.freeZonePrefixes);
	return { profile: { target, sourcePrefixes, freeZonePrefixes, source: "project" }, diagnostics: [], overridden };
}

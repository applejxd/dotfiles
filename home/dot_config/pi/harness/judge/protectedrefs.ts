// 保護 ref の判定 (純関数)。`refs/heads/` 付きでも省略形でも受け、大文字小文字は区別しない。
// see docs/change/0053-worktree-integration-gate.md

const HEADS = "refs/heads/";

/** `refs/heads/` を外して小文字にする。それ以外の `refs/` (remotes / tags) は null (ブランチではない)。 */
function branchName(ref: string): string | null {
	const lower = ref.trim().toLowerCase();
	if (lower.startsWith(HEADS)) return lower.slice(HEADS.length);
	if (lower.startsWith("refs/")) return null;
	return lower;
}

/** ref が patterns (完全一致か末尾 `/*`) のいずれかに当たるか。`release/*` は `release` 単体には当たらない。 */
export function isProtectedRef(ref: string, patterns: readonly string[]): boolean {
	const name = branchName(ref);
	if (name === null || name === "") return false;
	for (const raw of patterns) {
		const pattern = branchName(raw);
		if (pattern === null || pattern === "") continue;
		if (pattern.endsWith("/*")) {
			const prefix = pattern.slice(0, -1);
			if (name.startsWith(prefix) && name.length > prefix.length) return true;
		} else if (name === pattern) {
			return true;
		}
	}
	return false;
}

/** `feature/<非空>` だけが true (大文字小文字は区別しない)。 */
export function isFeatureSourceRef(ref: string): boolean {
	const name = branchName(ref);
	return name !== null && name.startsWith("feature/") && name.length > "feature/".length;
}

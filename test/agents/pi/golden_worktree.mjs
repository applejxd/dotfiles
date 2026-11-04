// judge_golden.mjs の `git worktree remove` の期待値 (implementer / worker の deny_except)。
// Python 版は deny のまま。TS 版の期待は標本ごとの明示とし、一括の許容はしない。
// force 付きの標本は decision が ask かつ mustConfirm が真でなければならない (欠落・不正な応答・通常の ask・allow は拒否)。
// see docs/spec/guard/pi-decide.md#git-worktree-remove-の例外

// 期待値: 標本のコマンド -> "mustConfirm" (force 付き。ask + mustConfirm が必須)
const WORKTREE_REMOVE_EXPECTED = new Map([["git worktree remove --force .", "mustConfirm"]]);

/** この標本が対象なら true / false (一致の可否)、対象外なら null を返す。 */
export function worktreeRemoveMatches(got, expected, request) {
	if (request?.tool !== "bash") return null;
	if (request?.role !== "implementer" && request?.role !== "worker") return null;
	if (expected?.check !== "check_policy_deny") return null;
	if (typeof expected?.reason !== "string" || !expected.reason.startsWith("`git worktree remove`")) return null;
	const want = WORKTREE_REMOVE_EXPECTED.get(request?.input?.command);
	// 表にない標本は、TS 版でも deny のまま (例外が効かない)
	if (want === undefined) return got?.decision === "deny" && got?.check === "check_policy_deny";
	return got?.decision === "ask" && got?.mustConfirm === true;
}

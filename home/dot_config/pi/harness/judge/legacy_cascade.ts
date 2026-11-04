// 旧の bash の判定のカスケード (G2a で段の表 `verdict.ts` へ置き換える前の実装の写し)。
//
// G7 で削除する oracle。試験 (`test_pi_stage_table.py`) だけが使い、本番の経路は `bash.ts` の `makeBashDecider` (段の表) を使う。
// 個別の検査関数は `bash.ts` の旧のものをそのまま呼ぶ。ここは、その呼び出しの順序 (先に当たった段が決める) だけを写している。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/guard/pi-decide.md#bash-の評価順段の表
import { CHECKS } from "./checks.ts";
import type { Tables } from "./context.ts";
import { newCtx } from "./context.ts";
import type { BashDecider } from "./decide.ts";
import { errorResponse, response } from "./decide.ts";
import { actionDenyReason } from "./actions.ts";
import { findMatch } from "./normalize.ts";
import type { Common } from "./policy.ts";
import { pyLen } from "./pystr.ts";
import { splitHeredocBody } from "./shared.ts";
import {
	allSegmentsAllowed,
	bashAsk,
	bashCommonDeny,
	confirmTable,
	denyForDenyDefaultRole,
	guide,
	localGitConfirm,
	MAX_COMMAND_LEN,
	restoreStagedExcepted,
	RESTORE_DENY,
	skillScriptAllowed,
	unwrapRemoteExec,
	withoutDeny,
	worktreeRemoveExcepted,
	WORKTREE_REMOVE,
} from "./bash.ts";

type Obj = Record<string, any>;

/** 旧のカスケードそのままの bash の判定器 (oracle)。 */
export function makeLegacyBashDecider(tables: Tables): BashDecider {
	const decide = (
		rawCmd: string,
		cwd: string,
		pi: Obj,
		profile: Obj,
		common: Common,
		remote: boolean,
	): ReturnType<BashDecider> => {
		// 判定ごとに文脈を作り直す (呼び出しの順に依らない)
		const ctx = newCtx(tables, common, cwd);
		let cmd = rawCmd;
		const loaded = CHECKS.get("check_policy_loaded")?.(ctx, cmd);
		if (loaded) return { commonDeny: errorResponse(loaded), roleRule: null };
		if (pyLen(cmd) > MAX_COMMAND_LEN) {
			return { commonDeny: errorResponse(`コマンドが長すぎます (${pyLen(cmd)} 文字)`), roleRule: null };
		}
		try {
			cmd = splitHeredocBody(ctx, cmd);
		} catch {
			// 解析できないときは元の文字列で検査
		}
		// ssh の許可は 1 段だけ。中身は同じ判定にかけるので、リモート側の `ssh` はそのまま deny に当たる
		const targets = ((pi.remote_exec?.targets as unknown[] | undefined) ?? []).map(String);
		const inner = remote ? null : unwrapRemoteExec(cmd, targets);
		if (inner !== null) return decide(inner, cwd, pi, profile, common, true);
		// 例外は直接実行だけ (ssh のリモート側を再帰判定しているときは効かせない)
		let denyCtx = ctx;
		if (!remote && worktreeRemoveExcepted(rawCmd, pi, profile)) denyCtx = withoutDeny(denyCtx, WORKTREE_REMOVE);
		const restoreOk = !remote && restoreStagedExcepted(rawCmd, pi, profile);
		if (restoreOk) denyCtx = withoutDeny(denyCtx, RESTORE_DENY);
		const deny = bashCommonDeny(denyCtx, cmd);
		if (deny) return { commonDeny: deny, roleRule: null };
		const g = guide(cmd, pi);
		if (g) return { commonDeny: null, roleRule: g };
		// action ツールを持つ役割だけ: 操作表 [[pi.actions]] の replaces に当たるコマンドは guarded_action へ誘導する (bypass でも外れない)
		if (Array.isArray(profile.tools) && profile.tools.includes("action")) {
			const reason = actionDenyReason(cmd, pi);
			if (reason !== null) return { commonDeny: null, roleRule: response("deny", reason, "rule") };
		}
		// 役割だけの禁止。共通の禁止ではないが、bypass では外れない (bypass は ask だけを変える)
		// 例外に当たった `git restore --staged` は、役割の shell_deny の「git restore」も外す
		const roleDenyList = ((profile.shell_deny as unknown[] | undefined) ?? []).map(String).filter((p) => !(restoreOk && p === RESTORE_DENY));
		const roleDeny = findMatch(cmd, roleDenyList);
		if (roleDeny) {
			return { commonDeny: null, roleRule: response("deny", `\`${roleDeny}\` はこの役割の shell_deny にある`, "rule") };
		}
		const confirm = confirmTable(cmd, pi);
		if (confirm) return { commonDeny: null, roleRule: confirm };
		const localGit = localGitConfirm(cmd, pi, profile);
		if (localGit) return { commonDeny: null, roleRule: localGit };
		const ask = bashAsk(ctx, cmd, pi);
		if (ask) return { commonDeny: null, roleRule: denyForDenyDefaultRole(ask, profile) };
		// 役割が shell_allow を持てば、[pi.shell] allow の代わりにそれを使う
		const own = profile.shell_allow;
		const allowList: unknown[] = own != null ? own : (pi.shell?.allow ?? []);
		const where = own != null ? "役割の shell_allow" : "[pi.shell] allow";
		const matched = allSegmentsAllowed(cmd, allowList.map(String));
		if (matched) return { commonDeny: null, roleRule: response("allow", `\`${matched}\` は ${where} にある`, "rule") };
		const script = skillScriptAllowed(cmd, pi);
		if (script) return { commonDeny: null, roleRule: response("allow", `\`${script}\` は [pi.skill_scripts] にある`, "rule") };
		return { commonDeny: null, roleRule: null };
	};
	return (rawCmd, cwd, pi, profile, common: Common) => decide(rawCmd, cwd, pi, profile, common, false);
}

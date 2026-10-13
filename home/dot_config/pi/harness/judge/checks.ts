// bash 検査関数の登録簿 (bashrules/__init__.py の DENY_CHECKS / PATH_CHECKS / ASK_CHECKS の移植)。
//
// CHECKS は「名前 → 関数」の対応で、差分試験 (test/agents/pi/checks_golden.mjs) が名前で引く。
// 名前は Python 版の関数名 (`check_xxx`) のまま使う。順序に意味がある並びは移植が揃ってから足す。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/pi-decide.md#ts-版への移植
import type { Ctx } from "./context.ts";
import { checkCurlFileSend, checkCurlWgetMutation, checkHttpDangerousOutput } from "./http.ts";
import {
	checkEncodedCommand,
	checkInterpreterInlineCode,
	checkPipeToShell,
	checkReverseShell,
	checkXargsPipe,
} from "./rules_exec.ts";
import { checkPolicyAsk, checkPolicyDeny, checkPolicyLoaded } from "./bashpolicy.ts";
import { checkFindDangerous, checkFindRootGuard, checkRmRootGuard } from "./rm.ts";
import { checkArchive, checkEnvExposure, checkFileRead, checkPipRedirect } from "./rules_files.ts";
import {
	checkBlockDeviceWrite,
	checkGitConfigWrite,
	checkGlobalEnvMutation,
	checkGuardTampering,
	checkPrivilegeEscalation,
	checkShellStartupWrite,
	checkToolSelfUpdate,
} from "./rules_guard.ts";
import { checkGitAddSensitive, checkHistoryAccess, checkSecretEnvEcho } from "./sensitive.ts";

export type Check = (ctx: Ctx, cmd: string) => string | null;

export const CHECKS = new Map<string, Check>([
	["check_git_add_sensitive", checkGitAddSensitive],
	["check_history_access", checkHistoryAccess],
	["check_secret_env_echo", checkSecretEnvEcho],
	["check_curl_file_send", checkCurlFileSend],
	["check_curl_wget_mutation", checkCurlWgetMutation],
	["check_http_dangerous_output", checkHttpDangerousOutput],
	["check_xargs_pipe", checkXargsPipe],
	["check_pipe_to_shell", checkPipeToShell],
	["check_interpreter_inline_code", checkInterpreterInlineCode],
	["check_reverse_shell", checkReverseShell],
	["check_encoded_command", checkEncodedCommand],
	["check_find_dangerous", checkFindDangerous],
	["check_find_root_guard", checkFindRootGuard],
	["check_rm_root_guard", checkRmRootGuard],
	["check_policy_loaded", checkPolicyLoaded],
	["check_policy_deny", checkPolicyDeny],
	["check_policy_ask", checkPolicyAsk],
	["check_file_read", checkFileRead],
	["check_env_exposure", checkEnvExposure],
	["check_archive", checkArchive],
	["check_pip_redirect", checkPipRedirect],
	["check_guard_tampering", checkGuardTampering],
	["check_shell_startup_write", checkShellStartupWrite],
	["check_privilege_escalation", checkPrivilegeEscalation],
	["check_tool_self_update", checkToolSelfUpdate],
	["check_global_env_mutation", checkGlobalEnvMutation],
	["check_git_config_write", checkGitConfigWrite],
	["check_block_device_write", checkBlockDeviceWrite],
]);

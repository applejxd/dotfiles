// common.toml の [bash] deny / ask をコマンドに突き合わせる (bashrules/policy.py の移植)。
//
// パターンそのものは common.toml (JSON にしたもの) にある。ルールを足すときに編集するのはこのファイルではなく common.toml のほう。
// `checkPolicyLoaded` は設定を読めなかったときに fail-closed で拒否する。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/guard/pi-decide.md#ts-版への移植
import type { Ctx } from "./context.ts";
import { findMatch } from "./normalize.ts";
import { loadStrList } from "./policy.ts";
import { split } from "./pystr.ts";
import { rmAskExempt, rmAskHint } from "./rm.ts";
import { clip200 } from "./shared.ts";

const denyPatterns = (ctx: Ctx): string[] => loadStrList(ctx.common, "bash", "deny");
const askPatterns = (ctx: Ctx): string[] => loadStrList(ctx.common, "bash", "ask");

/** ポリシー設定を解釈できないときは fail-closed で拒否する (Python 版のモジュール読み込み・ファイル存在の確認は、JSON を受け取る TS では要らない)。 */
export function checkPolicyLoaded(ctx: Ctx, _cmd: string): string | null {
	let deny: string[];
	try {
		deny = denyPatterns(ctx);
		askPatterns(ctx);
	} catch (exc) {
		return `ポリシー定義を解釈できませんでした (${(exc as Error).message})。\n安全のため bash コマンドを拒否しています。`;
	}
	if (deny.length === 0) {
		return (
			"ポリシー定義に [bash] deny がありません。\n" +
			"設定が壊れている可能性があるため、安全のため拒否しています。\n" +
			"対処: `chezmoi apply ~/.config/agents` を実行してください。"
		);
	}
	return null;
}

/** common.toml の bash.deny に該当すれば block する。 */
export function checkPolicyDeny(ctx: Ctx, cmd: string): string | null {
	const matched = findMatch(cmd, denyPatterns(ctx));
	if (matched) {
		return (
			`\`${matched}\` は deny パターンに一致するためブロックされました。\n` +
			"このコマンドは common.toml の [bash] deny で禁止されています。"
		);
	}
	return null;
}

// ask を省いてよい条件。パターンの先頭トークンで引く
const ASK_EXEMPTIONS = new Map<string, (ctx: Ctx, cmd: string) => boolean>([["rm", rmAskExempt]]);

/** common.toml の bash.ask に該当すればユーザー承認を要求する (免除の条件を満たす種類は承認を省く)。 */
export function checkPolicyAsk(ctx: Ctx, cmd: string): string | null {
	const patterns = askPatterns(ctx);
	let matched = findMatch(cmd, patterns);
	if (matched) {
		const head = split(matched)[0];
		const exemption = ASK_EXEMPTIONS.get(head);
		if (exemption !== undefined && exemption(ctx, cmd)) {
			// 免除は当たった種類 (rm) だけに効かせる。他のセグメントの ask は残す
			matched = findMatch(
				cmd,
				patterns.filter((p) => split(p)[0] !== head),
			);
			if (!matched) return null;
		}
		const hint = split(matched)[0] === "rm" ? rmAskHint(cmd) : "";
		return (
			`\`${matched}\` は承認が必要な操作です (common.toml の [bash] ask)。\n` +
			`実行しようとしているコマンド: ${clip200(cmd)}\n` +
			`内容を確認して問題なければ承認してください。${hint}`
		);
	}
	return null;
}

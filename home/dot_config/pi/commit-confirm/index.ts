// 素の pi (ハーネス無し) 向けの補助。bash の git について:
//   git push   → 完全手動なので止める
//   git commit → 構造 (リポジトリ・ブランチ・対象・メッセージ) を見せて確認する。時間切れ・不在・画面なしのときは
//                コミットせず内容を refs/pi/pending/ へ退避し、作業を続けさせる
// 保護ではなく補助 (別名・スクリプト越しは検出しない)。ハーネス (pis) は同じ確認を自前で持つので -ne で外れる。
// see docs/spec/pi-harness.md#commit-の確認-素の-pi
import { analyze } from "./parse.ts";
import { describeCommit, rawText } from "./describe.ts";
import { pendingTarget, savePending, type Saved } from "./pending.ts";

// TUI は 15 分、RPC など (Zed) は 5 分。PI_COMMIT_CONFIRM_TIMEOUT_MS は試験用に両方を上書きする
const OVERRIDE = Number(process.env.PI_COMMIT_CONFIRM_TIMEOUT_MS) || 0;
const TUI_TIMEOUT_MS = OVERRIDE || 15 * 60 * 1000;
const OTHER_TIMEOUT_MS = OVERRIDE || 5 * 60 * 1000;

const PUSH_REASON =
	"git push は完全手動のため実行しない。push を除いた作業は続け、push が要る場合は利用者に依頼する。";

function after(saved: Saved, approx: boolean, compound: boolean): string {
	const where = saved.ok
		? `内容は ${saved.ref} (${saved.short}, ${saved.files} ファイル) に退避した` +
			(approx ? " (連結したコマンドだったので、今ステージされている内容と最初の commit のメッセージによる近似)。" : "。")
		: `内容は退避できなかった (${saved.reason})。`;
	// 読めない形はコマンド全体を止めている。連結していた commit 以外の操作も実行していない
	const rest = compound ? "連結していた他の操作も実行していないので、必要なら commit と分けて実行し直す。" : "";
	return (
		`${where}${rest}git commit を再試行しない。コミットが要らない作業を続け、` +
		"最後に「保留したコミット」として上の ref・件名・対象を報告する。"
	);
}

function waitText(ms: number): string {
	return ms >= 60_000 ? `${Math.round(ms / 60_000)} 分` : `${Math.round(ms / 1000)} 秒`;
}

export default async function (pi: any) {
	// 利用者が不在と分かった後 (確認が時間切れ) は、次の確認で待たない。利用者の入力で解除する
	let absent = false;
	pi.on("input", (event: any) => {
		if (event?.source !== "extension") absent = false;
	});

	// 確認は 1 件ずつ (TUI の confirm は 1 枠を共有し、後の確認が先の確認を置き換える)
	let queue: Promise<unknown> = Promise.resolve();

	pi.on("tool_call", async (event: any, ctx: any) => {
		if (event.toolName !== "bash") return;
		const command = String(event.input?.command ?? "");
		let a;
		try {
			a = analyze(command);
		} catch (e) {
			// 補助の不具合で bash 全体を止めない
			console.error(`[commit-confirm] コマンドを解析できなかった: ${(e as Error).message}`);
			return;
		}
		if (a.kind === "none") return;
		if (a.kind === "push") return { block: true, reason: PUSH_REASON };

		const cwd: string = ctx.cwd ?? process.cwd();
		const recognized = a.recognized ? a : null;
		const defer = (why: string) => {
			const t = pendingTarget(a);
			let saved: Saved;
			try {
				saved = t ? savePending(t.target, cwd) : { ok: false, reason: "読めない形のコマンド" };
			} catch (e) {
				saved = { ok: false, reason: (e as Error).message };
			}
			return {
				block: true,
				reason: `git commit は実行していない: ${why}。${after(saved, t?.approx ?? false, !a.recognized)}`,
			};
		};

		if (!ctx.hasUI) return defer("確認できる画面が無い (非対話の実行)");

		const timeout = ctx.mode === "tui" ? TUI_TIMEOUT_MS : OTHER_TIMEOUT_MS;
		// 表示は順番が来てから作る (先の確認が済んだ後に組む)。pi は同じ応答の全呼び出しの tool_call を終えてから実行を始めるので、先に承認したコミットの結果はまだ反映されない (後の表示は、先のコミットが入る前の状態を見せる)
		const makeText = (): string => {
			let body: string | null = null;
			try {
				body = recognized ? describeCommit(recognized, cwd) : null;
			} catch {
				body = null;
			}
			// 構造を組めないときは、「取れない」と書いて承認させず、生のコマンドを見せる
			const shown =
				body ??
				(recognized
					? rawText(command, "構造を取得できなかったので、生のコマンドを表示します。次がそのまま実行されます:")
					: rawText(command));
			return `${shown}\n\n${waitText(timeout)}応答が無ければ、コミットせず内容を退避して作業を続けます`;
		};
		// 順番が来た時点で判定する (1 回の応答に並んだ commit は、先の確認が時間切れなら後ろも待たない)
		const turn = queue.then(async (): Promise<"ok" | "declined" | "timeout" | "absent"> => {
			if (absent) return "absent";
			if (ctx.signal?.aborted) return "declined";
			const text = makeText();
			const t0 = Date.now();
			const v = await ctx.ui
				.confirm("git commit を実行しますか？", text, { signal: ctx.signal, timeout })
				.catch(() => false);
			if (v === true) return "ok";
			// pi は拒否と時間切れのどちらにも false を返す。経過時間で時間切れを判定する
			if (Date.now() - t0 >= timeout - Math.min(1500, timeout / 5) && !ctx.signal?.aborted) {
				absent = true;
				return "timeout";
			}
			return "declined";
		});
		queue = turn.catch(() => undefined);
		const result = await turn.catch(() => "declined" as const);
		if (result === "ok") return;
		if (result === "timeout") return defer(`確認が ${waitText(timeout)}の時間切れになった`);
		if (result === "absent") return defer("利用者が不在のため確認せずに退避した (前の確認が時間切れ)");
		return { block: true, reason: "利用者が git commit を拒否した。コミットしない。続け方を利用者に確認する。" };
	});
}

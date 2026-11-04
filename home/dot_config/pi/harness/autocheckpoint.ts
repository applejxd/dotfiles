// 文脈の使用率による自動の保存と圧縮。親のセッションだけで働く。
// 使用率が閾値以上になったら、(1) 保存の指示を積んで 1 回だけ継続し、(2) 次の settle で ctx.compact を起動する。
// 組み込みの自動圧縮 (窓 - reserveTokens 付近) は予備として残す。
// see docs/spec/guard/pi-extensions.md#文脈の使用率による自動の保存と圧縮
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export const DEFAULT_PERCENT = 80;
export const DEFAULT_COOLDOWN_MS = 10 * 60 * 1000;
export const CUSTOM_TYPE = "autocheckpoint";

// 保存の指示 (custom_message の本文)。私物の情報・コミット・本体の docs 編集を禁じる
export const CHECKPOINT_PROMPT = [
	"【自動の保存】文脈の使用率が高くなったので、圧縮の前に保存する。新しい作業は始めず、利用者への質問もせず、",
	"次だけを行い、終わったら「保存完了」と 1 行だけ答えて止まる。",
	"1. スキル sdd-docs に従い、この会話で確定した決定・実測・設計・案件の進捗のうち、docs に未反映のものを docs へ反映する。",
	"   **コミットしない**。**公開リポジトリの規約を守る**: 勤務先・所属組織の環境、社内の URL・ホスト名、ホームの絶対パス、",
	"   個人情報、秘密・認証情報、私物のホスト名は書かない (迷ったら書かず `.tmp/keep/` の私用メモへ)。",
	"   **本体の作業ツリー (develop) の docs は編集しない** (本体が dirty になると統合が断られる)。",
	"   docs を直すのは担当の feature の worktree の中だけ。該当の worktree が無ければ docs は触らず 2 以降だけ行う。",
	"2. 引き継ぎ文書 `.tmp/keep/checkpoint/NEXT.md` (私用。コミットしない) の先頭を、最新の状態 (押下待ちの PR・実行中の worker とジョブ id・",
	"   commit 済み未統合の枝・次にやること・利用者の未実施の操作・今日の決定と運用の学び) に**書き直す** (追記でなく書き換え)。",
	"3. todo の状態と note を最新にする。",
	"4. 実行中の子・背景ジョブがあれば、NEXT.md に id・目的・完了後にやることを書く (圧縮は子・背景ジョブを止めない。結果は後で通知される)。",
	"サブエージェントは起動しない (文脈の節約)。",
].join("\n");

// 圧縮の完了後に 1 回だけ送る再開の指示 (user メッセージ)。判断待ちだけなら 1 行で止まらせる
export const RESUME_PROMPT = [
	"【自動の再開】圧縮が完了した。`.tmp/keep/checkpoint/NEXT.md` の先頭と todo を読み、進められる作業があれば続ける。",
	"判断待ち・承認待ち・子や背景ジョブの完了待ちだけなら、「待機」と 1 行だけ答えて止まる。",
	"新しく大きな作業は始めない。",
].join("\n");

// 圧縮の完了通知は pi が圧縮の状態を解く前に届くので、解かれた後まで待ってから送る (index.ts の session_compact と同じ理由)
export const DEFAULT_RESUME_DELAY_MS = 200;

export interface AutoCheckpointOptions {
	/** 子エージェントなら何もしない */
	child: boolean;
	/** 圧縮に渡す指示 (index.ts の COMPACT_INSTRUCTIONS) */
	compactInstructions: string;
	env?: Record<string, string | undefined>;
	/** 時計 (試験で差し替える) */
	now?: () => number;
	cooldownMs?: number;
	/** 再開の指示を送る (registerAutoCheckpoint が pi.sendUserMessage を渡す。試験で差し替える) */
	resume?: (text: string) => void;
	/** 圧縮の完了から再開を送るまでの待ち (ms) */
	resumeDelayMs?: number;
}

type Phase = "idle" | "saving" | "compacting";

export function thresholdPercent(env: Record<string, string | undefined>): number {
	const n = Number(env.PI_AUTOCHECKPOINT_PERCENT);
	return env.PI_AUTOCHECKPOINT_PERCENT && Number.isFinite(n) && n > 0 && n <= 100 ? n : DEFAULT_PERCENT;
}

/** agent_before_settle の handler を作る。状態 (idle → saving → compacting → idle) はクロージャに持つ。 */
export function createAutoCheckpoint(opts: AutoCheckpointOptions) {
	const env = opts.env ?? process.env;
	const now = opts.now ?? Date.now;
	const cooldownMs = opts.cooldownMs ?? DEFAULT_COOLDOWN_MS;
	let phase: Phase = "idle";
	let coolUntil = 0;
	let cycle = 0; // 保存の周期の通し番号 (待つ間に周期が進んだかを見る)

	const notify = (ctx: any, text: string) => {
		try {
			ctx.ui?.notify?.(`自動保存: ${text}`, "info");
		} catch {
			/* 通知の失敗で本体を止めない */
		}
	};
	const finish = () => {
		phase = "idle";
		coolUntil = now() + cooldownMs;
	};
	const disabled = (ctx: any) => opts.child || env.PI_AUTOCHECKPOINT === "0" || ctx.mode === "print" || ctx.mode === "json";

	// 圧縮の成功後に 1 回だけ再開を送る。待つ間に状態が変わった (別の周期・無効化) ら送らない
	const scheduleResume = (ctx: any) => {
		if (!opts.resume || env.PI_AUTOCHECKPOINT_RESUME === "0") return;
		const myCycle = cycle;
		setTimeout(() => {
			if (phase !== "idle" || cycle !== myCycle || disabled(ctx) || env.PI_AUTOCHECKPOINT_RESUME === "0") return;
			try {
				notify(ctx, "圧縮が完了したので再開を指示する");
				opts.resume?.(RESUME_PROMPT);
			} catch {
				/* 再開の失敗で本体を止めない */
			}
		}, opts.resumeDelayMs ?? DEFAULT_RESUME_DELAY_MS);
	};

	return (event: any, ctx: any): { entries?: any[]; continue?: boolean } | undefined => {
		if (disabled(ctx)) return undefined;
		if (phase === "compacting") return undefined;
		if (phase === "saving") {
			// 保存の継続が終わった (失敗・エラーで終わっても圧縮は進める)。利用者の中断 (Esc) だけは周期ごと取りやめる
			if (event?.outcome === "aborted") {
				finish();
				notify(ctx, "中断されたので、圧縮は起動しない");
				return undefined;
			}
			phase = "compacting";
			notify(ctx, "保存が終わったので圧縮を起動する");
			try {
				ctx.compact({
					customInstructions: opts.compactInstructions,
					onComplete: () => {
						finish();
						notify(ctx, "圧縮が完了");
						scheduleResume(ctx);
					},
					onError: (e: Error) => {
						finish();
						notify(ctx, `圧縮に失敗: ${e?.message ?? e}`);
					},
				});
			} catch (e: any) {
				finish();
				notify(ctx, `圧縮を起動できない: ${e?.message ?? e}`);
			}
			return undefined;
		}
		// idle
		if (event?.outcome !== undefined && event.outcome !== "completed") return undefined;
		if (now() < coolUntil) return undefined;
		const percent = ctx.getContextUsage?.()?.percent;
		if (typeof percent !== "number" || percent < thresholdPercent(env)) return undefined;
		phase = "saving";
		cycle++;
		notify(ctx, `文脈の使用率 ${Math.round(percent)}% なので、保存を指示する`);
		return {
			entries: [{ type: "custom_message", customType: CUSTOM_TYPE, content: CHECKPOINT_PROMPT, display: true }],
			continue: true,
		};
	};
}

export function registerAutoCheckpoint(pi: ExtensionAPI, opts: AutoCheckpointOptions): void {
	if (opts.child) return;
	// アイドル中は新しいターンが始まる。streaming 中は followUp で待たせる (指定が無いと pi.prompt が例外にする)
	const resume =
		opts.resume ??
		((text: string) => {
			Promise.resolve(pi.sendUserMessage(text, { deliverAs: "followUp" })).catch(() => {});
		});
	const handler = createAutoCheckpoint({ ...opts, resume });
	pi.on("agent_before_settle", handler as any);
}

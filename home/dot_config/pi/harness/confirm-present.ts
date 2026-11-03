// 確認の提示: 選択肢を出し、期限・取消・「全文を見る」を扱う。guarded_action の確認 (actions.ts) が使う。
// 選ばれた結果を、承認・拒否・時間切れ・取消・例外に分類するのは呼び出し側 (承認の意味は操作ごとに違うため)。
//
// node の型除去でそのまま動く書き方だけを使う (enum・namespace は使わない)。
// see docs/change/closed/0055-async-approval.md

import { showTextViewer } from "./text-viewer.ts";

export const VIEW_FULL = "全文を見る";

/** TUI の組み込みの期限は、自前の期限より遅くして、保険にだけ使う (自前の期限で時間切れを判定する) */
export const BACKSTOP_MS = 3000;

export type PresentOptions = {
	title: string;
	options: string[];
	/** 自前の期限 (ミリ秒)。無ければ期限なし (保留の承認など) */
	timeoutMs?: number;
	/** options に VIEW_FULL を含めるときの全文。text は押されたときに作る */
	viewFull?: { title: string; text: () => string };
	signal?: AbortSignal;
};

export type PresentResult = {
	choice: string | undefined;
	/** 自前のタイマーが発火したときだけ真 (取消・呼び出し元の中断・例外とは区別する) */
	timedOut: boolean;
	error: boolean;
};

/** select を出す。「全文を見る」が選ばれたら全文を開き、閉じたら選び直させる (期限は select ごとに仕切り直す) */
export async function presentConfirm(ui: any, o: PresentOptions): Promise<PresentResult> {
	let timedOut = false;
	let choice: string | undefined;
	let error = false;
	for (;;) {
		choice = undefined;
		const own = new AbortController();
		const forward = () => own.abort();
		if (o.signal?.aborted) own.abort();
		else o.signal?.addEventListener("abort", forward, { once: true });
		const timer =
			o.timeoutMs === undefined
				? undefined
				: setTimeout(() => {
						timedOut = true;
						own.abort();
					}, o.timeoutMs);
		try {
			choice = await ui.select(o.title, o.options, {
				signal: own.signal,
				...(o.timeoutMs === undefined ? {} : { timeout: o.timeoutMs + BACKSTOP_MS }),
			});
		} catch {
			error = true;
		} finally {
			if (timer !== undefined) clearTimeout(timer);
			o.signal?.removeEventListener("abort", forward);
		}
		if (choice !== VIEW_FULL || o.signal?.aborted || !o.viewFull) break;
		try {
			// 読むだけ (変更しても反映されない)。先頭から表示するビューアで開き (pi の editor は末尾にカーソルを置くので末尾から見える)、閉じると確認に戻る
			if (typeof ui.custom === "function") await showTextViewer(ui, o.viewFull.title, o.viewFull.text());
			else await ui.editor(o.viewFull.title, o.viewFull.text());
		} catch {
			// 表示できなくても、確認に戻る
		}
	}
	return { choice, timedOut, error };
}

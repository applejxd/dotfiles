// 素の pi (ハーネス無し) 向けの補助: bash の `git commit` の前に、件名と本文を見せて確認する。
// 保護ではない (別名・sh -c などの経路は検出しない)。ハーネス (pis) は同じ確認を自前で持つので -ne で外れる。
// see docs/spec/pi-harness.md#commit-の確認-素の-pi
import { pathToFileURL } from "node:url";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
// 応えないクライアント (RPC) で永久に待たないよう、TUI 以外は期限を付ける (期限が来たら拒否)
const TIMEOUT_MS = 5 * 60 * 1000;
// コマンドの先頭にある `git commit` (git -C dir commit のようにオプションが挟まる形も)
const COMMIT = /(^|[;&|(\n])\s*git(\s+-\S+(\s+[^\s-]\S*)?)*\s+commit(\s|$)/;
const OPTIONS = { line_width: 72, max_lines: 8 };

type Preview = { subject: string; body: string[]; extra: string | null; added: string | null };

export default async function (pi: any) {
	let commitPreview: ((command: string, opts: unknown) => Preview | null) | null = null;
	try {
		// 件名・本文の取り出しは OpenCode の guide plugin と同じ純関数。読めなければ件名なしで確認だけ出す
		const url = pathToFileURL(join(HERE, "..", "..", "opencode", "guide-plugin", "commit-message.js")).href;
		commitPreview = (await import(url)).commitPreview;
	} catch {}

	// 確認は 1 件ずつ (TUI の confirm は 1 枠を共有し、後の確認が先の確認を置き換える)
	let queue: Promise<unknown> = Promise.resolve();

	pi.on("tool_call", async (event: any, ctx: any) => {
		if (event.toolName !== "bash") return;
		const command = String(event.input?.command ?? "");
		if (!COMMIT.test(command)) return;
		let text = command;
		try {
			const p = commitPreview?.(command, OPTIONS);
			if (p) {
				const lines = [`件名: ${p.subject}`, ...p.body.map((l) => `  ${l}`)];
				if (p.extra) lines.push(p.extra);
				if (p.added) lines.push(p.added);
				text = `${command}\n\n${lines.join("\n")}`;
			}
		} catch {}
		if (!ctx.hasUI) return { block: true, reason: "git commit は確認が要るが、確認できる画面が無い" };
		const timeout = ctx.mode === "tui" ? undefined : TIMEOUT_MS;
		const run = queue.then(() =>
			ctx.signal?.aborted ? false : ctx.ui.confirm("git commit を実行しますか？", text, { signal: ctx.signal, timeout }),
		);
		queue = run.catch(() => undefined);
		const ok = await run.then((v: unknown) => v === true).catch(() => false);
		if (!ok) return { block: true, reason: "利用者が git commit を拒否した (または確認が時間切れ)" };
	});
}

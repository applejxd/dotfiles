// 計画モード。`/plan` で切り替える。計画中は、書き込み・実行のツール (edit / write / bash / MCP など) を
// モデルから外し、読むツールだけにする。フルガード (`pis`) の `guarded_` 付きのツールも同じ扱い。
// see docs/spec/guard/pi-extensions.md#自作の拡張-todo--plan--btw
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

// 計画中に残すツール (`guarded_` を外した名前)
const KEEP = new Set(["read", "grep", "find", "ls", "todo", "task", "ask"]);
const baseName = (n: string) => (n.startsWith("guarded_") ? n.slice("guarded_".length) : n);

type State = { enabled: boolean; saved?: string[] };

const PLAN_PROMPT = `[計画モード]
今は計画モードで、ファイルの編集・コマンドの実行はできない（ツールを外してある）。
読むツールで調べ、実行に移せる計画を番号付きの手順で示す。変更は行わない。
- 前提が曖昧なら、先に質問する
- 各手順には、触るファイルと確認の方法を書く
- 最後の応答は、番号付きの手順で終える`;

export default function (pi: ExtensionAPI) {
	let enabled = false;
	let saved: string[] | undefined;

	const apply = () => {
		if (!saved) saved = pi.getActiveTools();
		pi.setActiveTools(saved.filter((n) => KEEP.has(baseName(n))));
	};
	const restore = () => {
		if (saved) pi.setActiveTools(saved);
		saved = undefined;
	};
	const status = (ctx: ExtensionContext) => {
		if (ctx.hasUI) ctx.ui.setStatus("plan", enabled ? ctx.ui.theme.fg("warning", "⏸ plan") : undefined);
	};
	const persist = () => pi.appendEntry("plan-mode", { enabled, saved } satisfies State);
	const set = (on: boolean, ctx: ExtensionContext) => {
		enabled = on;
		if (on) apply();
		else restore();
		status(ctx);
		persist();
		ctx.ui.notify(on ? "計画モード: 書き込み・実行のツールを外した" : "計画モードを終えた: ツールを戻した", "info");
	};

	pi.registerCommand("plan", {
		description: "計画モードの切り替え (書き込み・実行のツールを外す)",
		handler: async (_args, ctx) => set(!enabled, ctx),
	});

	pi.on("session_start", async (_e, ctx) => {
		const last = ctx.sessionManager
			.getEntries()
			.filter((e: { type: string; customType?: string }) => e.type === "custom" && e.customType === "plan-mode")
			.pop() as { data?: State } | undefined;
		enabled = last?.data?.enabled ?? false;
		saved = last?.data?.saved;
		if (enabled) apply();
		status(ctx);
	});

	pi.on("before_agent_start", async () => {
		if (!enabled) return undefined;
		return { message: { customType: "plan-mode-context", content: PLAN_PROMPT, display: false } };
	});

	// 計画モードを終えたあとに、古い指示が残らないようにする
	pi.on("context", async (event) => {
		if (enabled) return undefined;
		return { messages: event.messages.filter((m) => (m as { customType?: string }).customType !== "plan-mode-context") };
	});

	pi.on("agent_end", async (event, ctx) => {
		if (!enabled || !ctx.hasUI) return;
		const last = [...event.messages].reverse().find((m) => m.role === "assistant");
		const text = Array.isArray(last?.content)
			? last.content.map((b: { type: string; text?: string }) => (b.type === "text" ? b.text ?? "" : "")).join("\n")
			: "";
		if (!/^\s*\d+[.)]\s/m.test(text)) return; // 質問だけの応答では聞かない
		const choice = await ctx.ui.select("計画をどうしますか？", ["実行する", "計画のまま続ける", "計画を直す"]);
		if (choice === "実行する") {
			set(false, ctx);
			pi.sendUserMessage("上の計画を実行して。進捗は todo ツールで管理する。", { deliverAs: "followUp" });
		} else if (choice === "計画を直す") {
			const edit = await ctx.ui.editor("計画への指摘:", "");
			if (edit?.trim()) pi.sendUserMessage(edit.trim(), { deliverAs: "followUp" });
		}
	});
}

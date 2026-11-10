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
読むツールで調べ、利用者と対話して計画を詰める。変更は行わない。
- 前提が曖昧なら、先に質問する
- 計画が十分に詰まり、実行に移せると判断したときだけ、最後に「## 実行計画」の見出しをつけて、番号付きの手順を示す。各手順には、触るファイルと確認の方法を書く（この見出しがあるときだけ、利用者に「実行する」の確認画面が出る）
- それ以外の応答（質問・調査の途中・論点の整理）は、「## 実行計画」の見出しを使わない。毎回の応答では確認を求めない`;

// 応答が「実行に移せる計画」を示しているか。見出し「## 実行計画」と番号付きの手順の両方があるときだけ、確認の画面を出す
// （番号付きの行だけでは出さない。相談の途中の応答で毎回聞かれるのを避ける。試験: test/agents/test_pi_plan_ready.py）
export const isPlanReady = (text: string): boolean => /^#{1,3}\s*実行計画/m.test(text) && /^\s*\d+[.)]\s/m.test(text);

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
	// フルガードの guarded_task が見る印。計画の間は、書き込みの権限を持つ役割の子を起動・続行させない (CHG-0044)
	const publish = () => {
		(globalThis as any).__piPlanMode = enabled;
	};
	// 計画モードの前から動いている、書き込みの権限を持つ子 (止めはしない。利用者へ知らせるだけ)
	const runningWriters = (): string[] => {
		const g = globalThis as { __piChildren?: Map<string, { agent: string }>; __piReadOnlyAgents?: Set<string> };
		const readOnly = g.__piReadOnlyAgents;
		if (!readOnly || !g.__piChildren) return [];
		return [...new Set([...g.__piChildren.values()].map((c) => c.agent).filter((a) => !readOnly.has(a)))];
	};
	const set = (on: boolean, ctx: ExtensionContext) => {
		enabled = on;
		if (on) apply();
		else restore();
		publish();
		status(ctx);
		persist();
		ctx.ui.notify(on ? "計画モード: 書き込み・実行のツールを外した。子は読み取り専用の役割だけ" : "計画モードを終えた: ツールを戻した", "info");
		const writers = on ? runningWriters() : [];
		if (writers.length > 0) ctx.ui.notify(`計画モードの前から動いている子があります (${writers.join(", ")})。止めるには guarded_task の abort / close`, "warning");
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
		publish();
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
		if (!isPlanReady(text)) return; // 計画が詰まったと判断した応答（見出し「## 実行計画」つき）だけ聞く
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

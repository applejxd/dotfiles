// `/btw <質問>`: いまの会話を文脈にした「ついでの質問」に、現在のモデルが答える。
// ツールは使わず、答えは会話履歴にもモデルの文脈にも残さない (表示するだけ)。
// 応答中 (エージェントが動いている最中) でも実行できる。
// see docs/spec/pi-harness.md#自作の拡張-todo--plan--btw
import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { DynamicBorder, getMarkdownTheme } from "@earendil-works/pi-coding-agent";
import { Container, Markdown, matchesKey, Text } from "@earendil-works/pi-tui";

// 会話の引用に使う上限 (新しい側を残す)。モデルの文脈窓を超えないための安全弁
const MAX_CONVERSATION_CHARS = 60000;
const MAX_TOOL_ARGS_CHARS = 200;

const SYSTEM_PROMPT = `あなたは、作業中のコーディングエージェントのセッションを横から見ている助手。
<conversation> はそこまでの会話の写し。利用者の「ついでの質問」に、その内容を踏まえて簡潔に答える。
- ツールは使えない。ファイルや環境は見られないので、会話に無いことは推測だと断る
- 会話の作業を進めたり、続きを実行したりしない (質問に答えるだけ)
- 利用者の言語で答える`;

type Block = { type?: string; text?: string; name?: string; arguments?: unknown };
type Entry = { type: string; message?: { role?: string; content?: unknown } };

function textOf(content: unknown): string {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	const parts: string[] = [];
	for (const raw of content) {
		const b = raw as Block;
		if (b?.type === "text" && typeof b.text === "string") parts.push(b.text);
		else if (b?.type === "toolCall" && typeof b.name === "string") {
			const args = JSON.stringify(b.arguments ?? {});
			parts.push(`[tool ${b.name} ${args.length > MAX_TOOL_ARGS_CHARS ? `${args.slice(0, MAX_TOOL_ARGS_CHARS)}…` : args}]`);
		}
	}
	return parts.join("\n");
}

function conversationOf(entries: Entry[]): string {
	const sections: string[] = [];
	for (const e of entries) {
		const role = e.message?.role;
		if (e.type !== "message" || (role !== "user" && role !== "assistant")) continue;
		const text = textOf(e.message?.content).trim();
		if (text) sections.push(`${role === "user" ? "User" : "Assistant"}: ${text}`);
	}
	const all = sections.join("\n\n");
	return all.length > MAX_CONVERSATION_CHARS ? `…(古い部分は省略)\n${all.slice(-MAX_CONVERSATION_CHARS)}` : all;
}

async function show(title: string, body: string, ctx: ExtensionCommandContext) {
	if (ctx.mode !== "tui") {
		ctx.ui.notify(`${title}\n${body}`, "info");
		return;
	}
	await ctx.ui.custom((_tui, theme, _kb, done) => {
		const container = new Container();
		const border = new DynamicBorder((s: string) => theme.fg("accent", s));
		container.addChild(border);
		container.addChild(new Text(theme.fg("accent", theme.bold(title)), 1, 0));
		container.addChild(new Markdown(body, 1, 1, getMarkdownTheme()));
		container.addChild(new Text(theme.fg("dim", "Enter / Esc で閉じる"), 1, 0));
		container.addChild(border);
		return {
			render: (width: number) => container.render(width),
			invalidate: () => container.invalidate(),
			handleInput: (data: string) => {
				if (matchesKey(data, "enter") || matchesKey(data, "escape")) done(undefined);
			},
		};
	});
}

export default function (pi: ExtensionAPI) {
	pi.registerCommand("btw", {
		description: "いまの会話を踏まえた、ついでの質問 (履歴には残さない): /btw <質問>",
		handler: async (args, ctx) => {
			const question = (args ?? "").trim();
			if (!question) {
				ctx.ui.notify("使い方: /btw <質問>", "warning");
				return;
			}
			const model = ctx.model;
			if (!model) {
				ctx.ui.notify("モデルが選ばれていない", "warning");
				return;
			}
			if (!ctx.modelRegistry.hasConfiguredAuth(model)) {
				ctx.ui.notify(`${model.provider}/${model.id} の認証が未設定`, "warning");
				return;
			}

			const conversation = conversationOf(ctx.sessionManager.getBranch() as Entry[]);
			const prompt = [
				"<conversation>",
				conversation || "(まだ会話は無い)",
				"</conversation>",
				"",
				`ついでの質問: ${question}`,
			].join("\n");

			ctx.ui.notify("btw: 考え中…", "info");
			try {
				const response = await ctx.modelRegistry.complete(
					model,
					{
						systemPrompt: SYSTEM_PROMPT,
						messages: [{ role: "user" as const, content: [{ type: "text" as const, text: prompt }], timestamp: Date.now() }],
					},
					{ cacheRetention: "none" },
				);
				const answer = response.content
					.filter((c): c is { type: "text"; text: string } => c.type === "text")
					.map((c) => c.text)
					.join("\n")
					.trim();
				await show(`btw: ${question}`, answer || "(空の応答)", ctx);
			} catch (error) {
				ctx.ui.notify(`btw に失敗: ${error instanceof Error ? error.message : String(error)}`, "error");
			}
		},
	});
}

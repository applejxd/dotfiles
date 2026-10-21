// `/btw <質問>`: いまの会話を文脈にした「ついでの質問」に答える。
// 既定は、読み取り専用の子 (explore) がファイルを読んで確かめてから答える。`--plain` は、ツールなしで現在のモデルが答える。
// 答えは会話履歴にもモデルの文脈にも残さない (表示するだけ)。応答中 (エージェントが動いている最中) でも実行できる。
// 子の起動は、フルガード (harness) か Windows の subagents 拡張が `globalThis.__piAskReadChild` に置く入口を使う。無ければ `--plain` と同じ。
// see docs/spec/pi-guard.md#自作の拡張-todo--plan--btw
import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { DynamicBorder, getMarkdownTheme } from "@earendil-works/pi-coding-agent";
import { Container, Markdown, matchesKey, Text } from "@earendil-works/pi-tui";

// 会話の引用に使う上限 (新しい側を残す)。モデルの文脈窓を超えないための安全弁。
// 子へ渡すときは、Windows の引数長の上限 (32767) に収めるため短くする
const MAX_CONVERSATION_CHARS = 60000;
const MAX_CHILD_CONVERSATION_CHARS = 20000;
const MAX_TOOL_ARGS_CHARS = 200;
const CHILD_TIMEOUT_MS = 3 * 60 * 1000;

const SYSTEM_PROMPT = `あなたは、作業中のコーディングエージェントのセッションを横から見ている助手。
<conversation> はそこまでの会話の写し。利用者の「ついでの質問」に、その内容を踏まえて簡潔に答える。
- ツールは使えない。ファイルや環境は見られないので、会話に無いことは推測だと断る
- 会話の作業を進めたり、続きを実行したりしない (質問に答えるだけ)
- 利用者の言語で答える`;

// 子 (explore) は、自分の役割の指示を持つので、ここでは「ついでの質問」であることと答え方だけを伝える
const CHILD_TASK_HEADER = `これは作業中のエージェントのセッションを横から見ている利用者の「ついでの質問」です。
<conversation> はそこまでの会話の写し (古い部分は省略されていることがあります)。その内容を踏まえて簡潔に答えてください。
- 会話に無いことは、ファイルを読んで確かめてから答える。確かめられなかったことは推測だと断る
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

function conversationOf(entries: Entry[], max: number): string {
	const sections: string[] = [];
	for (const e of entries) {
		const role = e.message?.role;
		if (e.type !== "message" || (role !== "user" && role !== "assistant")) continue;
		const text = textOf(e.message?.content).trim();
		if (text) sections.push(`${role === "user" ? "User" : "Assistant"}: ${text}`);
	}
	const all = sections.join("\n\n");
	return all.length > max ? `…(古い部分は省略)\n${all.slice(-max)}` : all;
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
		description: "いまの会話を踏まえた、ついでの質問 (履歴には残さない)。既定はファイルを読んで確かめて答える: /btw [--plain] <質問>",
		handler: async (args, ctx) => {
			let question = (args ?? "").trim();
			// --plain: ツールなしで、現在のモデルが 1 回だけ答える (速い。ファイルは見ない)
			const plainFlag = /^--plain(\s|$)/.test(question);
			if (plainFlag) question = question.replace(/^--plain\s*/, "");
			if (!question) {
				ctx.ui.notify("使い方: /btw [--plain] <質問>", "warning");
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

			const entries = ctx.sessionManager.getBranch() as Entry[];

			// 既定: 読み取り専用の子 (explore)。入口が無いときや子が失敗したときは、ツールなしへ戻る
			const askChild = (globalThis as any).__piAskReadChild as
				| ((agent: string, task: string, ctx: unknown, signal?: AbortSignal) => Promise<{ ok: boolean; text: string }>)
				| undefined;
			let fallbackNote = "";
			if (!plainFlag && askChild) {
				const task = [
					CHILD_TASK_HEADER,
					"",
					"<conversation>",
					conversationOf(entries, MAX_CHILD_CONVERSATION_CHARS) || "(まだ会話は無い)",
					"</conversation>",
					"",
					`ついでの質問: ${question}`,
				].join("\n");
				ctx.ui.notify("btw: ファイルを読んで調べています… (速く答えるには --plain)", "info");
				// ctx.signal は本体の応答の中断で止まるものなので使わず、調査には独自の上限時間を置く
				const abort = new AbortController();
				const timer = setTimeout(() => abort.abort(), CHILD_TIMEOUT_MS);
				try {
					const r = await askChild("explore", task, ctx, abort.signal);
					if (r.ok) {
						await show(`btw: ${question}`, r.text, ctx);
						return;
					}
					fallbackNote = `explore が失敗したのでツールなしで答えます (${r.text.split("\n")[0].slice(0, 120)})`;
				} catch (error) {
					fallbackNote = `explore を起動できないのでツールなしで答えます (${error instanceof Error ? error.message : String(error)})`;
				} finally {
					clearTimeout(timer);
				}
				ctx.ui.notify(`btw: ${fallbackNote}`, "warning");
			}

			const conversation = conversationOf(entries, MAX_CONVERSATION_CHARS);
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

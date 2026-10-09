// 試験用。決まった tool call を返す偽のモデルと、/reload を起こすコマンド。
// see docs/spec/pi-harness.md
import { getCurrentSystemPrompt, getCurrentTools } from "@earendil-works/pi-ai";
import { type ExtensionAPI, getPackageDir } from "@earendil-works/pi-coding-agent";
import { rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

type Call = { name: string; args: Record<string, unknown> };

function textOf(content: unknown): string {
	if (!Array.isArray(content)) return String(content);
	return content.map((c: any) => (c?.type === "text" ? c.text : `[${c?.type}]`)).join("");
}

export default async function (pi: ExtensionAPI) {
	// pi-ai の faux は拡張から解決できる入口に無いので、同梱の実体を直接読む
	const fauxPath = join(getPackageDir(), "..", "pi-ai", "dist", "providers", "faux.js");
	const { createFauxCore, fauxAssistantMessage, fauxText, fauxToolCall } = await import(pathToFileURL(fauxPath).href);
	// 子エージェントとして起動されたら、子用の呼び出しを使う
	const source = process.env.PI_HARNESS_CHILD === "1" ? process.env.FAUX_CHILD_TOOL_CALLS : process.env.FAUX_TOOL_CALLS;
	const calls: Call[] = JSON.parse(source ?? "[]");
	const core = createFauxCore({ provider: "faux", models: [{ id: "spike" }] });
	const step = (context: any) => {
		const messages = context.messages;
		const last = messages[messages.length - 1];
		const tools = getCurrentTools(messages).map((t) => t.name).sort();
		// 圧縮の要約の依頼 (pi の要約の system prompt)。ハーネスの指示が入っているかも返す
		if (getCurrentSystemPrompt(messages).includes("context summarization assistant")) {
			const instr = JSON.stringify(messages).includes("【圧縮の指示】") ? "yes" : "no";
			return fauxAssistantMessage(fauxText(`SUMMARY INSTR=${instr}`));
		}
		// 利用者の発言をそのまま返す (プロンプトテンプレートの展開を見る)
		if (process.env.FAUX_ECHO_USER === "1" && last?.role === "user") {
			return fauxAssistantMessage(fauxText(`USER=${textOf(last.content)}`));
		}
		if (last?.role === "toolResult") {
			const results = messages
				.filter((m: any) => m.role === "toolResult")
				.slice(-calls.length)
				.map((m: any) => `${m.toolName}: isError=${m.isError} :: ${textOf(m.content).slice(0, 300)}`);
			return fauxAssistantMessage(fauxText(`TOOLS=${JSON.stringify(tools)}\n${results.join("\n")}`));
		}
		if (process.env.FAUX_DUMP_PROMPT === "1") return fauxAssistantMessage(fauxText(getCurrentSystemPrompt(messages)));
		if (calls.length === 0) return fauxAssistantMessage(fauxText(`TOOLS=${JSON.stringify(tools)}`));
		return fauxAssistantMessage(
			calls.map((c: Call) => fauxToolCall(c.name, c.args)),
			{ stopReason: "toolUse" },
		);
	};
	core.setResponses(Array.from({ length: 50 }, () => step));
	pi.registerProvider("faux", {
		baseUrl: "http://127.0.0.1:9",
		apiKey: "faux",
		api: core.api as any,
		streamSimple: core.streamSimple as any,
		models: [
			{
				id: "spike",
				name: "spike",
				reasoning: false,
				input: ["text"],
				cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
				contextWindow: 100000,
				maxTokens: 4096,
			},
		],
	});

	pi.registerCommand("spike-reload", {
		description: "壊す・消す操作をしてから /reload する（SPIKE_BREAK_MODE=syntax|delete）",
		handler: async (_args, ctx) => {
			const file = process.env.SPIKE_BREAK_FILE;
			if (file) {
				if (process.env.SPIKE_BREAK_MODE === "delete") rmSync(file);
				else writeFileSync(file, "export default function (pi) { this is not javascript\n");
			}
			await ctx.reload();
		},
	});
}

// 試験用。決まった tool call を返す偽のモデルと、/reload を起こすコマンド。
// see docs/spec/pi-guard.md
import { getCurrentSystemPrompt, getCurrentTools } from "@earendil-works/pi-ai";
import { type ExtensionAPI, getPackageDir } from "@earendil-works/pi-coding-agent";
import { existsSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

type Call = { name: string; args: Record<string, unknown> };

function textOf(content: unknown): string {
	if (!Array.isArray(content)) return String(content);
	return content.map((c: any) => (c?.type === "text" ? c.text : `[${c?.type}]`)).join("");
}

export default async function (pi: ExtensionAPI) {
	// pi-ai の faux は拡張から解決できる入口に無いので、同梱の実体を直接読む
	// 並び (mise / Unix) か、npm の global (Windows) の入れ子の並びのどちらか
	const piAi = [
		join(getPackageDir(), "..", "pi-ai"),
		join(getPackageDir(), "node_modules", "@earendil-works", "pi-ai"),
	].find((dir) => existsSync(join(dir, "dist", "providers", "faux.js")));
	if (!piAi) throw new Error("pi-ai の faux が見つからない");
	const fauxPath = join(piAi, "dist", "providers", "faux.js");
	const { createFauxCore, fauxAssistantMessage, fauxText, fauxToolCall } = await import(pathToFileURL(fauxPath).href);
	// 子エージェントとして起動されたら、子用の呼び出しを使う
	const source = process.env.PI_HARNESS_CHILD === "1" ? process.env.FAUX_CHILD_TOOL_CALLS : process.env.FAUX_TOOL_CALLS;
	const calls: Call[] = JSON.parse(source ?? "[]");
	// 親の複数ターン (試験用)。各ターンの呼び出しの一覧。引数の {{JOB}} は直前の結果の jobId に置き換える
	const rounds: Call[][] | null = process.env.FAUX_TOOL_ROUNDS && process.env.PI_HARNESS_CHILD !== "1" ? JSON.parse(process.env.FAUX_TOOL_ROUNDS) : null;
	const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
	const jobIn = (messages: any[]) => {
		for (const m of [...messages].reverse()) {
			const hit = m.role === "toolResult" ? /job-[0-9a-f]{16}/.exec(textOf(m.content)) : null;
			if (hit) return hit[0];
		}
		return "job-missing";
	};
	const core = createFauxCore({ provider: "faux", models: [{ id: "spike" }] });
	const step = async (context: any) => {
		const messages = context.messages;
		const last = messages[messages.length - 1];
		const tools = getCurrentTools(messages).map((t) => t.name).sort();
		// 圧縮の要約の依頼 (pi の要約の system prompt)。フルガードの指示が入っているかも返す
		if (getCurrentSystemPrompt(messages).includes("context summarization assistant")) {
			const instr = JSON.stringify(messages).includes("【圧縮の指示】") ? "yes" : "no";
			return fauxAssistantMessage(fauxText(`SUMMARY INSTR=${instr}`));
		}
		// 利用者の発言をそのまま返す (プロンプトテンプレートの展開を見る)
		if (process.env.FAUX_ECHO_USER === "1" && last?.role === "user") {
			return fauxAssistantMessage(fauxText(`USER=${textOf(last.content)}`));
		}
		// 子: 履歴にある利用者の発言の数を返す (履歴が続いているかを見る)。FAUX_DELAY_MS で遅らせる
		if (process.env.FAUX_COUNT_USER === "1" && process.env.PI_HARNESS_CHILD === "1" && last?.role === "user") {
			if (process.env.FAUX_DELAY_MS) await sleep(Number(process.env.FAUX_DELAY_MS));
			return fauxAssistantMessage(fauxText(`USERS=${messages.filter((m: any) => m.role === "user").length}`));
		}
		if (rounds) {
			const issued = messages.filter((m: any) => m.role === "assistant" && Array.isArray(m.content) && m.content.some((c: any) => c.type === "toolCall")).length;
			if (issued < rounds.length) {
				const job = jobIn(messages);
				const next = rounds[issued].map((c) => ({ name: c.name, args: JSON.parse(JSON.stringify(c.args).replaceAll("{{JOB}}", job)) }));
				return fauxAssistantMessage(
					next.map((c) => fauxToolCall(c.name, c.args)),
					{ stopReason: "toolUse" },
				);
			}
			const all = messages
				.filter((m: any) => m.role === "toolResult")
				.map((m: any) => `${m.toolName}: isError=${m.isError} :: ${textOf(m.content).slice(0, 400)}`);
			return fauxAssistantMessage(fauxText(`TOOLS=${JSON.stringify(tools)}\n${all.join("\n--\n")}`));
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

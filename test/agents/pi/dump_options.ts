// 試験専用。before_agent_start の event.systemPromptOptions の形を観測する (子の文脈の受け渡しの調査。CHG-0059 S0 / S4 前提の測定)。
// DUMP_OPTIONS_FILE: 書き出すパス (JSON)。キー一覧と、各値の形 (型・長さ・要素のキー・path 風の文字列) だけを書く。本文は書かない。
// DUMP_OPTIONS_MUTATE: "<キー>:<操作>[:<マーカー>]"。操作は drop (要素を空に) / replace (本文を差し替え) / first (先頭の 1 件だけ残す)
//   / add (配列の末尾へ {path, content: マーカー} を足す)。
//   要素の本文は content / text の文字列のキーを差し替える。最終の prompt への反映は faux の FAUX_DUMP_PROMPT で見る。
// 複数の拡張として読むとき (同じファイルを別名のコピーにして -e を 2 回): 拡張の名前 = ファイル名の拡張子なし。
//   DUMP_OPTIONS_MUTATE__<名前> / DUMP_OPTIONS_RETURN_PROMPT__<名前> が、名前つきの指定 (無ければ名前なしの指定)。
// DUMP_OPTIONS_RETURN_PROMPT: 設定すると、ハンドラが {systemPrompt: <その値>} を返す。
// DUMP_OPTIONS_CALLS_FILE: 呼び出しごとの観測 (JSON 行) を追記するパス。本文は書かず、contextFiles は path・長さ・先頭 24 字だけ。
//   before_agent_start (書き換え前と後) と turn_start (ctx.getSystemPrompt() の長さと、DUMP_OPTIONS_WATCH の有無) を書く。
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { appendFileSync } from "node:fs";
import { basename } from "node:path";
import { fileURLToPath } from "node:url";

function shape(v: unknown): unknown {
	if (typeof v === "string") return { type: "string", length: v.length };
	if (Array.isArray(v)) return { type: "array", length: v.length, items: v.slice(0, 20).map(shape) };
	if (v && typeof v === "object") {
		const out: Record<string, unknown> = {};
		for (const [k, x] of Object.entries(v)) out[k] = shape(x);
		return { type: "object", keys: out };
	}
	return { type: typeof v, value: typeof v === "boolean" || typeof v === "number" ? v : undefined };
}

function ctxFiles(options: any): unknown {
	const files = options?.contextFiles;
	if (!Array.isArray(files)) return null;
	return files.map((f: any) => ({
		path: String(f?.path ?? ""),
		length: String(f?.content ?? "").length,
		head: String(f?.content ?? "").slice(0, 24),
	}));
}

export default function (pi: ExtensionAPI) {
	const name = basename(fileURLToPath(import.meta.url)).replace(/\.ts$/, "");
	const pick = (key: string) => process.env[`${key}__${name}`] ?? process.env[key];
	let seq = 0;
	const log = (rec: Record<string, unknown>) => {
		const file = process.env.DUMP_OPTIONS_CALLS_FILE;
		if (file) appendFileSync(file, `${JSON.stringify({ ext: name, ...rec })}\n`, "utf-8");
	};
	pi.on("turn_start", async (_event: any, ctx: any) => {
		if (!process.env.DUMP_OPTIONS_CALLS_FILE) return;
		const prompt = String(ctx?.getSystemPrompt?.() ?? "");
		const watch = process.env.DUMP_OPTIONS_WATCH;
		log({ ev: "turn_start", promptLength: prompt.length, watch: watch ? prompt.includes(watch) : null });
	});
	pi.on("before_provider_request", async (event: any) => {
		if (!process.env.DUMP_OPTIONS_CALLS_FILE) return;
		const watch = process.env.DUMP_OPTIONS_WATCH;
		let text = "";
		try {
			text = JSON.stringify(event?.payload ?? null) ?? "";
		} catch {}
		log({ ev: "before_provider_request", keys: Object.keys(event ?? {}).sort(), payloadLength: text.length, watch: watch ? text.includes(watch) : null });
	});
	pi.on("before_agent_start", async (event: any) => {
		const options = event.systemPromptOptions;
		seq += 1;
		const file = process.env.DUMP_OPTIONS_FILE;
		if (file) {
			const info = {
				eventKeys: Object.keys(event).sort(),
				optionKeys: options ? Object.keys(options).sort() : null,
				options: options ? shape(options) : null,
				systemPromptLength: String(event.systemPrompt ?? "").length,
			};
			appendFileSync(file, `${JSON.stringify(info)}\n`, "utf-8");
		}
		const watch = process.env.DUMP_OPTIONS_WATCH;
		const before = ctxFiles(options);
		const beforePrompt = String(event.systemPrompt ?? "");
		const spec = pick("DUMP_OPTIONS_MUTATE");
		const returnPrompt = pick("DUMP_OPTIONS_RETURN_PROMPT");
		let result: { systemPrompt: string } | undefined;
		if (spec && options) {
			const [key, op, marker = "MUTATED_BY_HANDLER"] = spec.split(":");
			const cur = options[key];
			if (cur !== undefined) {
				const swap = (item: any) => {
					if (typeof item === "string") return marker;
					if (item && typeof item === "object") {
						const copy = { ...item };
						for (const f of ["content", "text"]) if (typeof copy[f] === "string") copy[f] = marker;
						return copy;
					}
					return item;
				};
				if (op === "drop") options[key] = Array.isArray(cur) ? [] : "";
				else if (op === "first") options[key] = Array.isArray(cur) ? cur.slice(0, 1) : cur;
				else if (op === "replace") options[key] = Array.isArray(cur) ? cur.map(swap) : swap(cur);
				else if (op === "add" && Array.isArray(cur)) cur.push({ path: `/virtual/${marker}.md`, content: marker });
			}
		}
		if (returnPrompt !== undefined) result = { systemPrompt: returnPrompt };
		log({
			ev: "before_agent_start",
			seq,
			before,
			after: ctxFiles(options),
			eventPromptLength: beforePrompt.length,
			eventPromptHasWatch: watch ? beforePrompt.includes(watch) : null,
			returned: result ? "systemPrompt" : null,
		});
		return result;
	});
}

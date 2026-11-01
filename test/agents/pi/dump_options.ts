// 試験専用。before_agent_start の event.systemPromptOptions の形を観測する (子の文脈の受け渡しの調査。CHG-0059 S0)。
// DUMP_OPTIONS_FILE: 書き出すパス (JSON)。キー一覧と、各値の形 (型・長さ・要素のキー・path 風の文字列) だけを書く。本文は書かない。
// DUMP_OPTIONS_MUTATE: "<キー>:<操作>[:<マーカー>]"。操作は drop (要素を空に) / replace (本文を差し替え) / first (先頭の 1 件だけ残す)。
//   要素の本文は content / text の文字列のキーを差し替える。最終の prompt への反映は faux の FAUX_DUMP_PROMPT で見る。
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { appendFileSync } from "node:fs";

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

export default function (pi: ExtensionAPI) {
	pi.on("before_agent_start", async (event: any) => {
		const options = event.systemPromptOptions;
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
		const spec = process.env.DUMP_OPTIONS_MUTATE;
		if (!spec || !options) return;
		const [key, op, marker = "MUTATED_BY_HANDLER"] = spec.split(":");
		const cur = options[key];
		if (cur === undefined) return;
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
	});
}

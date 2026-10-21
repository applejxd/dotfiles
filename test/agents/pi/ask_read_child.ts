// 試験用。`globalThis.__piAskReadChild` (btw が使う、読み取り専用の子の入口) を直接呼ぶコマンド。
// `/askchild <役割> <依頼>`。結果は ASKCHILD ok=<真偽> <本文> の 1 行で出す。
// see docs/spec/pi-guard.md#自作の拡張-todo--plan--btw
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
	// 試験だけ: 入口を差し替えて、btw が渡す役割と依頼文を記録する (先に読まれるフルガードの入口を上書きする)
	if (process.env.ASKCHILD_STUB === "1") {
		(globalThis as any).__piAskReadChild = async (agent: string, task: string) => {
			console.log(`STUB agent=${agent} task=${task.replaceAll("\n", " | ")}`);
			return { ok: true, text: "stub-answer" };
		};
	}
	pi.registerCommand("askchild", {
		description: "試験用: 読み取り専用の子の入口を呼ぶ",
		handler: async (args, ctx) => {
			const m = /^(\S+)\s+([\s\S]+)$/.exec(String(args ?? "").trim());
			const ask = (globalThis as any).__piAskReadChild;
			if (!m || !ask) {
				console.log("ASKCHILD missing");
				return;
			}
			const r = await ask(m[1], m[2], ctx);
			console.log(`ASKCHILD ok=${r.ok} ${String(r.text).replaceAll("\n", " | ")}`);
		},
	});
}

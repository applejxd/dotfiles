// 試験用。圧縮を起こして終わるまで待つコマンド。引数は /compact の引数 (利用者が指定する焦点) として渡す。
// see docs/spec/pi-guard.md
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
	pi.registerCommand("spike-compact", {
		description: "圧縮を起こして終わるまで待つ",
		handler: async (args, ctx) => {
			await new Promise<void>((resolve) => {
				ctx.compact({
					customInstructions: args?.trim() || undefined,
					onComplete: () => resolve(),
					onError: (error) => {
						console.error(`compaction failed: ${error.message}`);
						resolve();
					},
				});
			});
		},
	});
}

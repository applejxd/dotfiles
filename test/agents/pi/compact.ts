// 試験用。圧縮を起こして終わるまで待つコマンド。
// see docs/spec/pi-harness.md
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
	pi.registerCommand("spike-compact", {
		description: "圧縮を起こして終わるまで待つ",
		handler: async (_args, ctx) => {
			await new Promise<void>((resolve) => {
				ctx.compact({
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

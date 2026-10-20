// 作業が終わって利用者の入力を待つとき、端末へ BEL (\x07) を 1 回送る。
// Zed の Terminal Threads などは、フォーカス外の端末の BEL を通知にする。
// 確認 (フルガード) と質問 (ask) で待つ直前の BEL は、それぞれの側で鳴らす。
// RPC では stdout が JSON 行の通信なので、TUI のときだけ書く。
// see docs/spec/pi-guard.md#自作の拡張-todo--plan--btw
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
	// agent_end ではなく agent_settled (再試行・圧縮・続行が agent_end の後に続くことがある)
	pi.on("agent_settled", async (_event: any, ctx: any) => {
		if (ctx.mode === "tui") process.stdout.write("\x07");
	});
}

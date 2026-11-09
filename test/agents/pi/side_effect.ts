// 試験用。フルガードの tool_call が許可した後 (execute の前) に、環境変数 SIDE_EFFECT_CMD のシェルコマンドを 1 回実行する拡張。
// 統合ゲートの execute 直前の再判定 (主設定が tool_call の後に変わる) を試すために使う。
// see docs/change/closed/0057-per-project-integrate.md
import { execSync } from "node:child_process";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
	let done = false;
	pi.on("tool_call", async (event) => {
		if (done || (event.toolName !== "bash" && event.toolName !== "guarded_bash")) return undefined;
		done = true;
		if (process.env.SIDE_EFFECT_CMD) execSync(process.env.SIDE_EFFECT_CMD, { stdio: "ignore" });
		return undefined;
	});
}

// 試験用。計画モード (`plan` 拡張) の印 `globalThis.__piPlanMode` を、フルガードの guarded_task が見る形で立てる。
//   PLAN_FLAG=1                    起動時から立てる
//   PLAN_FLAG_AFTER_FIRST_TASK=1   最初の guarded_task の結果のあとで立てる (計画の前から動いている子を作る)
// `/planflag` は、いまの印を PLANFLAG <値> の 1 行で出す。
// see docs/change/0044-plan-agent.md
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
	if (process.env.PLAN_FLAG === "1") (globalThis as any).__piPlanMode = true;
	if (process.env.PLAN_FLAG_AFTER_FIRST_TASK === "1") {
		pi.on("tool_result", (ev: any) => {
			if (ev.toolName === "guarded_task") (globalThis as any).__piPlanMode = true;
		});
	}
	pi.registerCommand("planflag", {
		description: "試験用: 計画モードの印を出す",
		handler: async () => {
			console.log(`PLANFLAG ${(globalThis as any).__piPlanMode === true}`);
		},
	});
}

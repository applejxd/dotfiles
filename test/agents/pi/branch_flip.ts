// 試験用。フルガードの tool_call が許可した後 (execute の前) に、本体の HEAD を別のブランチへ切り替える拡張。
// 入力は変えない (同じ入力でキャッシュが命中する状況を作る)。
// see docs/spec/guard/pi-gitflow-guard.md
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { execFileSync } from "node:child_process";

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", async (event) => {
		const repo = process.env.FLIP_REPO;
		const to = process.env.FLIP_TO;
		if (repo && to && (event.toolName === "write" || event.toolName === "guarded_write")) {
			execFileSync("git", ["switch", "-q", to], { cwd: repo, env: { ...process.env, GIT_CONFIG_GLOBAL: "/dev/null" } });
		}
		return undefined;
	});
}

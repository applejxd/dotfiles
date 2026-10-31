// integration-gate.ts の試験用の実行器。標準入力の JSON を読み、結果を JSON で出す。
//
//   {"cases": [{"d": {decision, reason, source, mustConfirm?}, "tool": "bash", "input": {...}, "cwd": "...", "enabled": true?, "protected": [...]?}],
//    "env": {...}?}      → tightenIntegration の結果の配列
//   {"config": <judge.common>}   → integrationConfig の結果
//
// env を渡すと、自由区の判定の git に渡す環境を置き換える (偽の git で起動回数を数える試験用)。
// see docs/change/0053-worktree-integration-gate.md
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const harness = (name) => pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", name)).href;

const { integrationConfig, tightenIntegration } = await import(harness("integration-gate.ts"));
const { classifyFreeZone } = await import(harness("freezone.ts"));

const req = JSON.parse(readFileSync(0, "utf8"));
let result;
if (req.config !== undefined) {
	result = integrationConfig(req.config);
} else {
	const classify = (cwd, refs) => classifyFreeZone(cwd, refs, { env: req.env });
	result = req.cases.map((c) => {
		const cfg = { enabled: c.enabled ?? true, protectedRefs: c.protected ?? ["main", "master", "develop", "release/*", "hotfix/*"] };
		return tightenIntegration(c.d, c.tool ?? "bash", c.input, c.cwd, cfg, { classify });
	});
}
process.stdout.write(JSON.stringify(result));

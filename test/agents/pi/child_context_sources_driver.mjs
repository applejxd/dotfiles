// 正本 (agent-instructions.md・AGENTS.md) に child-context.ts の resolveContext / lint を当て、結果を JSON で標準出力へ出す。
// 照合は test_child_context_sources.py。
//
//   node test/agents/pi/child_context_sources_driver.mjs
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const mod = await import(pathToFileURL(join(ROOT, "home", "dot_config", "pi", "harness", "child-context.ts")).href);
const { resolveContext, lint } = mod;

const FILES = { global: "home/.chezmoitemplates/agent-instructions.md", repo: "AGENTS.md" };
const ROLES = ["explore", "review", "plan", "worker"];

const out = {};
for (const [key, rel] of Object.entries(FILES)) {
	const text = readFileSync(join(ROOT, rel), "utf-8");
	const extract = {};
	for (const role of ROLES) extract[role] = resolveContext(text, role, "extract");
	out[key] = { lint: lint(text), extract, inherit: resolveContext(text, "worker", "inherit") };
}
console.log(JSON.stringify(out));

// platform.ts と tools-ext.ts のパス展開の試験。引数: JSON の {op, ...}。結果を JSON で標準出力へ出す (照合は test_pi_platform.py)。
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const dir = resolve(ROOT, "home", "dot_config", "pi", "harness");
const plat = await import(pathToFileURL(resolve(dir, "platform.ts")).href);
const req = JSON.parse(process.argv[2]);
let out;
if (req.op === "findBash") {
	const present = new Set(req.exists.map((p) => p.toLowerCase()));
	out = plat.findBash(req.platform, req.env, (p) => present.has(p.toLowerCase()));
} else if (req.op === "supportsChildTasks") {
	out = plat.supportsChildTasks(req.platform);
} else if (req.op === "expandTilde") {
	out = plat.expandTilde(req.path, req.home);
} else if (req.op === "resolveInputPath") {
	const tools = await import(pathToFileURL(resolve(dir, "tools-ext.ts")).href);
	out = tools.resolveInputPath(req.path, req.cwd, req.home);
} else {
	throw new Error(`unknown op ${req.op}`);
}
console.log(JSON.stringify(out));

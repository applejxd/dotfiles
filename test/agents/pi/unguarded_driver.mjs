// unguarded.ts の試験。引数: JSON の {agentDir, cwd, argv}。結果を JSON で標準出力へ出す (照合は test_pi_unguarded.py)。
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const mod = await import(pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "unguarded.ts")).href);
const { agentDir, cwd, argv } = JSON.parse(process.argv[2]);
const found = mod.unguardedSources(agentDir, cwd, argv);
console.log(JSON.stringify({ found, message: found.length ? mod.unguardedMessage(found) : "" }));

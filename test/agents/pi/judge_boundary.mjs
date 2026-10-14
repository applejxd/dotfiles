// 試験用。標準入力の JSON ({ requests: [...] }) を判定器 (TS 版) に通し、応答の配列を標準出力へ出す。
//   node test/agents/pi/judge_boundary.mjs < requests.json
// サンドボックスの内側 (boundary / allowed) の緩和を、正解データ (Python 版) とは別に試すための口。
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const GOLDEN = resolve(ROOT, "test", "agents", "golden");
const JUDGE = resolve(ROOT, "home", "dot_config", "pi", "harness", "judge");
const { decide, setBashDecider } = await import(pathToFileURL(resolve(JUDGE, "decide.ts")).href);
const { makeBashDecider } = await import(pathToFileURL(resolve(JUDGE, "bash.ts")).href);
setBashDecider(makeBashDecider(JSON.parse(readFileSync(resolve(GOLDEN, "tables.json"), "utf8"))));
const common = JSON.parse(readFileSync(resolve(GOLDEN, "common.json"), "utf8"));
const { requests } = JSON.parse(readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(requests.map((r) => decide(r, common))));

// 判定器の構文解析 (judge/syntax.ts) の診断。  node judge/doctor.mjs  (終了コード 0 = OK、1 = NG)
// 実行環境・同梱の mvdan-sh の sha256・自己診断の結果・読み込みと解析の時間・メモリの増分を出す。
// node は型除去に対応した版 (22.18 以上。それ未満は --experimental-strip-types を付ける)。
// see docs/spec/guard/pi-extensions.md#確認画面の手順の一覧
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const HINT = "対処: `pis` の外のシェルで `chezmoi apply`";
const v = process.versions;
console.log(`実行環境: ${v.bun ? `bun ${v.bun} (JavaScriptCore)` : `node ${v.node} (V8)`} / ${process.platform}-${process.arch}`);

function ng(why) {
	console.log(`NG: ${why}`);
	console.log(HINT);
	process.exit(1);
}

let syn;
try {
	syn = await import(pathToFileURL(join(HERE, "syntax.ts")).href);
} catch (e) {
	ng(`syntax.ts を読み込めない: ${e instanceof Error ? e.message : e}`);
}

const dir = syn.defaultVendorDir();
let actual = "(読めない)";
try {
	actual = createHash("sha256").update(readFileSync(join(dir, "index.js"))).digest("hex");
} catch {}
console.log(`vendor: ${dir}`);
console.log(`sha256: ${actual}${actual === syn.MVDAN_SHA256 ? " (期待値と一致)" : ` (期待値 ${syn.MVDAN_SHA256} と不一致)`}`);

const rss0 = process.memoryUsage().rss;
const t0 = performance.now();
const loaded = syn.loadSyntax();
const t1 = performance.now();
const diag = syn.selfDiagnose();
const t2 = performance.now();
const rssMB = Math.round((process.memoryUsage().rss - rss0) / 1048576);
console.log(`読み込み: ${Math.round(t1 - t0)} ms / 自己診断 (解析 3 件): ${Math.round(t2 - t1)} ms / メモリ増分 (rss): ${rssMB} MB`);

if (!loaded.ok) ng(loaded.why);
if (!diag.ok) ng(diag.why);
console.log(`OK: ${diag.why}`);

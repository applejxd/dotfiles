// judge/syntax.ts の試験用の入口。vendor のディレクトリを引数で注入して、読み込み・解析・自己診断の結果を JSON で標準出力へ出す。
//
//   node test/agents/pi/syntax_driver.mjs <vendor/mvdan-sh のディレクトリ>
//
// see docs/spec/guard/pi-extensions.md#確認画面の手順の一覧
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const syn = await import(pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "judge", "syntax.ts")).href);

const dir = process.argv[2];
const load = syn.loadSyntax(dir);
const parsed = syn.parseSource("echo 日本語 && ls", dir);
console.log(
	JSON.stringify({
		load: { ok: load.ok, why: load.why ?? "" },
		parse: { ok: parsed.ok, why: parsed.why ?? "", stmts: parsed.ok ? syn.arr(parsed.src.file.Stmts).length : -1 },
		diag: syn.selfDiagnose(dir),
		globalRequireLeaked: typeof globalThis.require !== "undefined",
	}),
);

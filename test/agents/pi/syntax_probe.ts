// 試験用。実際の pi の中 (pi の runtime) で judge/syntax.ts を読み込んで解析できることを確かめる拡張。
// SYNTAX_PROBE_OUT: 結果 (JSON) を書き出すパス。SYNTAX_PROBE_SRC: syntax.ts の絶対パス。
// 読み込み・自己診断の時間 (ms)・runtime・メモリ (rss) の増分も書く。
// see docs/spec/guard/pi-extensions.md#確認画面の手順の一覧
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

export default async function (_pi: ExtensionAPI) {
	const out = process.env.SYNTAX_PROBE_OUT;
	const src = process.env.SYNTAX_PROBE_SRC;
	if (!out || !src) return;
	const versions: Record<string, string> = { ...(process.versions as any) };
	const runtime = versions.bun ? `bun ${versions.bun}` : `node ${versions.node}`;
	const rss0 = process.memoryUsage().rss;
	const syn: any = await import(pathToFileURL(src).href);
	const t0 = performance.now();
	const loaded = syn.loadSyntax();
	const t1 = performance.now();
	const diag = syn.selfDiagnose();
	const parsed = syn.parseSource("cd /x && git log | head -3 ; echo 確認");
	const t2 = performance.now();
	const stmts = parsed.ok ? syn.arr(parsed.src.file.Stmts).length : -1;
	writeFileSync(
		out,
		JSON.stringify({
			runtime,
			javascriptCore: Boolean(versions.bun),
			load: { ok: loaded.ok, why: loaded.why ?? "" },
			diag,
			parse: { ok: parsed.ok, why: parsed.why ?? "", stmts },
			loadMs: Math.round(t1 - t0),
			diagAndParseMs: Math.round(t2 - t1),
			rssDeltaMB: Math.round((process.memoryUsage().rss - rss0) / 1048576),
		}),
		"utf-8",
	);
}

// ledgerRoots の単体試験用 driver。標準入力の JSON `{cases: [{cwd, env}], many: N}` を読み、結果を JSON で返す。
// `many` があれば、別々の cwd を N 件引いたあとのキャッシュ件数も返す。
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../../..");
const mod = await import(
	pathToFileURL(resolve(root, "home/dot_config/pi/harness/judge/ledger_root.ts")).href
);
const input = JSON.parse(readFileSync(0, "utf8"));
const out = { results: [], same: [], cacheSize: null };
for (const c of input.cases ?? []) {
	const a = mod.ledgerRoots(c.cwd, c.env ?? {});
	const b = mod.ledgerRoots(c.cwd, c.env ?? {});
	out.results.push(a);
	out.same.push(a === b);
}
if (input.many) {
	for (let i = 0; i < input.many; i++) mod.ledgerRoots(`/nonexistent/cwd-${i}`, {});
	out.cacheSize = mod.ledgerRootsCacheSize();
}
console.log(JSON.stringify(out));

// quiet-notices.ts (自動の通知を畳む表示の純関数) の試験用 driver。標準入力の JSON の配列を実行して結果の配列を出す。
// 要素: {fn: "notice"|"action"|"user"|"width", args: {...}}。照合は test_pi_quiet_notices.py。
// see docs/spec/guard/pi-extensions.md#自動の通知を畳む表示
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const mod = await import(pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "quiet-notices.ts")).href);

const cases = JSON.parse(readFileSync(0, "utf-8"));
const out = cases.map((c) => {
	const a = c.args ?? {};
	switch (c.fn) {
		case "notice": {
			const r = mod.renderNotice(a);
			return { ...r, widths: r.lines.map((l) => mod.textWidth(l)) };
		}
		case "action":
			return mod.foldActionResult(a.text, a.details, { width: a.width, expanded: a.expanded, env: a.env });
		case "user":
			return { text: mod.foldUserMarkdown(a.markdown, a.env ?? {}) };
		case "width":
			return { width: mod.textWidth(a.text) };
		case "component": {
			const comp = mod.lineComponent(a.lines);
			return { rows: comp.render(a.width) };
		}
		default:
			throw new Error(`unknown fn: ${c.fn}`);
	}
});
process.stdout.write(JSON.stringify(out));

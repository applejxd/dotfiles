// /gitflow-allow (gitflow-allow.ts と gitflow_gate.ts の allow 部分。CHG-0049) の表試験の実行器。
// 標準入力の JSON (ケースの配列) を読み、結果を JSON で出す。
//
// ケース (id は必須):
//   {kind:"parse", text}                         → parseAllowArgs
//   {kind:"describe", allowance, now}            → describeAllowance
//   {kind:"permits", allow, op, owner}           → permits (allow: {allowance, now} か省略)
//   {kind:"gate", tool, input, cwd, facts, allow} → gate (facts は gitflow_guard_driver.mjs と同じ形)
//   {kind:"protected", owner}                    → isProtectedWorktree
//   {kind:"headName", head}                      → headName
//
// see docs/spec/guard/pi-gitflow-guard.md
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const harness = join(ROOT, "home", "dot_config", "pi", "harness");
const gateMod = await import(pathToFileURL(join(harness, "judge", "gitflow_gate.ts")).href);
const allowMod = await import(pathToFileURL(join(harness, "gitflow-allow.ts")).href);
const { gate, permits, isProtectedWorktree, headName } = gateMod;
const { parseAllowArgs, describeAllowance, DEFAULT_MINUTES, MAX_MINUTES } = allowMod;

function makeFacts(spec) {
	const real = spec.real ?? {};
	const owners = spec.owners ?? {};
	const models = spec.models ?? {};
	return {
		home: spec.home ?? "/home/u",
		realPath: (p) => (Object.hasOwn(real, p) ? real[p] : p),
		ownerOf(p) {
			const hit = Object.keys(owners)
				.filter((d) => p === d || p.startsWith(`${d}/`))
				.sort((a, b) => b.length - a.length)[0];
			return hit === undefined ? { kind: "no-repo" } : owners[hit];
		},
		modelOf: (dir) => models[dir] ?? "unknown",
		actionReady: () => spec.actionReady ?? true,
	};
}

const cases = JSON.parse(readFileSync(0, "utf8"));
const out = { __consts: { DEFAULT_MINUTES, MAX_MINUTES } };
for (const c of cases) {
	switch (c.kind) {
		case "parse":
			out[c.id] = parseAllowArgs(c.text);
			break;
		case "describe":
			out[c.id] = describeAllowance(c.allowance ?? null, c.now);
			break;
		case "permits":
			out[c.id] = permits(c.allow, c.op, c.owner);
			break;
		case "gate":
			out[c.id] = gate(c.tool, c.input, c.cwd ?? "/repo", makeFacts(c.facts ?? {}), c.allow);
			break;
		case "protected":
			out[c.id] = isProtectedWorktree(c.owner);
			break;
		case "headName":
			out[c.id] = headName(c.head);
			break;
		default:
			throw new Error(`unknown kind: ${c.kind}`);
	}
}
console.log(JSON.stringify(out));

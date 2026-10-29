// gitflow_gate.ts (CHG-0049) の表試験の実行器。標準入力の JSON (ケースの配列) を読み、結果を JSON で出す。
//
//   echo '[{"id":"a","kind":"gate",...}]' | node test/agents/pi/gitflow_guard_driver.mjs
//
// ケース:
//   {kind:"gate", tool, input, cwd, facts:{home, real:{入力→実体}, owners:{実体→Owner}, models:{commonDir→Model}, actionReady}}
//     real に無いパスは、そのまま実体とみなす。owners は、実体のパスの最長一致の前置き (ディレクトリ単位) で引く。無ければ no-repo。
//   {kind:"isGated", tool, input, facts}  → isGated の結果と、facts の呼び出し回数
//   {kind:"tighten", base, gate}          → tighten の結果
// 結果には facts の呼び出し回数 (calls) も付ける (git を起動しないことの確認用)。
//
// see docs/spec/guard/pi-gitflow-guard.md
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const base = join(ROOT, "home", "dot_config", "pi", "harness", "judge");
const { gate, isGated } = await import(pathToFileURL(join(base, "gitflow_gate.ts")).href);
const { tighten } = await import(pathToFileURL(join(base, "call.ts")).href);

function makeFacts(spec) {
	const calls = { realPath: 0, ownerOf: 0, modelOf: 0, actionReady: 0 };
	const real = spec.real ?? {};
	const owners = spec.owners ?? {};
	const models = spec.models ?? {};
	const facts = {
		home: spec.home ?? "/home/u",
		realPath(p) {
			calls.realPath++;
			return Object.hasOwn(real, p) ? real[p] : p;
		},
		ownerOf(p) {
			calls.ownerOf++;
			const hit = Object.keys(owners)
				.filter((d) => p === d || p.startsWith(`${d}/`))
				.sort((a, b) => b.length - a.length)[0];
			return hit === undefined ? { kind: "no-repo" } : owners[hit];
		},
		modelOf(dir) {
			calls.modelOf++;
			return models[dir] ?? "unknown";
		},
		actionReady() {
			calls.actionReady++;
			return spec.actionReady ?? true;
		},
	};
	return { facts, calls };
}

const cases = JSON.parse(readFileSync(0, "utf8"));
const out = {};
for (const c of cases) {
	if (c.kind === "tighten") {
		out[c.id] = tighten(c.base, c.gate);
		continue;
	}
	const { facts, calls } = makeFacts(c.facts ?? {});
	if (c.kind === "isGated") {
		out[c.id] = { gated: isGated(c.tool, c.input), calls };
	} else {
		out[c.id] = { result: gate(c.tool, c.input, c.cwd ?? "/repo", facts), calls };
	}
}
console.log(JSON.stringify(out));

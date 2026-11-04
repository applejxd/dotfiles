// autocheckpoint.ts の状態機械の試験用 driver。標準入力の JSON (シナリオ) を実行し、結果を JSON で標準出力へ出す。
// 照合は test_pi_autocheckpoint.py。
//
//   echo '{"env":{},"child":false,"steps":[...]}' | node test/agents/pi/autocheckpoint_driver.mjs
//
// steps の要素: {at: 時刻ms, percent: 数値|null, mode: "tui"|..., outcome: "completed"|..., finish: "complete"|"error"|"throw"}
// finish は、この step で compact が呼ばれたとき、その場で onComplete / onError を呼ぶか (省略なら呼ばない)
// see docs/spec/guard/pi-extensions.md#文脈の使用率による自動の保存と圧縮
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const mod = await import(pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "autocheckpoint.ts")).href);

const scenario = JSON.parse(readFileSync(0, "utf-8"));
let clock = 0;
const compacts = [];
const notes = [];
const handler = mod.createAutoCheckpoint({
	child: scenario.child === true,
	compactInstructions: "INSTR",
	env: scenario.env ?? {},
	now: () => clock,
	cooldownMs: scenario.cooldownMs,
});

const out = [];
for (const step of scenario.steps) {
	clock = step.at ?? clock;
	const before = compacts.length;
	const ctx = {
		mode: step.mode ?? "tui",
		ui: { notify: (m) => notes.push(m) },
		getContextUsage: () => ({ tokens: null, contextWindow: 0, percent: step.percent ?? null }),
		compact: (o) => {
			compacts.push(o);
			if (step.compactThrows) throw new Error("boom");
			if (step.finish === "complete") o.onComplete?.({});
			if (step.finish === "error") o.onError?.(new Error("fail"));
		},
	};
	const result = handler({ type: "agent_before_settle", outcome: step.outcome ?? "completed" }, ctx);
	out.push({ result: result ?? null, compacts: compacts.length - before });
}
console.log(JSON.stringify({ steps: out, compactOptions: compacts.map((o) => o.customInstructions), notes }));

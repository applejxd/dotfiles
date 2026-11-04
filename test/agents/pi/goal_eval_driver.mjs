// goal-eval.ts の試験用 driver。標準入力の JSON を実行し、結果を JSON で標準出力へ出す。照合は test_pi_goal_eval.py。
//
//   {"calls":[{"fn":"parseVerdict","args":["..."]}, ...]}      純関数を順に呼ぶ (引数は deep freeze して渡す = 入力を変更したら失敗する)
//   {"consts":true}                                             EVAL_SYSTEM と EVAL_LIMITS を返す
//   {"evals":[{"input":"..","timeoutMs":50,"fake":{..},"signal":"none|aborted|abortAfter","abortAfterMs":10,"noModel":false}]}
//       偽の complete を注入して評価役を呼ぶ。fake: {"kind":"ok","content":[..],"usage":{..},"stopReason":".."} | {"kind":"throw"}
//       | {"kind":"hang"} (signal が abort されるまで解決しない)。結果に、偽 complete が受けた引数の要約 (calls) を付ける
// see docs/spec/guard/pi-extensions.md (配線の後に書く)
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const mod = await import(pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "goal-eval.ts")).href);

const deepFreeze = (x) => {
	if (x && typeof x === "object" && !Object.isFrozen(x)) {
		Object.freeze(x);
		for (const v of Object.values(x)) deepFreeze(v);
	}
	return x;
};

const runEval = async (e) => {
	const seen = [];
	const parent = e.signal && e.signal !== "none" ? new AbortController() : undefined;
	if (e.signal === "aborted") parent.abort();
	const fake = e.fake ?? { kind: "ok", content: [] };
	const complete = (model, ctx, opts) => {
		const rec = {
			model,
			systemPrompt: ctx.systemPrompt,
			userText: ctx.messages[0].content[0].text,
			role: ctx.messages[0].role,
			cacheRetention: opts.cacheRetention,
			sameSignal: parent ? opts.signal === parent.signal : false,
			abortedAtCall: opts.signal.aborted,
		};
		seen.push(rec);
		if (fake.kind === "throw") return Promise.reject(new Error("boom"));
		if (fake.kind === "ok") return Promise.resolve({ content: fake.content, usage: fake.usage, stopReason: fake.stopReason });
		return new Promise((_, reject) => {
			opts.signal.addEventListener("abort", () => {
				rec.abortedWhileHanging = true;
				reject(new Error("aborted"));
			});
		});
	};
	const ev = mod.createEvaluator({ complete, model: () => (e.noModel ? undefined : "M"), timeoutMs: e.timeoutMs });
	if (e.signal === "abortAfter") setTimeout(() => parent.abort(), e.abortAfterMs ?? 10);
	const t0 = Date.now();
	const r = await ev(e.input ?? "入力", parent?.signal);
	return { result: r, calls: seen, ms: Date.now() - t0 };
};

const input = JSON.parse(readFileSync(0, "utf-8"));
if (input.calls) {
	const results = input.calls.map((c) => mod[c.fn](...deepFreeze(structuredClone(c.args ?? []))));
	console.log(JSON.stringify({ results }));
} else if (input.consts) {
	console.log(JSON.stringify({ system: mod.EVAL_SYSTEM, limits: mod.EVAL_LIMITS }));
} else if (input.evals) {
	const out = [];
	const keep = setInterval(() => {}, 1000); // AbortSignal.timeout は unref されるので、試験では終了させない
	for (const e of input.evals) out.push(await runEval(e));
	clearInterval(keep);
	console.log(JSON.stringify({ evals: out }));
}

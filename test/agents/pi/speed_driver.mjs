// speed 拡張の表試験 (純関数と、時計を差し替えたイベント列)。結果を JSON で標準出力へ出す
// (照合は test_pi_speed.py)。
//
//   node test/agents/pi/speed_driver.mjs
//
// see docs/spec/guard/pi-extensions.md#自作の拡張-todo--plan--btw
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const mod = await import(pathToFileURL(resolve(ROOT, "home", "dot_pi", "agent", "extensions", "speed", "index.ts")).href);
const { computeSpeed, formatSpeed, speedExtension } = mod;

const base = { t0: 0, tFirst: 1200, tEnd: 3200, output: 120, reasoning: 0, sawThinking: false };
const cs = (over) => computeSpeed({ ...base, ...over });
const out = {};
out.compute = {
	normal: cs({}),
	short_output: cs({ output: 29 }),
	min_output: cs({ output: 30 }),
	short_span: cs({ tEnd: 1499, output: 100 }),
	min_span: cs({ tEnd: 1500, output: 100 }),
	no_first: cs({ tFirst: undefined }),
	no_t0: cs({ t0: undefined }),
	reasoning_unseen: cs({ reasoning: 50 }),
	reasoning_seen: cs({ reasoning: 50, sawThinking: true }),
	reasoning_zero_unseen: cs({ reasoning: 0, sawThinking: false }),
	approx_without_rate: cs({ reasoning: 50, output: 10 }),
};
const fmt = (over) => formatSpeed(cs(over));
out.format = {
	normal: fmt({}),
	approx: fmt({ reasoning: 50 }),
	no_rate: fmt({ output: 10 }),
	no_ttft: fmt({ t0: undefined }),
	none: fmt({ tFirst: undefined }),
	long: fmt({ tFirst: 123456, tEnd: 223456, output: 12345 }),
};

// 時計を差し替えて、イベントの流れから表示を確かめる
function run(events) {
	const handlers = {};
	const pi = { on: (name, fn) => (handlers[name] = fn) };
	let clock = 0;
	speedExtension(pi, () => clock);
	const statuses = [];
	const ctx = { hasUI: true, ui: { setStatus: (key, text) => statuses.push([key, text]) } };
	return (async () => {
		for (const [at, name, event, c] of events) {
			clock = at;
			await handlers[name]?.(event, c ?? ctx);
		}
		return statuses;
	})();
}
const update = (type) => ({ type: "message_update", assistantMessageEvent: { type } });
const end = (usage, stopReason = "stop") => ({ message: { role: "assistant", stopReason, usage } });
const flow = (deltaType, usage, extra = []) => [
	[0, "session_start", {}],
	[100, "before_provider_request", { payload: {} }],
	[200, "message_update", update("start")],
	[1300, "message_update", update(deltaType)],
	[2000, "message_update", update("text_delta")],
	...extra,
	[3300, "message_end", end(usage)],
];
out.events = {
	text: await run(flow("text_delta", { output: 110, reasoning: 0 })),
	thinking: await run(flow("thinking_delta", { output: 110, reasoning: 40 })),
	toolcall: await run(flow("toolcall_delta", { output: 110 })),
	reasoning_hidden: await run(flow("text_delta", { output: 110, reasoning: 40 })),
	no_request_hook: await run([
		[0, "message_update", update("text_delta")],
		[2000, "message_end", end({ output: 110 })],
	]),
	// start だけで delta が来ない応答は、最初のトークンを取れない
	no_delta: await run([
		[0, "before_provider_request", {}],
		[100, "message_update", update("start")],
		[2000, "message_end", end({ output: 110 })],
	]),
	error: await run(flow("text_delta", { output: 110 }).slice(0, -1).concat([[3300, "message_end", end({ output: 110 }, "error")]])),
	aborted: await run(flow("text_delta", { output: 110 }).slice(0, -1).concat([[3300, "message_end", end({ output: 110 }, "aborted")]])),
	user_message: await run([
		[0, "before_provider_request", {}],
		[100, "message_end", { message: { role: "user" } }],
	]),
	second_call_resets: await run([
		...flow("thinking_delta", { output: 110, reasoning: 40 }),
		[4000, "before_provider_request", {}],
		[4500, "message_update", update("text_delta")],
		[6500, "message_end", end({ output: 100, reasoning: 40 })],
	]),
	cleared_on_switch: await run([...flow("text_delta", { output: 110 }), [9000, "session_start", {}]]),
	no_ui: await run([
		[0, "session_start", {}, { hasUI: false, ui: { setStatus: () => { throw new Error("no ui") } } }],
		[0, "before_provider_request", {}],
		[100, "message_update", update("text_delta")],
		[2000, "message_end", end({ output: 110 }), { hasUI: false, ui: { setStatus: () => { throw new Error("no ui") } } }],
	]),
};

// 子 (PI_HARNESS_CHILD=1) では何も登録しない
const registered = [];
const piChild = { on: (name) => registered.push(name) };
process.env.PI_HARNESS_CHILD = "1";
mod.default(piChild);
const childRegistered = registered.length;
delete process.env.PI_HARNESS_CHILD;
mod.default(piChild);
out.child = { child: childRegistered, parent: registered.length };
process.stdout.write(JSON.stringify(out));

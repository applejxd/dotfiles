// 直近 1 回のモデル呼び出しの TTFT と decode 速度 (tok/s) を、ステータス行に出すだけ (記録・コマンド・通信は無い)。
// 最初のトークンの時刻は、型のある message_update の *_delta で取る (provider_stream_event の data は提供元ごとの生の値)。
// see docs/spec/guard/pi-extensions.md#自作の拡張-todo--plan--btw
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const MIN_TOKENS = 30;
const MIN_DECODE_MS = 300;
const NONE = "—";

export type SpeedInput = { t0?: number; tFirst?: number; tEnd: number; output: number; reasoning: number; sawThinking: boolean };
export type Speed = { ttftMs?: number; tps?: number; approx: boolean };

export function computeSpeed(i: SpeedInput): Speed {
	const ttftMs = i.t0 !== undefined && i.tFirst !== undefined ? Math.max(0, i.tFirst - i.t0) : undefined;
	const span = i.tFirst !== undefined ? i.tEnd - i.tFirst : undefined;
	const ok = span !== undefined && span >= MIN_DECODE_MS && i.output >= MIN_TOKENS;
	const tps = ok ? i.output / (span / 1000) : undefined;
	// reasoning を数えているのに thinking のデルタを見ていない = 思考がストリームに出ない経路。分母が過小になる
	return { ttftMs, tps, approx: tps !== undefined && i.reasoning > 0 && !i.sawThinking };
}

export function formatSpeed(s: Speed): string {
	if (s.ttftMs === undefined && s.tps === undefined) return NONE;
	const rate = s.tps === undefined ? NONE : `${s.approx ? "~" : ""}${Math.round(s.tps)}t/s`;
	const ttft = s.ttftMs === undefined ? NONE : `${(s.ttftMs / 1000).toFixed(1)}s`;
	return `📝${rate} ${ttft}`;
}

/** 今回の値で、取れなかった項目 (出力が短い・最初のトークンが無い) は直近の値を残す (表示が「—」に戻らないように) */
export function mergeSpeed(prev: Speed | undefined, cur: Speed): Speed {
	return {
		ttftMs: cur.ttftMs ?? prev?.ttftMs,
		tps: cur.tps ?? prev?.tps,
		approx: cur.tps !== undefined ? cur.approx : (prev?.approx ?? false),
	};
}

export function speedExtension(pi: ExtensionAPI, now: () => number) {
	let t0: number | undefined;
	let tFirst: number | undefined;
	let sawThinking = false;
	// 直近の有効な値 (セッションを開いてから)。短い応答で decode が取れないときは、これを表示し続ける
	let last: Speed | undefined;

	const reset = () => {
		t0 = tFirst = undefined;
		sawThinking = false;
	};
	const safe = <A extends unknown[]>(fn: (...a: A) => void) => async (...a: A) => {
		try {
			fn(...a);
		} catch {}
		return undefined;
	};

	pi.on(
		"session_start",
		safe((_e: any, ctx: ExtensionContext) => {
			reset();
			last = undefined;
			if (ctx.hasUI) ctx.ui.setStatus("speed", undefined);
		}),
	);
	pi.on(
		"before_provider_request",
		safe(() => {
			reset();
			t0 = now();
		}),
	);
	pi.on(
		"message_update",
		safe((event: any) => {
			const type = event?.assistantMessageEvent?.type;
			if (typeof type !== "string" || !type.endsWith("_delta")) return;
			tFirst ??= now();
			if (type === "thinking_delta") sawThinking = true;
		}),
	);
	pi.on(
		"message_end",
		safe((event: any, ctx: ExtensionContext) => {
			const m = event?.message;
			if (m?.role !== "assistant" || !ctx.hasUI) return;
			const tEnd = now();
			const done = m.stopReason !== "error" && m.stopReason !== "aborted";
			const speed = computeSpeed({ t0, tFirst, tEnd, output: m.usage?.output ?? 0, reasoning: m.usage?.reasoning ?? 0, sawThinking });
			reset();
			if (done) {
				last = mergeSpeed(last, speed);
				ctx.ui.setStatus("speed", formatSpeed(last));
			}
		}),
	);
}

export default function (pi: ExtensionAPI) {
	if (process.env.PI_HARNESS_CHILD === "1") return;
	speedExtension(pi, () => performance.now());
}

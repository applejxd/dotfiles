// agent_before_settle への接着層。調停 (arbiter.ts の settle) を pi の唯一のハンドラとして登録する。
// 旗 PI_WORK_ARBITER=1 のときだけ登録 (既定は何もしない)。子は登録しない。二重に呼ばれても登録は 1 回 (べき等)。
// entries は前のハンドラの分を保つ (置換されるため)。wake・notify・append_event・checkpoint は effects 経由でだけ実行する。
// 例外は握りつぶして継続しない ({} を返す)。see docs/spec/work/settle.md
import { settle } from "./arbiter.ts";
import type { Decision, Effect, Facts } from "./arbiter.ts";
import { makeAux } from "./events.ts";
import { select } from "./notices.ts";

/** 呼び出し側 (台帳の投影・各拡張の状態) が写して渡す事実。イベント由来の項目 (outcome など) は含めない */
export type SettleSnapshot = Pick<Facts, "phase" | "streak" | "maxStreak" | "budgetExhausted" | "checkpoint" | "todo" | "goal" | "children"> & {
	compacting?: boolean;
};

export interface SettleDeps {
	snapshot(): SettleSnapshot;
	exec: {
		wake(prompt: string, opts?: { customType?: string; why?: string }): void;
		notify(kind: "silent" | "line" | "alert", text: string): void;
		checkpoint(action?: "compact" | "cancel"): void;
	};
	runtime?: { submit(events: any[]): Promise<unknown> };
	journal?: { emit(type: any, data?: Record<string, unknown>, node?: string): void };
}

export interface SettleOpts {
	enabled: boolean;
	child: boolean;
}

const registered = new WeakSet<object>();

/** イベントと snapshot から Facts を組む */
export function buildFacts(event: any, ctx: any, snap: SettleSnapshot, opts: SettleOpts): Facts {
	const outcome = event?.outcome === "aborted" || event?.outcome === "error" ? event.outcome : "completed";
	let pending = false;
	try {
		pending = ctx?.hasPendingMessages?.() === true;
	} catch {
		pending = false;
	}
	let compacting = snap.compacting === true;
	try {
		compacting = compacting || ctx?.isCompacting?.() === true;
	} catch {
		/* 取れなければ snapshot の値のまま */
	}
	return {
		trigger: "settle",
		mode: ctx?.mode === "print" || ctx?.mode === "json" ? ctx.mode : "interactive",
		child: opts.child,
		outcome,
		phase: snap.phase,
		compacting,
		userInput: pending,
		streak: snap.streak,
		maxStreak: snap.maxStreak,
		budgetExhausted: snap.budgetExhausted,
		checkpoint: snap.checkpoint,
		todo: snap.todo,
		goal: snap.goal,
		children: snap.children,
	};
}

const safe = (f: () => void): void => {
	try {
		f();
	} catch {
		/* 効果の失敗で本体を止めない */
	}
};

/** effects を実行する。wake はここだけ (高々 1 回)。notify は select を通す */
export function runEffects(effects: Effect[], deps: SettleDeps): void {
	let woke = false;
	for (const e of effects) {
		if (e.kind === "wake") {
			if (woke) continue;
			woke = true;
			safe(() => deps.exec.wake(e.content, { customType: e.customType, why: e.why }));
		} else if (e.kind === "notify") {
			safe(() => {
				select(e.event); // 表に無い事象は例外 → 出さない
				deps.exec.notify(e.show, e.text);
			});
		} else if (e.kind === "append_event") {
			safe(() => {
				const p = deps.runtime?.submit([makeAux(e.name as any, e.data ?? {})]);
				Promise.resolve(p).catch(() => {});
			});
		} else if (e.kind === "checkpoint") {
			safe(() => deps.exec.checkpoint(e.action));
		}
	}
}

/** ハンドラの本体 (試験から直接呼べる)。返り値は pi の agent_before_settle の返り値 */
export function handleSettle(event: any, ctx: any, deps: SettleDeps, opts: SettleOpts): { entries?: any[]; continue?: boolean } {
	try {
		const d: Decision = settle(buildFacts(event, ctx, deps.snapshot(), opts));
		runEffects(d.effects, deps);
		safe(() =>
			deps.journal?.emit("settle", {
				source: "arbiter",
				outcome: event?.outcome ?? "completed",
				continue: d.continue,
				by: d.entries[0]?.customType,
				row: d.row,
				why: d.why,
			}),
		);
		if (!d.continue || d.entries.length === 0) return {};
		const prev = Array.isArray(event?.entries) ? event.entries : [];
		return { entries: [...prev, ...d.entries], continue: true };
	} catch {
		return {};
	}
}

/** agent_before_settle に調停を登録する。旗が偽・子なら何もしない。べき等 */
export function registerSettle(pi: any, deps: SettleDeps, opts: SettleOpts): { registered: boolean } {
	if (!opts.enabled || opts.child) return { registered: false };
	if (registered.has(pi)) return { registered: true }; // 既に登録済み (ハンドラは増やさない)
	registered.add(pi);
	pi.on("agent_before_settle", async (event: any, ctx: any) => handleSettle(event, ctx, deps, opts));
	return { registered: true };
}

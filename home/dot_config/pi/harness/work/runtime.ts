// 作業台帳の実行時の接着層。1 つの会話が台帳を開いて持ち続け、イベントを reduce → 永続 → 状態更新の順で通す。pi の API には依存しない。
// 守る条件: 状態は常に「永続済みのイベントの fold」と一致・不変条件違反は永続しない・2 つ目は読み取り専用・
// 読み取り専用と off は何も書かない。仕様: docs/spec/work/runtime.md
import { execFileSync } from "node:child_process";
import { accessSync, constants, mkdirSync } from "node:fs";
import { isAbsolute, resolve } from "node:path";
import { check as checkInvariants } from "./invariants.ts";
import type { Violation } from "./invariants.ts";
import { makeEvent } from "./events.ts";
import { emptyState, fold, reduce } from "./reduce.ts";
import type { LedgerState } from "./reduce.ts";
import { resolveStoreRoot } from "./root.ts";
import { createStore } from "./store.ts";
import type { StoreOptions, WorkStore } from "./store.ts";
import type { LedgerEvent, NewEvent } from "./types.ts";

export type RuntimeMode = "driver" | "readonly" | "degraded" | "off";

export const HEARTBEAT_INTERVAL_MS = 30_000;

export interface RuntimeTimers {
	setInterval(fn: () => void, ms: number): unknown;
	clearInterval(handle: unknown): void;
}

export interface RuntimeOptions {
	cwd: string;
	sessionId: string;
	holder: string;
	pid: number;
	now?: () => number;
	env?: Record<string, string | undefined>;
	timers?: RuntimeTimers;
	/** 永続に成功したイベントを状態に反映した直後 (状態は読み取り専用の複製) */
	onChange?: (state: LedgerState, applied: LedgerEvent[]) => void;
	/** 降格・書き込み失敗などの警告 (利用者に見せる) */
	onAlert?: (message: string) => void;
	/** 旗 (既定 true)。偽なら off */
	enabled?: boolean;
	/** 既定 true。goal の作成と start で lease.acquired を自動で追記する (I8)。試験だけが false にする */
	autoLease?: boolean;
	/** 置き場を直接指定する (試験用)。省略時は resolveStoreRoot で解く */
	root?: string;
	gitCommonDir?: string;
	/** 試験用: store への追加の設定 (障害注入・pid の生死・segmentSize など) */
	storeOptions?: Partial<StoreOptions>;
	/** 試験用: 不変条件の検査の差し替え */
	check?: (state: LedgerState, prev?: LedgerState) => Violation[];
}

export interface SubmitResult {
	ok: boolean;
	/** 永続に成功したイベント (失敗した場合も、成功した分までは入る) */
	applied: LedgerEvent[];
	error?: string;
}

export interface Runtime {
	readonly mode: RuntimeMode;
	readonly readonlyReason: string | null;
	start(): Promise<void>;
	state(): Readonly<LedgerState>;
	submit(events: NewEvent[]): Promise<SubmitResult>;
	/** heartbeat を 1 回行う (タイマーが呼ぶ。試験からも呼べる) */
	heartbeatNow(): Promise<void>;
	close(): Promise<void>;
}

/** Map の書き換えを塞いだ深い凍結 (Object.freeze は Map の中身を守らない) */
const deepFreeze = <T>(v: T): T => {
	if (typeof v !== "object" || v === null || Object.isFrozen(v)) return v;
	if (v instanceof Map) {
		for (const [k, x] of v) {
			deepFreeze(k);
			deepFreeze(x);
		}
		const deny = () => {
			throw new TypeError("台帳の状態は読み取り専用");
		};
		for (const m of ["set", "delete", "clear"]) Object.defineProperty(v, m, { value: deny });
	} else {
		for (const x of Object.values(v)) deepFreeze(x);
	}
	return Object.freeze(v);
};

const msg = (e: unknown): string => (e instanceof Error ? e.message : String(e));

const defaultGitCommonDir = (cwd: string): string | undefined => {
	try {
		const out = execFileSync("git", ["rev-parse", "--git-common-dir"], { cwd, encoding: "utf-8", stdio: ["ignore", "pipe", "ignore"] }).trim();
		return out ? (isAbsolute(out) ? out : resolve(cwd, out)) : undefined;
	} catch {
		return undefined;
	}
};

const canWrite = (path: string): boolean => {
	try {
		mkdirSync(path, { recursive: true });
		accessSync(path, constants.W_OK);
		return true;
	} catch {
		return false;
	}
};

export function createRuntime(opts: RuntimeOptions): Runtime {
	const env = opts.env ?? process.env;
	const now = opts.now ?? (() => Date.now());
	const timers: RuntimeTimers = opts.timers ?? {
		setInterval: (fn, ms) => {
			const h = setInterval(fn, ms);
			(h as { unref?: () => void }).unref?.();
			return h;
		},
		clearInterval: (h) => clearInterval(h as ReturnType<typeof setInterval>),
	};
	const inv = opts.check ?? checkInvariants;
	const off = opts.enabled === false || env.PI_WORK === "0" || !!env.PI_HARNESS_CHILD;

	let mode: RuntimeMode = off ? "off" : "readonly";
	let reason: string | null = off ? "off" : "未開始";
	let store: WorkStore | null = null;
	let cur: LedgerState = emptyState();
	let frozen: LedgerState | null = null;
	let timer: unknown = null;
	let chain: Promise<unknown> = Promise.resolve();

	const alert = (m: string) => {
		try {
			opts.onAlert?.(m);
		} catch {
			// 表示側の失敗で台帳の処理を止めない
		}
	};

	const demote = (to: RuntimeMode, why: string) => {
		mode = to;
		reason = why;
		if (timer !== null) {
			timers.clearInterval(timer);
			timer = null;
		}
		alert(`作業台帳: ${why}`);
	};

	const setState = (s: LedgerState) => {
		cur = s;
		frozen = null;
	};

	/** 直列化 (submit の並行呼び出しで seq が前後しない) */
	const serial = <T>(fn: () => Promise<T>): Promise<T> => {
		const p = chain.then(fn, fn);
		chain = p.catch(() => {});
		return p;
	};

	const acquired = (goal: string) => makeEvent("lease.acquired", goal, { holder: opts.holder, pid: opts.pid }, "system");

	/** 生きた goal の lease を自分に付け替える (前の保持者は expired で外す)。自分が保持中の goal は何もしない */
	const leaseEvents = (s: LedgerState): NewEvent[] => {
		if (opts.autoLease === false) return [];
		const out: NewEvent[] = [];
		for (const id of s.goals) {
			const g = s.nodes.get(id);
			if (!g || !(["draft", "planned", "active", "paused"] as string[]).includes(g.state)) continue;
			if (g.owner?.holder === opts.holder) continue;
			if (g.owner) out.push(makeEvent("lease.expired", id, { holder: g.owner.holder }, "system"));
			out.push(acquired(id));
		}
		return out;
	};

	const start = async (): Promise<void> => {
		if (off || store) return;
		const gcd = opts.gitCommonDir ?? (opts.root ? undefined : defaultGitCommonDir(opts.cwd));
		const root = opts.root ?? resolveStoreRoot({ gitCommonDir: gcd, cwd: opts.cwd, canWrite }).root;
		store = createStore({ now, pid: opts.pid, ...opts.storeOptions, root });
		// 回復 (torn の切り詰め・隔離) は書き手として行うため、lease を先に取ってから読む
		let lease = null;
		try {
			lease = await store.acquireLease(opts.holder, opts.pid);
		} catch (e) {
			demote("readonly", `lease を取れない (${msg(e)})`);
		}
		let loaded;
		try {
			loaded = await store.load();
		} catch (e) {
			demote("degraded", `台帳を読めない (${msg(e)})`);
			if (lease) await store.releaseLease().catch(() => {});
			return;
		}
		try {
			setState(fold(loaded.events));
		} catch (e) {
			demote("readonly", `台帳の再生に失敗した (${msg(e)})`);
			if (lease) await store.releaseLease().catch(() => {});
			return;
		}
		const bad = inv(cur);
		if (bad.length > 0) {
			demote("readonly", `不変条件の違反 (${bad[0].inv}: ${bad[0].message}) のため読み取り専用`);
			if (lease) await store.releaseLease().catch(() => {});
			return;
		}
		if (loaded.degraded) {
			demote("degraded", `台帳が破損のため読み取り専用 (${loaded.degraded.reason})`);
			if (lease) await store.releaseLease().catch(() => {});
			return;
		}
		if (!lease) {
			mode = "readonly";
			reason = store.readonlyReason ?? "別の会話が駆動中 (lease を取れない)";
			return;
		}
		mode = "driver";
		reason = null;
		// I8: holder 付きの追記は、goal の lease.acquired より後でなければ拒否される。生きた goal ごとに先に書く
		const pre = leaseEvents(cur);
		if (pre.length > 0) {
			const r = await submit(pre);
			if (!r.ok) return;
		}
		timer = timers.setInterval(() => {
			void heartbeatNow();
		}, HEARTBEAT_INTERVAL_MS);
	};

	let hb: Promise<void> | null = null;
	const heartbeatNow = (): Promise<void> => {
		// 同時に 1 回だけ (タイマーと手動の重複で警告を二重に出さない)
		hb ??= heartbeatOnce().finally(() => {
			hb = null;
		});
		return hb;
	};

	const heartbeatOnce = async (): Promise<void> => {
		if (mode !== "driver" || !store) return;
		try {
			await store.heartbeat();
		} catch (e) {
			const code = (e as { code?: string }).code;
			if (code === "NO_LEASE") demote("readonly", "lease を引き継がれた (以後は読み取り専用)");
			else demote("degraded", `heartbeat に失敗した (${msg(e)})`);
		}
	};

	const submit = (input: NewEvent[]): Promise<SubmitResult> =>
		serial(async (): Promise<SubmitResult> => {
			// 新しい goal は作成の直後に lease を取る (後続の holder 付きの追記が I8 で拒否されない)
			const events =
				opts.autoLease === false ? input : input.flatMap((e) => (e.type === "goal.created" && e.node ? [e, acquired(e.node)] : [e]));
			if (mode !== "driver" || !store) return { ok: false, applied: [], error: `書き込めない (${mode}: ${reason ?? ""})` };
			if (events.length === 0) return { ok: true, applied: [] };
			// ① 先に全部を reduce と検査にかける (純関数。1 件でも失敗なら何も追記しない)
			try {
				let s = cur;
				for (let i = 0; i < events.length; i++) {
					const next = reduce(s, { ...events[i], seq: s.seq + 1, ts: now() });
					const bad = inv(next, s);
					if (bad.length > 0) return { ok: false, applied: [], error: `不変条件の違反 (${bad[0].inv}: ${bad[0].message})` };
					s = next;
				}
			} catch (e) {
				return { ok: false, applied: [], error: msg(e) };
			}
			// ② 永続。成功した分だけ状態へ反映する (状態は常に永続済みの fold)
			const applied: LedgerEvent[] = [];
			let s = cur;
			let failure: string | undefined;
			for (const ev of events) {
				let full: LedgerEvent;
				try {
					full = await store.append(ev);
				} catch (e) {
					const code = (e as { code?: string }).code;
					failure = msg(e);
					if (code === "NO_LEASE") demote("readonly", `lease を失った (${failure})`);
					else demote("degraded", `台帳に書けない (${failure})`);
					break;
				}
				try {
					s = reduce(s, full);
				} catch (e) {
					// 永続した後に畳めない (reduce の前検査と食い違った)。状態は進めず、以後は書かない
					failure = `永続後の再生に失敗した (${msg(e)})`;
					demote("degraded", failure);
					break;
				}
				applied.push(full);
			}
			if (applied.length > 0) {
				setState(s);
				try {
					opts.onChange?.(runtime.state(), applied);
				} catch {
					// 表示側の失敗で台帳の処理を止めない
				}
			}
			return failure === undefined ? { ok: true, applied } : { ok: false, applied, error: failure };
		});

	const close = async (): Promise<void> => {
		if (timer !== null) {
			timers.clearInterval(timer);
			timer = null;
		}
		await chain.catch(() => {});
		if (store?.currentLease()) await store.releaseLease().catch(() => {});
		if (!off) {
			mode = "readonly";
			reason = "閉じた";
		}
	};

	const runtime: Runtime = {
		get mode() {
			return mode;
		},
		get readonlyReason() {
			return reason;
		},
		start,
		state: () => {
			if (!frozen) frozen = deepFreeze(structuredClone(cur));
			return frozen;
		},
		submit,
		heartbeatNow,
		close,
	};
	return runtime;
}

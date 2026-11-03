// PR レビューの受信箱 (/pr inbox)。見張りは ref を読むだけで、受領して会話へ渡すのは利用者が打つ take だけ。
// 振る舞いと範囲は docs/change/0061-pr-inbox.md が正本。
import { randomUUID } from "node:crypto";
import { candidatesOfKey, collectInjection, gitIn, myWorktreeId, type Candidate } from "./pr-review.ts";
import { REF_PREFIX, type Git } from "./review-git.ts";

const POLL_MS = 5000;
const MAX_KEYS = 200;
const STATUS_KEY = "pr-inbox";
const LIST_RE = /^([0-9a-f]{40}) refs\/pi\/review\/(p[0-9a-f]{16})$/;

export type InboxDeps = {
	child: boolean;
	gitFor?: (cwd: string) => Git;
	now?: () => string;
	sessionId?: () => string;
	/** 圧縮中は保留する (index.ts の deferWhileCompacting を渡す) */
	defer: (fn: () => void) => void;
	pollMs?: number;
	timers?: { setInterval: typeof setInterval; clearInterval: typeof clearInterval };
	/** BEL (試験で差し替える)。既定は標準出力へ \x07 */
	bell?: () => void;
};

/** そのセッション (session_start・コマンド) で受けた pi と ctx。callback はこれだけを使う */
export type Env = { pi: any; ctx: any };

const isStale = (e: unknown): boolean => /stale/i.test(String((e as any)?.message ?? e));

export function createInbox(deps: Omit<InboxDeps, "child">) {
	const gitFor = deps.gitFor ?? gitIn;
	const now = deps.now ?? (() => new Date().toISOString());
	const session = deps.sessionId ? deps.sessionId() : randomUUID();
	const timers = deps.timers ?? { setInterval, clearInterval };
	const pollMs = deps.pollMs ?? POLL_MS;
	const bell = deps.bell ?? (() => void process.stdout.write("\x07"));

	let gen = 0;
	// session_shutdown ごとに進める。take は、shutdown をまたいだら受領も通知も送信もしない (off では進めない: 明示の take は続ける)
	let epoch = 0;
	let timer: any = null;
	let current: Env | null = null;
	let busyGen = -1; // tick の実行中の世代 (重なり防止)
	let mine: string | null = null;
	let lastN = 0; // 最後に通知した (または見えていた) 件数。再開始では保つ (同じ件数を再通知しない)
	let needBadge = false; // 開始後の最初の tick は、件数が同じでもバッジを出し直す
	let lastTick: string | null = null;
	let startedAt: string | null = null;
	// キー → { oid, 候補 }。読めなかったキーは入れない (次の tick で再試行)
	let cache = new Map<string, { oid: string; cands: Candidate[] }>();

	const unread = (): number => [...cache.values()].reduce((n, e) => n + e.cands.length, 0);

	/** 古い ctx (/reload や新セッションの後) の例外は握る。通知は失敗しても何も起きない */
	function say(ctx: any, text: string, level = "info"): void {
		try {
			ctx?.ui?.notify?.(text, level);
		} catch {
			// 古い ctx。何もしない
		}
	}

	function clearBadge(env: Env | null): void {
		try {
			if (env?.ctx?.hasUI) env.ctx.ui.setStatus(STATUS_KEY, undefined);
		} catch {
			// 古い ctx。何もしない
		}
	}

	/** 閉じる。冪等。世代を進めるので、実行中の tick は副作用を出さない。reset=false は件数の記憶を残す (再開始・shutdown) */
	function stop(reset = true): void {
		gen++;
		if (timer) {
			timers.clearInterval(timer);
			timer = null;
		}
		clearBadge(current);
		current = null;
		startedAt = null;
		if (reset) lastN = 0;
	}

	async function tick(g: number, env: Env): Promise<void> {
		if (g !== gen || busyGen === g) return;
		busyGen = g;
		try {
			const git = gitFor(env.ctx.cwd);
			// 共有の mine には、世代を確かめてから書く (旧世代の取得が、新世代の値を null などで上書きしない)
			let who = mine;
			if (who === null) {
				const resolved = await myWorktreeId(git);
				if (g !== gen || resolved === null) return;
				mine = who = resolved;
			}
			const r = await git(["for-each-ref", "--format=%(objectname) %(refname)", REF_PREFIX]);
			if (g !== gen || r.code !== 0) return;
			const listed = new Map<string, string>();
			for (const line of r.stdout.split("\n")) {
				const m = LIST_RE.exec(line);
				if (m && listed.size < MAX_KEYS) listed.set(m[2], m[1]);
			}
			const next = new Map<string, { oid: string; cands: Candidate[] }>();
			for (const [key, oid] of listed) {
				const old = cache.get(key);
				if (old && old.oid === oid) {
					next.set(key, old);
					continue;
				}
				const cands = await candidatesOfKey(git, key, who);
				if (g !== gen) return;
				if (cands) next.set(key, { oid, cands });
				// 読めなかった: oid を覚えず (次の tick で再試行)、前の結果があればそれを使う
				else if (old) next.set(key, { oid: "", cands: old.cands });
			}
			cache = next;
			lastTick = now();
			const n = unread();
			const first = needBadge;
			if (n === lastN && !first) return;
			const grew = n > lastN;
			lastN = n;
			if (g !== gen) return;
			needBadge = false;
			env.ctx.ui.setStatus(STATUS_KEY, n > 0 ? `📨 レビュー ${n} 件` : undefined);
			if (grew) {
				env.ctx.ui.notify(`PR レビューが ${n} 件届いています。/pr inbox take で取り込めます`, "info");
				if (env.ctx.mode === "tui") bell();
			}
		} catch (e) {
			// 古い ctx (/reload や新セッションの後) は、静かに止める。ほかの失敗は次の tick で再試行
			if (isStale(e) && g === gen) stop();
		} finally {
			if (busyGen === g) busyGen = -1;
		}
	}

	/** 見張りを始める。冪等 (すでにあれば閉じてから)。最初の tick (全 PR を読む) の完了を待てる。通知済みの件数は保つ */
	function start(env: Env): Promise<void> {
		stop(false);
		const g = gen;
		current = env;
		mine = null;
		needBadge = true;
		cache = new Map();
		startedAt = now();
		timer = timers.setInterval(() => tick(g, env), pollMs);
		timer?.unref?.();
		return tick(g, env);
	}

	/** session_shutdown。見張りを閉じ、進行中の take を無効にする (通知済みの件数は保つ) */
	function shutdown(): void {
		epoch++;
		stop(false);
	}

	/** 受領して文面を会話へ渡す。利用者専用 (モデルは呼べない)。shutdown をまたいだら、新たに受領も通知も送信もしない */
	async function take(env: Env): Promise<void> {
		const { ctx, pi } = env;
		const mineEpoch = epoch;
		const alive = () => mineEpoch === epoch;
		let content: string | null;
		try {
			content = await collectInjection(gitFor(ctx.cwd), session, now, alive);
		} catch (e) {
			if (!isStale(e) && alive()) say(ctx, "レビューの取り込みに失敗しました", "error");
			return;
		}
		// 受領を始めた後に shutdown が来たときは送れない (受領済みなら、アプリの「再送」で送り直せる)
		if (!alive()) return;
		if (!content) {
			say(ctx, "取り込める新着はありません", "info");
			return;
		}
		deps.defer(() => {
			if (!alive()) return;
			try {
				const opts = ctx.isIdle() ? { triggerTurn: true } : { deliverAs: "followUp" };
				pi.sendMessage({ customType: "pr-review", content, display: true }, opts);
			} catch (e) {
				// 受領は取り消せない。アプリの「再送」で救う
				if (!isStale(e)) say(ctx, "受領したが、会話への送信に失敗しました。アプリの「再送」で送り直せます", "error");
			}
		});
		// 受領で件数が変わるので、見張りの表示を早めに更新する (重なっていれば次の tick に任せる)
		if (current && timer) await tick(gen, current);
	}

	function status() {
		return { on: timer !== null, unread: unread(), lastTick, startedAt };
	}

	return { start, stop, shutdown, take, status, tick: () => (current ? tick(gen, current) : Promise.resolve()) };
}

/** /pr コマンドとイベントを登録する。子には何も登録しない */
export function registerPrInbox(pi: any, deps: InboxDeps): void {
	if (deps.child) return;
	const inbox = createInbox(deps);
	let enabled = false; // プロセスのメモリだけ (/reload で戻る)

	pi.on("session_start", async (_event: any, ctx: any) => {
		if (enabled && ctx?.hasUI) await inbox.start({ pi, ctx });
	});
	pi.on("session_shutdown", async () => {
		inbox.shutdown();
	});

	pi.registerCommand("pr", {
		description: "PR レビューの受信箱: /pr inbox on|off|status|take",
		handler: async (args: string, ctx: any) => {
			const [sub, action] = String(args ?? "").trim().split(/\s+/);
			const say = (text: string, level = "info") => ctx.ui?.notify?.(text, level);
			if (sub !== "inbox" || !["on", "off", "status", "take"].includes(action ?? "")) {
				say("使い方: /pr inbox on|off|status|take", "warning");
				return;
			}
			if (action === "on") {
				if (!ctx.hasUI) {
					say("対話 (TUI) の pi でないため、受信箱は始められません (take は使えます)", "warning");
					return;
				}
				enabled = true;
				await inbox.start({ pi, ctx });
				say("受信箱を on にした (このセッションだけ)", "info");
			} else if (action === "off") {
				enabled = false;
				inbox.stop();
				say("受信箱を off にした", "info");
			} else if (action === "status") {
				const s = inbox.status();
				say(`受信箱: ${s.on ? "on" : "off"} / 未受領 ${s.unread} 件 / 最後の確認 ${s.lastTick ?? "-"} / 開始 ${s.startedAt ?? "-"}`, "info");
			} else {
				await inbox.take({ pi, ctx });
			}
		},
	});
}

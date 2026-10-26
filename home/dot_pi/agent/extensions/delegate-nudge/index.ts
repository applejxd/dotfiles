// 親の読み取り量と委譲の件数を、利用者の発言ごとに数えて記録するだけ (N1a。通知も結果の変更もしない)。
// 親だけで動く。記録は `delegate-stats` のカスタムエントリ。`/delegate-stats` で直近を見る。
// see docs/spec/guard/pi-extensions.md#自作の拡張-todo--plan--btw
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { randomBytes } from "node:crypto";

const ENTRY = "delegate-stats";
const READ_TOOLS = new Set(["guarded_read", "guarded_grep", "guarded_find", "guarded_ls", "read", "grep", "find", "ls"]);
const AGENTS = ["explore", "review", "commit", "worker"] as const;
const SHOW = 10;

type Agent = (typeof AGENTS)[number];
type Stats = {
	v: 1;
	turnId: string;
	seq: number;
	ts: string;
	nudge: "off";
	readCalls: number;
	readLines: number;
	readChars: number;
	readErrors: number;
	byTool: Record<string, number>;
	delegations: Record<Agent, number>;
	otherCalls: number;
	endReason: string;
};
type Turn = Omit<Stats, "seq" | "ts" | "endReason">;

const newTurn = (): Turn => ({
	v: 1,
	turnId: randomBytes(4).toString("hex"),
	nudge: "off",
	readCalls: 0,
	readLines: 0,
	readChars: 0,
	readErrors: 0,
	byTool: {},
	delegations: { explore: 0, review: 0, commit: 0, worker: 0 },
	otherCalls: 0,
});

// 実質の値があるときだけ「指定あり」とみなす (harness の parseTaskInput と同じ。埋め草の "" / false / 0 / [] を除く)
const has = (p: any, k: string) => {
	const v = p?.[k];
	return v !== undefined && v !== null && v !== false && v !== "" && v !== 0 && !(Array.isArray(v) && v.length === 0);
};
const isAgent = (a: unknown): a is Agent => (AGENTS as readonly string[]).includes(a as string);

// 新しい子の起動の agent 名の一覧。status・steer・追加依頼 (jobId つき)・list は空
function newAgents(p: any): Agent[] {
	if (has(p, "list") || has(p, "jobId")) return [];
	if (has(p, "tasks")) {
		if (!Array.isArray(p.tasks)) return [];
		return p.tasks.filter((t: any) => isAgent(t?.agent) && typeof t?.task === "string" && t.task !== "").map((t: any) => t.agent);
	}
	return isAgent(p?.agent) && typeof p?.task === "string" && p.task !== "" ? [p.agent] : [];
}

const lineCount = (s: string) => (s === "" ? 0 : s.split("\n").length);

export default function (pi: ExtensionAPI) {
	if (process.env.PI_HARNESS_CHILD === "1" || process.env.PI_DELEGATE_NUDGE === "0") return;

	let turn: Turn | undefined;
	let hint: string | undefined;
	let seq = 0;
	let records: Stats[] = [];

	const ensure = () => (turn ??= newTurn());
	// 未記録の集計を 1 回だけ書く (書いたら turn を空にするので、二重には書かない)
	const flush = (reason: string) => {
		const t = turn;
		turn = undefined;
		hint = undefined;
		if (!t) return;
		const data: Stats = { ...t, seq: ++seq, ts: new Date().toISOString(), endReason: reason };
		records.push(data);
		pi.appendEntry(ENTRY, data);
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
			turn = undefined;
			hint = undefined;
			records = [];
			for (const entry of ctx.sessionManager.getBranch() as any[]) {
				if (entry?.type === "custom" && entry.customType === ENTRY && typeof entry.data?.seq === "number") records.push(entry.data);
			}
			seq = records.reduce((m, r) => Math.max(m, r.seq), 0);
		}),
	);
	pi.on(
		"before_agent_start",
		safe((event: any) => {
			// 利用者の発言ごとに区切る。拡張が起こした続行は、同じ発言として数える
			if (event?.messageType !== "user") {
				ensure();
				return;
			}
			flush("next_user");
			turn = newTurn();
		}),
	);
	pi.on(
		"agent_end",
		safe((event: any) => {
			const last = [...(event?.messages ?? [])].reverse().find((m: any) => m?.role === "assistant");
			hint = last?.stopReason === "aborted" ? "aborted" : last?.stopReason === "error" ? "error" : undefined;
		}),
	);
	pi.on(
		"agent_settled",
		safe((event: any) => {
			flush(event?.aborted === true ? "aborted" : (hint ?? "completed"));
		}),
	);
	pi.on(
		"session_shutdown",
		safe(() => flush("shutdown")),
	);

	pi.on(
		"tool_call",
		safe((event: any) => {
			const t = ensure();
			if (READ_TOOLS.has(event?.toolName)) return;
			t.otherCalls++;
			if (event?.toolName === "guarded_task") for (const a of newAgents(event.input)) t.delegations[a]++;
		}),
	);
	pi.on(
		"tool_result",
		safe((event: any) => {
			if (!READ_TOOLS.has(event?.toolName)) return;
			const t = ensure();
			t.readCalls++;
			t.byTool[event.toolName] = (t.byTool[event.toolName] ?? 0) + 1;
			if (event.isError === true) t.readErrors++;
			for (const c of Array.isArray(event.content) ? event.content : []) {
				if (c?.type !== "text" || typeof c.text !== "string") continue;
				t.readLines += lineCount(c.text);
				t.readChars += c.text.length;
			}
		}),
	);

	pi.registerCommand("delegate-stats", {
		description: "直近の発言ごとの、読み取り量と委譲の件数 (記録のみ。通知はしない)",
		handler: async (_args, ctx) => {
			try {
				if (!ctx.hasUI) return;
				if (records.length === 0) return ctx.ui.notify("記録はまだありません", "info");
				const shown = records.slice(-SHOW);
				const deleg = (r: Stats) => AGENTS.reduce((n, a) => n + (r.delegations?.[a] ?? 0), 0);
				const rows = shown.map((r) => `#${r.seq}: 読み取り ${r.readCalls} 回 / ${r.readLines} 行 / 委譲 ${deleg(r)} 件`);
				const sum = (f: (r: Stats) => number) => records.reduce((n, r) => n + f(r), 0);
				rows.push(`合計 (${records.length} 発言): 読み取り ${sum((r) => r.readCalls)} 回 / ${sum((r) => r.readLines)} 行 / 委譲 ${sum(deleg)} 件`);
				ctx.ui.notify(rows.join("\n"), "info");
			} catch {}
		},
	});
}

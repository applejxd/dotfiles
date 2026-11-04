// 作業台帳の不変条件 I1〜I10。check(state, prev?) は違反の一覧を返す (空なら健全)。reducer の後に毎回検査する。純関数。
// prev を渡すと、前の状態との比較が要る条件 (I7 の追記のみ・I3 の使用量の単調増加) も検査する。仕様: docs/spec/work/ledger.md
import { NOTE_MAX } from "./events.ts";
import { globsMayOverlap } from "./globs.ts";
import { isLiveRun, isTaskLike, MONEY_KEYS } from "./reduce.ts";
import type { LedgerState } from "./reduce.ts";
import type { Node } from "./types.ts";

export { globsMayOverlap };

export interface Violation {
	inv: string;
	node?: string;
	message: string;
}

const EPS = 1e-9;
const ACTIVE = ["running", "waiting", "checking"];

/** I1: after が非循環 (任意の長さ)・依存先が存在する。色塗りの反復 DFS で、見つけた循環ごとに 1 件 */
const i1 = (s: LedgerState, out: Violation[]): void => {
	const color = new Map<string, number>(); // 1 = 探索中, 2 = 完了
	for (const root of s.nodes.keys()) {
		if (color.get(root)) continue;
		const stack: { id: string; i: number }[] = [{ id: root, i: 0 }];
		color.set(root, 1);
		while (stack.length > 0) {
			const top = stack[stack.length - 1];
			const after = s.nodes.get(top.id)?.after ?? [];
			if (top.i >= after.length) {
				color.set(top.id, 2);
				stack.pop();
				continue;
			}
			const to = after[top.i++];
			if (!s.nodes.has(to)) {
				out.push({ inv: "I1", node: top.id, message: `依存先 ${to} が存在しない` });
				continue;
			}
			const c = color.get(to);
			if (c === 1) out.push({ inv: "I1", node: top.id, message: `after が循環する (${top.id} → ${to})` });
			else if (!c) {
				color.set(to, 1);
				stack.push({ id: to, i: 0 });
			}
		}
	}
};

/** I2: running には生きた run か開いた wait。waiting には開いた wait */
const i2 = (s: LedgerState, out: Violation[]): void => {
	const live = new Set<string>();
	for (const n of s.nodes.values()) if (isLiveRun(n) && n.parent) live.add(n.parent);
	for (const n of s.nodes.values()) {
		if (!isTaskLike(n)) continue;
		if (n.state === "running" && !live.has(n.id) && n.waits.length === 0) {
			out.push({ inv: "I2", node: n.id, message: "running なのに生きた run も開いた wait も無い" });
		}
		if (n.state === "waiting" && n.waits.length === 0) out.push({ inv: "I2", node: n.id, message: "waiting なのに開いた wait が無い" });
	}
};

/** I3: 各階層で spent ≤ reserved ≤ budget、親の reserved・spent ≥ Σ 子。prev があれば spent は減らない */
const i3 = (s: LedgerState, prev: LedgerState | undefined, out: Violation[]): void => {
	const sums = new Map<string, { reserved: number[]; spent: number[] }>();
	for (const n of s.nodes.values()) {
		for (const k of MONEY_KEYS) {
			if (n.spent[k] < -EPS || n.reserved[k] < -EPS) out.push({ inv: "I3", node: n.id, message: `${k} が負` });
			if (n.spent[k] > n.reserved[k] + EPS) {
				out.push({ inv: "I3", node: n.id, message: `spent ${k} (${n.spent[k]}) > reserved (${n.reserved[k]})` });
			}
			if (n.budget && n.reserved[k] > n.budget[k] + EPS) {
				out.push({ inv: "I3", node: n.id, message: `reserved ${k} (${n.reserved[k]}) > budget (${n.budget[k]})` });
			}
		}
		if (n.parent) {
			const a = sums.get(n.parent) ?? { reserved: [0, 0, 0], spent: [0, 0, 0] };
			MONEY_KEYS.forEach((k, i) => {
				a.reserved[i] += n.reserved[k];
				a.spent[i] += n.spent[k];
			});
			sums.set(n.parent, a);
		}
	}
	for (const [pid, a] of sums) {
		const p = s.nodes.get(pid);
		if (!p) continue;
		MONEY_KEYS.forEach((k, i) => {
			if (p.reserved[k] + EPS < a.reserved[i]) {
				out.push({ inv: "I3", node: pid, message: `reserved ${k} (${p.reserved[k]}) < Σ 子 (${a.reserved[i]})` });
			}
			if (p.spent[k] + EPS < a.spent[i]) out.push({ inv: "I3", node: pid, message: `spent ${k} (${p.spent[k]}) < Σ 子 (${a.spent[i]})` });
		});
	}
	if (prev) {
		for (const [id, o] of prev.nodes) {
			const n = s.nodes.get(id);
			if (!n) continue;
			for (const k of MONEY_KEYS) if (n.spent[k] + EPS < o.spent[k]) out.push({ inv: "I3", node: id, message: `spent ${k} が減った` });
		}
	}
};

/** I4: 同時に走る task (running・waiting・checking) の writes は互いに素。保守的に判定する (迷えば重なる) */
const i4 = (s: LedgerState, out: Violation[]): void => {
	const isWriter = (n: Node) => (n.kind === "task" || n.kind === "integrate") && ACTIVE.includes(n.state) && n.writes.length > 0;
	const act = [...s.nodes.values()].filter(isWriter);
	for (let i = 0; i < act.length; i++) {
		for (let j = i + 1; j < act.length; j++) {
			if (act[i].writes.some((a) => act[j].writes.some((b) => globsMayOverlap(a, b)))) {
				out.push({ inv: "I4", node: act[i].id, message: `writes が ${act[j].id} と重なる` });
			}
		}
	}
};

/** I5: 待ちの形 (user 待ちは auto でない・重複なし) と、解除の記録 (user 待ちは利用者だけ、他は同種の事実か利用者) */
const i5 = (s: LedgerState, out: Violation[]): void => {
	for (const n of s.nodes.values()) {
		const keys = new Set<string>();
		for (const w of n.waits) {
			if (w.on === "user" && w.auto) out.push({ inv: "I5", node: n.id, message: `user 待ち ${w.ref} が auto` });
			const k = `${w.on}:${w.ref}`;
			if (keys.has(k)) out.push({ inv: "I5", node: n.id, message: `待ち ${k} が重複` });
			keys.add(k);
		}
	}
	for (const r of s.resolutions) {
		const ok = r.on === "user" ? r.by === "user" && r.source === "user" : r.by === r.on || (r.by === "user" && r.source === "user");
		if (!ok) out.push({ inv: "I5", node: r.node, message: `${r.on} 待ち ${r.ref} が ${r.by} (出所 ${r.source}) で解除された (seq ${r.seq})` });
	}
};

const settled = (n: Node): boolean => n.state === "done" || n.state === "skipped" || n.state === "cancelled";

const chainHas = (s: LedgerState, id: string, anc: string): boolean => {
	let cur = s.nodes.get(id)?.parent;
	for (let i = 0; cur !== undefined && i < 10000; i++) {
		if (cur === anc) return true;
		cur = s.nodes.get(cur)?.parent;
	}
	return false;
};

/** I6: done の task には check の証拠。goal の done には verdict done と全 task の決着 */
const i6 = (s: LedgerState, out: Violation[]): void => {
	for (const n of s.nodes.values()) {
		if (isTaskLike(n) && n.state === "done" && !n.evidence.some((e) => e.startsWith("check:"))) {
			out.push({ inv: "I6", node: n.id, message: "done なのに check の証拠が無い" });
		}
		if (n.kind !== "goal" || n.state !== "done") continue;
		if (!n.evidence.some((e) => /^verdict:\d+:done$/.test(e))) {
			out.push({ inv: "I6", node: n.id, message: "goal が done なのに verdict done が無い" });
		}
		for (const t of s.nodes.values()) {
			if (t.id === n.id || !(isTaskLike(t) || isLiveRun(t)) || !chainHas(s, t.id, n.id)) continue;
			if (isLiveRun(t) || !settled(t)) out.push({ inv: "I6", node: n.id, message: `goal が done なのに ${t.id} が未決着 (${t.state})` });
		}
	}
};

/** I7: 注釈は追記のみ (prev の注釈は現在の先頭に変わらず残る)・上限の字数・差出人の形 */
const i7 = (s: LedgerState, prev: LedgerState | undefined, out: Violation[]): void => {
	for (const n of s.nodes.values()) {
		for (const note of n.notes) {
			if (note.text.length > NOTE_MAX) out.push({ inv: "I7", node: n.id, message: `注釈が ${NOTE_MAX} 字を超える` });
			if (!(note.by === "user" || note.by === "llm" || note.by.startsWith("run:"))) {
				out.push({ inv: "I7", node: n.id, message: `注釈の差出人が不正 (${note.by})` });
			}
		}
	}
	if (!prev) return;
	for (const [id, o] of prev.nodes) {
		const n = s.nodes.get(id);
		if (!n) {
			out.push({ inv: "I7", node: id, message: "ノードが消えた (台帳は追記のみ)" });
			continue;
		}
		if (n.notes.length < o.notes.length || o.notes.some((x, i) => JSON.stringify(x) !== JSON.stringify(n.notes[i]))) {
			out.push({ inv: "I7", node: id, message: "既存の注釈が変更・削除された" });
		}
	}
};

/** I8: lease の形 (保持者がいる・goal だけが持つ)。保持者でない追記は reducer が拒否し、拒否できなかった分は anomalies に残る */
const i8 = (s: LedgerState, out: Violation[]): void => {
	for (const n of s.nodes.values()) {
		if (n.owner && (!n.owner.holder || !Number.isInteger(n.owner.pid))) out.push({ inv: "I8", node: n.id, message: "lease の保持者か pid が不正" });
		if (n.owner && n.kind !== "goal") out.push({ inv: "I8", node: n.id, message: "lease は goal だけが持つ" });
	}
	for (const a of s.anomalies) if (a.inv === "I8") out.push({ inv: "I8", message: a.message });
};

/** I9: seq に欠番も重複もない */
const i9 = (s: LedgerState, out: Violation[]): void => {
	for (const a of s.anomalies) if (a.inv === "I9") out.push({ inv: "I9", message: a.message });
};

/** I10: 利用者専用イベントの出所。active 以降の goal は、利用者の承認 (plan.approved) を経ている */
const i10 = (s: LedgerState, out: Violation[]): void => {
	for (const n of s.nodes.values()) {
		if (n.kind === "goal" && ["active", "paused", "done"].includes(n.state) && n.attrs.approvedBy !== "user") {
			out.push({ inv: "I10", node: n.id, message: `goal が ${n.state} なのに利用者の承認が無い` });
		}
	}
	for (const a of s.anomalies) if (a.inv === "I10") out.push({ inv: "I10", message: a.message });
};

export const check = (state: LedgerState, prev?: LedgerState): Violation[] => {
	const out: Violation[] = [];
	i1(state, out);
	i2(state, out);
	i3(state, prev, out);
	i4(state, out);
	i5(state, out);
	i6(state, out);
	i7(state, prev, out);
	i8(state, out);
	i9(state, out);
	i10(state, out);
	return out;
};

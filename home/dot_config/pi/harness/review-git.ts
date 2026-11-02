// PR レビュー状態を git の ref (refs/pi/review/<prKey>) に保存する入出力。
// git の実行は注入で受ける (作業ディレクトリは呼び出し側が束縛する)。worktree.ts などは import しない。
// 書き込むのは refs/pi/review/ の下だけ。スキーマの正本: .tmp/keep/pr-viewer/design-decisions.md §2。
import {
	LIMITS,
	SCHEMA,
	checkAppend,
	foldState,
	mergedOk,
	parseEvents,
	prKeyOf,
	serializeEvents,
	type Meta,
	type ReviewEvent,
	type State,
	type Vs,
} from "./review-log.ts";

export type GitResult = { code: number; stdout: string; stderr: string };
export type Git = (argv: string[], opts?: { input?: string }) => Promise<GitResult>;

export const REF_PREFIX = "refs/pi/review/";
const ZERO = "0".repeat(40);
const OID_RE = /^[0-9a-f]{40}$/;
const KEY_RE = /^p[0-9a-f]{16}$/;
const MAX_ATTEMPTS = 8;

export function refOf(prKey: string): string {
	if (!KEY_RE.test(prKey)) throw new Error("invalid prKey");
	return REF_PREFIX + prKey;
}

export async function listPrKeys(git: Git): Promise<string[]> {
	const r = await git(["for-each-ref", "--format=%(refname)", REF_PREFIX]);
	if (r.code !== 0) return [];
	return r.stdout
		.split("\n")
		.filter((l) => l.startsWith(REF_PREFIX))
		.map((l) => l.slice(REF_PREFIX.length))
		.filter((k) => KEY_RE.test(k));
}

export type PrRead =
	| { kind: "none" }
	| { kind: "ok"; commit: string; meta: Meta; metaText: string; eventsText: string; events: ReviewEvent[] }
	| { kind: "readonly"; commit: string; meta: Record<string, unknown> }
	| { kind: "bad"; reason: string };

const bad = (reason: string): PrRead => ({ kind: "bad", reason });

async function blobSize(git: Git, oid: string): Promise<number> {
	const r = await git(["cat-file", "-s", oid]);
	const n = Number(r.stdout.trim());
	return r.code === 0 && Number.isInteger(n) ? n : -1;
}

/** ref の commit を、自己検査しながら読む。巨大な blob は読まない */
export async function readPr(git: Git, prKey: string): Promise<PrRead> {
	const ref = refOf(prKey);
	const rp = await git(["rev-parse", "--verify", "--quiet", ref]);
	if (rp.code !== 0) return { kind: "none" };
	const commit = rp.stdout.trim();
	if (!OID_RE.test(commit)) return bad("bad_ref");
	const ls = await git(["ls-tree", "-z", commit]);
	if (ls.code !== 0) return bad("tree_unreadable");
	const entries = ls.stdout.split("\0").filter((s) => s !== "");
	const files = new Map<string, string>();
	for (const ent of entries) {
		const m = /^(\d+) (\w+) ([0-9a-f]{40})\t(.+)$/.exec(ent);
		if (!m) return bad("bad_tree_entry");
		if (m[1] !== "100644" || m[2] !== "blob") return bad("bad_tree_mode");
		files.set(m[4], m[3]);
	}
	if (files.size !== 2 || entries.length !== 2 || !files.has("meta.json") || !files.has("events.jsonl")) return bad("bad_tree_files");
	const metaOid = files.get("meta.json")!;
	const evOid = files.get("events.jsonl")!;
	const ms = await blobSize(git, metaOid);
	if (ms < 0 || ms > LIMITS.metaBytes) return bad("meta_too_large");
	const es = await blobSize(git, evOid);
	if (es < 0 || es > LIMITS.eventsBytes) return bad("events_too_large");
	const mr = await git(["cat-file", "blob", metaOid]);
	if (mr.code !== 0) return bad("meta_unreadable");
	let meta: unknown;
	try {
		meta = JSON.parse(mr.stdout);
	} catch {
		return bad("meta_invalid_json");
	}
	if (typeof meta !== "object" || meta === null || Array.isArray(meta)) return bad("meta_invalid");
	const m = meta as Record<string, unknown>;
	if (typeof m.schema !== "number" || !Number.isInteger(m.schema) || m.schema < 1) return bad("meta_invalid");
	if (m.schema > SCHEMA) return { kind: "readonly", commit, meta: m };
	if (typeof m.pr !== "string" || typeof m.branch !== "string" || typeof m.target !== "string" || typeof m.createdAt !== "string") {
		return bad("meta_invalid");
	}
	if (m.pr !== prKey || prKeyOf(m.branch) !== prKey) return bad("pr_key_mismatch");
	const er = await git(["cat-file", "blob", evOid]);
	if (er.code !== 0) return bad("events_unreadable");
	const parsed = parseEvents(er.stdout);
	if (!parsed.ok) return bad(parsed.reason);
	return { kind: "ok", commit, meta: m as unknown as Meta, metaText: mr.stdout, eventsText: er.stdout, events: parsed.events };
}

export type BuildResult = ReviewEvent[] | null | { refuse: string };
export type AppendOpts = {
	/** 現在の source・target・base (stale の判定に使う)。省略時は最後の記録の vs */
	current?: Vs;
	/** 競合時の待ち時間の揺らぎ (ms) の上限。既定 8 */
	jitterMs?: number;
};
export type AppendResult =
	| { ok: true; commit: string }
	| { ok: true; noop: true }
	| { ok: false; refused: string }
	| { ok: false; error: string };

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** 追記する。CAS (update-ref の旧値つき) で競合したら再読して build をやり直す (最大 8 回) */
export async function appendEvents(
	git: Git,
	prKey: string,
	metaIfNew: Meta | null,
	build: (state: State) => BuildResult | Promise<BuildResult>,
	opts: AppendOpts = {},
): Promise<AppendResult> {
	const ref = refOf(prKey);
	for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
		if (attempt > 0) await sleep(Math.random() * (opts.jitterMs ?? 8) * attempt);
		const cur = await readPr(git, prKey);
		if (cur.kind === "bad") return { ok: false, refused: "bad" };
		if (cur.kind === "readonly") return { ok: false, refused: "readonly" };
		let meta: Meta;
		let metaText: string;
		let oldText = "";
		let oldEvents: ReviewEvent[] = [];
		let oldCommit = ZERO;
		if (cur.kind === "ok") {
			meta = cur.meta;
			metaText = cur.metaText;
			oldText = cur.eventsText;
			oldEvents = cur.events;
			oldCommit = cur.commit;
		} else {
			if (!metaIfNew) return { ok: false, refused: "not_found" };
			if (metaIfNew.pr !== prKey || prKeyOf(metaIfNew.branch) !== prKey || metaIfNew.schema !== SCHEMA) {
				return { ok: false, refused: "bad_meta" };
			}
			if ((await listPrKeys(git)).length >= LIMITS.prs) return { ok: false, refused: "too_many_prs" };
			meta = metaIfNew;
			metaText = JSON.stringify(metaIfNew) + "\n";
		}
		const lastVs = oldEvents.length > 0 ? oldEvents[oldEvents.length - 1].vs : null;
		const state = foldState(meta, oldEvents, opts.current ?? lastVs ?? { source: ZERO, target: ZERO, base: ZERO });
		if (mergedOk(state)) return { ok: false, refused: "merged" };
		const out = await build(state);
		if (out === null) return { ok: true, noop: true };
		if (!Array.isArray(out)) return { ok: false, refused: String(out.refuse) };
		if (out.length === 0) return { ok: true, noop: true };

		let bytes = Buffer.byteLength(oldText, "utf8");
		let count = oldEvents.length;
		for (const e of out) {
			const c = checkAppend(bytes, count, e);
			if (!c.ok) return { ok: false, refused: c.reason };
			bytes += Buffer.byteLength(JSON.stringify(e) + "\n", "utf8");
			count++;
		}
		const newText = oldText + serializeEvents(out);
		const check = parseEvents(newText);
		if (!check.ok) return { ok: false, refused: "invalid_event" };

		// 記録する source (最初の記録と、source が変わったときの新しい source) を、追加の親にする。
		// 追記を待たずに、最後にレビューした版も gc 後に到達できる (前の版は、その時点の commit が親として持つ)
		const extra: string[] = [];
		let prev = lastVs ? lastVs.source : null;
		for (const e of out) {
			if (e.vs.source !== prev && !extra.includes(e.vs.source)) {
				const t = await git(["cat-file", "-t", e.vs.source]);
				if (t.code === 0 && t.stdout.trim() === "commit") extra.push(e.vs.source);
			}
			prev = e.vs.source;
		}

		const mb = await git(["hash-object", "-w", "--stdin"], { input: metaText });
		const eb = await git(["hash-object", "-w", "--stdin"], { input: newText });
		if (mb.code !== 0 || eb.code !== 0) return { ok: false, error: "git_failed" };
		const tree = await git(["mktree"], {
			input: `100644 blob ${eb.stdout.trim()}\tevents.jsonl\n100644 blob ${mb.stdout.trim()}\tmeta.json\n`,
		});
		if (tree.code !== 0) return { ok: false, error: "git_failed" };
		const kinds = [...new Set(out.map((e) => e.t))].join(",");
		const parents = [...(oldCommit === ZERO ? [] : [oldCommit]), ...extra].flatMap((p) => ["-p", p]);
		const cm = await git(
			[
				"-c",
				"user.name=pr-review",
				"-c",
				"user.email=pr-review@localhost",
				"-c",
				"commit.gpgsign=false",
				"commit-tree",
				tree.stdout.trim(),
				...parents,
				"-F",
				"-",
			],
			{ input: `pr-review: ${kinds}\n` },
		);
		const commit = cm.stdout.trim();
		if (cm.code !== 0 || !OID_RE.test(commit)) return { ok: false, error: "git_failed" };
		const up = await git(["update-ref", "--no-deref", ref, commit, oldCommit]);
		if (up.code === 0) return { ok: true, commit };
		// 競合 (旧値が違う)。再読して build をやり直す
	}
	return { ok: false, error: "cas_exhausted" };
}

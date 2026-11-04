// PR レビュー (ローカル PR ビューア) の pi 側: 道具 pr_summary (作業のサマリーをレビュー画面へ投稿する)。
// 状態の正本は git の ref (review-log.ts・review-git.ts)。アプリへは通信しない (アプリが止まっていても動く。C2・C7)。
// レビューコメントの送信 (コメントを読む道具と、次の入力の前の注入) は撤去した。see docs/spec/pr-viewer.md
import { spawn } from "node:child_process";
import { appendEvents, type AppendResult, type Git } from "./review-git.ts";
import { newId, prKeyOf, type Meta, type ReviewEvent, type Vs } from "./review-log.ts";

export const PR_SUMMARY_TOOL = "pr_summary";

const BRANCH_RE = /^(feature|bugfix)\/[A-Za-z0-9._-]+(\/[A-Za-z0-9._-]+)*$/;
const TARGETS = ["develop", "main", "master"];
const MAX_FIELD = 4000;
const GIT_TIMEOUT_MS = 15_000;

// 設定が指す外部のコードを動かさない固定の先頭引数 (アプリの git-view.ts と同じ考え方)
const SAFE_ARGS = [
	"--no-pager",
	"--no-replace-objects",
	"--literal-pathspecs",
	"-c",
	"core.hooksPath=/dev/null",
	"-c",
	"core.fsmonitor=false",
	"-c",
	"core.pager=cat",
	"-c",
	"gc.auto=0",
	"-c",
	"maintenance.auto=false",
];

/** 作業ディレクトリを束縛した、非同期の git 実行 (review-git.ts に注入する) */
export function gitIn(cwd: string): Git {
	return (argv, opts) =>
		new Promise((resolve) => {
			const child = spawn("git", [...SAFE_ARGS, ...argv], {
				cwd,
				env: {
					...process.env,
					GIT_TERMINAL_PROMPT: "0",
					GIT_OPTIONAL_LOCKS: "0",
					LC_ALL: "C",
					// partial clone で足りないオブジェクトを読んだときに、git が自動で fetch (ssh などを起動) するのを止める (C9)
					GIT_NO_LAZY_FETCH: "1",
					GIT_ALLOW_PROTOCOL: "",
				},
				stdio: ["pipe", "pipe", "pipe"],
			});
			let stdout = "";
			let stderr = "";
			let done = false;
			const finish = (code: number, err = "") => {
				if (done) return;
				done = true;
				clearTimeout(timer);
				resolve({ code, stdout, stderr: err || stderr });
			};
			const timer = setTimeout(() => {
				child.kill("SIGKILL");
				finish(124, "timeout");
			}, GIT_TIMEOUT_MS);
			child.stdout.on("data", (d) => (stdout += d));
			child.stderr.on("data", (d) => (stderr += d));
			child.on("error", () => finish(127, "spawn_failed"));
			child.on("close", (code) => finish(code ?? 1));
			child.stdin.on("error", () => {});
			child.stdin.end(opts?.input ?? "");
		});
}

type Resolved = { ok: true; key: string; targetName: string; vs: Vs } | { ok: false; error: string };

/** ブランチ名から、PR の鍵と、現在の source・target・base の OID を求める */
async function resolveBranch(git: Git, branch: string): Promise<Resolved> {
	if (typeof branch !== "string" || !BRANCH_RE.test(branch) || branch.includes("..")) {
		return { ok: false, error: "branch は feature/<名前> か bugfix/<名前> の形で指定してください" };
	}
	const oidOf = async (ref: string): Promise<string | null> => {
		const r = await git(["rev-parse", "--verify", "--quiet", `${ref}^{commit}`]);
		const oid = r.stdout.trim();
		return r.code === 0 && /^[0-9a-f]{40}$/.test(oid) ? oid : null;
	};
	const source = await oidOf(`refs/heads/${branch}`);
	if (!source) return { ok: false, error: `ブランチ ${branch} が見つかりません` };
	let targetName = "";
	let target: string | null = null;
	for (const t of TARGETS) {
		target = await oidOf(`refs/heads/${t}`);
		if (target) {
			targetName = t;
			break;
		}
	}
	if (!target) return { ok: false, error: "統合先 (develop・main・master) が見つかりません" };
	const mb = await git(["merge-base", target, source]);
	const base = mb.stdout.trim();
	if (mb.code !== 0 || !/^[0-9a-f]{40}$/.test(base)) return { ok: false, error: "統合先との共通の祖先が見つかりません" };
	return { ok: true, key: prKeyOf(branch), targetName, vs: { source, target, base } };
}

const metaOf = (branch: string, r: { key: string; targetName: string }, now: string): Meta => ({
	schema: 1,
	pr: r.key,
	branch,
	target: r.targetName,
	createdAt: now,
});

const REFUSED: Record<string, string> = {
	merged: "統合済みの PR には書けません。ブランチ名を変えてください",
	bad: "この PR の ref が壊れているため書けません",
	readonly: "この PR の ref の版が新しいため書けません (pi を更新してください)",
	body_too_large: "本文が上限 (16 KB) を超えています",
	events_too_large: "この PR のイベントが上限に達しました",
	too_many_events: "この PR のイベントが上限に達しました",
	reserved: "この PR のイベントが上限に近いため、これ以上書けません",
	too_many_prs: "PR の数が上限に達しました",
};

function describe(res: AppendResult, done: string): { text: string; isError: boolean } {
	if ("noop" in res) return { text: "変更はありません", isError: false };
	if (res.ok) return { text: done, isError: false };
	if ("refused" in res) return { text: REFUSED[res.refused] ?? `書き込みを断りました (${res.refused})`, isError: true };
	return { text: `書き込めませんでした (${res.error})`, isError: true };
}

export type PrDeps = {
	Type: any;
	prefix: string;
	child: boolean;
	/** 役割の道具に含まれるか (profile_tools) */
	hasTool: (name: string) => boolean;
	gitFor?: (cwd: string) => Git;
	now?: () => string;
};

const result = (text: string, isError = false) => ({ content: [{ type: "text", text }], details: {}, isError });

/** 道具を登録する。子 (worker など) には何も登録しない */
export function registerPr(pi: any, deps: PrDeps): void {
	if (deps.child) return;
	const gitFor = deps.gitFor ?? gitIn;
	const now = deps.now ?? (() => new Date().toISOString());
	const T = deps.Type;

	if (deps.hasTool(PR_SUMMARY_TOOL)) {
		pi.registerTool({
			name: `${deps.prefix}${PR_SUMMARY_TOOL}`,
			label: "pr_summary",
			promptSnippet: "Post a completion summary to the local PR review (a feature branch). Writes only refs/pi/review/*",
			promptGuidelines: [
				`${deps.prefix}${PR_SUMMARY_TOOL}: after finishing the work for a feature/bugfix branch, post what you did, the changed files, how you handled each point the user raised, and what the user should check. Do not include test results (the review screen shows them).`,
			],
			description:
				"Post a work summary for a feature or bugfix branch to the local PR review screen. Arguments: branch (feature/<name> or bugfix/<name>), done (what you did), files (changed files), findings (optional: how you handled each point the user raised: {ref: a short label for the point, reply}), notes (optional: points to check, unverified items, limits), mergeMessage (optional: a draft of the merge message).",
			parameters: T.Object(
				{
					branch: T.String({ description: "feature/<name> or bugfix/<name>" }),
					done: T.String({ description: "what you did (a short summary)" }),
					files: T.Array(T.String(), { description: "changed files" }),
					findings: T.Optional(
						T.Array(T.Object({ ref: T.String({ description: "a short label for the point the user raised" }), reply: T.String() }, { additionalProperties: false })),
					),
					notes: T.Optional(T.String({ description: "points to check, unverified items, limits" })),
					mergeMessage: T.Optional(T.String({ description: "a draft of the merge message" })),
				},
				{ additionalProperties: false },
			),
			async execute(_id: string, p: any, _signal: any, _onUpdate: any, ctx: any) {
				try {
					const git = gitFor(ctx.cwd);
					const r = await resolveBranch(git, p.branch);
					if (!r.ok) return result(r.error, true);
					const files: unknown = p.files;
					const findings: unknown = p.findings ?? [];
					if (typeof p.done !== "string" || p.done.trim() === "" || p.done.length > MAX_FIELD) return result(`done は 1〜${MAX_FIELD} 文字で指定してください`, true);
					if (!Array.isArray(files) || files.length > 200 || files.some((f) => typeof f !== "string" || f.length > 300)) {
						return result("files は 200 件まで・各 300 文字までの文字列の配列です", true);
					}
					if (
						!Array.isArray(findings) ||
						findings.length > 100 ||
						findings.some((f: any) => typeof f?.ref !== "string" || typeof f?.reply !== "string" || f.reply.length > MAX_FIELD)
					) {
						return result("findings は 100 件まで ({ref, reply}) の配列です", true);
					}
					for (const k of ["notes", "mergeMessage"]) {
						if (p[k] !== undefined && (typeof p[k] !== "string" || p[k].length > MAX_FIELD)) return result(`${k} は ${MAX_FIELD} 文字までの文字列です`, true);
					}
					const at = now();
					const d: Record<string, unknown> = { done: p.done, files, findings };
					if (p.notes !== undefined) d.notes = p.notes;
					if (p.mergeMessage !== undefined) d.mergeMessage = p.mergeMessage;
					const ev = { v: 1, id: newId(), t: "summary", by: "pi", at, vs: r.vs, d } as ReviewEvent;
					const res = await appendEvents(git, r.key, metaOf(p.branch, r, at), () => [ev], { current: r.vs });
					const out = describe(res, `サマリーを ${p.branch} のレビューに投稿しました`);
					return result(out.text, out.isError);
				} catch {
					return result("pr_summary が失敗しました", true);
				}
			},
		});
	}
}

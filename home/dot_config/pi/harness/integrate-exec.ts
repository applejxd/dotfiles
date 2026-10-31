// 保護ブランチへの統合 (squash) の実行器。承認前に算出した計画 (IntegratePlan) をそのとおりに反映する。
// 結果の commit は通常の git commit で作る (pre-commit・commit-msg・署名をそのまま通す)。ref だけを進めない。
// see docs/change/0055
import { execFile } from "node:child_process";
import { existsSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, sep } from "node:path";
import type { IntegratePlan } from "./integrate-plan.ts";
import type { ResultBody } from "./pending-ops.ts";
import { repoTargetEnv } from "./pending-store.ts";

export type IntegrateExecInput = {
	plan: IntegratePlan;
	cleanup: "none" | "branch" | "branch_and_worktree";
	/** 承認した pi の cwd。その worktree は片付けない */
	approverCwd: string;
	env?: NodeJS.ProcessEnv;
	signal?: AbortSignal;
	/** git commit (hook を含む) の時間切れ。既定 120000 */
	commitTimeoutMs?: number;
};

type G = { ok: boolean; code: number | null; out: string; err: string; timedOut: boolean; aborted: boolean; spawnFail: boolean };

// biome-ignore lint/suspicious/noControlCharactersInRegex: 制御文字の除去が目的
const CTRL_G = /[\u0000-\u001f\u007f]/g;

/** 1 文 500 文字以内・制御文字なしにする */
function clean(s: string): string {
	const t = s.replace(CTRL_G, " ").replace(/\s+/g, " ").trim();
	return t.length > 500 ? t.slice(0, 500) : t;
}
/** 長い出力は末尾 300 文字だけ */
function tail(s: string): string {
	const t = s.replace(CTRL_G, " ").replace(/\s+/g, " ").trim();
	return t.length > 300 ? t.slice(-300) : t;
}
const short = (oid: string) => oid.slice(0, 10);

function git(args: string[], cwd: string, env: NodeJS.ProcessEnv, opts: { timeout?: number; signal?: AbortSignal } = {}): Promise<G> {
	return new Promise((res) => {
		try {
			execFile(
				"git",
				args,
				{ cwd, env, encoding: "utf8", timeout: opts.timeout ?? 60000, signal: opts.signal, maxBuffer: 64 * 1024 * 1024 },
				(e, stdout, stderr) => {
					if (!e) return res({ ok: true, code: 0, out: stdout, err: stderr, timedOut: false, aborted: false, spawnFail: false });
					const x = e as { code?: unknown; killed?: boolean; name?: string; signal?: unknown };
					const aborted = x.name === "AbortError" || x.code === "ABORT_ERR";
					const timedOut = !aborted && x.killed === true;
					const spawnFail = typeof x.code === "string" && !aborted;
					res({ ok: false, code: typeof x.code === "number" ? x.code : null, out: stdout ?? "", err: stderr ?? "", timedOut, aborted, spawnFail });
				},
			);
		} catch (e) {
			res({ ok: false, code: null, out: "", err: String((e as Error).message ?? e), timedOut: false, aborted: false, spawnFail: true });
		}
	});
}

const OPS = ["MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "BISECT_LOG"];

export async function executeIntegration(input: IntegrateExecInput): Promise<ResultBody> {
	const body: ResultBody = { outcome: "not_executed", phase: "precheck", confirmedEffects: [], remainingCleanup: [], evidence: [] };
	const fin = (): ResultBody => {
		body.confirmedEffects = body.confirmedEffects.map(clean).slice(0, 50);
		body.remainingCleanup = body.remainingCleanup.map(clean).slice(0, 50);
		body.evidence = body.evidence.map(clean).slice(0, 50);
		return body;
	};
	const tmpRef: { dir: string | null } = { dir: null };
	let tmpDir: string | null = null;
	try {
		await run(input, body, tmpRef);
	} catch (e) {
		const first = String((e as Error)?.message ?? e).split("\n")[0];
		body.outcome = "unknown";
		body.evidence.push(`例外: ${first}`);
	} finally {
		tmpDir = tmpRef.dir;
		tmpRef.dir = null;
		if (tmpDir) {
			try {
				rmSync(tmpDir, { recursive: true, force: true });
			} catch {
				/* 一時ファイルの掃除の失敗は結果に影響しない */
			}
		}
	}
	return fin();
}

async function run(input: IntegrateExecInput, body: ResultBody, tmpRef: { dir: string | null }): Promise<void> {
	const { plan } = input;
	const base: NodeJS.ProcessEnv = { ...repoTargetEnv(input.env ?? process.env), GIT_OPTIONAL_LOCKS: "0", GIT_TERMINAL_PROMPT: "0" };
	const wt = plan.targetWorktree;
	const refuse = (phase: string, msg: string) => {
		body.outcome = "not_executed";
		body.phase = phase;
		body.evidence.push(msg);
	};

	// --- precheck ---
	if (!wt) return refuse("precheck", "統合先がどの worktree にもチェックアウトされていない");
	if (plan.message.trim() === "" || plan.message.length > 1200 || plan.message.includes("\0")) {
		return refuse("precheck", "統合のメッセージが空か長すぎるか、NUL を含む");
	}
	const head = await git(["symbolic-ref", "-q", "HEAD"], wt, base);
	if (!head.ok || head.out.trim() !== plan.target.ref) return refuse("precheck", "統合先の worktree の HEAD が、承認した統合先のブランチに付いていない");
	const tOid = await git(["rev-parse", "--verify", "--quiet", "HEAD^{commit}"], wt, base);
	const sOid = await git(["rev-parse", "--verify", "--quiet", `${plan.source.ref}^{commit}`], wt, base);
	if (!tOid.ok || tOid.out.trim() !== plan.target.oid || !sOid.ok || sOid.out.trim() !== plan.source.oid) {
		return refuse("precheck", "統合先・統合元が、承認した後に進んだ");
	}
	for (const op of OPS) {
		const p = await git(["rev-parse", "--git-path", op], wt, base);
		if (p.ok && existsSync(resolve(wt, p.out.trim()))) return refuse("precheck", `統合先の worktree で ${op} が進行中`);
	}
	const st = await git(["status", "--porcelain=v1", "-z", "--untracked-files=normal"], wt, base);
	if (!st.ok) return refuse("precheck", "統合先の worktree の状態を読めなかった");
	if (st.out !== "") return refuse("precheck", "統合先の worktree に未コミットの変更か追跡外のファイルがある");
	const drv = await git(["config", "--get-regexp", "^merge\\..*\\.driver$"], wt, base);
	if ((drv.ok && drv.out.trim() !== "") || (!drv.ok && drv.code !== 1)) return refuse("precheck", "外部の merge driver が設定されている (または確かめられない)");

	// 元に戻す (reset --hard)。戻せたか返す
	const rollback = async (): Promise<boolean> => {
		const r = await git(["reset", "--hard", plan.target.oid], wt, base);
		if (!r.ok) return false;
		const h = await git(["rev-parse", "HEAD"], wt, base);
		const s2 = await git(["status", "--porcelain=v1", "-z", "--untracked-files=normal"], wt, base);
		return h.ok && h.out.trim() === plan.target.oid && s2.ok && s2.out === "";
	};
	const unrolled = (phase: string, why: string) => {
		body.outcome = "unknown";
		body.phase = phase;
		body.evidence.push(why);
		body.remainingCleanup.push("作業ツリーに squash の変更が残っている");
	};

	// --- merge ---
	body.phase = "merge";
	const mg = await git(["merge", "--squash", "--no-commit", plan.source.oid], wt, base, { signal: input.signal });
	if (!mg.ok) {
		const why = `squash を反映できなかった: ${tail(mg.err || mg.out)}`;
		if (await rollback()) return refuse("merge", why);
		return unrolled("merge", why);
	}
	const wtree = await git(["write-tree"], wt, base);
	if (!wtree.ok || wtree.out.trim() !== plan.resultTree) {
		const why = "結果の tree が、承認した計画と違う";
		if (await rollback()) return refuse("merge", why);
		return unrolled("merge", why);
	}

	// --- commit ---
	body.phase = "commit";
	tmpRef.dir = mkdtempSync(join(tmpdir(), "integrate-"));
	const msgFile = join(tmpRef.dir, "msg");
	writeFileSync(msgFile, plan.message.endsWith("\n") ? plan.message : `${plan.message}\n`, { mode: 0o600 });
	const cenv: NodeJS.ProcessEnv = { ...base, GIT_EDITOR: "true" };
	const cm = await git(["commit", "-F", msgFile], wt, cenv, { timeout: input.commitTimeoutMs ?? 120000, signal: input.signal });
	if (!cm.ok) {
		const cur = await git(["rev-parse", "HEAD"], wt, base);
		if (!cur.ok) {
			body.outcome = "unknown";
			body.evidence.push("commit が失敗し、HEAD を確かめられなかった");
			return;
		}
		if (cur.out.trim() === plan.target.oid) {
			const why = cm.aborted ? "中断された" : cm.timedOut ? `commit が時間切れ: ${tail(cm.err || cm.out)}` : `commit が失敗した: ${tail(cm.err || cm.out)}`;
			if (await rollback()) {
				body.outcome = cm.aborted ? "not_executed" : "failed_confirmed";
				body.evidence.push(why);
				return;
			}
			return unrolled("commit", `${why} (元に戻せなかった)`);
		}
		body.evidence.push("commit は成立していた (失敗の報告だが HEAD が進んでいる)");
	}

	// --- verify ---
	body.phase = "verify";
	const info = await git(["log", "-1", "--format=%H%x00%P%x00%T%x00%B"], wt, base);
	if (!info.ok) {
		body.outcome = "unknown";
		body.evidence.push("commit の内容を読めなかった");
		return;
	}
	const [newHead, parents, tree, msg] = info.out.split("\0");
	const ps = parents.trim() === "" ? [] : parents.trim().split(/\s+/);
	if (ps.length !== 1 || ps[0] !== plan.target.oid) {
		body.outcome = "unknown";
		body.evidence.push(`commit の親が想定と違う: ${ps.map(short).join(",") || "なし"} (HEAD ${short(newHead)})`);
		return;
	}
	body.outcome = "success";
	if (tree.trim() !== plan.resultTree) body.evidence.push(`hook が内容を変えた: 計画の tree ${short(plan.resultTree)} → 実際 ${short(tree.trim())}`);
	else body.evidence.push("結果の tree は承認した計画と一致した");
	if ((msg ?? "").replace(/\n+$/, "") !== plan.message.replace(/\n+$/, "")) body.evidence.push("commit のメッセージが計画と違う (hook が変えた)");
	const headOid = newHead.trim();
	body.confirmedEffects.push(`${plan.target.ref} を ${short(headOid)} に進めた (squash)`);

	// --- cleanup ---
	if (input.cleanup !== "none") {
		body.phase = "cleanup";
		try {
			await cleanup(input, body, wt, base);
		} catch (e) {
			body.remainingCleanup.push(`後片付けで例外: ${String((e as Error)?.message ?? e).split("\n")[0]}`);
		}
	}
	body.phase = "done";
}

function real(p: string): string {
	try {
		return realpathSync(p);
	} catch {
		return resolve(p);
	}
}

async function cleanup(input: IntegrateExecInput, body: ResultBody, wt: string, env: NodeJS.ProcessEnv): Promise<void> {
	const { plan } = input;
	const ls = await git(["worktree", "list", "--porcelain"], wt, env);
	let w: string | null = null;
	let wHead = "";
	if (ls.ok) {
		let cur: string | null = null;
		let curHead = "";
		for (const line of ls.out.split("\n")) {
			if (line.startsWith("worktree ")) {
				cur = line.slice(9);
				curHead = "";
			} else if (line.startsWith("HEAD ")) curHead = line.slice(5);
			else if (line === `branch ${plan.source.ref}` && cur) {
				w = cur;
				wHead = curHead;
			}
		}
	} else {
		body.remainingCleanup.push("worktree の一覧を読めなかったため、後片付けをしていない");
		return;
	}

	if (input.cleanup === "branch") {
		if (w) {
			body.remainingCleanup.push("feature ブランチは worktree で使用中のため、削除していない");
			return;
		}
	} else if (w) {
		const a = real(input.approverCwd);
		const wr = real(w);
		if (a === wr || a.startsWith(wr + sep)) {
			body.remainingCleanup.push("承認した pi がその worktree の中にいるので、worktree は削除していない");
			body.remainingCleanup.push("feature ブランチは worktree で使用中のため、削除していない");
			return;
		}
		const st = await git(["status", "--porcelain=v1", "-z", "--untracked-files=normal"], w, env);
		if (wHead !== plan.source.oid || !st.ok || st.out !== "") {
			body.remainingCleanup.push("feature の worktree が clean でないか HEAD が違うため、worktree は削除していない");
			body.remainingCleanup.push("feature ブランチは worktree で使用中のため、削除していない");
			return;
		}
		const rm = await git(["worktree", "remove", w], wt, env);
		if (!rm.ok) {
			body.remainingCleanup.push(`worktree を削除できなかった: ${tail(rm.err || rm.out)}`);
			body.remainingCleanup.push("feature ブランチは worktree で使用中のため、削除していない");
			return;
		}
		body.confirmedEffects.push(`feature の worktree を削除した: ${w}`);
	}
	const del = await git(["update-ref", "-d", plan.source.ref, plan.source.oid], wt, env);
	if (del.ok) body.confirmedEffects.push(`${plan.source.ref} を削除した`);
	else body.remainingCleanup.push(`feature ブランチを削除できなかった: ${tail(del.err || del.out)}`);
}

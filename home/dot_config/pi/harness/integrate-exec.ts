// 保護ブランチへの統合 (squash) の実行器。承認前に算出した計画 (IntegratePlan) をそのとおりに反映する。
// 結果の commit は通常の git commit で作る (pre-commit・commit-msg・署名をそのまま通す)。ref だけを進めない。
// see docs/change/0055
import { execFile, spawn } from "node:child_process";
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
	/** 試験用: 中断・時間切れの後の停止確認を差し替える (pid = プロセスグループのリーダー)。false なら「停止を確認できない」 */
	stopVerifier?: (pid: number) => boolean | Promise<boolean>;
	/** 試験用: グループへシグナルを送る関数の差し替え。既定は process.kill(-pid, sig) */
	killSignal?: (pid: number, sig: NodeJS.Signals) => void;
	/** 試験用: SIGTERM の後の猶予 (既定 2000)・SIGKILL の後の確認の上限 (既定 5000) */
	graceMs?: number;
	killMs?: number;
};

type Stopping = {
	stopVerifier?: (pid: number) => boolean | Promise<boolean>;
	killSignal?: (pid: number, sig: NodeJS.Signals) => void;
	graceMs?: number;
	killMs?: number;
};

type G = {
	ok: boolean;
	code: number | null;
	out: string;
	err: string;
	timedOut: boolean;
	aborted: boolean;
	spawnFail: boolean;
	/** gitGroup だけが設定する。git とその子孫 (hook) の停止を確認できたか */
	stopped?: boolean | "unknown";
};

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
				["-c", "core.fsmonitor=false", ...args],
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

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

function groupGone(pid: number): boolean {
	try {
		process.kill(-pid, 0);
		return false;
	} catch (e) {
		return (e as NodeJS.ErrnoException).code === "ESRCH";
	}
}

/** プロセスグループが消えるまで待つ。上限 ms を過ぎたら false */
async function waitGone(pid: number, ms: number): Promise<boolean> {
	const end = Date.now() + ms;
	while (Date.now() < end) {
		if (groupGone(pid)) return true;
		await sleep(50);
	}
	return groupGone(pid);
}

/** グループへ SIGTERM → 猶予 → SIGKILL。消滅を確認できたか返す */
async function killGroup(pid: number, st: Stopping): Promise<boolean> {
	const send = st.killSignal ?? ((p: number, s: NodeJS.Signals) => process.kill(-p, s));
	try {
		send(pid, "SIGTERM");
	} catch {
		/* すでに無い */
	}
	if (await waitGone(pid, st.graceMs ?? 2000)) return true;
	try {
		send(pid, "SIGKILL");
	} catch {
		/* すでに無い */
	}
	return waitGone(pid, st.killMs ?? 5000);
}

/**
 * hook が動く git (merge --squash・commit) の起動。専用のプロセスグループで動かし、中断・時間切れ・失敗では
 * グループ全体を止めて消滅を確認する (stopped)。Windows は従来の方式 (stopped = "unknown")。
 */
function gitGroup(
	args: string[],
	cwd: string,
	env: NodeJS.ProcessEnv,
	opts: { timeout?: number; signal?: AbortSignal } & Stopping = {},
): Promise<G> {
	if (process.platform === "win32") {
		return git(args, cwd, env, opts).then((g) => ({ ...g, stopped: "unknown" as const }));
	}
	const CAP = 64 * 1024 * 1024;
	return new Promise((res) => {
		let out = "";
		let err = "";
		let timedOut = false;
		let aborted = false;
		let settled = false;
		if (opts.signal?.aborted) {
			return res({ ok: false, code: null, out: "", err: "", timedOut: false, aborted: true, spawnFail: false, stopped: true });
		}
		let child: ReturnType<typeof spawn>;
		try {
			child = spawn("git", ["-c", "core.fsmonitor=false", ...args], { cwd, env, detached: true, stdio: ["ignore", "pipe", "pipe"] });
		} catch (e) {
			return res({ ok: false, code: null, out: "", err: String((e as Error).message ?? e), timedOut: false, aborted: false, spawnFail: true, stopped: true });
		}
		const pid = child.pid;
		let killing: Promise<boolean> | null = null;
		// 実測の消滅と verifier の両方が true のときだけ true (確認を弱めない)。例外は false
		const confirm = async (gone: boolean): Promise<boolean> => {
			if (!gone) return false;
			if (!opts.stopVerifier || pid === undefined) return true;
			try {
				return (await opts.stopVerifier(pid)) === true;
			} catch {
				return false;
			}
		};
		const stopGroup = (): Promise<boolean> => {
			if (!killing) {
				killing = (async () => {
					if (pid === undefined) return false;
					try {
						return await confirm(await killGroup(pid, opts));
					} catch {
						return false;
					}
				})();
			}
			return killing;
		};
		// 停止要求。停止を確認できなかったら、子の exit を待たずに 1 度だけ結果を返す
		const requestStop = () => {
			void stopGroup().then((ok) => {
				if (!ok) void finish(null, false, false);
			});
		};
		child.stdout?.setEncoding("utf8");
		child.stderr?.setEncoding("utf8");
		const NOTE = "\n[出力が上限を超えたため、以降を捨てた]";
		child.stdout?.on("data", (d: string) => {
			if (out.length < CAP) out += d;
			else if (!out.endsWith(NOTE)) out += NOTE;
		});
		child.stderr?.on("data", (d: string) => {
			if (err.length < CAP) err += d;
			else if (!err.endsWith(NOTE)) err += NOTE;
		});
		const timer = setTimeout(() => {
			timedOut = true;
			requestStop();
		}, opts.timeout ?? 60000);
		const onAbort = () => {
			aborted = true;
			requestStop();
		};
		opts.signal?.addEventListener("abort", onAbort, { once: true });
		const finish = async (code: number | null, spawnFail: boolean, forced?: boolean) => {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			opts.signal?.removeEventListener("abort", onAbort);
			child.stdout?.destroy();
			child.stderr?.destroy();
			const ok = !spawnFail && !timedOut && !aborted && code === 0;
			let stopped: boolean;
			if (forced !== undefined) stopped = forced;
			else if (spawnFail || pid === undefined) stopped = true;
			else if (killing) stopped = await killing;
			else if (groupGone(pid)) stopped = await confirm(true);
			else stopped = await stopGroup();
			res({ ok, code, out, err, timedOut, aborted, spawnFail, stopped });
		};
		child.on("error", (e) => {
			err += String(e.message ?? e);
			void finish(null, true);
		});
		child.on("exit", (code) => {
			// 子孫が出力の端を握っていても待ち続けない
			const t = setTimeout(() => void finish(code, false), 1000);
			child.once("close", () => {
				clearTimeout(t);
				void finish(code, false);
			});
		});
	});
}

const OPS = ["MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "BISECT_LOG"];

/** 停止の観測と、承認の結果に載せる事実。run・cleanup が書く */
type Track = { unconfirmed: boolean; resultCommit?: string; resultTree?: string };

export async function executeIntegration(input: IntegrateExecInput): Promise<ResultBody> {
	return (await executeIntegrationOutcome(input)).body;
}

/**
 * 結果と、git・hook の停止状態を返す。termination は停止の観測から直接決める:
 * hook が動く git のどれかで停止を確認できなければ "unconfirmed"、そうでなければ "stopped" (何も起動しなかった場合を含む)。
 */
export async function executeIntegrationOutcome(input: IntegrateExecInput): Promise<{ body: ResultBody; termination: "stopped" | "unconfirmed" }> {
	const body: ResultBody = { outcome: "not_executed", phase: "precheck", confirmedEffects: [], remainingCleanup: [], evidence: [] };
	const track: Track = { unconfirmed: false };
	const fin = (): ResultBody => {
		body.confirmedEffects = body.confirmedEffects.map(clean).slice(0, 50);
		body.remainingCleanup = body.remainingCleanup.map(clean).slice(0, 50);
		body.evidence = body.evidence.map(clean).slice(0, 50);
		const facts: Record<string, string> = {
			source_ref: clean(input.plan.source.ref).slice(0, 200),
			source_oid: input.plan.source.oid,
			target_ref: clean(input.plan.target.ref).slice(0, 200),
			target_oid_before: input.plan.target.oid,
			cleanup: input.cleanup,
		};
		if (track.resultCommit) facts.result_commit = track.resultCommit;
		if (track.resultTree) facts.result_tree = track.resultTree;
		body.facts = facts;
		return body;
	};
	const tmpRef: { dir: string | null } = { dir: null };
	let tmpDir: string | null = null;
	try {
		await run(input, body, tmpRef, track);
	} catch (e) {
		const first = String((e as Error)?.message ?? e).split("\n")[0];
		body.outcome = "unknown";
		body.evidence.push(`例外: ${first}`);
		// 想定外の例外では、git・hook の停止を保証できない (fail-closed)
		track.unconfirmed = true;
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
	return { body: fin(), termination: track.unconfirmed ? "unconfirmed" : "stopped" };
}

async function run(input: IntegrateExecInput, body: ResultBody, tmpRef: { dir: string | null }, track: Track): Promise<void> {
	const { plan } = input;
	const base: NodeJS.ProcessEnv = { ...repoTargetEnv(input.env ?? process.env), GIT_OPTIONAL_LOCKS: "0", GIT_TERMINAL_PROMPT: "0" };
	const wt = plan.targetWorktree;
	const stopping: Stopping = {
		stopVerifier: input.stopVerifier,
		killSignal: input.killSignal,
		graceMs: input.graceMs,
		killMs: input.killMs,
	};
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
	// status・merge が外部 filter (clean/smudge) を起動し得るので、作業ツリーに触る git の前に断る
	const flt = await git(["config", "--get-regexp", "^filter\\..*\\.(clean|smudge|process)$"], wt, base);
	if ((flt.ok && flt.out.trim() !== "") || (!flt.ok && flt.code !== 1)) return refuse("precheck", "外部の filter が設定されている (または確かめられない)");
	const st = await git(["status", "--porcelain=v1", "-z", "--untracked-files=normal"], wt, base);
	if (!st.ok) return refuse("precheck", "統合先の worktree の状態を読めなかった");
	if (st.out !== "") return refuse("precheck", "統合先の worktree に未コミットの変更か追跡外のファイルがある");
	const drv = await git(["config", "--get-regexp", "^merge\\..*\\.driver$"], wt, base);
	if ((drv.ok && drv.out.trim() !== "") || (!drv.ok && drv.code !== 1)) return refuse("precheck", "外部の merge driver が設定されている (または確かめられない)");

	// Windows では git・hook (とその子孫) の停止を保証できないので、最初の変更の前に断る (試験用の stopVerifier があるときを除く)
	if (process.platform === "win32" && !input.stopVerifier) {
		return refuse("precheck", "Windows では git・hook の停止を保証できないので実行しない");
	}

	// 元に戻す (reset --hard)。hook が動くので停止管理つき。"unstopped" = 停止を確認できない
	const rollback = async (): Promise<boolean | "unstopped"> => {
		const r = await gitGroup(["reset", "--hard", plan.target.oid], wt, base, stopping);
		if (r.stopped !== true) return "unstopped";
		if (!r.ok) return false;
		const h = await git(["rev-parse", "HEAD"], wt, base);
		const s2 = await git(["status", "--porcelain=v1", "-z", "--untracked-files=normal"], wt, base);
		return h.ok && h.out.trim() === plan.target.oid && s2.ok && s2.out === "";
	};
	const notStopped = (phase: string) => {
		track.unconfirmed = true;
		body.outcome = "unknown";
		body.phase = phase;
		body.evidence.push("git・hook の停止を確認できない。rollback しない");
		body.remainingCleanup.push("作業ツリー・index・HEAD が中途の状態のままの可能性がある");
	};
	const unrolled = (phase: string, why: string) => {
		body.outcome = "unknown";
		body.phase = phase;
		body.evidence.push(why);
		body.remainingCleanup.push("作業ツリーに squash の変更が残っている");
	};

	// rollback して、結果で分岐する。停止を確認できなければ notStopped
	const rolledBack = async (phase: string, why: string, onOk: () => void) => {
		const r = await rollback();
		if (r === "unstopped") return notStopped(phase);
		if (r) return onOk();
		return unrolled(phase, why);
	};

	// --- merge ---
	body.phase = "merge";
	const mg = await gitGroup(["merge", "--squash", "--no-commit", plan.source.oid], wt, base, {
		...stopping,
		signal: input.signal,
	});
	// 終了コードと独立に、停止の確認を要求する (成功でも、背景の子孫が残っていれば進まない)
	if (mg.stopped !== true) return notStopped("merge");
	if (!mg.ok) {
		const why = `squash を反映できなかった: ${tail(mg.err || mg.out)}`;
		return rolledBack("merge", why, () => refuse("merge", why));
	}
	const wtree = await git(["write-tree"], wt, base);
	if (!wtree.ok || wtree.out.trim() !== plan.resultTree) {
		const why = "結果の tree が、承認した計画と違う";
		return rolledBack("merge", why, () => refuse("merge", why));
	}

	// --- commit ---
	body.phase = "commit";
	tmpRef.dir = mkdtempSync(join(tmpdir(), "integrate-"));
	const msgFile = join(tmpRef.dir, "msg");
	writeFileSync(msgFile, plan.message.endsWith("\n") ? plan.message : `${plan.message}\n`, { mode: 0o600 });
	const cenv: NodeJS.ProcessEnv = { ...base, GIT_EDITOR: "true" };
	const cm = await gitGroup(["commit", "-F", msgFile], wt, cenv, {
		...stopping,
		timeout: input.commitTimeoutMs ?? 120000,
		signal: input.signal,
	});
	if (cm.stopped !== true) return notStopped("commit");
	if (!cm.ok) {
		const cur = await git(["rev-parse", "HEAD"], wt, base);
		if (!cur.ok) {
			body.outcome = "unknown";
			body.evidence.push("commit が失敗し、HEAD を確かめられなかった");
			return;
		}
		if (cur.out.trim() === plan.target.oid) {
			const why = cm.aborted ? "中断された" : cm.timedOut ? `commit が時間切れ: ${tail(cm.err || cm.out)}` : `commit が失敗した: ${tail(cm.err || cm.out)}`;
			const r = await rollback();
			if (r === "unstopped") return notStopped("commit");
			if (r) {
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
	const headOid = newHead.trim();
	track.resultCommit = headOid;
	const tref = await git(["rev-parse", "--verify", "--quiet", `${plan.target.ref}^{commit}`], wt, base);
	if (!tref.ok || tref.out.trim() !== headOid) {
		body.outcome = "unknown";
		body.evidence.push(`統合先 ref が結果コミットを指していない (結果コミット ${short(headOid)}${tref.ok ? `、統合先 ${short(tref.out.trim())}` : "、統合先を読めなかった"})`);
		body.remainingCleanup.push(`結果コミット ${short(headOid)} は統合先ブランチに反映されていない。手動で確認する`);
		return;
	}
	body.outcome = "success";
	if (tree.trim() !== plan.resultTree) body.evidence.push(`hook が内容を変えた: 計画の tree ${short(plan.resultTree)} → 実際 ${short(tree.trim())}`);
	else body.evidence.push("結果の tree は承認した計画と一致した");
	if ((msg ?? "").replace(/\n+$/, "") !== plan.message.replace(/\n+$/, "")) body.evidence.push("commit のメッセージが計画と違う (hook が変えた)");
	track.resultTree = tree.trim();
	body.confirmedEffects.push(`${plan.target.ref} を ${short(headOid)} に進めた (squash)`);

	// --- cleanup ---
	if (input.cleanup !== "none") {
		body.phase = "cleanup";
		try {
			await cleanup(input, body, wt, base, stopping, track);
		} catch (e) {
			body.remainingCleanup.push(`後片付けで例外: ${String((e as Error)?.message ?? e).split("\n")[0]}`);
		}
	}
	body.phase = body.outcome === "unknown" ? "cleanup" : "done";
}

function real(p: string): string {
	try {
		return realpathSync(p);
	} catch {
		return resolve(p);
	}
}

async function cleanup(input: IntegrateExecInput, body: ResultBody, wt: string, env: NodeJS.ProcessEnv, stopping: Stopping, track: Track): Promise<void> {
	const { plan } = input;
	// hook が動く更新系の git は停止管理つき。停止を確認できなければ unknown にして、次の変更へ進まない
	const mutate = async (args: string[], cwd: string): Promise<G | null> => {
		const g = await gitGroup(args, cwd, env, { ...stopping, signal: input.signal });
		if (g.stopped === true) return g;
		track.unconfirmed = true;
		body.outcome = "unknown";
		body.evidence.push("git・hook の停止を確認できない。後片付けを続けない");
		body.remainingCleanup.push("後片付けの git が停止したか確認できない");
		return null;
	};
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
		const rm = await mutate(["worktree", "remove", w], wt);
		if (!rm) return;
		if (!rm.ok) {
			body.remainingCleanup.push(`worktree を削除できなかった: ${tail(rm.err || rm.out)}`);
			body.remainingCleanup.push("feature ブランチは worktree で使用中のため、削除していない");
			return;
		}
		body.confirmedEffects.push(`feature の worktree を削除した: ${w}`);
	}
	const del = await mutate(["update-ref", "--no-deref", "-d", plan.source.ref, plan.source.oid], wt);
	if (!del) return;
	if (del.ok) body.confirmedEffects.push(`${plan.source.ref} を削除した`);
	else body.remainingCleanup.push(`feature ブランチを削除できなかった: ${tail(del.err || del.out)}`);
}

// 起票の git 操作（段 B1 の S）。新しい feature の枝と worktree を作り、検証し、依頼文の記録を呼び出し側に書かせる。
// 設計: .tmp/subagents/8-job-d926e8589179d27b.md §2.2・§2.3、契約: .tmp/keep/prv-app/api-contract-create.md。
// 作る順序: 事前検査 → worktree add -b → 検証 → 記録（record の呼び出し）。記録を先に書かない。
// 巻き戻し（worktree remove（--force なし）と枝の CAS 削除）は、清潔・進行中の操作なし・外部コード設定なしが確かめられたときだけ。
// git の実行は merge-git.ts の runGit だけを使う（固定の先頭引数・hook 無効）。`git flow` と pis は呼ばない。
import { lstat, mkdir, realpath } from "node:fs/promises";
import { basename, dirname, join } from "node:path";
import { prKeyOf, LIMITS } from "../../home/dot_config/pi/harness/review-log.ts";
import { ApiError } from "./git-view.ts";
import { configHasExternalCode, runGit } from "./merge-git.ts";
import { formatReason, release as releaseOwner } from "./worktree-owner.ts";

const NAME_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;
// Windows の予約名（拡張子つきも同じ扱いになるので、最初の「.」までを見る）
const RESERVED_RE = /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$/;
const OID40 = /^[0-9a-f]{40}$/;
const GITFLOW_WORKTREE_PATH = ".tmp/worktrees/{{ branchName }}";
const IN_PROGRESS = ["MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "index.lock"];

export type CreateEnv = { testDelayMs: number; testFail: string | null };
export type CreateInput = { gitDir: string; name: string; expectTarget: string; env: CreateEnv };
export type Created = { branch: string; baseOid: string };

const bad = (code: string, message: string): ApiError => new ApiError(400, code, message);
const conflict = (code: string, message: string): ApiError => new ApiError(409, code, message);

/** 名前の規則（種類は feature だけ）。区切り文字を含められないので、パス走査はここで断てる。 */
export function nameProblem(name: unknown): boolean {
	if (typeof name !== "string" || !NAME_RE.test(name)) return true;
	if (name.includes("..") || name.endsWith(".") || name.endsWith(".lock") || name.endsWith(".git")) return true;
	return RESERVED_RE.test(name.split(".")[0]);
}

const sleep = (ms: number): Promise<void> => new Promise((done) => setTimeout(done, ms));

async function lstatOrNull(p: string): Promise<Awaited<ReturnType<typeof lstat>> | null> {
	try {
		return await lstat(p);
	} catch {
		return null;
	}
}

async function oidOf(gitDir: string, ref: string): Promise<string | null> {
	const r = await runGit(["rev-parse", "--verify", "--quiet", `${ref}^{commit}`], { gitDir });
	const oid = r.out.trim();
	return r.code === 0 && OID40.test(oid) ? oid : null;
}

async function refExists(gitDir: string, ref: string): Promise<boolean> {
	return (await runGit(["rev-parse", "--verify", "--quiet", ref], { gitDir })).code === 0;
}

/** 起票の枝（feature/<名>）が既にあるか（枝そのもの・D/F 衝突を含む）。衝突の検査に使う。 */
export async function featureBranchExists(gitDir: string, name: string): Promise<boolean> {
	const r = await runGit(["for-each-ref", "--count=1", "--format=%(refname)", `refs/heads/feature/${name}`], { gitDir });
	return r.code !== 0 || r.out.trim() !== "" ? true : await refExists(gitDir, "refs/heads/feature");
}

/** 起票の枝そのもの（完全一致の branch ref）があるか。D/F 衝突は含まない。再送の判定に使う。 */
export async function featureBranchRefExists(gitDir: string, name: string): Promise<boolean> {
	return await refExists(gitDir, `refs/heads/feature/${name}`);
}

type Layout = { root: string; wt: string; rel: string };

/** worktree の登録の一覧（porcelain の worktree 行のパス）。読めなければ null。 */
async function registeredPaths(gitDir: string): Promise<string[] | null> {
	const r = await runGit(["worktree", "list", "--porcelain"], { gitDir });
	if (r.code !== 0) return null;
	return r.out.split("\n").filter((l) => l.startsWith("worktree ")).map((l) => l.slice("worktree ".length));
}

async function ensureDir(p: string): Promise<void> {
	let st = await lstatOrNull(p);
	if (!st) {
		try {
			await mkdir(p); // 非再帰。symlink を辿って作らない
		} catch {
			// 競合で先に作られたときは、直後の検査に任せる
		}
		st = await lstatOrNull(p);
	}
	if (!st || !st.isDirectory()) throw conflict("bad_layout", "作業ツリーの配置が想定と違います（.tmp が実ディレクトリではありません）。");
}

/** 事前検査（何も作らない）。通れば、基点の OID と配置を返す。 */
async function precheck(input: CreateInput): Promise<{ baseOid: string; layout: Layout }> {
	const { gitDir, name } = input;
	if (!OID40.test(input.expectTarget)) throw bad("bad_expect", "表示中の版の指定が正しくありません。");
	// 名前: 形 → git の ref 規則
	if (nameProblem(name)) throw bad("bad_name", "名前が正しくありません（小文字・数字・. _ - の 64 字まで）。");
	const fc = await runGit(["check-ref-format", `refs/heads/feature/${name}`]);
	if (fc.code !== 0) throw bad("bad_name", "名前が正しくありません（枝名として使えません）。");
	// 標準の配置: <root>/.git の非 bare
	const gst = await lstatOrNull(gitDir);
	if (basename(gitDir) !== ".git" || !gst || !gst.isDirectory()) throw conflict("unsupported_repo", "このリポジトリには起票できません（標準の配置ではありません）。");
	const bare = await runGit(["config", "--get", "core.bare"], { gitDir });
	if (bare.out.trim().toLowerCase() === "true") throw conflict("unsupported_repo", "このリポジトリには起票できません（bare です）。");
	const baseOid = await oidOf(gitDir, "refs/heads/develop");
	if (!baseOid) throw conflict("unsupported_repo", "このリポジトリには起票できません（develop がありません）。");
	if (baseOid !== input.expectTarget) throw conflict("stale_view", "表示中の版から develop が更新されています。再読み込みしてください。");
	// 外部のコードを動かしうる設定
	if ((await configHasExternalCode(join(gitDir, "config"))) || (await configHasExternalCode(join(gitDir, "config.worktree")))) {
		throw conflict("external_code", "リポジトリの設定に外部のコードを動かす項目があるため、起票できません。");
	}
	const root = dirname(gitDir);
	// .gitflow があれば、worktreePath が固定の値と一致すること（断る目的でだけ読む）
	if (await lstatOrNull(join(root, ".gitflow"))) {
		const g = await runGit(["config", "--file", join(root, ".gitflow"), "--no-includes", "--get", "gitflow.worktreePath"], { cwd: root });
		const v = g.out.split("\n")[0];
		if (g.code === 0 && v !== GITFLOW_WORKTREE_PATH) throw conflict("bad_layout", "作業ツリーの配置が想定と違います（.gitflow の worktreePath）。");
		if (g.code > 1) throw conflict("bad_layout", "作業ツリーの配置を確認できません。");
	}
	// 衝突: 枝・D/F・記録・ディレクトリ・登録
	if (await featureBranchExists(gitDir, name)) throw conflict("name_used", "その名前の枝がすでにあります。別の名前にしてください。");
	if (await refExists(gitDir, `refs/pi/review/${prKeyOf(`feature/${name}`)}`)) {
		throw conflict("name_used", "その名前の記録がすでにあります。別の名前にしてください。");
	}
	const rel = `.tmp/worktrees/${name}`;
	const wt = join(root, rel);
	const tmpSt = await lstatOrNull(join(root, ".tmp"));
	if (tmpSt && !tmpSt.isDirectory()) throw conflict("bad_layout", "作業ツリーの配置が想定と違います（.tmp が実ディレクトリではありません）。");
	const wtsSt = tmpSt ? await lstatOrNull(join(root, ".tmp", "worktrees")) : null;
	if (wtsSt && !wtsSt.isDirectory()) throw conflict("bad_layout", "作業ツリーの配置が想定と違います（.tmp/worktrees が実ディレクトリではありません）。");
	if (await lstatOrNull(wt)) throw conflict("name_used", "その名前の作業ツリーのディレクトリがすでにあります。別の名前にしてください。");
	const reg = await registeredPaths(gitDir);
	if (reg === null) throw conflict("unsupported_repo", "作業ツリーの一覧を確認できません。");
	if (reg.includes(wt)) throw conflict("worktree_registered", "その名前の作業ツリーがすでに登録されています。");
	// check-ignore は pathspec の magic を受け付けないので、固定の --literal-pathspecs をここだけ外す（引数は固定の相対パスで、名前は検査済み）
	const ign = await runGit(["--no-literal-pathspecs", "check-ignore", "-q", rel], { cwd: root });
	if (ign.code !== 0) throw conflict("bad_layout", "作業ツリーの置き場（.tmp/）が .gitignore で除外されていません。");
	const keys = await runGit(["for-each-ref", "--format=%(refname)", "refs/pi/review/"], { gitDir });
	if (keys.code !== 0) throw conflict("unsupported_repo", "レビューの記録を確認できません。");
	if (keys.out.split("\n").filter((l) => l !== "").length >= LIMITS.prs) throw conflict("limit", "記録された PR の数が上限に達しています。");
	return { baseOid, layout: { root, wt, rel } };
}

/** 作った worktree が想定どおりか（HEAD・枝・清潔さ・配置）。 */
async function verify(input: CreateInput, layout: Layout, baseOid: string): Promise<boolean> {
	const { wt, root } = layout;
	const head = await runGit(["rev-parse", "HEAD"], { cwd: wt });
	if (head.code !== 0 || head.out.trim() !== baseOid) return false;
	const sym = await runGit(["symbolic-ref", "-q", "HEAD"], { cwd: wt });
	if (sym.code !== 0 || sym.out.trim() !== `refs/heads/feature/${input.name}`) return false;
	const st = await runGit(["status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored"], { cwd: wt });
	if (st.code !== 0 || st.out !== "") return false;
	try {
		const real = await realpath(wt);
		return real === join(await realpath(root), ".tmp", "worktrees", input.name);
	} catch {
		return false;
	}
}

/** 巻き戻してよい状態か（清潔・進行中の操作なし・外部コード設定なしの 3 つがすべて確かめられたとき）。 */
async function safeToRemove(input: CreateInput, layout: Layout, baseOid: string): Promise<boolean> {
	// 外部コード設定の検査を、git status（filter を動かしうる）より先に行う。rev-parse は filter を動かさない
	const gd = await runGit(["rev-parse", "--absolute-git-dir"], { cwd: layout.wt });
	const wtGit = gd.out.trim();
	if (gd.code !== 0 || wtGit === "") return false;
	if (await configHasExternalCode(join(wtGit, "config.worktree"))) return false;
	if ((await configHasExternalCode(join(input.gitDir, "config"))) || (await configHasExternalCode(join(input.gitDir, "config.worktree"))))
		return false;
	for (const f of IN_PROGRESS) if (await lstatOrNull(join(wtGit, f))) return false;
	return await verify(input, layout, baseOid);
}

/** 巻き戻す。残ったものの種類（"branch" / "worktree"）を返す。空なら完全に戻した。 */
async function rollback(input: CreateInput, layout: Layout, baseOid: string): Promise<string[]> {
	const branchRef = `refs/heads/feature/${input.name}`;
	const residue: string[] = [];
	const wtExists = (await lstatOrNull(layout.wt)) !== null;
	const reg = await registeredPaths(input.gitDir);
	if (wtExists || reg === null || reg.includes(layout.wt)) {
		let removed = false;
		if (wtExists && (await safeToRemove(input, layout, baseOid))) {
			removed = (await runGit(["worktree", "remove", layout.wt], { gitDir: input.gitDir, write: true })).code === 0;
		}
		if (!removed) residue.push("worktree");
	}
	const tip = await oidOf(input.gitDir, branchRef);
	if (tip !== null || (await refExists(input.gitDir, branchRef))) {
		// 作業ツリーが残っている間は枝を消さない（消すと worktree が壊れる）
		let deleted = false;
		if (residue.length === 0 && tip === baseOid) {
			deleted = (await runGit(["update-ref", "-d", "--no-deref", branchRef, baseOid], { gitDir: input.gitDir, write: true })).code === 0;
		}
		if (!deleted) residue.push("branch");
	}
	return residue;
}

/** 依頼文の記録の結果。unknown は「書けたか確定できない」（失敗の結果を受け取っただけでは、未保存とは言えない）。 */
export type RecordOutcome = "recorded" | "not_recorded" | "unknown";

/** 残骸の診断（何も消さない）。枝・worktree（ディレクトリか登録）が残っていれば、その種類を返す。 */
async function diagnose(input: CreateInput, layout: Layout): Promise<string[]> {
	const residue: string[] = [];
	const reg = await registeredPaths(input.gitDir);
	if ((await lstatOrNull(layout.wt)) !== null || reg === null || reg.includes(layout.wt)) residue.push("worktree");
	if (await refExists(input.gitDir, `refs/heads/feature/${input.name}`)) residue.push("branch");
	return residue;
}

/**
 * 枝と worktree を作り、record（依頼文の記録）を呼ぶ。
 * 巻き戻しは、自分の worktree add が成功した（= 枝と worktree を自分が作った）うえで、記録が「書かれなかった」と確定したときだけ。
 * add が失敗したとき・記録が不明なときは、何も消さず残骸を診断する（無ければ 500 create_failed、あれば 500 create_partial）。
 * 巻き戻せたら create_failed、戻せなかったら create_partial（残骸の種類だけ）。
 */
export async function createFeature(input: CreateInput, record: (baseOid: string) => Promise<RecordOutcome>): Promise<Created> {
	const { baseOid, layout } = await precheck(input);
	const branch = `feature/${input.name}`;
	await ensureDir(join(layout.root, ".tmp"));
	await ensureDir(join(layout.root, ".tmp", "worktrees"));
	let ok = false;
	let added = false; // 自分の worktree add が成功した（所有の証拠）
	let unknown = false;
	try {
		if (input.env.testFail === "race") {
			// 試験用: 事前検査の後に、別の操作が同名の枝と worktree を作った状態を再現する
			await runGit(["worktree", "add", "-b", branch, layout.wt, baseOid], { gitDir: input.gitDir, write: true, timeoutMs: 120_000 });
		}
		if (input.env.testFail === "add") {
			// 試験用: git が枝だけ作って失敗した状態を再現する
			await runGit(["branch", "--no-track", branch, baseOid], { gitDir: input.gitDir, write: true });
		} else {
			const reason = formatReason({ kind: "create", id: input.name, pid: process.pid, started: Math.floor(Date.now() / 1000) });
			// 作成中だけ lock して所有を表明する（add と同時。解除は下の releaseOwner）
			const r = await runGit(["worktree", "add", "--lock", "--reason", reason, "-b", branch, layout.wt, baseOid], { gitDir: input.gitDir, write: true, timeoutMs: 120_000 });
			added = r.code === 0;
		}
		ok = added;
		if (ok) ok = await verify(input, layout, baseOid);
		if (ok && input.env.testDelayMs > 0) await sleep(input.env.testDelayMs);
		if (ok && input.env.testFail === "record") ok = false;
		else if (ok) {
			let out: RecordOutcome;
			try {
				out = await record(baseOid);
			} catch {
				out = "unknown";
			}
			ok = out === "recorded";
			unknown = out === "unknown";
		}
	} catch {
		ok = false;
	}
	if (added) await releaseOwner(input.gitDir, layout.wt, input.name).catch(() => false); // 作成後は lock を残さない（巻き戻しも解除が先）
	if (ok) return { branch, baseOid };
	const residue = added && !unknown ? await rollback(input, layout, baseOid) : await diagnose(input, layout);
	if (residue.length === 0) throw new ApiError(500, "create_failed", "起票に失敗しました（作ったものは元に戻しました）。");
	const why = !added ? "枝・worktree を自分が作ったと確かめられないため" : unknown ? "依頼文の記録が書かれたか確かめられないため" : "安全に戻せないため";
	throw new ApiError(
		500,
		"create_partial",
		`起票に失敗し、${why}一部を残しました（残り: ${residue.join(", ")}）。内容を確かめて、git worktree remove と枝の削除で手動で片付けてください。`,
	);
}

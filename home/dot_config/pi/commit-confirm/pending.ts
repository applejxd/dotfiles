// 確認が取れなかった git commit の内容を、HEAD・インデックス・作業ツリーに触れずに退避する。
// コミットのオブジェクトだけを作り、refs/pi/pending/<時刻> に置く。直前の保留を親にして鎖にする。
// 後から: git log refs/pi/pending/<名前> で見て、git reset --soft <名前> で HEAD だけ進められる (作業ツリーは変わらない)。
// see docs/spec/pi-harness.md#時間切れと退避
import { git, readMessage, walk, wouldCommit } from "./describe.ts";
import type { Analysis } from "./parse.ts";

export const PENDING_PREFIX = "refs/pi/pending/";

// 退避の対象。読めた形はそのまま、読めない形 (連結など) は最初の commit から近似する (近似なら approx: true)
export function pendingTarget(
	a: Extract<Analysis, { kind: "commit" }>,
): { target: Extract<Analysis, { recognized: true }>; approx: boolean } | null {
	if (a.recognized) return { target: a, approx: false };
	if (!a.approx) return null;
	return {
		target: { kind: "commit", recognized: true, steps: [], dirs: a.approx.dirs, spec: a.approx.spec },
		approx: true,
	};
}

export type Saved = { ok: true; ref: string; short: string; files: number } | { ok: false; reason: string };

export function savePending(a: Extract<Analysis, { recognized: true }>, cwd: string): Saved {
	const { dir, adds } = walk(a, cwd);
	const spec = a.spec;
	// 直前のコミットの書き換えは、HEAD の子として表せない
	if (spec.amend) return { ok: false, reason: "--amend (直前のコミットの書き換え) は退避できない" };
	const top = git(dir, ["rev-parse", "--show-toplevel"]);
	if (!top.ok) return { ok: false, reason: "リポジトリを特定できない" };

	// 鎖の先頭 (ref 名の順。同じ秒でも崩れない)。HEAD がそこへ続いていなければ (その間にコミットされた)、HEAD から始め直す
	const head = git(dir, ["rev-parse", "-q", "--verify", "HEAD"]);
	let tip = git(dir, ["for-each-ref", "--sort=-refname", "--count=1", "--format=%(refname)", PENDING_PREFIX]).out;
	if (tip && head.ok && !git(dir, ["merge-base", "--is-ancestor", "HEAD", tip]).ok) tip = "";
	const baseRef = tip || "HEAD";

	const w = wouldCommit(dir, spec, adds, top.out, baseRef);
	if (!w) return { ok: false, reason: "コミットされる内容を再現できなかった" };
	if (w.empty && !spec.allowEmpty) return { ok: false, reason: "退避する変更が無い (HEAD・直前の保留と同じ内容)" };

	const msg = readMessage(spec, dir).text ?? "(pi) 退避したコミット (メッセージを取得できなかった)";
	// git の user.name / user.email が無い環境でも作れるように、無いときだけ代わりを渡す
	const env: Record<string, string> = {};
	if (!git(dir, ["var", "GIT_COMMITTER_IDENT"]).ok || !git(dir, ["var", "GIT_AUTHOR_IDENT"]).ok) {
		Object.assign(env, {
			GIT_AUTHOR_NAME: "pi pending",
			GIT_AUTHOR_EMAIL: "pi-pending@localhost",
			GIT_COMMITTER_NAME: "pi pending",
			GIT_COMMITTER_EMAIL: "pi-pending@localhost",
		});
	}
	const parent = tip || (head.ok ? "HEAD" : "");
	// 署名の設定や hook に左右されない (commit-tree は hook を呼ばない)
	const made = git(
		dir,
		["-c", "commit.gpgsign=false", "commit-tree", w.tree, ...(parent ? ["-p", parent] : []), "-F", "-"],
		env,
		msg.endsWith("\n") ? msg : `${msg}\n`,
	);
	if (!made.ok || !made.out) return { ok: false, reason: "commit-tree に失敗した" };

	const base = `${PENDING_PREFIX}${String(Date.now()).padStart(15, "0")}`;
	for (let n = 0; n < 20; n++) {
		// 同じミリ秒は 2 桁の連番 (ref 名の辞書順 = 作る順を保つ)
		const ref = n === 0 ? base : `${base}-${String(n).padStart(2, "0")}`;
		// 空の古い値 = 無いときだけ作る (同じ時刻の ref を上書きしない)
		if (git(dir, ["update-ref", ref, made.out, ""]).ok) {
			return {
				ok: true,
				ref,
				short: made.out.slice(0, 7),
				files: w.status.split("\n").filter(Boolean).length,
			};
		}
	}
	return { ok: false, reason: "ref を作れなかった" };
}

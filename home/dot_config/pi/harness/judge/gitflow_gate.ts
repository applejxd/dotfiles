// gitflow-lite 規約の強制 (CHG-0049): develop / main の作業ツリーを直接編集・コミットさせない。
//
// 純粋な関数だけ。git の状態は facts として受け取る (収集は ../gitstate.ts)。
// 既存の判定 (decide.ts) の結果を緩めない。deny か mustConfirm を足すだけ (call.ts の tighten)。
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/guard/pi-gitflow-guard.md

export type Head = { kind: "branch"; ref: string } | { kind: "detached" } | { kind: "unreadable" };

/** パスを所有する git の単位 */
export type Owner =
	| { kind: "no-repo" }
	| { kind: "unknown"; why: string }
	// .git の中 (リポジトリの管理領域)
	| { kind: "git-dir"; commonDir: string }
	| { kind: "worktree"; top: string; commonDir: string; primary: boolean; head: Head };

/** none: .gitflow が無い。other: gitflow-lite ではない構成。unknown: 読めなかった */
export type ModelFact = "gitflow-lite" | "other" | "none" | "unknown";

export type Facts = {
	home: string;
	/** 実体解決 (存在しない末尾は、存在する最寄りの親の実体に連結) */
	realPath(path: string): string;
	ownerOf(realPath: string): Owner;
	modelOf(commonDir: string): ModelFact;
	/** 固定操作 (gitflow_feature_*) を安全に実行できるか。案内文の出し分けにだけ使う */
	actionReady(top: string): boolean;
};

export type GateResult =
	| { kind: "pass" }
	| { kind: "deny"; reason: string }
	// key: 承認した状態のまま実行されることの照合に使う (承認の後でブランチが変わったら、承認を使わない)
	| { kind: "confirm"; reason: string; key: string };

const PASS: GateResult = { kind: "pass" };
const PROTECTED_REFS = ["refs/heads/develop", "refs/heads/main"];

/** この呼び出しを、規約の強制の対象として調べるか (調べる前に git を起動しないための前置き) */
export function isGated(tool: string, input: unknown): boolean {
	if (tool === "edit" || tool === "write") return typeof (input as any)?.path === "string";
	if (tool === "action") return (input as any)?.action === "git_commit";
	return false;
}

function expandHome(path: string, home: string): string {
	if (path === "~") return home;
	return path.startsWith("~/") ? home + path.slice(1) : path;
}

function isAbsolutePath(p: string): boolean {
	return p.startsWith("/") || /^[A-Za-z]:[\\/]/.test(p) || p.startsWith("\\\\");
}

function joinPath(base: string, rel: string): string {
	const sep = base.includes("\\") && !base.includes("/") ? "\\" : "/";
	return `${base.replace(/[\\/]+$/, "")}${sep}${rel}`;
}

/** 親ディレクトリの文字列の前方一致ではなく、実体解決後のパスの区切りで比べる */
function isUnder(path: string, dir: string): boolean {
	const norm = (s: string) => s.replace(/\\/g, "/").replace(/\/+$/, "");
	const p = norm(path);
	const d = norm(dir);
	return p === d || p.startsWith(`${d}/`);
}

function headRef(head: Head): string {
	return head.kind === "branch" ? head.ref : head.kind;
}

/** 保護の対象か: develop / main の作業ツリー、または本体 (primary) の detached。linked worktree の detached は対象にしない (隔離 worker など) */
function protectedHead(head: Head, primary: boolean): "yes" | "no" | "unreadable" {
	if (head.kind === "unreadable") return "unreadable";
	if (head.kind === "branch") return PROTECTED_REFS.includes(head.ref) ? "yes" : "no";
	return primary ? "yes" : "no";
}

function guide(facts: Facts, top: string, what: string): string {
	const lines = [
		`gitflow-lite のリポジトリでは、develop / main の作業ツリーに直接${what}しない (CHG-0049)。`,
		"`gitflow_feature_start` で feature を起票し、`.tmp/worktrees/<名前>/` の中で作業する。",
		"子エージェントは、親に feature の起票を依頼する。",
	];
	if (!facts.actionReady(top)) {
		lines.push("git flow の設定がこの環境に取り込まれていない。利用者が `scripts/gitflow-setup.sh` を実行する。");
	}
	return lines.join("\n");
}

function unknownConfirm(why: string, key: string): GateResult {
	return { kind: "confirm", reason: `git の状態を読めなかったので、規約を確かめられない (${why})`, key: `unknown:${key}` };
}

/**
 * edit / write (path) と git_commit (cwd) を調べる。判定の対象でない呼び出しは pass。
 * 保証するのは、直接のツール呼び出しだけ。外部スクリプトや bash の中の書き込みは対象外 (docs に書く)。
 */
export function gate(tool: string, input: unknown, cwd: string, facts: Facts): GateResult {
	if (!isGated(tool, input)) return PASS;
	if (tool === "action") return gateCommit(cwd, facts);
	const raw = expandHome(String((input as any).path), facts.home);
	const real = facts.realPath(isAbsolutePath(raw) ? raw : joinPath(cwd, raw));
	const owner = facts.ownerOf(real);
	switch (owner.kind) {
		case "no-repo":
			return PASS;
		case "unknown":
			return unknownConfirm(owner.why, real);
		case "git-dir": {
			const m = facts.modelOf(owner.commonDir);
			if (m === "gitflow-lite") return { kind: "deny", reason: "gitflow-lite のリポジトリの `.git/` の中は、編集しない (CHG-0049)。" };
			return m === "unknown" ? unknownConfirm("model", owner.commonDir) : PASS;
		}
		case "worktree": {
			const p = protectedHead(owner.head, owner.primary);
			if (p === "no") return PASS;
			if (p === "unreadable") return unknownConfirm("HEAD", owner.top);
			const m = facts.modelOf(owner.commonDir);
			if (m === "none" || m === "other") return PASS;
			if (m === "unknown") return unknownConfirm("model", owner.commonDir);
			// .tmp/ は、実体解決した上でこの worktree の .tmp/ の中のときだけ許す (使い捨て・session の置き場)
			if (isUnder(real, facts.realPath(joinPath(owner.top, ".tmp")))) return PASS;
			return { kind: "deny", reason: guide(facts, owner.top, "編集") };
		}
	}
}

function gateCommit(cwd: string, facts: Facts): GateResult {
	const owner = facts.ownerOf(facts.realPath(cwd));
	if (owner.kind === "no-repo" || owner.kind === "git-dir") return PASS;
	if (owner.kind === "unknown") return { kind: "deny", reason: `git の状態を読めなかったので、コミットを止めた (${owner.why})` };
	const p = protectedHead(owner.head, owner.primary);
	if (p === "no") return PASS;
	if (p === "unreadable") return { kind: "deny", reason: "HEAD を読めなかったので、コミットを止めた" };
	const m = facts.modelOf(owner.commonDir);
	if (m === "none" || m === "other") return PASS;
	if (m === "unknown") return { kind: "deny", reason: "リポジトリの運用 (.gitflow) を読めなかったので、コミットを止めた" };
	return { kind: "deny", reason: `${guide(facts, owner.top, "コミット")}\n(今のブランチ: ${headRef(owner.head)})` };
}

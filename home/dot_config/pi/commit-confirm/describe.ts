// 実行される git commit を、リポジトリ・ブランチ・対象ファイル・メッセージの構造にして文字にする。
// 事実 (リポジトリ・ブランチ・ファイル) は git から取り、メッセージだけコマンドから読む。
// ★git は読み取りだけ (一時のインデックスと GIT_OPTIONAL_LOCKS=0)。HEAD・本物のインデックス・作業ツリーは変えない。
// see docs/spec/pi-harness.md#commit-の確認-素の-pi
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join, resolve, sep } from "node:path";
import type { Analysis, CommitSpec } from "./parse.ts";

export const EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904";
const MAX_FILES = 12;
const WIDTH = 72;
const MAX_BODY = 8;

export type Run = { ok: boolean; out: string };
export function git(dir: string, args: string[], env: Record<string, string> = {}, input?: string): Run {
	const r = spawnSync("git", ["-c", "core.fsmonitor=false", "-c", "core.quotepath=false", ...args], {
		cwd: dir,
		encoding: "utf8",
		timeout: 8000,
		input,
		env: { ...process.env, ...env, GIT_OPTIONAL_LOCKS: "0", GIT_TERMINAL_PROMPT: "0" },
	});
	return { ok: r.status === 0, out: String(r.stdout ?? "").replace(/\n+$/, "") };
}

function wide(cp: number): boolean {
	return (
		(cp >= 0x1100 && cp <= 0x115f) || (cp >= 0x2e80 && cp <= 0xa4cf) || (cp >= 0xac00 && cp <= 0xd7a3) ||
		(cp >= 0xf900 && cp <= 0xfaff) || (cp >= 0xfe30 && cp <= 0xfe4f) || (cp >= 0xff00 && cp <= 0xff60) ||
		(cp >= 0xffe0 && cp <= 0xffe6) || (cp >= 0x1f300 && cp <= 0x1faff) || (cp >= 0x20000 && cp <= 0x3fffd)
	);
}
// 端末の桁数 (全角は 2 桁) で切る。収まるならそのまま
export function clip(text: string, width: number): string {
	const w = (ch: string) => (wide(ch.codePointAt(0)!) ? 2 : 1);
	const chars = [...text];
	if (chars.reduce((sum, ch) => sum + w(ch), 0) <= width) return text;
	let used = 0;
	let out = "";
	for (const ch of chars) {
		if (used + w(ch) > width - 1) break;
		out += ch;
		used += w(ch);
	}
	return `${out}…`;
}

function tilde(p: string): string {
	const h = homedir();
	return p === h ? "~" : p.startsWith(h + sep) ? `~${p.slice(h.length)}` : p;
}

// 手順 (cd / add) を辿って、commit が動く作業ディレクトリと、add の一覧を決める
export function walk(a: Extract<Analysis, { recognized: true }>, cwd: string) {
	let dir = cwd;
	const adds: { dir: string; args: string[] }[] = [];
	for (const s of a.steps) {
		if (s.kind === "cd") dir = resolve(dir, s.dir);
		else {
			let d = dir;
			for (const c of s.dirs) d = resolve(d, c);
			adds.push({ dir: d, args: s.args });
		}
	}
	for (const c of a.dirs) dir = resolve(dir, c);
	return { dir, adds };
}

export function readMessage(spec: CommitSpec, dir: string): { text: string | null; note?: string } {
	if (spec.messages.length) return { text: spec.messages.join("\n\n") };
	const f = spec.fileMessage;
	if (f && "stdin" in f) return { text: f.stdin };
	if (f) {
		try {
			const p = resolve(dir, f.path);
			if (statSync(p).size > 64 * 1024) return { text: null, note: `メッセージのファイル ${f.path} が大きすぎて読まない` };
			return { text: readFileSync(p, "utf8") };
		} catch {
			return { text: null, note: `メッセージのファイル ${f.path} を読めない` };
		}
	}
	return { text: null };
}

export type Would = { tree: string; empty: boolean; status: string; num: string };

// 実行すると何がコミットされるか。一時のインデックスに、実行される add / -a / パス指定を再現して数える。
// baseRef: パス指定 (コミットにパスを渡す形) の土台と「変更なし」の比べ先。表示は HEAD、退避は直前の保留
export function wouldCommit(
	dir: string,
	spec: CommitSpec,
	adds: { dir: string; args: string[] }[],
	top: string,
	baseRef = "HEAD",
): Would | null {
	const tmp = mkdtempSync(join(tmpdir(), "pi-commit-"));
	const idx = join(tmp, "index");
	try {
		const env = { GIT_INDEX_FILE: idx };
		const baseOk = git(dir, ["rev-parse", "-q", "--verify", `${baseRef}^{commit}`]).ok;
		const real = git(dir, ["rev-parse", "--path-format=absolute", "--git-path", "index"]);
		if (spec.pathspec.length > 0 && !spec.all) {
			// パス指定: 土台の木に、そのパスの今の内容だけを足したものがコミットされる
			if (baseOk && !git(dir, ["read-tree", baseRef], env).ok) return null;
			if (!git(top, ["add", "--", ...spec.pathspec.map((p) => resolve(dir, p))], env).ok) return null;
		} else {
			try {
				copyFileSync(resolve(dir, real.out), idx);
			} catch (e) {
				// インデックスがまだ無い (初回) のは正常。それ以外の失敗は再現できない
				if ((e as NodeJS.ErrnoException).code !== "ENOENT") return null;
			}
			for (const a of adds) if (!git(a.dir, ["add", ...a.args], env).ok) return null;
			if (spec.all && !git(top, ["add", "-u"], env).ok) return null;
		}
		const tree = git(dir, ["write-tree"], env);
		if (!tree.ok) return null;
		const baseTree = baseOk ? git(dir, ["rev-parse", `${baseRef}^{tree}`]).out : EMPTY_TREE;
		// --amend は直前のコミットの親との差が、書き換え後のコミットの中身
		let diffBase = baseOk ? baseRef : EMPTY_TREE;
		if (spec.amend && baseOk) {
			diffBase = git(dir, ["rev-parse", "-q", "--verify", `${baseRef}^`]).ok ? `${baseRef}^` : EMPTY_TREE;
		}
		const status = git(dir, ["diff-index", "--cached", "--name-status", "-M", "--no-ext-diff", diffBase], env);
		const num = git(dir, ["diff-index", "--cached", "--numstat", "-M", "--no-ext-diff", diffBase], env);
		if (!status.ok || !num.ok) return null;
		return { tree: tree.out, empty: tree.out === baseTree, status: status.out, num: num.out };
	} finally {
		rmSync(tmp, { recursive: true, force: true });
	}
}

function fileLines(status: string, num: string): { lines: string[]; total: string } {
	const counts = new Map<string, [string, string]>();
	let add = 0;
	let del = 0;
	for (const l of num.split("\n").filter(Boolean)) {
		const [a, d, ...p] = l.split("\t");
		counts.set(p.join("\t"), [a, d]);
		if (a !== "-") add += Number(a);
		if (d !== "-") del += Number(d);
	}
	const rows = status.split("\n").filter(Boolean).map((l) => {
		const [st, ...p] = l.split("\t");
		const path = st.startsWith("R") || st.startsWith("C") ? `${p[0]} → ${p[1]}` : p[0];
		const key = p[p.length - 1];
		const c = counts.get(key) ?? counts.get(`${p[0]} => ${p[1]}`);
		const stat = c ? (c[0] === "-" ? "(バイナリ)" : `(+${c[0]} −${c[1]})`) : "";
		return `  ${st[0]} ${path} ${stat}`.trimEnd();
	});
	const shown = rows.slice(0, MAX_FILES);
	if (rows.length > MAX_FILES) shown.push(`  …ほか ${rows.length - MAX_FILES} 件`);
	return { lines: shown, total: `${rows.length} ファイル  +${add} −${del}` };
}

function messageLines(text: string): string[] {
	const lines = text.split("\n").map((l) => l.trimEnd());
	while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
	if (!lines.length) return ["  (空)"];
	const out = [`  ${lines[0]}`];
	const body = lines.slice(1).filter((l) => l.trim());
	out.push(...body.slice(0, MAX_BODY).map((l) => `  ${clip(l, WIDTH)}`));
	if (body.length > MAX_BODY) out.push(`  …ほか ${body.length - MAX_BODY} 行`);
	return out;
}

// 読めない形のコマンド。そのまま実行されることを断って、生で見せる。
// 承認の根拠になるので、後ろに付いた操作を隠さない: できるだけ全文を出し、超えるときは先頭と末尾を出して省略を明示する
const FULL_LINES = 60;
const FULL_COLS = 240;
export function rawText(
	command: string,
	heading = "解釈できない形のコマンドです。次がそのまま実行されます:",
): string {
	let truncated = false;
	const cut = (l: string) => {
		if (l.length <= FULL_COLS) return l;
		truncated = true;
		return `${l.slice(0, FULL_COLS - 30)} …(${l.length - FULL_COLS + 10} 文字を省略)… ${l.slice(-20)}`;
	};
	const lines = command.split("\n");
	let shown: string[];
	if (lines.length <= FULL_LINES) shown = lines.map(cut);
	else {
		truncated = true;
		shown = [
			...lines.slice(0, 40).map(cut),
			`…(途中の ${lines.length - 55} 行を省略)…`,
			...lines.slice(-15).map(cut),
		];
	}
	const warn = truncated ? "\n⚠ 長いので途中を省略しています。全体を確認できないので、通常は拒否してください" : "";
	return `${heading}\n${shown.join("\n")}${warn}`;
}

// origin の URL。https://user:token@host/… の認証情報は出さない
export function originUrl(dir: string): string | null {
	const r = git(dir, ["remote", "get-url", "origin"]);
	return r.ok && r.out ? r.out.replace(/^([a-z][a-z0-9+.-]*:\/\/)[^@/]+@/i, "$1") : null;
}

// 構造を組めたら文章を、組めなかった (リポジトリ不明・対象やメッセージを取れない) ら null。
// 取れないものを「取れない」と書いて承認させないよう、呼び出し側は生のコマンドの表示に切り替える
export function describeCommit(a: Extract<Analysis, { recognized: true }>, cwd: string): string | null {
	const { dir, adds } = walk(a, cwd);
	const spec = a.spec;
	const top = git(dir, ["rev-parse", "--show-toplevel"]);
	if (!top.ok) return null;
	const out: string[] = [];
	const url = originUrl(dir);
	out.push(`リポジトリ: ${url ?? `(origin なし) ${tilde(top.out)}`}`);
	const branch = git(dir, ["branch", "--show-current"]).out;
	const hasHead = git(dir, ["rev-parse", "-q", "--verify", "HEAD"]).ok;
	let line = branch
		? `ブランチ:   ${branch}${hasHead ? "" : " (初回のコミット)"}`
		: hasHead
			? `ブランチ:   (detached HEAD ${git(dir, ["rev-parse", "--short", "HEAD"]).out})`
			: "ブランチ:   (初回のコミット)";
	const up = git(dir, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]);
	if (up.ok) {
		const lr = git(dir, ["rev-list", "--left-right", "--count", "@{u}...HEAD"]).out.split(/\s+/);
		line += `  → ${up.out}` + (lr.length === 2 ? ` (${lr[1]} ahead, ${lr[0]} behind)` : "");
	}
	out.push(line, "");

	const w = wouldCommit(dir, spec, adds, top.out);
	if (!w) return null;
	{
		const f = fileLines(w.status, w.num);
		const empty = w.empty && !spec.amend && !spec.allowEmpty;
		out.push(empty ? "対象:       コミットする変更が無い (実行すると失敗する)" : `対象:       ${f.total}`);
		out.push(...f.lines);
		if (!spec.all && !(spec.pathspec.length > 0)) {
			const un = git(dir, ["diff", "--name-only", "--no-ext-diff"]).out.split("\n").filter(Boolean);
			if (un.length) out.push(`  (含まれない未ステージの変更: ${un.length} ファイル)`);
		}
	}
	out.push("");
	const notes: string[] = [];
	if (spec.amend) {
		const last = git(dir, ["log", "-1", "--format=%h %s"]).out;
		notes.push(`--amend: 直前のコミットを書き換える (${last})`);
	}
	if (spec.noVerify) notes.push("--no-verify: コミットの hook を飛ばす");
	if (spec.allowEmpty) notes.push("--allow-empty");
	if (spec.sign) notes.push("-S: 署名する");
	if (spec.signoff) notes.push("-s: Signed-off-by の行がメッセージの末尾に付く");
	notes.push(...spec.notes);
	const msg = readMessage(spec, dir);
	if (msg.text !== null) out.push("メッセージ:", ...messageLines(msg.text));
	else if (spec.amend && spec.noEdit) out.push("メッセージ: (変更しない。直前のコミットのまま)");
	else return null;
	if (notes.length) out.push("", "注意:", ...notes.map((n) => `  ${n}`));
	return out.join("\n");
}

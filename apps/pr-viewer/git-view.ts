// PR ビューアの読み取り専用 git 実行器。承認の前に、リポジトリ内の設定・属性・hook が指す外部のコードを動かさない。
// 設計: docs/change/0060-local-pr-viewer.md の C9。契約: .tmp/keep/prv-app/api-contract.md
// 段 1 は独立させるため、harness の .ts は import しない。
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join, resolve } from "node:path";

/** 契約のエラー。message は日本語の短文で、パス・引数・内部の例外を含めない。 */
export class ApiError extends Error {
	status: number;
	code: string;
	/** 統合の衝突したパス（conflict のときだけ。件数・長さは呼び出し側で絞る） */
	conflicts?: string[];
	/** 拒否の原因の詳細（paths・pathCount・op。安全な形に絞って渡す） */
	details?: Record<string, unknown>;
	constructor(status: number, code: string, message: string, conflicts?: string[], details?: Record<string, unknown>) {
		super(message);
		this.status = status;
		this.code = code;
		if (conflicts !== undefined) this.conflicts = conflicts;
		if (details !== undefined) this.details = details;
	}
}

export type Limits = { timeoutMs: number; maxBytes: number };
const limits: Limits = { timeoutMs: 10_000, maxBytes: 4 * 1024 * 1024 };

/** 試験・開発用に上限を差し替える（起動の引数からだけ呼ぶ）。 */
export function configureLimits(next: Partial<Limits>): void {
	if (next.timeoutMs !== undefined) limits.timeoutMs = next.timeoutMs;
	if (next.maxBytes !== undefined) limits.maxBytes = next.maxBytes;
}

// 設定が指す外部のコードを止める固定の先頭引数（worktree.ts の SAFE_GIT_ARGS と同じ考え方）
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
	"core.untrackedCache=false",
	"-c",
	"core.attributesFile=/dev/null",
	"-c",
	"core.quotePath=false",
	"-c",
	"diff.external=",
	"-c",
	"diff.submodule=short",
	"-c",
	"protocol.ext.allow=never",
	"-c",
	"log.showSignature=false",
	"-c",
	"color.ui=never",
	"-c",
	"gc.auto=0",
	"-c",
	"maintenance.auto=false",
];

// HOME に使う空のディレクトリ（利用者の global 設定を読ませない）。cwd にも使い、実際のパスを子に見せない
const sandboxDir = mkdtempSync(join(tmpdir(), "prv-home-"));
process.on("exit", () => {
	try {
		rmSync(sandboxDir, { recursive: true, force: true });
	} catch {
		// 後片付けの失敗は無視
	}
});

function gitEnv(): Record<string, string> {
	return {
		PATH: process.env.PATH ?? "/usr/local/bin:/usr/bin:/bin",
		HOME: sandboxDir,
		GIT_OPTIONAL_LOCKS: "0",
		GIT_TERMINAL_PROMPT: "0",
		GIT_LITERAL_PATHSPECS: "1",
		GIT_CONFIG_NOSYSTEM: "1",
		GIT_CONFIG_GLOBAL: "/dev/null",
		GIT_ATTR_NOSYSTEM: "1",
		// partial clone の不足 object を、承認の前に外部へ取りに行かせない
		GIT_NO_LAZY_FETCH: "1",
		GIT_ALLOW_PROTOCOL: "",
		LC_ALL: "C",
	};
}

export type GitOut = { code: number; out: string; truncated: boolean };

/**
 * git を 1 回実行する。shell は使わない。
 * cap を超えた出力は、mode が "error" なら git_too_large、"truncate" なら途中で打ち切って truncated にする。
 */
function spawnGit(
	gitDir: string | null,
	args: string[],
	mode: "error" | "truncate",
	cap: number,
	input?: string,
): Promise<GitOut> {
	return new Promise((resolvePromise, reject) => {
		const argv = [...(gitDir ? [`--git-dir=${gitDir}`] : []), ...SAFE_ARGS, ...args];
		const child = spawn("git", argv, {
			shell: false,
			cwd: sandboxDir,
			env: gitEnv(),
			stdio: [input === undefined ? "ignore" : "pipe", "pipe", "ignore"],
		});
		if (input !== undefined && child.stdin) {
			child.stdin.on("error", () => {
				// git が入力を読まずに終わったときの EPIPE は、終了コードで判断する
			});
			child.stdin.end(input);
		}
		const chunks: Buffer[] = [];
		let size = 0;
		let truncated = false;
		let settled = false;
		const finish = (fn: () => void) => {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			fn();
		};
		const timer = setTimeout(() => {
			child.kill("SIGKILL");
			finish(() => reject(new ApiError(500, "git_timeout", "git の実行が時間切れになりました。")));
		}, limits.timeoutMs);
		child.stdout.on("data", (buf: Buffer) => {
			if (settled || truncated) return;
			if (size + buf.length > cap) {
				if (mode === "error") {
					child.kill("SIGKILL");
					finish(() => reject(new ApiError(500, "git_too_large", "git の出力が大きすぎます。")));
					return;
				}
				chunks.push(buf.subarray(0, cap - size));
				size = cap;
				truncated = true;
				child.kill("SIGKILL");
				return;
			}
			chunks.push(buf);
			size += buf.length;
		});
		child.on("error", () => {
			finish(() => reject(new ApiError(500, "git_failed", "git を実行できませんでした。")));
		});
		child.on("close", (code) => {
			finish(() =>
				resolvePromise({
					code: truncated ? 0 : (code ?? 1),
					out: Buffer.concat(chunks).toString("utf8"),
					truncated,
				}),
			);
		});
	});
}

/** 出力が上限を超えたらエラーにする。終了コードが 0 でなければ git_failed（allowFail のときは返す）。 */
export async function git(
	repo: Repo | null,
	args: string[],
	allowFail = false,
): Promise<GitOut> {
	const r = await spawnGit(repo ? repo.gitDir : null, args, "error", limits.maxBytes);
	if (r.code !== 0 && !allowFail) throw new ApiError(500, "git_failed", "git の実行に失敗しました。");
	return r;
}

// ---- 書き込み用の入口 ----

const MAX_INPUT_BYTES = 1024 * 1024;
const OID_ANY = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/;
const REVIEW_REF_RE = /^refs\/pi\/review\/p[0-9a-f]{16}$/;
const ALLOWED_CONFIG_RE = /^(?:user\.name|user\.email|commit\.gpgsign)=[^\0\n]*$/;
const noDash = (a: string): boolean => a !== "" && !a.startsWith("-") && !a.includes("\0");
const flagsOnly = (args: string[], flags: readonly string[]): boolean => args.every((a) => flags.includes(a) || noDash(a));

/** 書き込み用の git に許す argv か。先頭の -c はコミットの作者設定 3 つだけ。 */
export function writeArgvAllowed(argv: string[]): boolean {
	let i = 0;
	while (argv[i] === "-c") {
		if (typeof argv[i + 1] !== "string" || !ALLOWED_CONFIG_RE.test(argv[i + 1])) return false;
		i += 2;
	}
	const sub = argv[i];
	const rest = argv.slice(i + 1);
	if (rest.some((a) => typeof a !== "string" || a.includes("\0"))) return false;
	switch (sub) {
		case "rev-parse":
			return flagsOnly(rest, ["--verify", "--quiet", "--git-common-dir", "--show-toplevel", "--is-bare-repository"]);
		case "cat-file":
			return flagsOnly(rest, ["-s", "-t", "-e", "-p"]);
		case "ls-tree":
			return flagsOnly(rest, ["-z", "-r", "--name-only", "-l"]);
		case "for-each-ref":
			return rest.every((a) => noDash(a) || /^--(?:format|count|sort)=[^\0]*$/.test(a));
		case "hash-object":
			return rest.length === 2 && rest[0] === "-w" && rest[1] === "--stdin";
		case "mktree":
			return rest.length === 0 || (rest.length === 1 && rest[0] === "-z");
		case "commit-tree": {
			// commit-tree <tree> (-p <親>)* -F -
			if (rest.length < 3 || !OID_ANY.test(rest[0])) return false;
			const tail = rest.slice(-2);
			if (tail[0] !== "-F" || tail[1] !== "-") return false;
			const mid = rest.slice(1, -2);
			if (mid.length % 2 !== 0) return false;
			for (let k = 0; k < mid.length; k += 2) if (mid[k] !== "-p" || !OID_ANY.test(mid[k + 1])) return false;
			return true;
		}
		case "update-ref": {
			// update-ref --no-deref <ref> <新> [<旧>]。-d・--stdin は許さない
			if (rest[0] !== "--no-deref" || rest.length < 3 || rest.length > 4) return false;
			return REVIEW_REF_RE.test(rest[1]) && rest.slice(2).every((a) => OID_ANY.test(a));
		}
		case "merge-base":
			return flagsOnly(rest, ["--is-ancestor"]);
	}
	return false;
}

export type WriteResult = { code: number; stdout: string; stderr: string };

/** 書き込み用の git。allowlist にある argv だけを、安全な実行（固定の先頭引数・空の HOME・shell なし）で動かす。 */
export async function gitWrite(repo: Repo, argv: string[], input?: string): Promise<WriteResult> {
	if (!writeArgvAllowed(argv)) throw new ApiError(500, "git_denied", "許可されていない git の操作です。");
	if (input !== undefined && Buffer.byteLength(input, "utf8") > MAX_INPUT_BYTES) {
		throw new ApiError(500, "git_too_large", "git への入力が大きすぎます。");
	}
	const r = await spawnGit(repo.gitDir, argv, "error", limits.maxBytes, input);
	return { code: r.code, stdout: r.out, stderr: "" };
}

/** review-git.ts の Git 型に合うアダプター（リポジトリごとに束縛する）。 */
export function gitAdapter(repo: Repo): (argv: string[], opts?: { input?: string }) => Promise<WriteResult> {
	return (argv, opts) => gitWrite(repo, argv, opts?.input);
}

/** 出力が cap を超えたら打ち切って truncated を返す（diff 用）。 */
export async function gitCapped(repo: Repo, args: string[], cap: number): Promise<GitOut> {
	const r = await spawnGit(repo.gitDir, args, "truncate", Math.min(cap, limits.maxBytes));
	if (r.code !== 0 && !r.truncated) throw new ApiError(500, "git_failed", "git の実行に失敗しました。");
	return r;
}

// ---- 形の検査 ----

const OID_RE = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/;
export function isOid(s: string): boolean {
	return OID_RE.test(s);
}

function sha256Hex(s: string): string {
	return createHash("sha256").update(s).digest("hex");
}

export function prKeyOf(branch: string): string {
	return `p${sha256Hex(`v1\0refs/heads/${branch}`).slice(0, 16)}`;
}

// ---- リポジトリ ----

export type Repo = { repoId: string; name: string; gitDir: string };

/** `--repo` のパスを登録する。git のリポジトリでなければ null。パスは Repo の gitDir にだけ残る（応答へ出さない）。 */
export async function openRepo(path: string): Promise<Repo | null> {
	let real: string;
	try {
		real = realpathSync(resolve(path));
	} catch {
		return null;
	}
	// 利用者が指したリポジトリで最初に動かす git。固定の argv と空の HOME で実行する
	// bare では --show-toplevel が失敗するので、--is-bare-repository で受ける。
	// 指したパスがリポジトリの最上位（または bare の git dir 自身）でなければ断る（親のリポジトリを黙って拾わない）
	const r = await revParse(real, ["--git-common-dir", "--show-toplevel"]);
	let lines: string[] | null = null;
	if (r !== null) {
		try {
			if (r[1] && realpathSync(r[1]) === real) lines = r;
		} catch {
			lines = null;
		}
	} else {
		const b = await revParse(real, ["--git-common-dir", "--is-bare-repository"]);
		if (b && b[1] === "true") lines = [b[0], ""];
	}
	if (!lines || !lines[0]) return null;
	let gitDir: string;
	try {
		gitDir = realpathSync(resolve(real, lines[0]));
	} catch {
		return null;
	}
	if (lines[1] === "" && gitDir !== real) return null;
	const top = lines[1] ? lines[1] : gitDir.replace(/\.git$/, "").replace(/\/$/, "");
	return { repoId: `r${sha256Hex(gitDir).slice(0, 8)}`, name: basename(top), gitDir };
}

function revParse(cwd: string, args: string[]): Promise<string[] | null> {
	return new Promise((done) => {
		const child = spawn("git", [...SAFE_ARGS, "rev-parse", ...args], {
			shell: false,
			cwd,
			env: gitEnv(),
			stdio: ["ignore", "pipe", "ignore"],
		});
		const chunks: Buffer[] = [];
		const timer = setTimeout(() => child.kill("SIGKILL"), limits.timeoutMs);
		child.stdout.on("data", (b: Buffer) => chunks.push(b));
		child.on("error", () => done(null));
		child.on("close", (code) => {
			clearTimeout(timer);
			done(code === 0 ? Buffer.concat(chunks).toString("utf8").split("\n") : null);
		});
	});
}

// ---- ref ----

export type BranchRef = {
	branch: string; // "feature/x"
	oid: string;
	author: string;
	at: string;
	atUnix: number;
	subject: string;
};

/** feature/* と bugfix/* の先頭。出力にあるものだけを PR とする（利用者の入力から ref を作らない）。 */
export async function listBranches(repo: Repo): Promise<BranchRef[]> {
	const fmt = ["%(refname)", "%(objectname)", "%(objecttype)", "%(committerdate:unix)", "%(committerdate:iso-strict)", "%(authorname)", "%(contents:subject)"].join("%00");
	const r = await git(repo, ["for-each-ref", `--format=${fmt}`, "refs/heads/feature/", "refs/heads/bugfix/"]);
	const out: BranchRef[] = [];
	for (const line of r.out.split("\n")) {
		if (!line) continue;
		const f = line.split("\0");
		if (f.length < 7) continue;
		const [refname, oid, type, unix, iso, author, subject] = f;
		if (type !== "commit" || !isOid(oid) || !refname.startsWith("refs/heads/")) continue;
		out.push({ branch: refname.slice("refs/heads/".length), oid, author, at: iso, atUnix: Number(unix) || 0, subject });
	}
	return out;
}

/** 統合先: develop → main → master。どれも無ければ null。 */
export async function resolveTarget(repo: Repo): Promise<{ name: string; oid: string } | null> {
	const r = await git(repo, ["for-each-ref", "--format=%(refname)%00%(objectname)%00%(objecttype)", "refs/heads/develop", "refs/heads/main", "refs/heads/master"]);
	const found = new Map<string, string>();
	for (const line of r.out.split("\n")) {
		const f = line.split("\0");
		if (f.length === 3 && f[2] === "commit" && isOid(f[1])) found.set(f[0].slice("refs/heads/".length), f[1]);
	}
	for (const name of ["develop", "main", "master"]) {
		const oid = found.get(name);
		if (oid) return { name, oid };
	}
	return null;
}

// ---- 解析 ----

export type FileStatus = "A" | "M" | "D" | "R";
export type FileEntry = {
	path: string;
	oldPath: string | null;
	status: FileStatus;
	additions: number;
	deletions: number;
	binary: boolean;
};

/** `git diff -z --raw` の出力。[status, oldPath, path] の列。 */
export function parseRaw(out: string): Array<{ status: FileStatus; oldPath: string | null; path: string }> {
	const t = out.split("\0");
	const res: Array<{ status: FileStatus; oldPath: string | null; path: string }> = [];
	for (let i = 0; i < t.length; ) {
		const meta = t[i++];
		if (!meta.startsWith(":")) continue;
		const letter = meta.split(" ")[4]?.[0] ?? "M";
		if (letter === "R" || letter === "C") {
			const oldPath = t[i++];
			const path = t[i++];
			res.push({ status: "R", oldPath, path });
		} else {
			const path = t[i++];
			const status: FileStatus = letter === "A" ? "A" : letter === "D" ? "D" : "M";
			res.push({ status, oldPath: null, path });
		}
	}
	return res;
}

/** `git diff -z --numstat` の出力。バイナリは additions・deletions が "-"。 */
export function parseNumstat(out: string): Array<{ path: string; additions: number; deletions: number; binary: boolean }> {
	const t = out.split("\0");
	const res: Array<{ path: string; additions: number; deletions: number; binary: boolean }> = [];
	for (let i = 0; i < t.length; ) {
		const head = t[i++];
		if (!head) continue;
		const m = /^(\d+|-)\t(\d+|-)\t(.*)$/s.exec(head);
		if (!m) continue;
		let path = m[3];
		if (path === "") {
			// 改名: 次の 2 つが旧・新
			i++;
			path = t[i++];
		}
		const binary = m[1] === "-";
		res.push({ path, additions: binary ? 0 : Number(m[1]), deletions: binary ? 0 : Number(m[2]), binary });
	}
	return res;
}

export type DiffLine = { t: " " | "+" | "-"; o: number | null; n: number | null; s: string };
export type Hunk = { header: string; oldStart: number; oldLines: number; newStart: number; newLines: number; lines: DiffLine[] };

/** unified diff を Hunk の列にする。ファイルの見出し（diff --git・---・+++）は読み飛ばす。 */
export function parseDiff(text: string): Hunk[] {
	const hunks: Hunk[] = [];
	let cur: Hunk | null = null;
	let o = 0;
	let n = 0;
	const lines = text.split("\n");
	if (lines.length && lines[lines.length - 1] === "") lines.pop();
	for (const line of lines) {
		const h = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/.exec(line);
		if (h) {
			cur = {
				header: line,
				oldStart: Number(h[1]),
				oldLines: h[2] === undefined ? 1 : Number(h[2]),
				newStart: Number(h[3]),
				newLines: h[4] === undefined ? 1 : Number(h[4]),
				lines: [],
			};
			o = cur.oldStart;
			n = cur.newStart;
			hunks.push(cur);
			continue;
		}
		if (!cur) continue;
		const c = line[0];
		if (c === "+") cur.lines.push({ t: "+", o: null, n: n++, s: line.slice(1) });
		else if (c === "-") cur.lines.push({ t: "-", o: o++, n: null, s: line.slice(1) });
		else if (c === " " || line === "") cur.lines.push({ t: " ", o: o++, n: n++, s: line.slice(1) });
		// "\ No newline at end of file" などは捨てる
	}
	return hunks;
}

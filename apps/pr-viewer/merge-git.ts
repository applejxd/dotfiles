// 統合器（merge.ts）が使う git の実行器。書き込みを含む。
// 設計: docs/change/0062-pr-hub-simplify.md の §3.2・§3.4.1。hook・外部の driver・filter を動かさない（S1）。
// 独立させるため、node: 標準ライブラリと ./ だけを import する。
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, realpathSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

export type GitRun = { code: number; out: string };

type RunOpts = {
	gitDir?: string; // --git-dir（共通ディレクトリ）。指定が無ければ cwd のリポジトリ
	cwd?: string; // 既定は空のサンドボックス
	input?: string; // 標準入力（メッセージなど）
	write?: boolean; // 書き込み系。GIT_OPTIONAL_LOCKS を設定しない
	env?: Record<string, string>; // 追加の環境変数（コミットの作者など）
	timeoutMs?: number;
	maxBytes?: number;
};

// 設定・属性・hook が指す外部のコードを止める固定の先頭引数
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
	"-c",
	"commit.gpgsign=false",
	"-c",
	"merge.autoStash=false",
	"-c",
	"merge.verifySignatures=false",
	"-c",
	"submodule.recurse=false",
	"-c",
	"fetch.recurseSubmodules=false",
	"-c",
	"core.sparseCheckout=false",
];

// 実行用の空の HOME / cwd。import 時には作らず、最初の使用時に作る (作れない例外を、呼び出し側の固定のエラーに変えられるようにする。S8)
let sandboxCache: string | null = null;
function sandboxDir(): string {
	if (sandboxCache === null) {
		sandboxCache = mkdtempSync(join(tmpdir(), "prv-merge-home-"));
		const dir = sandboxCache;
		process.on("exit", () => {
			try {
				rmSync(dir, { recursive: true, force: true });
			} catch {
				// 後片付けの失敗は無視
			}
		});
	}
	return sandboxCache;
}

function gitEnv(write: boolean, extra?: Record<string, string>): Record<string, string> {
	const env: Record<string, string> = {
		PATH: process.env.PATH ?? "/usr/local/bin:/usr/bin:/bin",
		HOME: sandboxDir(),
		GIT_TERMINAL_PROMPT: "0",
		GIT_LITERAL_PATHSPECS: "1",
		GIT_CONFIG_NOSYSTEM: "1",
		GIT_CONFIG_GLOBAL: "/dev/null",
		GIT_ATTR_NOSYSTEM: "1",
		GIT_NO_LAZY_FETCH: "1",
		GIT_ALLOW_PROTOCOL: "",
		GIT_EDITOR: "true",
		GIT_MERGE_AUTOEDIT: "no",
		LC_ALL: "C",
	};
	if (!write) env.GIT_OPTIONAL_LOCKS = "0";
	return { ...env, ...(extra ?? {}) };
}

/** git を 1 回実行する。shell は使わず、標準エラーは捨てる（S8）。失敗・時間切れ・出力超過は code に載せる。 */
export function runGit(args: string[], opts: RunOpts = {}): Promise<GitRun> {
	const timeoutMs = opts.timeoutMs ?? 60_000;
	const maxBytes = opts.maxBytes ?? 8 * 1024 * 1024;
	return new Promise((done) => {
		const argv = [...(opts.gitDir ? [`--git-dir=${opts.gitDir}`] : []), ...SAFE_ARGS, ...args];
		let child;
		try {
			child = spawn("git", argv, {
				shell: false,
				cwd: opts.cwd ?? sandboxDir(),
				env: gitEnv(opts.write === true, opts.env),
				stdio: [opts.input === undefined ? "ignore" : "pipe", "pipe", "ignore"],
			});
		} catch {
			done({ code: 127, out: "" });
			return;
		}
		if (opts.input !== undefined && child.stdin) {
			child.stdin.on("error", () => {
				// git が入力を読まずに終わったときの EPIPE は、終了コードで判断する
			});
			child.stdin.end(opts.input);
		}
		const chunks: Buffer[] = [];
		let size = 0;
		let settled = false;
		let forced: number | null = null; // 時間切れ・出力超過で止めたときの結果。子の終了を確かめてから返す
		const finish = (r: GitRun) => {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			clearTimeout(grace);
			done(r);
		};
		let grace: ReturnType<typeof setTimeout> | undefined;
		const stop = (code: number) => {
			if (forced !== null) return;
			forced = code;
			child.kill("SIGKILL");
			// 終了通知を待つ。来ないときだけ、一定時間の後に返す
			grace = setTimeout(() => finish({ code, out: "" }), 3000);
		};
		const timer = setTimeout(() => stop(124), timeoutMs);
		child.stdout.on("data", (buf: Buffer) => {
			if (settled || forced !== null) return;
			size += buf.length;
			if (size > maxBytes) {
				stop(125);
				return;
			}
			chunks.push(buf);
		});
		child.on("error", () => finish({ code: 127, out: "" }));
		child.on("close", (code) => finish(forced !== null ? { code: forced, out: "" } : { code: code ?? 1, out: Buffer.concat(chunks).toString("utf8") }));
	});
}

// 最小の git の版。merge-tree --write-tree（2.38）と check-attr --source（2.40）を使う。git は最新版を使う前提なので、古い版への互換は作らない
const MIN_GIT: readonly [number, number] = [2, 40];
let gitVersionCache: Promise<boolean> | null = null;

/** git の版が最小以上か。版を確認できないときも false（安全側）。プロセス内で版は変わらないので、結果を覚える。 */
export function gitVersionOk(): Promise<boolean> {
	gitVersionCache ??= (async () => {
		const r = await runGit(["--version"]);
		// "git version 2.43.0"、"git version 2.39.3 (Apple Git-145)"、"git version 2.43.0.windows.1"
		const m = r.out.match(/^git version (\d+)\.(\d+)/);
		if (r.code !== 0 || !m) return false;
		const major = Number(m[1]);
		const minor = Number(m[2]);
		return major > MIN_GIT[0] || (major === MIN_GIT[0] && minor >= MIN_GIT[1]);
	})();
	return gitVersionCache;
}

/** 共通ディレクトリ（realpath）。リポジトリでなければ null。 */
export async function resolveCommonDir(repo: string): Promise<string | null> {
	let cwd: string;
	try {
		cwd = realpathSync(resolve(repo));
		if (!statSync(cwd).isDirectory()) return null;
	} catch {
		return null;
	}
	const r = await runGit(["rev-parse", "--git-common-dir"], { cwd });
	if (r.code !== 0) return null;
	const line = r.out.split("\n")[0];
	if (!line) return null;
	try {
		return realpathSync(resolve(cwd, line));
	} catch {
		return null;
	}
}

/** 外部のコードを動かしうる設定のキーか（キーは小文字で渡す）。 */
function dangerousKey(key: string, value: string): boolean {
	if (/^merge\..+\.(?:driver|recursivename)$/.test(key)) return true;
	if (/^filter\..+\.(?:clean|smudge|process)$/.test(key)) return true;
	if (/^diff\..+\.(?:command|textconv)$/.test(key) || key === "diff.external") return true;
	if (key === "core.fsmonitor") return value.toLowerCase() !== "false";
	if (key === "core.hookspath") return value !== "/dev/null";
	if (key === "core.alternaterefscommand") return true;
	if (/^include\./.test(key) || /^includeif\./.test(key)) return true;
	if (key === "submodule.recurse") return !/^(?:false|no|off|0)$/i.test(value);
	return false;
}

/** 設定ファイルに外部のコードを動かしうる項目があれば true。ファイルが無ければ false。読めなければ true（安全側）。 */
export async function configHasExternalCode(file: string): Promise<boolean> {
	if (!existsSync(file)) return false;
	const r = await runGit(["config", "--file", file, "--list", "-z"]);
	if (r.code !== 0) return true;
	for (const entry of r.out.split("\0")) {
		if (!entry) continue;
		const nl = entry.indexOf("\n");
		const key = (nl < 0 ? entry : entry.slice(0, nl)).toLowerCase();
		const value = nl < 0 ? "" : entry.slice(nl + 1);
		if (dangerousKey(key, value)) return true;
	}
	return false;
}

export type Identity = { name: string; email: string };

/**
 * 統合器が扱わない設定があるか（外部コードの設定とは別。安全のためではなく、結果が変わるため）。
 * sparse checkout: 統合器は core.sparseCheckout=false で動かすので、sparse のリポジトリでは作業ツリーの展開が変わる。
 * ファイルが無いときは false。読めないときは true（安全側）。
 */
export async function configHasUnsupported(file: string): Promise<boolean> {
	if (!existsSync(file)) return false;
	const r = await runGit(["config", "--file", file, "--list", "-z"]);
	if (r.code !== 0) return true;
	for (const entry of r.out.split("\0")) {
		if (!entry) continue;
		const nl = entry.indexOf("\n");
		const key = (nl < 0 ? entry : entry.slice(0, nl)).toLowerCase();
		const value = nl < 0 ? "" : entry.slice(nl + 1);
		// 値の省略（"[core] sparseCheckout" だけ）は true として扱う（git も同じ）
		if (key === "core.sparsecheckout" && !/^(?:false|no|off|0)$/i.test(value)) return true;
	}
	return false;
}

/** コミットの作者。対象リポジトリの通常の設定（global を含む）を読み取りで 1 回だけ読む。外部のコードは動かない。
 * worktree があれば、その worktree の設定 (config.worktree) も読むように、worktree のパスを cwd にする。 */
export async function readIdentity(gitDir: string, worktree?: string): Promise<Identity | null> {
	const env: Record<string, string> = {};
	const pass = ["HOME", "XDG_CONFIG_HOME", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM"];
	for (const k of pass) {
		const v = process.env[k];
		if (v !== undefined) env[k] = v;
	}
	// gitEnv の既定（HOME のサンドボックスなど）を上書きするため、既定を外した実行を行う
	const r = await runGitPlain(["config", "--get-regexp", "^user\\.(name|email)$"], gitDir, env, worktree);
	if (r.code !== 0) return null;
	let name = "";
	let email = "";
	for (const line of r.out.split("\n")) {
		const sp = line.indexOf(" ");
		if (sp < 0) continue;
		const key = line.slice(0, sp).toLowerCase();
		const value = line.slice(sp + 1).trim();
		if (key === "user.name") name = value;
		if (key === "user.email") email = value;
	}
	const ok = (s: string) => s.length > 0 && s.length <= 256 && !/[\u0000-\u001f\u007f<>]/.test(s);
	return ok(name) && ok(email) ? { name, email } : null;
}

/** 通常の設定を読む専用の実行（識別子の読み取りだけで使う）。固定の先頭引数は付ける。 */
function runGitPlain(args: string[], gitDir: string, env: Record<string, string>, worktree?: string): Promise<GitRun> {
	return new Promise((done) => {
		let child;
		try {
			// worktree があれば、その中で実行して、worktree 固有の設定を読む（--git-dir は使わない）
			child = spawn("git", [...(worktree ? [] : [`--git-dir=${gitDir}`]), ...SAFE_ARGS, ...args], {
				shell: false,
				cwd: worktree ?? sandboxDir(),
				env: {
					PATH: process.env.PATH ?? "/usr/local/bin:/usr/bin:/bin",
					LC_ALL: "C",
					GIT_TERMINAL_PROMPT: "0",
					GIT_OPTIONAL_LOCKS: "0",
					GIT_NO_LAZY_FETCH: "1",
					GIT_ALLOW_PROTOCOL: "",
					...env,
				},
				stdio: ["ignore", "pipe", "ignore"],
			});
		} catch {
			done({ code: 127, out: "" });
			return;
		}
		const chunks: Buffer[] = [];
		const timer = setTimeout(() => child.kill("SIGKILL"), 10_000);
		child.stdout.on("data", (b: Buffer) => {
			if (chunks.length < 64) chunks.push(b);
		});
		child.on("error", () => {
			clearTimeout(timer);
			done({ code: 127, out: "" });
		});
		child.on("close", (code) => {
			clearTimeout(timer);
			done({ code: code ?? 1, out: Buffer.concat(chunks).toString("utf8") });
		});
	});
}

export type WorktreeInfo = { path: string; branch: string | null };

/** `git worktree list --porcelain` の worktree の一覧（bare・実体が無いものは除く）。 */
export async function listWorktrees(gitDir: string): Promise<WorktreeInfo[] | null> {
	let r = await runGit(["worktree", "list", "--porcelain", "-z"], { gitDir });
	let sep = "\0";
	if (r.code !== 0) {
		// -z を知らない古い git
		r = await runGit(["worktree", "list", "--porcelain"], { gitDir });
		sep = "\n";
	}
	if (r.code !== 0) return null;
	const res: WorktreeInfo[] = [];
	let cur: { path: string; branch: string | null; bare: boolean } | null = null;
	const flush = () => {
		if (cur && !cur.bare && existsSync(cur.path)) res.push({ path: cur.path, branch: cur.branch });
		cur = null;
	};
	for (const tok of r.out.split(sep)) {
		if (tok === "") {
			flush();
			continue;
		}
		if (tok.startsWith("worktree ")) {
			flush();
			cur = { path: tok.slice("worktree ".length), branch: null, bare: false };
		} else if (cur && tok.startsWith("branch ")) cur.branch = tok.slice("branch ".length);
		else if (cur && tok === "bare") cur.bare = true;
	}
	flush();
	return res;
}

export type StatusEntry = { code: string; path: string };

/** `git status --porcelain=v1 -z` の解析。改名・複製は旧新の両方を別の項目で返す。 */
export function parseStatus(out: string): StatusEntry[] {
	const t = out.split("\0");
	const res: StatusEntry[] = [];
	for (let i = 0; i < t.length; i++) {
		const e = t[i];
		if (e.length < 4) continue;
		const code = e.slice(0, 2);
		res.push({ code, path: e.slice(3) });
		if (code[0] === "R" || code[0] === "C" || code[1] === "R" || code[1] === "C") {
			const orig = t[++i];
			if (orig) res.push({ code, path: orig });
		}
	}
	return res;
}

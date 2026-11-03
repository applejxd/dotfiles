// PR ビューアのサーバ（段 1: 読み取り専用、段 2: レビューの書き込み、段 A2: 統合）。
// 起動: node apps/pr-viewer/server.ts --repo <パス> [--repo <パス>…] [--port <N>] [--allow-host <名前>…] [--web-dir <パス>]
//       [--allow-merge] [--allow-create] [--rules-file <パス>]
//       [--allow-jobs] [--job-timeout-ms <N>] [--test-platform <名前>] [--pis-command <絶対パス>]
//       [--state-dir <パス>] [--job-model <提供元/モデル>]
// 設計: docs/change/0060-local-pr-viewer.md・docs/change/0062-pr-hub-simplify.md。契約: .tmp/keep/prv-app/api-contract.md
import { createServer } from "node:http";
import type { IncomingMessage, ServerResponse } from "node:http";
import { lstat, readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { ApiError, configureLimits, openRepo } from "./git-view.ts";
import type { Repo } from "./git-view.ts";
import { mergeRequestError, stopMerges } from "./merge-api.ts";
import type { MergeEnv, PostResult } from "./merge-api.ts";
import { createRequestError, stopCreates } from "./feature-api.ts";
import { handleApi, handlePost, isFeaturePostRoute, isJobGetRoute, isJobPostRoute, isMergePostRoute, isPostRoute } from "./routes.ts";
import { DEFAULT_JOB_TIMEOUT_MS, MAX_JOB_TIMEOUT_MS, acquireInstanceLock, jobCapabilities, jobRequestError, recoverJobs, stateDirIsolated, stopJobs } from "./job-api.ts";
import type { JobsConfig } from "./job-api.ts";
import { buildArgv } from "./job-runner.ts";
import { defaultStateDir } from "./job-store.ts";

const DEFAULT_PORT = 8780;
const HOST = "127.0.0.1";

type Options = {
	repos: string[];
	port: number;
	allowHosts: string[];
	webDir: string;
	timeoutMs?: number;
	maxBytes?: number;
	/** 統合を許可する（既定で無効）。値を取らない旗 */
	allowMerge: boolean;
	/** リスクパスを読む rules.json（既定: ~/.config/pi/harness/rules.json。試験で差し替える） */
	rulesFile: string;
	/** 試験用: ff の直前に入れる遅延（競合・停止の再現） */
	mergeDelayMs: number;
	/** pi への依頼（ジョブ）を許可する（既定で無効。Linux のみ）。値を取らない旗 */
	allowJobs: boolean;
	/** 1 回の上限。試験用に ms で指定する（1 ms〜30 分） */
	jobTimeoutMs: number;
	/** 試験用: process.platform の代わりに使う名前 */
	testPlatform: string | null;
	/** pis の絶対パス（既定: ~/.local/bin/pis。試験で偏の pis に差し替える） */
	pisCommand: string;
	/** ジョブの保存先（絶対パス。既定: $XDG_STATE_HOME/pr-viewer） */
	stateDir: string;
	/** pis へ渡す --model（既定は pi の既定に任せる） */
	jobModel: string | null;
	/** 起票を許可する（既定で無効）。値を取らない旗 */
	allowCreate: boolean;
	/** 試験用: 起票の検証の後（記録の前）に入れる遅延 */
	createDelayMs: number;
	/** 試験用: 起票の失敗の注入（add: 枝だけ残る失敗・record: 記録の失敗） */
	createFail: string | null;
};

function parseArgs(argv: string[]): Options | null {
	const o: Options = {
		repos: [],
		port: DEFAULT_PORT,
		allowHosts: [],
		webDir: join(dirname(fileURLToPath(import.meta.url)), "web"),
		allowMerge: false,
		rulesFile: join(homedir(), ".config", "pi", "harness", "rules.json"),
		mergeDelayMs: 0,
		allowJobs: false,
		jobTimeoutMs: DEFAULT_JOB_TIMEOUT_MS,
		testPlatform: null,
		pisCommand: join(homedir(), ".local", "bin", "pis"),
		stateDir: defaultStateDir(),
		jobModel: null,
		allowCreate: false,
		createDelayMs: 0,
		createFail: null,
	};
	for (let i = 0; i < argv.length; i++) {
		const a = argv[i];
		if (a === "--allow-merge") {
			o.allowMerge = true; // 値を取らない。`--allow-merge=1` は未知の旗として断る
			continue;
		}
		if (a === "--allow-create") {
			o.allowCreate = true; // 値を取らない
			continue;
		}
		if (a === "--allow-jobs") {
			o.allowJobs = true; // 値を取らない
			continue;
		}
		const v = argv[i + 1];
		if (v === undefined) return null;
		if (a === "--repo") o.repos.push(v);
		else if (a === "--port") {
			if (!/^\d+$/.test(v) || Number(v) > 65535) return null;
			o.port = Number(v);
		} else if (a === "--allow-host") o.allowHosts.push(v.toLowerCase());
		else if (a === "--web-dir") o.webDir = resolve(v);
		else if (a === "--rules-file") o.rulesFile = resolve(v);
		else if (a === "--git-timeout-ms") o.timeoutMs = Number(v); // 試験用
		else if (a === "--git-max-bytes") o.maxBytes = Number(v); // 試験用
		else if (a === "--merge-test-delay-ms") {
			if (!/^\d+$/.test(v) || Number(v) > 60_000) return null; // 試験用
			o.mergeDelayMs = Number(v);
		} else if (a === "--job-timeout-ms") {
			if (!/^\d+$/.test(v) || Number(v) < 1 || Number(v) > MAX_JOB_TIMEOUT_MS) return null; // 試験用
			o.jobTimeoutMs = Number(v);
		} else if (a === "--test-platform") {
			if (!/^[a-z0-9]{1,16}$/.test(v)) return null; // 試験用
			o.testPlatform = v;
		} else if (a === "--pis-command") {
			if (!isAbsolute(v) || v.includes("\0")) return null;
			o.pisCommand = v;
		} else if (a === "--state-dir") {
			if (!isAbsolute(v) || v.includes("\0")) return null;
			o.stateDir = v;
		} else if (a === "--job-model") {
			if (v.startsWith("-") || buildArgv("x", v) === null) return null; // "<provider>/<model>" の形だけ（先頭の - は旗と紛れるので不可）
			o.jobModel = v;
		} else if (a === "--create-test-delay-ms") {
			if (!/^\d+$/.test(v) || Number(v) > 60_000) return null; // 試験用
			o.createDelayMs = Number(v);
		} else if (a === "--create-test-fail") {
			if (v !== "add" && v !== "record") return null; // 試験用
			o.createFail = v;
		} else return null;
		i++;
	}
	return o;
}

/** Host ヘッダーの検査（DNS rebinding 対策）。ループバック・tailnet の名前・明示した名前だけ許す。 */
export function hostAllowed(header: string | undefined, extra: string[]): boolean {
	if (!header) return false;
	const m = /^([a-z0-9]([a-z0-9.-]*[a-z0-9])?)(:\d{1,5})?$/.exec(header.toLowerCase());
	if (!m) return false;
	const name = m[1];
	if (name === "127.0.0.1" || name === "localhost") return true;
	if (/^[a-z0-9-]+(\.[a-z0-9-]+)*\.ts\.net$/.test(name)) return true;
	return extra.includes(name);
}

const SECURITY_HEADERS: Record<string, string> = {
	"Content-Security-Policy": "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
	"X-Content-Type-Options": "nosniff",
	"Referrer-Policy": "no-referrer",
	"Cache-Control": "no-store",
};

function send(res: ServerResponse, status: number, type: string, body: string | Buffer, extra: Record<string, string> = {}): void {
	res.writeHead(status, { ...SECURITY_HEADERS, "Content-Type": type, ...extra });
	res.end(body);
}

function sendJson(res: ServerResponse, status: number, value: unknown, extra: Record<string, string> = {}): void {
	send(res, status, "application/json; charset=utf-8", JSON.stringify(value), extra);
}

function sendError(res: ServerResponse, status: number, code: string, message: string, extra: Record<string, string> = {}, conflicts?: string[]): void {
	sendJson(res, status, { error: { code, message, ...(conflicts !== undefined ? { conflicts } : {}) } }, extra);
}

// 許可リスト: ディレクトリを走査しない。名前は index.html・app.css・*.js だけ
const STATIC_RE = /^(index\.html|app\.css|[A-Za-z0-9_][A-Za-z0-9_.-]*\.js)$/;
const STATIC_TYPES: Record<string, string> = {
	".html": "text/html; charset=utf-8",
	".css": "text/css; charset=utf-8",
	".js": "text/javascript; charset=utf-8",
};

async function serveStatic(res: ServerResponse, webDir: string, rawName: string): Promise<void> {
	let name: string;
	try {
		name = decodeURIComponent(rawName);
	} catch {
		name = "";
	}
	if (!STATIC_RE.test(name)) return sendError(res, 404, "not_found", "見つかりません。");
	const file = join(webDir, name);
	try {
		const st = await lstat(file);
		if (!st.isFile()) return sendError(res, 404, "not_found", "見つかりません。");
		const body = await readFile(file);
		send(res, 200, STATIC_TYPES[name.slice(name.lastIndexOf("."))] ?? "application/octet-stream", body);
	} catch {
		sendError(res, 404, "not_found", "見つかりません。");
	}
}

const MAX_BODY = 64 * 1024;
const JSON_TYPE_RE = /^application\/json\s*(?:;\s*charset=utf-8\s*)?$/i;

/** Origin があるときは、その host が Host ヘッダーと一致すること（別のサイトからの書き込みを止める）。 */
function originAllowed(origin: string | undefined, host: string | undefined): boolean {
	if (origin === undefined) return true;
	try {
		return host !== undefined && new URL(origin).host.toLowerCase() === host.toLowerCase();
	} catch {
		return false;
	}
}

class TooLarge extends Error {}

function readBody(req: IncomingMessage): Promise<Buffer> {
	return new Promise((done, fail) => {
		const declared = Number(req.headers["content-length"]);
		if (Number.isFinite(declared) && declared > MAX_BODY) return fail(new TooLarge());
		const chunks: Buffer[] = [];
		let size = 0;
		req.on("data", (b: Buffer) => {
			size += b.length;
			if (size > MAX_BODY) {
				chunks.length = 0;
				req.removeAllListeners("data");
				req.resume();
				return fail(new TooLarge());
			}
			chunks.push(b);
		});
		req.on("end", () => done(Buffer.concat(chunks)));
		req.on("error", () => fail(new ApiError(400, "bad_request", "リクエストの形が正しくありません。")));
	});
}

/** 設定から、ジョブ API に渡す形を作る。 */
function jobsOf(opts: Options): JobsConfig {
	return {
		enabled: opts.allowJobs,
		platform: opts.testPlatform ?? process.platform,
		pisCommand: opts.pisCommand,
		stateDir: opts.stateDir,
		timeoutMs: opts.jobTimeoutMs,
		model: opts.jobModel,
		rulesFile: opts.rulesFile,
	};
}

/** 書き込み（POST）。共通の規則を検査してから routes.ts へ渡す。統合系・ジョブ系は Origin 必須・--allow-merge / --allow-jobs が要る（先に断る）。 */
async function servePost(repos: Repo[], req: IncomingMessage, res: ServerResponse, pathname: string, opts: Options): Promise<void> {
	if (isFeaturePostRoute(pathname)) {
		const denied = createRequestError(req.headers, opts.allowCreate);
		if (denied) return sendError(res, denied.status, denied.code, denied.message);
	} else if (isMergePostRoute(pathname)) {
		const denied = mergeRequestError(req.headers, opts.allowMerge);
		if (denied) return sendError(res, denied.status, denied.code, denied.message);
	} else if (isJobPostRoute(pathname)) {
		const denied = jobRequestError(req.headers, jobsOf(opts), "POST");
		if (denied) return sendError(res, denied.status, denied.code, denied.message);
	} else if (!originAllowed(req.headers.origin, req.headers.host)) {
		return sendError(res, 403, "forbidden_origin", "この Origin は許可されていません。");
	}
	if (req.headers["x-prv"] !== "1" || !JSON_TYPE_RE.test(req.headers["content-type"] ?? "")) {
		return sendError(res, 400, "bad_request", "必要なヘッダーがありません。");
	}
	let raw: Buffer;
	try {
		raw = await readBody(req);
	} catch (e) {
		if (e instanceof TooLarge) {
			res.on("finish", () => req.destroy());
			return sendError(res, 413, "too_large", "リクエストの本文が大きすぎます。", { Connection: "close" });
		}
		throw e;
	}
	let body: unknown;
	try {
		body = JSON.parse(raw.toString("utf8"));
	} catch {
		return sendError(res, 400, "bad_json", "JSON の形が正しくありません。");
	}
	if (typeof body !== "object" || body === null || Array.isArray(body)) {
		return sendError(res, 400, "bad_request", "リクエストの形が正しくありません。");
	}
	const env: MergeEnv = { rulesFile: opts.rulesFile, testDelayMs: opts.mergeDelayMs };
	const result: PostResult = await handlePost(repos, pathname, body as Record<string, unknown>, env, jobsOf(opts), {
		testDelayMs: opts.createDelayMs,
		testFail: opts.createFail,
	});
	sendJson(res, result.status, result.body);
}

/** 統合の処理が終わった後、応答を送り終えるのを待つ上限（ミリ秒）。 */
const FLUSH_WAIT_MS = 5000;
/** 実行中の統合の要求。停止のとき、これらが応答を書き終えるのを待つ（途中で止めると、状態ファイルが残って復旧が要る）。 */
const activeMerges = new Set<Promise<void>>();

async function drainMerges(): Promise<void> {
	while (activeMerges.size > 0) await Promise.allSettled([...activeMerges]);
}

function isMergePost(req: IncomingMessage): boolean {
	if (req.method !== "POST") return false;
	try {
		const p = new URL(req.url ?? "", "http://localhost").pathname;
		return isMergePostRoute(p) || isJobPostRoute(p) || isFeaturePostRoute(p); // ジョブや起票も、応答を書き終えるまで停止を待つ
	} catch {
		return false;
	}
}

function makeHandler(repos: Repo[], opts: Options) {
	const handle = makeInnerHandler(repos, opts);
	return async (req: IncomingMessage, res: ServerResponse): Promise<void> => {
		if (!isMergePost(req)) return await handle(req, res);
		let settle: () => void = () => {};
		const tracked = new Promise<void>((done) => (settle = done));
		activeMerges.add(tracked);
		try {
			await handle(req, res); // 内側で結果（エラーを含む）を送る
			// 応答を送り終える（または接続が切れている）まで待つ。応答を読まないクライアントで停止が終わらないよう、上限を設ける
			if (!res.writableFinished && !res.destroyed) {
				await Promise.race([
					new Promise<void>((done) => res.once("close", () => done())),
					new Promise<void>((done) => setTimeout(done, FLUSH_WAIT_MS).unref()),
				]);
			}
		} finally {
			activeMerges.delete(tracked);
			settle();
		}
	};
}

function makeInnerHandler(repos: Repo[], opts: Options) {
	return async (req: IncomingMessage, res: ServerResponse): Promise<void> => {
		try {
			if (!hostAllowed(req.headers.host, opts.allowHosts)) {
				return sendError(res, 403, "forbidden_host", "この Host は許可されていません。");
			}
			if (req.method === "POST") {
				let pathname = "";
				try {
					pathname = new URL(req.url ?? "", "http://localhost").pathname;
				} catch {
					pathname = "";
				}
				if (isPostRoute(pathname)) return await servePost(repos, req, res, pathname, opts);
			}
			if (req.method !== "GET" && req.method !== "HEAD") {
				return sendError(res, 405, "method_not_allowed", "GET と HEAD だけ使えます。", { Allow: "GET, HEAD" });
			}
			const target = req.url ?? "";
			if (!target.startsWith("/")) return sendError(res, 400, "bad_request", "リクエストの形が正しくありません。");
			let url: URL;
			try {
				url = new URL(target, "http://localhost");
			} catch {
				return sendError(res, 400, "bad_request", "リクエストの形が正しくありません。");
			}
			const p = url.pathname;
			if (p === "/") return await serveStatic(res, opts.webDir, "index.html");
			if (p.startsWith("/web/")) return await serveStatic(res, opts.webDir, p.slice("/web/".length));
			if (p === "/api/capabilities") {
				return sendJson(res, 200, {
					merge: opts.allowMerge,
					create: opts.allowCreate,
					targets: ["develop"],
					...jobCapabilities(jobsOf(opts)),
				});
			}
			if (isJobGetRoute(p)) {
				const denied = jobRequestError(req.headers, jobsOf(opts), "GET");
				if (denied) return sendError(res, denied.status, denied.code, denied.message);
			}
			if (p.startsWith("/api/")) return sendJson(res, 200, await handleApi(repos, p, url.searchParams, jobsOf(opts)));
			return sendError(res, 404, "not_found", "見つかりません。");
		} catch (e) {
			if (e instanceof ApiError) return sendError(res, e.status, e.code, e.message, {}, e.conflicts);
			return sendError(res, 500, "internal", "内部エラーです。"); // 例外の中身は返さない
		}
	};
}

async function main(): Promise<void> {
	const opts = parseArgs(process.argv.slice(2));
	if (!opts || opts.repos.length === 0) {
		process.stderr.write(
			"使い方: node server.ts --repo <パス> [--repo <パス>…] [--port <N>] [--allow-host <名前>…] [--web-dir <パス>] [--allow-merge] [--allow-create] [--allow-jobs] [--rules-file <パス>]\n",
		);
		process.exit(2);
	}
	const jobs = jobsOf(opts);
	if (jobs.enabled && jobs.platform !== "linux") {
		process.stderr.write("--allow-jobs は Linux でだけ使えます。\n");
		process.exit(2);
	}
	const repos: Repo[] = [];
	for (const [i, p] of opts.repos.entries()) {
		const r = await openRepo(p);
		if (!r) {
			process.stderr.write(`--repo の ${i + 1} 番目が git のリポジトリではありません。\n`);
			process.exit(2);
		}
		if (!repos.some((x) => x.repoId === r.repoId)) repos.push(r);
	}
	configureLimits({ timeoutMs: opts.timeoutMs, maxBytes: opts.maxBytes });
	if (jobs.enabled) {
		// 保存先が共通 .git や worktree の中なら、何も作らずに断る
		if (!(await stateDirIsolated(jobs, repos))) {
			process.stderr.write("--state-dir は、対象リポジトリの .git や worktree の中には置けません。別の場所を指定してください。\n");
			process.exit(2);
		}
		// 同じ state root でこのアプリは 1 つだけ。回復より先に取る（先発の健全なジョブを止めないため）
		const inst = await acquireInstanceLock(jobs.stateDir);
		if (!inst.ok) {
			process.stderr.write(
				inst.reason === "held"
					? "同じ --state-dir を使う、ほかのサーバがすでに動いています。先にそちらを止めるか、別の --state-dir を指定してください。\n"
					: "--state-dir の排他（flock）を取れませんでした。flock コマンドと --state-dir の書き込み権限を確認してください。\n",
			);
			process.exit(2);
		}
	}
	await recoverJobs(jobs, repos); // 前回の実行中のジョブを interrupted にし、古い排他を掃除する（自動では再開しない）
	const server = createServer(makeHandler(repos, opts));
	server.listen(opts.port, HOST, () => {
		const addr = server.address();
		const port = typeof addr === "object" && addr ? addr.port : opts.port;
		process.stdout.write(`listening http://${HOST}:${port}\n`);
	});
	// 停止: 新しい統合は受けず、実行中の統合は終わる（応答を書き終える）まで待つ。途中で止めると、状態ファイルが残って recover が要る。
	// 一律の強制終了は設けない（強制するなら SIGKILL。そのときは recover）
	let stopped = false;
	const stop = () => {
		if (stopped) return; // 重複した SIGTERM・SIGINT でも、実行中の統合は止めない
		stopped = true;
		stopMerges();
		stopCreates();
		// 終了は 1 本の順序だけで行う: 実行中の統合の完了 → 接続を閉じる → server が閉じる → exit。
		// server.close の callback で直接 exit すると、通信が切れた統合の途中で終わってしまう
		const closed = new Promise<void>((done) => server.close(() => done()));
		server.closeIdleConnections();
		void (async () => {
			await stopJobs(); // 実行中のジョブは interrupted にして止め、結果の確定中のものだけ待つ
			await drainMerges();
			server.closeAllConnections();
			await closed;
			process.exit(0);
		})();
	};
	process.on("SIGINT", stop);
	process.on("SIGTERM", stop);
}

await main();

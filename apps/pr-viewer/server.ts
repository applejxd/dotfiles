// PR ビューアのサーバ（段 1: 読み取り専用、段 2: レビューの書き込み、段 A2: 統合）。
// 起動: node apps/pr-viewer/server.ts --repo <パス> [--repo <パス>…] [--port <N>] [--allow-host <名前>…] [--web-dir <パス>]
//       [--allow-merge] [--rules-file <パス>] [--state-dir <パス>]
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
import { handleApi, handlePost, isMergePostRoute, isPostRoute } from "./routes.ts";

/** 既定の stateDir（$XDG_STATE_HOME/pr-viewer）。統合の掃除の退避先に使う。 */
function defaultStateDir(env: NodeJS.ProcessEnv = process.env): string {
	const base = env.XDG_STATE_HOME && env.XDG_STATE_HOME.startsWith("/") ? env.XDG_STATE_HOME : join(homedir(), ".local", "state");
	return join(base, "pr-viewer");
}

const DEFAULT_PORT = 8780;
const HOST = "127.0.0.1";

/** GET /api/version の本体。main() が起動時に 1 回だけ決める（稼働中は変わらない）。 */
let versionInfo: { pinned: boolean; oid: string | null; ref: string | null; pinnedAt: string | null } = {
	pinned: false,
	oid: null,
	ref: null,
	pinnedAt: null,
};

/** pr_app.py が書いた PINNED.json を読む。形が正しくなければ「固定なし」。 */
async function readPinned(file: string | null): Promise<typeof versionInfo> {
	const none = { pinned: false, oid: null, ref: null, pinnedAt: null };
	if (file === null) return none;
	try {
		const j = JSON.parse(await readFile(file, "utf8")) as Record<string, unknown>;
		const str = (x: unknown, re: RegExp): string | null => (typeof x === "string" && re.test(x) ? x : null);
		const oid = str(j.oid, /^[0-9a-f]{40}$/);
		if (oid === null) return none;
		return { pinned: true, oid, ref: str(j.ref, /^[\w./-]{1,100}$/), pinnedAt: str(j.pinnedAt, /^[0-9TZ:.+-]{10,40}$/) };
	} catch {
		return none;
	}
}

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
	/** 統合の掃除の退避先などの保存先（絶対パス。既定: $XDG_STATE_HOME/pr-viewer） */
	stateDir: string;
	/** 稼働版の記録（pr_app.py が固定した checkout の PINNED.json。無ければ固定なし） */
	pinnedFile: string | null;
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
		stateDir: defaultStateDir(),
		pinnedFile: null,
	};
	for (let i = 0; i < argv.length; i++) {
		const a = argv[i];
		if (a === "--allow-merge") {
			o.allowMerge = true; // 値を取らない。`--allow-merge=1` は未知の旗として断る
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
		} else if (a === "--pinned-file") {
			if (!isAbsolute(v) || v.includes("\0")) return null;
			o.pinnedFile = v;
		} else if (a === "--state-dir") {
			if (!isAbsolute(v) || v.includes("\0")) return null;
			o.stateDir = v;
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

function sendError(
	res: ServerResponse,
	status: number,
	code: string,
	message: string,
	extra: Record<string, string> = {},
	conflicts?: string[],
	details?: Record<string, unknown>,
): void {
	const error = { code, message, ...(conflicts !== undefined ? { conflicts } : {}), ...(details !== undefined ? { details } : {}) };
	sendJson(res, status, { error }, extra);
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

/** 書き込み（POST）。共通の規則を検査してから routes.ts へ渡す。統合系は Origin 必須・--allow-merge が要る（先に断る）。 */
async function servePost(repos: Repo[], req: IncomingMessage, res: ServerResponse, pathname: string, opts: Options): Promise<void> {
	if (isMergePostRoute(pathname)) {
		const denied = mergeRequestError(req.headers, opts.allowMerge);
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
	const env: MergeEnv = { rulesFile: opts.rulesFile, testDelayMs: opts.mergeDelayMs, backupDir: join(opts.stateDir, "cleanup-backups") };
	const result: PostResult = await handlePost(repos, pathname, body as Record<string, unknown>, env);
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
		return isMergePostRoute(p);
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
					targets: ["develop"],
				});
			}
			if (p === "/api/version") return sendJson(res, 200, versionInfo);
			if (p.startsWith("/api/")) return sendJson(res, 200, await handleApi(repos, p, url.searchParams));
			return sendError(res, 404, "not_found", "見つかりません。");
		} catch (e) {
			if (e instanceof ApiError) return sendError(res, e.status, e.code, e.message, {}, e.conflicts, e.details);
			return sendError(res, 500, "internal", "内部エラーです。"); // 例外の中身は返さない
		}
	};
}

async function main(): Promise<void> {
	const opts = parseArgs(process.argv.slice(2));
	if (!opts || opts.repos.length === 0) {
		process.stderr.write(
			"使い方: node server.ts --repo <パス> [--repo <パス>…] [--port <N>] [--allow-host <名前>…] [--web-dir <パス>] [--allow-merge] [--rules-file <パス>]\n",
		);
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
	versionInfo = await readPinned(opts.pinnedFile);
	const server = createServer(makeHandler(repos, opts));
	server.listen(opts.port, HOST, () => {
		const addr = server.address();
		const port = typeof addr === "object" && addr ? addr.port : opts.port;
		process.stdout.write(`listening http://${HOST}:${port}\n`);
		process.stdout.write(versionInfo.pinned ? `稼働版 ${versionInfo.oid} (${versionInfo.ref ?? "?"}, ${versionInfo.pinnedAt ?? "?"})\n` : "稼働版 固定なし（作業ツリーをそのまま使っています）\n");
	});
	// 停止: 新しい統合は受けず、実行中の統合は終わる（応答を書き終える）まで待つ。途中で止めると、状態ファイルが残って recover が要る。
	// 一律の強制終了は設けない（強制するなら SIGKILL。そのときは recover）
	let stopped = false;
	const stop = () => {
		if (stopped) return; // 重複した SIGTERM・SIGINT でも、実行中の統合は止めない
		stopped = true;
		stopMerges();
		// 終了は 1 本の順序だけで行う: 実行中の統合の完了 → 接続を閉じる → server が閉じる → exit。
		// server.close の callback で直接 exit すると、通信が切れた統合の途中で終わってしまう
		const closed = new Promise<void>((done) => server.close(() => done()));
		server.closeIdleConnections();
		void (async () => {
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

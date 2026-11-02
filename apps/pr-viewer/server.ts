// PR ビューアのサーバ（段 1: 読み取り専用）。
// 起動: node apps/pr-viewer/server.ts --repo <パス> [--repo <パス>…] [--port <N>] [--allow-host <名前>…] [--web-dir <パス>]
// 設計: docs/change/0060-local-pr-viewer.md。契約: .tmp/keep/prv-app/api-contract.md
import { createServer } from "node:http";
import type { IncomingMessage, ServerResponse } from "node:http";
import { lstat, readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { ApiError, configureLimits, openRepo } from "./git-view.ts";
import type { Repo } from "./git-view.ts";
import { handleApi } from "./routes.ts";

const DEFAULT_PORT = 8780;
const HOST = "127.0.0.1";

type Options = { repos: string[]; port: number; allowHosts: string[]; webDir: string; timeoutMs?: number; maxBytes?: number };

function parseArgs(argv: string[]): Options | null {
	const o: Options = {
		repos: [],
		port: DEFAULT_PORT,
		allowHosts: [],
		webDir: join(dirname(fileURLToPath(import.meta.url)), "web"),
	};
	for (let i = 0; i < argv.length; i++) {
		const a = argv[i];
		const v = argv[i + 1];
		if (v === undefined) return null;
		if (a === "--repo") o.repos.push(v);
		else if (a === "--port") {
			if (!/^\d+$/.test(v) || Number(v) > 65535) return null;
			o.port = Number(v);
		} else if (a === "--allow-host") o.allowHosts.push(v.toLowerCase());
		else if (a === "--web-dir") o.webDir = resolve(v);
		else if (a === "--git-timeout-ms") o.timeoutMs = Number(v); // 試験用
		else if (a === "--git-max-bytes") o.maxBytes = Number(v); // 試験用
		else return null;
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

function sendError(res: ServerResponse, status: number, code: string, message: string, extra: Record<string, string> = {}): void {
	sendJson(res, status, { error: { code, message } }, extra);
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

function makeHandler(repos: Repo[], opts: Options) {
	return async (req: IncomingMessage, res: ServerResponse): Promise<void> => {
		try {
			if (!hostAllowed(req.headers.host, opts.allowHosts)) {
				return sendError(res, 403, "forbidden_host", "この Host は許可されていません。");
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
			if (p.startsWith("/api/")) return sendJson(res, 200, await handleApi(repos, p, url.searchParams));
			return sendError(res, 404, "not_found", "見つかりません。");
		} catch (e) {
			if (e instanceof ApiError) return sendError(res, e.status, e.code, e.message);
			return sendError(res, 500, "internal", "内部エラーです。"); // 例外の中身は返さない
		}
	};
}

async function main(): Promise<void> {
	const opts = parseArgs(process.argv.slice(2));
	if (!opts || opts.repos.length === 0) {
		process.stderr.write("使い方: node server.ts --repo <パス> [--repo <パス>…] [--port <N>] [--allow-host <名前>…] [--web-dir <パス>]\n");
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
	const server = createServer(makeHandler(repos, opts));
	server.listen(opts.port, HOST, () => {
		const addr = server.address();
		const port = typeof addr === "object" && addr ? addr.port : opts.port;
		process.stdout.write(`listening http://${HOST}:${port}\n`);
	});
	const stop = () => {
		server.close(() => process.exit(0));
		server.closeAllConnections();
	};
	process.on("SIGINT", stop);
	process.on("SIGTERM", stop);
}

await main();

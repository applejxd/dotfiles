// curl / wget の字句解析と、HTTP 転送に関する判定 (bashrules/http.py の移植)。
//
// curl のオプションは短縮・連結・`--long=value` と形が多いため、ここだけ本格的なトークン解析を持つ。
// フラグ名の一覧は tables.toml (tables.json) にある。
//
// Python の `urllib.parse.urlsplit` と `ipaddress.ip_address(...).is_loopback` は、
// この判定が使う範囲 (ホストとポートの取り出し・ループバックの判定) を CPython の実装どおりに書き写した。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/guard/pi-decide.md#ts-版への移植
import type { Ctx } from "./context.ts";
import { tableSet } from "./context.ts";
import { extractCommandSubstitutions, extractFunctionBodies, splitCommandSegments } from "./normalize.ts";
import { basename, pyRegex, shlexSplit, ShlexError, strip, stripChars } from "./pystr.ts";
import { baseName, FETCH_COMMAND_RE, normalizeCached, payloadSource, takeOptionValue } from "./shared.ts";
import { isSensitiveToken } from "./sensitive.ts";
import { parse, redirectWrites } from "./shellparse.ts";

export type HttpCall = {
	tool: string;
	method: string | null;
	bodyKinds: string[];
	payloadSources: string[];
	outputTargets: string[];
	outputDir: string | null;
	remoteName: boolean;
	urls: string[];
	getMode: boolean;
	ambiguous: boolean;
	// localhost 例外を無効化する要因があるか (proxy / socket / redirect 等)。wget は既定でリダイレクトを追うため常に無効化する
	blocksLocal: boolean;
};

const CURL_NO_VALUE_SHORT_FLAGS = new Set(Array.from("012346#BaJMRZfFsSLIikvVqgGNnO"));

/** curl / wget の長いオプションの、曖昧でない前方一致を解決する。 */
function resolveHttpLongOption(token: string, options: ReadonlySet<string>): [string, boolean] {
	if (!token.startsWith("--")) return [token, false];
	const eq = token.indexOf("=");
	const name = eq === -1 ? token : token.slice(0, eq);
	const value = eq === -1 ? "" : token.slice(eq + 1);
	if (options.has(name)) return [token, false];
	const matches = [...options].filter((option) => option.startsWith(name));
	if (matches.length !== 1) return [token, matches.length > 1];
	let resolved = matches[0];
	if (eq !== -1) resolved = `${resolved}=${value}`;
	return [resolved, false];
}

function newHttpCall(tool: string): HttpCall {
	return {
		tool,
		method: null,
		bodyKinds: [],
		payloadSources: [],
		outputTargets: [],
		outputDir: null,
		remoteName: false,
		urls: [],
		getMode: false,
		ambiguous: false,
		blocksLocal: tool !== "curl",
	};
}

/** 値を取らない curl の短いフラグの意味を反映する。 */
function applyCurlNoValueFlags(call: HttpCall, flags: string): void {
	if (flags.includes("I")) call.method = "HEAD";
	if (flags.includes("G")) call.getMode = true;
	if (flags.includes("O")) call.remoteName = true;
	if (flags.includes("L")) call.blocksLocal = true;
}

const CURL_LONG_OPTIONS = [
	"--request",
	"--data",
	"--data-ascii",
	"--data-binary",
	"--data-raw",
	"--data-urlencode",
	"--json",
	"--form",
	"--form-string",
	"--upload-file",
	"--output",
	"--dump-header",
	"--cookie-jar",
	"--stderr",
	"--trace",
	"--trace-ascii",
	"--config",
	"--get",
	"--head",
	"--next",
	"--output-dir",
	"--remote-name",
	"--remote-name-all",
	"--url",
];

const CURL_CLUSTER_KIND: Record<string, string> = { X: "-X", d: "-d", F: "-F", T: "-T", o: "-o", D: "-D", c: "-c" };

const CURL_VALUE_OPTION_PAIRS: [string | null, string][] = [
	["-d", "--data"],
	[null, "--data-ascii"],
	[null, "--data-binary"],
	[null, "--data-raw"],
	[null, "--data-urlencode"],
	[null, "--json"],
	["-F", "--form"],
	[null, "--form-string"],
	["-T", "--upload-file"],
	["-o", "--output"],
	["-D", "--dump-header"],
	["-c", "--cookie-jar"],
	[null, "--stderr"],
	[null, "--trace"],
	[null, "--trace-ascii"],
	[null, "--output-dir"],
	[null, "--url"],
];

/** curl の 1 コマンドを解析する (`--next` で区切られた転送ごとに返す)。 */
function parseCurlTokens(ctx: Ctx, tokens: readonly string[], commandIndex: number): HttpCall[] {
	const localBlocking = tableSet(ctx, "http", "curl_local_blocking_flags");
	const outputFlags = tableSet(ctx, "http", "curl_output_flags");
	const valueFlags = tableSet(ctx, "http", "curl_value_flags");
	const configFlags = tableSet(ctx, "http", "curl_config_flags");
	const longOptions = new Set([...CURL_LONG_OPTIONS, ...[...localBlocking].filter((f) => f.startsWith("--"))]);
	const shortValueFlags = [...valueFlags]
		.filter((f) => Array.from(f).length === 2 && f.startsWith("-"))
		.map((f) => Array.from(f)[1])
		.sort();
	const shortValueClass = shortValueFlags.map((c) => c.replace(/[\\\]^-]/g, "\\$&")).join("");
	const valueCluster = new RegExp(`^-([fFsSLIikvVqgGNnO]*)([${shortValueClass}])([^\\n]*)(?![\\s\\S])`, "u");
	const cluster = /^-([fFsSLIikvVqgGNnO]*)([XdFToDc])([^\n]*)(?![\s\S])/u;

	const calls: HttpCall[] = [];
	let call = newHttpCall("curl");
	const args = tokens.slice(commandIndex + 1);
	let i = 0;
	while (i < args.length) {
		let token = args[i];
		let ambiguousPrefix: boolean;
		[token, ambiguousPrefix] = resolveHttpLongOption(token, longOptions);
		if (ambiguousPrefix) {
			call.ambiguous = true;
			i += 1;
			continue;
		}
		if (localBlocking.has(token.split("=")[0])) call.blocksLocal = true;
		if (token === "-:" || token === "--next") {
			calls.push(call);
			call = newHttpCall("curl");
			i += 1;
			continue;
		}

		const m = cluster.exec(token);
		if (m) {
			const [, prefix, option, attached] = m;
			applyCurlNoValueFlags(call, prefix);
			let value = attached;
			if (!value) {
				if (i + 1 >= args.length) {
					call.ambiguous = true;
					i += 1;
					continue;
				}
				value = args[i + 1];
				i += 1;
			}
			const kind = CURL_CLUSTER_KIND[option];
			if (kind === "-X") {
				call.method = value;
			} else if (outputFlags.has(kind)) {
				call.outputTargets.push(value);
			} else {
				call.bodyKinds.push(kind);
				const source = payloadSource(ctx, kind, value);
				if (source) call.payloadSources.push(source);
			}
			i += 1;
			continue;
		}

		let [value, nextI] = takeOptionValue(args, i, token, "-X", "--request");
		if (nextI !== i) {
			if (value === null) call.ambiguous = true;
			else call.method = value;
			i = nextI;
			continue;
		}
		if (token === "-I" || token === "--head") {
			call.method = "HEAD";
			i += 1;
			continue;
		}
		if (token === "-G" || token === "--get") {
			call.getMode = true;
			i += 1;
			continue;
		}
		if (token === "-O" || token === "--remote-name" || token === "--remote-name-all") {
			call.remoteName = true;
			i += 1;
			continue;
		}

		let matchedKind: string | null = null;
		let matchedValue: string | null = null;
		for (const [short, long] of CURL_VALUE_OPTION_PAIRS) {
			[value, nextI] = takeOptionValue(args, i, token, short, long);
			if (nextI !== i) {
				matchedKind = token.split("=")[0];
				matchedKind = short && matchedKind.startsWith(short) ? short : long;
				matchedValue = value;
				break;
			}
		}
		if (matchedKind !== null) {
			if (matchedValue === null) {
				call.ambiguous = true;
			} else if (outputFlags.has(matchedKind)) {
				call.outputTargets.push(matchedValue);
			} else if (matchedKind === "--output-dir") {
				call.outputDir = matchedValue;
			} else if (matchedKind === "--url") {
				call.urls.push(matchedValue);
			} else {
				call.bodyKinds.push(matchedKind);
				const source = payloadSource(ctx, matchedKind, matchedValue);
				if (source) call.payloadSources.push(source);
			}
			i = nextI;
			continue;
		}

		if ([...configFlags].some((flag) => token === flag || token.startsWith(`${flag}=`))) {
			call.ambiguous = true;
			i += configFlags.has(token) && !token.includes("=") ? 2 : 1;
			continue;
		}

		const valueFlag = [...valueFlags].find(
			(flag) =>
				token === flag ||
				token.startsWith(`${flag}=`) ||
				(Array.from(flag).length === 2 && token.startsWith(flag) && token !== flag),
		);
		if (valueFlag) {
			if (localBlocking.has(valueFlag)) call.blocksLocal = true;
			i += token === valueFlag ? 2 : 1;
			if (i > args.length) call.ambiguous = true;
			continue;
		}
		const vc = valueCluster.exec(token);
		if (vc) {
			const [, prefix, option, attached] = vc;
			applyCurlNoValueFlags(call, prefix);
			if (localBlocking.has(`-${option}`)) call.blocksLocal = true;
			if (!attached) {
				i += 2;
				if (i > args.length) call.ambiguous = true;
			} else {
				i += 1;
			}
			continue;
		}
		if (token.startsWith("--")) {
			i += 1;
			continue;
		}
		if (token.startsWith("-") && Array.from(token).length > 1) {
			const flags = Array.from(token).slice(1);
			if (flags.every((c) => CURL_NO_VALUE_SHORT_FLAGS.has(c))) applyCurlNoValueFlags(call, flags.join(""));
			else call.ambiguous = true;
			i += 1;
			continue;
		}
		call.urls.push(token);
		i += 1;
	}
	calls.push(call);
	return calls;
}

const WGET_LONG_OPTIONS = new Set([
	"--method",
	"--post-data",
	"--post-file",
	"--body-data",
	"--body-file",
	"--output-document",
	"--execute",
	"--config",
	"--directory-prefix",
]);

const WGET_VALUE_OPTION_PAIRS: [string | null, string][] = [
	[null, "--post-data"],
	[null, "--post-file"],
	[null, "--body-data"],
	[null, "--body-file"],
	["-O", "--output-document"],
	["-P", "--directory-prefix"],
];

/** wget の 1 コマンドを、リクエストに関わる項目に解析する。 */
function parseWgetTokens(ctx: Ctx, tokens: readonly string[], commandIndex: number): HttpCall[] {
	const outputFlags = tableSet(ctx, "http", "wget_output_flags");
	const configFlags = tableSet(ctx, "http", "wget_config_flags");
	const outputCluster = /^-[A-Za-z]*O([^\n]*)(?![\s\S])/u;
	const call = newHttpCall("wget");
	const args = tokens.slice(commandIndex + 1);
	let i = 0;
	while (i < args.length) {
		let token = args[i];
		let ambiguousPrefix: boolean;
		[token, ambiguousPrefix] = resolveHttpLongOption(token, WGET_LONG_OPTIONS);
		if (ambiguousPrefix) {
			call.ambiguous = true;
			i += 1;
			continue;
		}
		const oc = outputCluster.exec(token);
		if (oc && !token.startsWith("--")) {
			let output = oc[1];
			if (!output) {
				if (i + 1 >= args.length) {
					call.ambiguous = true;
					i += 1;
					continue;
				}
				output = args[i + 1];
				i += 1;
			}
			call.outputTargets.push(output);
			i += 1;
			continue;
		}
		let [value, nextI] = takeOptionValue(args, i, token, null, "--method");
		if (nextI !== i) {
			if (value === null) call.ambiguous = true;
			else call.method = value;
			i = nextI;
			continue;
		}

		let matchedKind: string | null = null;
		let matchedValue: string | null = null;
		for (const [short, long] of WGET_VALUE_OPTION_PAIRS) {
			[value, nextI] = takeOptionValue(args, i, token, short, long);
			if (nextI !== i) {
				matchedKind = short && token.startsWith(short) ? short : long;
				matchedValue = value;
				break;
			}
		}
		if (matchedKind !== null) {
			if (matchedValue === null) {
				call.ambiguous = true;
			} else if (outputFlags.has(matchedKind)) {
				call.outputTargets.push(matchedValue);
			} else if (matchedKind === "-P") {
				call.outputDir = matchedValue;
			} else {
				call.bodyKinds.push(matchedKind);
				const source = payloadSource(ctx, matchedKind, matchedValue);
				if (source) call.payloadSources.push(source);
			}
			i = nextI;
			continue;
		}

		if ([...configFlags].some((flag) => token === flag || token.startsWith(`${flag}=`))) {
			call.ambiguous = true;
			i += configFlags.has(token) && !token.includes("=") ? 2 : 1;
			continue;
		}
		if (!token.startsWith("-")) call.urls.push(token);
		i += 1;
	}
	return [call];
}

// ─── URL がループバック宛だと確証できるか ─────────────────────────────────

// localhost であっても特権的な制御 API が動くポート。ここへの mutation は localhost 例外の対象外にする。
const UNSAFE_LOCAL_PORTS = new Set([2375, 2376, 4243, 2379, 2380, 6443, 8443, 10250, 10255, 10256, 6379, 11211]);
// 静的にホストを確定できなくなる文字 (変数展開・コマンド置換・curl の glob)
const UNRESOLVABLE_URL_CHARS = "$`{}[]";

class ValueErrorPy extends Error {}

const HEX_DIGITS = /^[0-9A-Fa-f]*$/;

/** `ipaddress.IPv4Address` の文字列解析 (失敗は null)。32 ビットの値を返す。 */
function parseIPv4(s: string): number | null {
	const octets = s.split(".");
	if (octets.length !== 4) return null;
	let value = 0;
	for (const octet of octets) {
		if (!/^[0-9]+$/.test(octet) || octet.length > 3) return null;
		if (octet.length > 1 && octet.startsWith("0")) return null; // 先頭の 0 は許さない (3.9.5 以降)
		const n = Number.parseInt(octet, 10);
		if (n > 255) return null;
		value = value * 256 + n;
	}
	return value;
}

/** `ipaddress.IPv6Address` の文字列解析 (失敗は null)。128 ビットの値を返す。 */
function parseIPv6(addr: string): bigint | null {
	let s = addr;
	const pct = s.indexOf("%");
	if (pct !== -1) {
		const scope = s.slice(pct + 1);
		if (!scope || scope.includes("%")) return null;
		s = s.slice(0, pct);
	}
	if (s.includes("/")) return null;
	const parts = s.split(":");
	if (parts.length < 3) return null;
	if (parts[parts.length - 1].includes(".")) {
		const v4 = parseIPv4(parts.pop() as string);
		if (v4 === null) return null;
		parts.push(((v4 >>> 16) & 0xffff).toString(16));
		parts.push((v4 & 0xffff).toString(16));
	}
	if (parts.length > 9) return null;
	let skip: number | null = null;
	for (let i = 1; i < parts.length - 1; i++) {
		if (!parts[i]) {
			if (skip !== null) return null;
			skip = i;
		}
	}
	let hi: number;
	let lo: number;
	let skipped: number;
	if (skip !== null) {
		hi = skip;
		lo = parts.length - skip - 1;
		if (!parts[0]) {
			hi -= 1;
			if (hi) return null;
		}
		if (!parts[parts.length - 1]) {
			lo -= 1;
			if (lo) return null;
		}
		skipped = 8 - (hi + lo);
		if (skipped < 1) return null;
	} else {
		if (parts.length !== 8) return null;
		if (!parts[0] || !parts[parts.length - 1]) return null;
		hi = parts.length;
		lo = 0;
		skipped = 0;
	}
	const hextet = (h: string): bigint | null => {
		if (!HEX_DIGITS.test(h) || h.length > 4 || h.length === 0) return null;
		return BigInt(`0x${h}`);
	};
	let value = 0n;
	for (let i = 0; i < hi; i++) {
		const h = hextet(parts[i]);
		if (h === null) return null;
		value = (value << 16n) | h;
	}
	value <<= BigInt(16 * skipped);
	for (let i = parts.length - lo; i < parts.length; i++) {
		const h = hextet(parts[i]);
		if (h === null) return null;
		value = (value << 16n) | h;
	}
	return value;
}

/** `ipaddress.ip_address(host).is_loopback`。解析できなければ ValueErrorPy。 */
function isLoopbackAddress(host: string): boolean {
	const v4 = parseIPv4(host);
	if (v4 !== null) return Math.floor(v4 / 2 ** 24) === 127;
	const v6 = parseIPv6(host);
	if (v6 === null) throw new ValueErrorPy("not an IP address");
	if (v6 === 1n) return true;
	// IPv4 射影 (::ffff:a.b.c.d) は IPv4 としての判定に従う
	if (v6 >> 32n === 0xffffn) return Number((v6 & 0xffffffffn) >> 24n) === 127;
	return false;
}

/** CPython 3.13 の `_check_bracketed_host` */
function checkBracketedHost(hostname: string): void {
	if (hostname.startsWith("v")) {
		if (!/^v[a-fA-F0-9]+\.[^\n]+(?![\s\S])/.test(hostname)) throw new ValueErrorPy("IPvFuture address is invalid");
		return;
	}
	if (parseIPv4(hostname) !== null) throw new ValueErrorPy("An IPv4 address cannot be in brackets");
	if (parseIPv6(hostname) === null) throw new ValueErrorPy("not an IP address");
}

/** CPython 3.13.11 の `_check_bracketed_netloc` (ブラケットの前後に余計な文字があれば拒否する) */
function checkBracketedNetloc(netloc: string): void {
	const hostPort = netloc.slice(netloc.lastIndexOf("@") + 1);
	const open = hostPort.indexOf("[");
	let hostname: string;
	if (open !== -1) {
		// ブラケットの前に文字は許されない
		if (hostPort.slice(0, open)) throw new ValueErrorPy("Invalid IPv6 URL");
		const bracketed = hostPort.slice(open + 1);
		const close = bracketed.indexOf("]");
		hostname = close === -1 ? bracketed : bracketed.slice(0, close);
		const port = close === -1 ? "" : bracketed.slice(close + 1);
		// ブラケットの後ろは、ポートの区切りまで文字を許さない
		if (port && !port.startsWith(":")) throw new ValueErrorPy("Invalid IPv6 URL");
	} else {
		const c = hostPort.indexOf(":");
		hostname = c === -1 ? hostPort : hostPort.slice(0, c);
	}
	checkBracketedHost(hostname);
}

/** `urlsplit(candidate)` の hostname と port (必要な範囲)。不正なら ValueErrorPy。 */
function urlHostAndPort(candidate: string): { host: string | null; port: number | null } {
	let url = candidate.replace(/^[\x00-\x20]+/, "");
	for (const b of ["\t", "\r", "\n"]) url = url.replaceAll(b, "");
	const colon = url.indexOf(":");
	if (colon > 0 && /^[A-Za-z]/.test(url[0])) {
		const scheme = url.slice(0, colon);
		if (/^[A-Za-z0-9+\-.]*$/.test(scheme)) url = url.slice(colon + 1);
	}
	let netloc = "";
	if (url.startsWith("//")) {
		let delim = url.length;
		for (const c of "/?#") {
			const w = url.indexOf(c, 2);
			if (w >= 0) delim = Math.min(delim, w);
		}
		netloc = url.slice(2, delim);
		if ((netloc.includes("[") && !netloc.includes("]")) || (netloc.includes("]") && !netloc.includes("["))) {
			throw new ValueErrorPy("Invalid IPv6 URL");
		}
		if (netloc.includes("[") && netloc.includes("]")) checkBracketedNetloc(netloc);
	}
	const hostinfo = netloc.slice(netloc.lastIndexOf("@") + 1);
	let hostname: string;
	let port: string | null;
	const open = hostinfo.indexOf("[");
	if (open !== -1) {
		const bracketed = hostinfo.slice(open + 1);
		const close = bracketed.indexOf("]");
		hostname = close === -1 ? bracketed : bracketed.slice(0, close);
		const rest = close === -1 ? "" : bracketed.slice(close + 1);
		const c = rest.indexOf(":");
		port = c === -1 ? "" : rest.slice(c + 1);
	} else {
		const c = hostinfo.indexOf(":");
		hostname = c === -1 ? hostinfo : hostinfo.slice(0, c);
		port = c === -1 ? "" : hostinfo.slice(c + 1);
	}
	if (!port) port = null;
	let host: string | null = null;
	if (hostname) {
		const p = hostname.indexOf("%");
		host = p === -1 ? hostname.toLowerCase() : hostname.slice(0, p).toLowerCase() + hostname.slice(p);
	}
	let portNumber: number | null = null;
	if (port !== null) {
		if (!/^[0-9]+$/.test(port)) throw new ValueErrorPy("Port could not be cast to integer value");
		portNumber = Number.parseInt(port, 10);
		if (!(portNumber >= 0 && portNumber <= 65535)) throw new ValueErrorPy("Port out of range 0-65535");
	}
	return { host, port: portNumber };
}

/** URL がこのマシンのループバックを指すと静的に確証できるか。ホストを確定できなければ false。 */
export function isLocalUrl(ctx: Ctx, url: unknown): boolean {
	if (typeof url !== "string" || !url) return false;
	let candidate = stripChars(strip(url), "'\"");
	if (!candidate) return false;
	// IPv6 リテラルの [] は例外的に許す (ホスト全体が括られている形のみ)
	const stripped = candidate.replace(pyRegex("^(\\w+://)?\\[[0-9A-Fa-f:.]+\\]"), "$1");
	if (Array.from(UNRESOLVABLE_URL_CHARS).some((c) => stripped.includes(c))) return false;
	const sep = candidate.indexOf("://");
	if (sep !== -1) {
		if (!tableSet(ctx, "http", "local_url_schemes").has(candidate.slice(0, sep).toLowerCase())) return false;
	} else {
		// scheme 省略形。`gopher:127.0.0.1` のような scheme 付きの別形式は弾く
		const head = candidate.split("/")[0];
		if (head.includes(":") && !pyRegex("^[^:/]+:\\d*(?![^])").test(head)) return false;
		candidate = `http://${candidate}`;
	}
	let host: string | null;
	let port: number | null;
	try {
		({ host, port } = urlHostAndPort(candidate));
	} catch (e) {
		if (e instanceof ValueErrorPy) return false;
		throw e;
	}
	if (!host) return false;
	if (port !== null && UNSAFE_LOCAL_PORTS.has(port)) return false;
	host = host.replace(/\.+$/, "").toLowerCase();
	if (host === "localhost") return true;
	try {
		// 10 進・16 進表記 (2130706433 / 0x7f000001) は ip_address が拒否するので自動的に対象外になる
		return isLoopbackAddress(host);
	} catch (e) {
		if (e instanceof ValueErrorPy) return false;
		throw e;
	}
}

function parseHttpTokens(ctx: Ctx, tokens: readonly string[], commandIndex: number): HttpCall[] {
	const tool = baseName(tokens[commandIndex]);
	return tool === "curl" ? parseCurlTokens(ctx, tokens, commandIndex) : parseWgetTokens(ctx, tokens, commandIndex);
}

const shlexOrNull = (s: string): string[] | null => {
	try {
		return shlexSplit(s);
	} catch (e) {
		if (e instanceof ShlexError) return null;
		throw e;
	}
};

/** ラッパー・コマンド置換・関数を通して、curl / wget の転送を見つける。 */
export function httpTransferCalls(ctx: Ctx, cmd: string): HttpCall[] {
	const nonExecuting = tableSet(ctx, "http", "non_executing_http_prefixes");
	const calls: HttpCall[] = [];
	for (const body of extractFunctionBodies(cmd)) calls.push(...httpTransferCalls(ctx, body));
	for (const rawSegment of splitCommandSegments(cmd)) {
		const rawTokens = shlexOrNull(rawSegment) ?? [];
		let commandIndex: number | null = null;
		if (rawTokens.length > 0 && !nonExecuting.has(baseName(rawTokens[0]))) {
			const found = rawTokens.findIndex((t) => baseName(t) === "curl" || baseName(t) === "wget");
			commandIndex = found === -1 ? null : found;
		}
		if (commandIndex !== null) {
			calls.push(...parseHttpTokens(ctx, rawTokens, commandIndex));
			for (const inner of extractCommandSubstitutions(rawSegment)) calls.push(...httpTransferCalls(ctx, inner));
			continue;
		}

		const normalizedSegments = normalizeCached(ctx, rawSegment).filter(
			(segment) => segment.startsWith("curl ") || segment.startsWith("wget ") || segment === "curl" || segment === "wget",
		);
		if (normalizedSegments.length === 0) continue;
		if (rawTokens.length === 0) {
			calls.push({ ...newHttpCall("unknown"), ambiguous: true });
			continue;
		}
		for (const normalizedSegment of normalizedSegments) {
			const normalizedTokens = shlexOrNull(normalizedSegment);
			if (normalizedTokens === null) {
				calls.push({ ...newHttpCall("unknown"), ambiguous: true });
				continue;
			}
			calls.push(...parseHttpTokens(ctx, normalizedTokens, 0));
		}
	}
	return calls;
}

/** curl/wget でセンシティブファイルの内容を送信しようとしていないか */
export function checkCurlFileSend(ctx: Ctx, cmd: string): string | null {
	for (const call of httpTransferCalls(ctx, cmd)) {
		const sources = call.payloadSources;
		const readsStdin = sources.some((source) => source === "-" || source === "/dev/stdin");
		for (const source of sources) {
			if (source === "-") continue;
			const matched = isSensitiveToken(ctx, source);
			if (matched) return `${call.tool} でセンシティブなファイルを送信しようとしています (パターン: ${matched})`;
		}
		if (readsStdin) {
			for (const match of cmd.matchAll(pyRegex("(?<!<)<(?!<)\\s*([^\\s;&|]+)", "g"))) {
				const source = stripChars(match[1], "'\"");
				const matched = isSensitiveToken(ctx, source);
				if (matched) {
					return `${call.tool} が標準入力からセンシティブなファイルを送信しようとしています (パターン: ${matched})`;
				}
			}
		}
	}
	return null;
}

const DANGEROUS_OUTPUT_TARGETS = [
	".bashrc",
	".bash_profile",
	".bash_login",
	".zshrc",
	".zshenv",
	".zprofile",
	".profile",
	".login",
	".cshrc",
	".kshrc",
	"authorized_keys",
	"known_hosts",
	".ssh/config",
	".netrc",
	"crontab",
	".gitconfig",
];

/** curl/wget の出力が、起動・認証設定ファイルを上書きしないか。 */
export function checkHttpDangerousOutput(ctx: Ctx, cmd: string): string | null {
	for (const call of httpTransferCalls(ctx, cmd)) {
		// call は他の検査とも共有されるので、派生した出力先はコピーへ足す
		const outputTargets = [...call.outputTargets];
		let urls = call.urls;
		const outputDir = call.outputDir;
		const remoteName = call.remoteName;
		if (call.tool === "wget" && outputTargets.length > 0) urls = [];
		if (call.tool === "wget" || remoteName) {
			for (const url of urls) {
				const path = url.split("?")[0].replace(/\/+$/, "");
				const name = path.slice(path.lastIndexOf("/") + 1);
				if (name) {
					if (outputDir !== null) outputTargets.push(`${outputDir.replace(/\/+$/, "")}/${name}`);
					else if (remoteName) outputTargets.push(name);
				}
			}
		}
		for (const output of outputTargets) {
			const cleaned = stripChars(output, "'\"");
			if (DANGEROUS_OUTPUT_TARGETS.some((target) => cleaned.endsWith(target) || cleaned.includes(`/${target}`))) {
				return `\`${call.tool}\` が起動・認証設定ファイル \`${output}\` を上書きしようとしています。`;
			}
		}
	}
	return null;
}

/** HTTP の書き込みは承認を求め、読み取りだと確認できたものは auto / assisted に委ねる。 */
export function checkCurlWgetMutation(ctx: Ctx, cmd: string): string | null {
	const readMethods = tableSet(ctx, "http", "http_read_methods");
	const dataFlags = tableSet(ctx, "http", "curl_data_flags");
	for (const call of httpTransferCalls(ctx, cmd)) {
		const { tool, method, bodyKinds, payloadSources, getMode } = call;
		if (call.ambiguous) return `\`${tool}\` の request method または引数を静的に判定できません。`;
		// ループバック宛だと確証できる transfer は mutation でも承認を求めない。
		// DENY_CHECKS は ASK_CHECKS より前に走るので、秘密情報の送信・起動ファイルの上書き・取得結果の直接実行は deny のまま
		const urls = call.urls;
		if (!call.blocksLocal && urls.length > 0 && urls.every((url) => isLocalUrl(ctx, url))) continue;
		const explicitMethod = method !== null ? method.toUpperCase() : null;
		if (explicitMethod !== null && !/^[A-Za-z]+(?![\s\S])/.test(explicitMethod)) {
			return `\`${tool}\` の HTTP method を静的に判定できません。`;
		}
		if (explicitMethod !== null && !readMethods.has(explicitMethod)) {
			return `\`${tool}\` が読み取り以外の HTTP method (${explicitMethod}) を使用します。`;
		}
		if (bodyKinds.length > 0) {
			const queryOnly =
				tool === "curl" &&
				getMode &&
				explicitMethod === null &&
				payloadSources.length === 0 &&
				bodyKinds.every((kind) => dataFlags.has(kind));
			if (!queryOnly) return `\`${tool}\` が request body または upload payload を送信します。`;
		}
		if ((explicitMethod !== null && readMethods.has(explicitMethod)) || getMode || bodyKinds.length === 0) continue;
		return `\`${tool}\` の request を読み取り専用と確認できません。`;
	}
	return null;
}

/** curl / wget が書き出すローカルパスと、その basename を返す。 */
export function fetchedOutputPaths(ctx: Ctx, cmd: string): Set<string> {
	const paths = new Set<string>();
	const add = (value: string): void => {
		const cleaned = stripChars(value, "'\"");
		if (cleaned && cleaned !== "-" && cleaned !== "/dev/stdout" && cleaned !== "/dev/null") paths.add(cleaned);
	};
	for (const call of httpTransferCalls(ctx, cmd)) {
		const outputs = call.outputTargets;
		for (const output of outputs) add(output);
		// `curl -O` と、出力先を指定しない `wget` は URL の basename に保存する
		const derivesName = call.remoteName || (call.tool === "wget" && outputs.length === 0);
		if (derivesName) {
			for (const url of call.urls) {
				const path = url.split("?")[0].replace(/\/+$/, "");
				const name = path.slice(path.lastIndexOf("/") + 1);
				if (name) add(name);
			}
		}
	}
	// 取得と同じセグメント内のリダイレクト先
	for (const segment of splitCommandSegments(cmd)) {
		if (!FETCH_COMMAND_RE.test(segment)) continue;
		for (const command of parse(segment)) {
			for (const r of command.redirects) {
				if (redirectWrites(r) && r.target !== null) add(r.target.value);
			}
		}
	}
	for (const p of [...paths]) paths.add(basename(p));
	return paths;
}

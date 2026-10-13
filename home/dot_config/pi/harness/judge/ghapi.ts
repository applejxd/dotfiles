// `gh api` の REST method / GraphQL operation の解析と判定 (bashrules/ghapi.py の移植)。
//
// 読み取り (GET / HEAD / query) は通し、mutation と判定不能な形式だけを承認対象にする。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/pi-decide.md#ts-版への移植
import type { Ctx } from "./context.ts";
import { tableSet } from "./context.ts";
import { extractCommandSubstitutions, extractFunctionBodies, splitCommandSegments } from "./normalize.ts";
import { pyRegex, shlexSplit, ShlexError, strip } from "./pystr.ts";
import { baseName, normalizeCached, optionValue } from "./shared.ts";
import { isSensitiveToken } from "./sensitive.ts";

export type GhApiCall = {
	endpoint: string | null;
	method: string | null;
	fields: [string, string][];
	input: string | null;
	ambiguous: boolean;
};

/** `gh api` 1 回分のトークン列を解析する。 */
function parseGhApiTokens(ctx: Ctx, rawTokens: readonly string[], ghIndex: number): GhApiCall {
	const methodFlags = tableSet(ctx, "ghapi", "gh_api_method_flags");
	const inputFlags = tableSet(ctx, "ghapi", "gh_api_input_flags");
	const valueFlags = tableSet(ctx, "ghapi", "gh_api_value_flags");
	let endpoint: string | null = null;
	let method: string | null = null;
	const fields: [string, string][] = [];
	let inputPath: string | null = null;
	let ambiguous = false;
	const args = rawTokens.slice(ghIndex + 2);
	let i = 0;
	while (i < args.length) {
		const token = args[i];
		if (token === "--") {
			if (i + 1 < args.length && endpoint === null) {
				endpoint = args[i + 1];
				i += 2;
				continue;
			}
			ambiguous = true;
			i += 1;
			continue;
		}

		const attachedMethod = optionValue(token, "-X", "--method");
		if (attachedMethod !== null) {
			method = attachedMethod;
			i += 1;
			continue;
		}
		if (methodFlags.has(token)) {
			if (i + 1 >= args.length) {
				ambiguous = true;
				i += 1;
				continue;
			}
			method = args[i + 1];
			i += 2;
			continue;
		}

		let fieldKind: string | null = null;
		let fieldValue: string | null = null;
		for (const [short, long] of [
			["-f", "--raw-field"],
			["-F", "--field"],
		]) {
			const attached = optionValue(token, short, long);
			if (attached !== null) {
				fieldKind = short;
				fieldValue = attached;
				break;
			}
			if (token === short || token === long) {
				fieldKind = short;
				if (i + 1 < args.length) {
					fieldValue = args[i + 1];
					i += 1;
				} else {
					ambiguous = true;
				}
				break;
			}
		}
		if (fieldKind !== null) {
			if (fieldValue !== null) fields.push([fieldKind, fieldValue]);
			i += 1;
			continue;
		}

		if (token.startsWith("--input=")) {
			inputPath = token.slice(token.indexOf("=") + 1);
			i += 1;
			continue;
		}
		if (inputFlags.has(token)) {
			if (i + 1 >= args.length) {
				ambiguous = true;
				i += 1;
				continue;
			}
			inputPath = args[i + 1];
			i += 2;
			continue;
		}

		const valueFlag = [...valueFlags].find((flag) => token === flag || token.startsWith(`${flag}=`));
		if (valueFlag) {
			if (token === valueFlag) {
				if (i + 1 >= args.length) {
					ambiguous = true;
					i += 1;
					continue;
				}
				i += 2;
			} else {
				i += 1;
			}
			continue;
		}

		if (token.startsWith("-")) {
			i += 1;
			continue;
		}
		if (endpoint === null) endpoint = token;
		else ambiguous = true;
		i += 1;
	}
	return { endpoint, method, fields, input: inputPath, ambiguous };
}

const ambiguousGhApiCall = (): GhApiCall => ({ endpoint: null, method: null, fields: [], input: null, ambiguous: true });

const shlexOrNull = (s: string): string[] | null => {
	try {
		return shlexSplit(s);
	} catch (e) {
		if (e instanceof ShlexError) return null;
		throw e;
	}
};

/** 正規化した `gh api` のセグメントから、判定に要る項目を取り出す。 */
export function ghApiCalls(ctx: Ctx, cmd: string): GhApiCall[] {
	const calls: GhApiCall[] = [];
	for (const body of extractFunctionBodies(cmd)) calls.push(...ghApiCalls(ctx, body));
	for (const rawSegment of splitCommandSegments(cmd)) {
		const normalizedSegments = normalizeCached(ctx, rawSegment).filter((segment) => segment.startsWith("gh api"));
		if (normalizedSegments.length === 0) continue;
		const rawTokens = shlexOrNull(rawSegment);
		if (rawTokens === null) {
			calls.push(ambiguousGhApiCall());
			continue;
		}
		let ghIndex: number | null = null;
		for (let i = 0; i < rawTokens.length - 1; i++) {
			if (baseName(rawTokens[i]) === "gh" && rawTokens[i + 1] === "api") {
				ghIndex = i;
				break;
			}
		}
		if (ghIndex !== null) {
			calls.push(parseGhApiTokens(ctx, rawTokens, ghIndex));
			for (const inner of extractCommandSubstitutions(rawSegment)) calls.push(...ghApiCalls(ctx, inner));
			continue;
		}
		for (const normalizedSegment of normalizedSegments) {
			const normalizedTokens = shlexOrNull(normalizedSegment);
			if (normalizedTokens === null) {
				calls.push(ambiguousGhApiCall());
				continue;
			}
			calls.push(parseGhApiTokens(ctx, normalizedTokens, 0));
		}
	}
	return calls;
}

/** インラインの GraphQL query と、その出所を確認できるか。 */
function graphqlQuery(fields: readonly [string, string][]): [string | null, boolean] {
	const queries: string[] = [];
	for (const [kind, field] of fields) {
		if (!field.includes("=")) continue;
		const eq = field.indexOf("=");
		const key = field.slice(0, eq);
		const value = field.slice(eq + 1);
		if (key !== "query") continue;
		if (kind === "-F" && value.startsWith("@")) return [null, false];
		queries.push(value);
	}
	if (queries.length !== 1) return [null, false];
	let query = queries[0].replace(/^\ufeff+/u, "");
	if (/(?:\$\(|\$\{|`)/u.test(query)) return [null, false];
	// Python の `(?m)^\s*#.*$` (行頭・行末は \n だけを区切りとみなす)
	query = strip(query.replace(pyRegex("(?<![^\\n])\\s*#[^\\n]*(?![^\\n])", "g"), ""));
	return [query, Boolean(query)];
}

/** `gh auth status --show-token` のように token を表示する形を止める。 */
export function checkGhTokenExposure(ctx: Ctx, cmd: string): string | null {
	for (const segment of normalizeCached(ctx, cmd)) {
		const tokens = shlexOrNull(segment);
		if (tokens === null) continue;
		if (
			tokens.length >= 3 &&
			baseName(tokens[0]) === "gh" &&
			tokens[1] === "auth" &&
			tokens[2] === "status" &&
			tokens.slice(3).some((t) => t === "-t" || t === "--show-token")
		) {
			return "`gh auth status --show-token` による token 表示は禁止されています。";
		}
	}
	return null;
}

/** センシティブなローカルファイルを `gh api` のリクエスト内容に使う形を止める。 */
export function checkGhApiSensitiveInput(ctx: Ctx, cmd: string): string | null {
	for (const call of ghApiCalls(ctx, cmd)) {
		if (call.input !== null && call.input !== "-") {
			const matched = isSensitiveToken(ctx, call.input);
			if (matched) return `\`gh api --input\` がセンシティブなファイルを送信します (${matched})。`;
		}
		for (const [kind, field] of call.fields) {
			if (kind !== "-F" || !field.includes("=")) continue;
			const value = field.slice(field.indexOf("=") + 1);
			if (!value.startsWith("@") || value === "@-") continue;
			const matched = isSensitiveToken(ctx, value.slice(1));
			if (matched) return `\`gh api -F\` がセンシティブなファイルを送信します (${matched})。`;
		}
	}
	return null;
}

/** API の書き込みは承認を求め、読み取りだと確認できたものは auto / assisted に委ねる。 */
export function checkGhApiMutation(ctx: Ctx, cmd: string): string | null {
	const readMethods = tableSet(ctx, "ghapi", "gh_api_read_methods");
	for (const call of ghApiCalls(ctx, cmd)) {
		const { endpoint, method, fields, input } = call;
		if (endpoint === null || call.ambiguous) return "`gh api` の endpoint または引数を静的に判定できません。";

		if (endpoint === "graphql") {
			if (input !== null) return "`gh api graphql` の input 内容を静的に判定できません。";
			const [query, inspectable] = graphqlQuery(fields);
			if (!inspectable || query === null) return "`gh api graphql` の query 内容を静的に判定できません。";
			if (pyRegex("\\bmutation\\b", "i").test(query)) return "`gh api graphql` が mutation を実行しようとしています。";
			if (!(pyRegex("^query(?:\\s|\\()", "i").test(query) || query.startsWith("{"))) {
				return "`gh api graphql` が読み取り query であることを確認できません。";
			}
			continue;
		}

		const explicitMethod = method !== null ? method.toUpperCase() : null;
		if (explicitMethod !== null && !/^[A-Za-z]+(?![\s\S])/u.test(explicitMethod)) {
			return "`gh api` の HTTP method を静的に判定できません。";
		}
		if (input !== null) return "`gh api --input` は request body を送信します。";
		if (explicitMethod !== null && readMethods.has(explicitMethod)) continue;
		if (explicitMethod === null && fields.length === 0) continue;
		const effectiveMethod = explicitMethod || "POST";
		return `\`gh api\` が読み取り以外の HTTP method (${effectiveMethod}) を使用します。`;
	}
	return null;
}

// `[[pi.actions]]` (guarded_action の操作表) の判定側。lib/decide.py の `_action_deny` と同じ文字列を返す。
//
// action ツールを持つ役割では、操作表の `replaces` に当たる bash を deny し、guarded_action の呼び出し例を案内する。
// 照合は `[pi.confirm] bash` の確認表と同じ正規化 (`normalize` / `patternMatches`)。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/guard/pi-decide.md
import { normalize, patternMatches, splitCommandSegments } from "./normalize.ts";
import { ShlexError, shlexSplit, split } from "./pystr.ts";

type Obj = Record<string, any>;

const REPO_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]*\/[A-Za-z0-9_.-]+$/;
const INT_RE = /^[0-9]+$/;
const VALUE_FLAGS = new Set(["-R", "--repo", "-b", "--body", "-F", "--body-file", "-t", "--title", "-m", "--message"]);

const TYPE_RANK: Record<string, number> = { repo: 0, int: 1, line: 2, text: 3 };

/** 判定器が見る操作表の 1 項目 (形が壊れていれば例外 = 判定に失敗した deny)。fields は型 (repo, int, line, text) → 名前の順に並べる。 */
export type ActionEntry = { id: string; replaces: string[]; fields: [string, string][] };

export function actionEntries(pi: Obj): ActionEntry[] {
	const table = pi.actions;
	if (table === undefined || table === null) return [];
	if (!Array.isArray(table)) throw new Error("[[pi.actions]] が配列ではありません");
	return table.map((a: any) => {
		if (a === null || typeof a !== "object" || typeof a.id !== "string") throw new Error("[[pi.actions]] の項目に id (文字列) が要ります");
		const replaces = a.replaces;
		if (!Array.isArray(replaces) || !replaces.every((r: unknown) => typeof r === "string")) {
			throw new Error(`[[pi.actions]] ${JSON.stringify(a.id)} の replaces が文字列の配列ではありません`);
		}
		const fields = a.fields;
		if (fields === null || typeof fields !== "object" || Array.isArray(fields)) {
			throw new Error(`[[pi.actions]] ${JSON.stringify(a.id)} の fields が表ではありません`);
		}
		const sorted = Object.entries(fields).map(([k, v]: [string, any]) => [k, String(v?.type)] as [string, string]);
		// JSON の正解データはキーを整列して保存するので、TOML の並びには頼らない (Python 版と同じ並べ方)
		sorted.sort((x, y) => (TYPE_RANK[x[1]] ?? 9) - (TYPE_RANK[y[1]] ?? 9) || (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : 0));
		return { id: a.id, replaces, fields: sorted };
	});
}

const tokensOf = (s: string): string[] => {
	try {
		return shlexSplit(s);
	} catch (e) {
		if (!(e instanceof ShlexError)) throw e;
		return split(s);
	}
};

const flat = (s: string): string[] => tokensOf(s).flatMap((t) => t.split(/[ \t\n]+/)).filter((t) => t);

function repoIn(tokens: string[]): string | null {
	for (let i = 0; i < tokens.length; i++) {
		const t = tokens[i];
		const value = t === "-R" || t === "--repo" ? tokens[i + 1] : t.startsWith("--repo=") ? t.slice("--repo=".length) : undefined;
		if (value !== undefined && REPO_RE.test(value)) return value;
	}
	return null;
}

function numberIn(rest: string[]): number | null {
	for (let i = 0; i < rest.length; i++) {
		const t = rest[i];
		if (VALUE_FLAGS.has(t)) {
			i++;
			continue;
		}
		if (t.startsWith("-")) continue;
		if (INT_RE.test(t)) {
			const n = Number(t);
			if (n >= 1 && n <= 1000000000) return n;
		}
	}
	return null;
}

/** 案内に入れる候補の値。コマンドから確実に分かるものだけ。 */
function candidates(cmd: string, segment: string, prefixLen: number): { repo: string | null; number: number | null } {
	const tokens = flat(segment);
	let repo = repoIn(tokens);
	if (repo === null) {
		// 正規化は gh のグローバルオプション (-R) を落とすので、元のセグメントでも探す
		for (const raw of splitCommandSegments(cmd)) {
			const raws = flat(raw);
			if (!raws.some((t) => t === "gh" || t.endsWith("/gh"))) continue;
			repo = repoIn(raws);
			if (repo !== null) break;
		}
	}
	return { repo, number: numberIn(tokensOf(segment).slice(prefixLen)) };
}

const PLACEHOLDER_TEXT: Record<string, string> = { body: "<本文>", message: "<件名と本文>", title: "<タイトル>" };

/** action ツールを持つ役割の bash が、操作表の `replaces` に当たれば deny の理由を返す (当たらなければ null)。 */
export function actionDenyReason(cmd: string, pi: Obj): string | null {
	const entries = actionEntries(pi);
	if (entries.length === 0) return null;
	const segments = normalize(cmd);
	// 同じコマンドに当たる操作が複数あるとき (issue の本文とタイトルなど) は、表の順に全部の例を出す
	const examples: string[] = [];
	for (const entry of entries) {
		for (const segment of segments) {
			const pattern = entry.replaces.find((p) => patternMatches(segment, p));
			if (pattern === undefined) continue;
			const found = candidates(cmd, segment, split(pattern).length);
			const parts = entry.fields.map(([name, type]) => {
				const key = JSON.stringify(name);
				if (type === "repo") return `${key}:${found.repo === null ? JSON.stringify("<owner/name>") : JSON.stringify(found.repo)}`;
				if (type === "int") return `${key}:${found.number === null ? "<N>" : String(found.number)}`;
				return `${key}:${JSON.stringify(PLACEHOLDER_TEXT[name] ?? `<${name}>`)}`;
			});
			examples.push(`guarded_action {"action":${JSON.stringify(entry.id)},"params":{${parts.join(",")}}}`);
			break;
		}
	}
	if (examples.length === 0) return null;
	return (
		"投稿・コミットは guarded_action で行う（承認はそのツールが 1 回だけ取る。事前に ask やチャットで承認を取らない）。" +
		`呼び出し例（値は候補。実際の値を確認する）: ${examples.join(" または ")}`
	);
}

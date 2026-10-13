// シェルのコマンドを、git の呼び出しとして読むための小さな字句解析と解釈 (純関数。git は呼ばない)。
// 方針: 読めないものは「読めない」と言う。読めない形を、読めたことにして表示しない。
// see docs/spec/pi-harness.md#commit-の確認-素の-pi

export type Word = { text: string; dynamic: boolean };
export type Heredoc = { body: string; dynamic: boolean };
export type Segment = { sep: string; words: Word[]; heredocs: Heredoc[] };
export type Tokens = { segments: Segment[]; opaque: boolean };

const TAG = String.raw`(?:'([A-Za-z_]\w*)'|"([A-Za-z_]\w*)"|([A-Za-z_]\w*))`;

// 引用符の外の区切り (&& || ; | & 改行) でコマンドを分け、単語の引用符を外す。
// $() ` ` サブシェル・リダイレクトなど、値が決まらないものは opaque にする。
// 例外: "$(cat <<'EOF' … EOF)" (コミットメッセージの定番) だけは中身を値として読む。
export function tokenize(src: string): Tokens {
	const segments: Segment[] = [];
	let cur: Segment = { sep: "", words: [], heredocs: [] };
	let word: Word | null = null;
	let opaque = false;
	const pending: { seg: Segment; tag: string; strip: boolean; quoted: boolean }[] = [];
	const n = src.length;
	let i = 0;

	const add = (s: string, dynamic = false) => {
		word ??= { text: "", dynamic: false };
		word.text += s;
		if (dynamic) word.dynamic = true;
	};
	const endWord = () => {
		if (word) cur.words.push(word);
		word = null;
	};
	const endSeg = (sep: string) => {
		endWord();
		if (cur.words.length || cur.heredocs.length) segments.push(cur);
		cur = { sep, words: [], heredocs: [] };
	};
	// 位置 j (行頭) からヒアドキュメントの本文を読む。終端の行の次の位置と本文を返す
	const readBody = (j: number, tag: string, strip: boolean): { body: string; next: number } | null => {
		const lines: string[] = [];
		while (j <= n) {
			let e = src.indexOf("\n", j);
			if (e < 0) e = n;
			const line = src.slice(j, e);
			const shown = strip ? line.replace(/^\t+/, "") : line; // <<- はシェルも行頭のタブを除く
			if (shown === tag) return { body: lines.join("\n"), next: Math.min(e + 1, n) };
			lines.push(shown);
			if (e >= n) return null;
			j = e + 1;
		}
		return null;
	};
	// "…$(cat <<'EOF'\n本文\nEOF\n)…" の `$(` の後ろから。読めたら本文と次の位置
	const readCat = (j: number): { body: string; next: number; dynamic: boolean } | null => {
		const m = new RegExp(String.raw`^\s*cat\s+<<(-?)\s*` + TAG + String.raw`[ \t]*\n`).exec(src.slice(j));
		if (!m) return null;
		const tag = m[2] ?? m[3] ?? m[4];
		const quoted = m[2] !== undefined || m[3] !== undefined;
		const got = readBody(j + m[0].length, tag, m[1] === "-");
		if (!got) return null;
		const close = /^\s*\)/.exec(src.slice(got.next));
		if (!close) return null;
		return { body: got.body, next: got.next + close[0].length, dynamic: !quoted && /[$`\\]/.test(got.body) };
	};

	while (i < n) {
		const c = src[i];
		if (c === "\\") {
			if (src[i + 1] === "\n") i += 2;
			else {
				if (i + 1 < n) add(src[i + 1]);
				i += 2;
			}
			continue;
		}
		if (c === "'") {
			const j = src.indexOf("'", i + 1);
			if (j < 0) {
				opaque = true;
				break;
			}
			add(src.slice(i + 1, j));
			i = j + 1;
			continue;
		}
		if (c === '"') {
			add("");
			i++;
			let closed = false;
			while (i < n) {
				const d = src[i];
				if (d === '"') {
					closed = true;
					i++;
					break;
				}
				if (d === "\\") {
					const e = src[i + 1];
					if (e === "\n") i += 2;
					else if (e !== undefined && '"\\$`'.includes(e)) {
						add(e);
						i += 2;
					} else {
						add("\\");
						i++;
					}
					continue;
				}
				if (d === "$" && src[i + 1] === "(") {
					const cat = readCat(i + 2);
					if (!cat) break;
					add(cat.body, cat.dynamic);
					i = cat.next;
					continue;
				}
				if (d === "`" || (d === "$" && src[i + 1] === "(")) break;
				if (d === "$") {
					add("$", true);
					i++;
					continue;
				}
				add(d);
				i++;
			}
			if (!closed) {
				opaque = true;
				break;
			}
			continue;
		}
		if (c === "#" && !word) {
			const e = src.indexOf("\n", i);
			i = e < 0 ? n : e;
			continue;
		}
		if (c === " " || c === "\t") {
			endWord();
			i++;
			continue;
		}
		if (c === "\n") {
			endWord();
			i++;
			for (const p of pending.splice(0)) {
				const got = readBody(i, p.tag, p.strip);
				if (!got) {
					opaque = true;
					i = n;
					break;
				}
				p.seg.heredocs.push({ body: got.body, dynamic: !p.quoted && /[$`\\]/.test(got.body) });
				i = got.next;
			}
			endSeg("\n");
			continue;
		}
		if (c === "&" && src[i + 1] === "&") {
			endSeg("&&");
			i += 2;
			continue;
		}
		if (c === "|" && src[i + 1] === "|") {
			endSeg("||");
			i += 2;
			continue;
		}
		if (c === "|" || c === ";" || c === "&") {
			endSeg(c);
			i++;
			continue;
		}
		if (c === "<" && src[i + 1] === "<" && src[i + 2] !== "<") {
			const m = new RegExp(String.raw`^<<(-?)[ \t]*` + TAG).exec(src.slice(i));
			if (!m) {
				opaque = true;
				break;
			}
			endWord();
			pending.push({
				seg: cur,
				tag: m[2] ?? m[3] ?? m[4],
				strip: m[1] === "-",
				quoted: m[2] !== undefined || m[3] !== undefined,
			});
			i += m[0].length;
			continue;
		}
		if ("<>()`".includes(c)) {
			opaque = true;
			add(c, true);
			i++;
			continue;
		}
		if (c === "$" || "*?[{~".includes(c)) {
			add(c, true);
			i++;
			continue;
		}
		add(c);
		i++;
	}
	if (pending.length) opaque = true;
	endSeg("");
	return { segments, opaque };
}

// prefixed: `VAR=値 git …` や `sudo git …` のように、git の前に実行条件を変えるものが付いている
export type GitCall = { dirs: string[]; sub: string; args: Word[]; prefixed: boolean };

// git の前に付いて、実行の条件や権限を変えるもの (sudo -n git …、env -i git …、timeout 10 git …)
const WRAPPERS = new Set([
	"command", "sudo", "doas", "env", "time", "nohup", "exec", "nice", "ionice", "stdbuf", "timeout",
	"xargs", "setsid", "unbuffer",
]);
const GLOBAL_FLAGS = new Set(["--no-pager", "--paginate", "-P", "-p", "--no-optional-locks", "--no-replace-objects"]);
// git の対象や設定の探し方を変えるオプション。読めたことにしない (表示の git に同じ条件を渡せないので)
const REDIRECTING = /^--(git-dir|work-tree|namespace|super-prefix|exec-path|config-env)(=|$)/;
const isGit = (t: string) => /(^|[/\\])git(\.exe)?$/.test(t);

// `git [-C dir] [-c k=v] <sub> <args…>` を読む。git でなければ null。
// prefixed: git の前後で実行の条件が変わる (wrapper・環境変数・-c・--git-dir など)。構造化しない印
export function gitCall(seg: Segment): GitCall | null {
	const words = seg.words;
	let k = 0;
	while (k < words.length && /^\w+=/.test(words[k].text)) k++;
	let g = -1;
	if (isGit(words[k]?.text ?? "")) g = k;
	else if (WRAPPERS.has(words[k]?.text ?? "")) {
		// wrapper の後ろ (そのオプションと値) を読み飛ばして、最初の git を探す
		for (let j = k + 1; j < Math.min(words.length, k + 10); j++) {
			if (isGit(words[j].text)) {
				g = j;
				break;
			}
		}
	}
	if (g < 0) return null;
	let prefixed = g > 0;
	const dirs: string[] = [];
	const aliases = new Map<string, string>();
	const unknown = (): GitCall => ({ dirs, sub: "?", args: [], prefixed: true });
	for (k = g + 1; k < words.length; k++) {
		const t = words[k].text;
		if (t === "-C") {
			const v = words[++k];
			if (!v) return unknown();
			dirs.push(v.text);
		} else if (/^-C./.test(t)) {
			dirs.push(t.slice(2));
		} else if (t === "-c") {
			const v = words[++k];
			if (!v) return unknown();
			const alias = /^alias\.([^=]+)=(.*)$/.exec(v.text);
			if (alias) aliases.set(alias[1], alias[2]);
			prefixed = true; // 設定の上書き (core.hooksPath など) はコミットの挙動を変えうる
		} else if (REDIRECTING.test(t)) {
			prefixed = true;
			if (!t.includes("=")) k++;
		} else if (GLOBAL_FLAGS.has(t)) {
			continue;
		} else if (t.startsWith("-")) {
			return unknown();
		} else {
			let sub = t;
			let args = words.slice(k + 1);
			const alias = aliases.get(t);
			if (alias !== undefined) {
				// -c alias.x=… で定義された別名。push に化けるものを見逃さない (リポジトリの設定の別名は読めない)
				const parts = alias.replace(/^!/, "").trim().split(/\s+/);
				if (alias.startsWith("!") && !/(^|\s)git(\s+-\S+)*\s+push(\s|$)/.test(alias.slice(1))) return unknown();
				sub = alias.startsWith("!") ? "push" : parts[0];
				args = [...parts.slice(1).map((text) => ({ text, dynamic: false })), ...args];
			}
			return { dirs, sub, args, prefixed };
		}
	}
	return unknown();
}

export type CommitSpec = {
	messages: string[];
	fileMessage: { path: string } | { stdin: string } | null;
	all: boolean;
	amend: boolean;
	noEdit: boolean;
	noVerify: boolean;
	sign: boolean;
	signoff: boolean;
	allowEmpty: boolean;
	pathspec: string[];
	notes: string[];
};
export type Step = { kind: "cd"; dir: string } | { kind: "add"; dirs: string[]; args: string[] };
export type Analysis =
	| { kind: "none" }
	| { kind: "push" }
	// approx: 読めない形でも、最初の commit だけ読めたとき。退避 (バックアップ) の近似にだけ使う。表示には使わない
	| { kind: "commit"; recognized: false; approx?: { dirs: string[]; spec: CommitSpec } }
	| { kind: "commit"; recognized: true; steps: Step[]; dirs: string[]; spec: CommitSpec };

const LOOSE_PUSH = /(^|[\s;&|(`])git(\s+-\S+(\s+[^\s-]\S*)?)*\s+push(\s|$)/;
const LOOSE_COMMIT = /(^|[\s;&|(`])git(\s+-\S+(\s+[^\s-]\S*)?)*\s+commit(\s|$)/;
const SHELLS = new Set(["sh", "bash", "zsh", "dash", "eval"]);
const ADD_FLAGS = new Set(["-A", "--all", "-u", "--update", "-v", "--verbose"]);

// 1 つの `git commit …` の引数を読む。読めない引数 (-e、-C <commit> など) があれば null
function parseCommitArgs(args: Word[], heredocs: Heredoc[]): CommitSpec | null {
	const spec: CommitSpec = {
		messages: [], fileMessage: null, all: false, amend: false, noEdit: false, noVerify: false,
		sign: false, signoff: false, allowEmpty: false, pathspec: [], notes: [],
	};
	if (args.some((w) => w.dynamic)) return null;
	const a = args.map((w) => w.text);
	for (let i = 0; i < a.length; i++) {
		const t = a[i];
		const value = (): string | null => (i + 1 < a.length ? a[++i] : null);
		if (t === "--") {
			spec.pathspec.push(...a.slice(i + 1));
			break;
		}
		if (t.startsWith("--")) {
			const [name, eq] = [t.split("=")[0], t.includes("=") ? t.slice(t.indexOf("=") + 1) : null];
			if (name === "--message") {
				const v = eq ?? value();
				if (v === null) return null;
				spec.messages.push(v);
			} else if (name === "--file") {
				const v = eq ?? value();
				if (v === null) return null;
				if (v === "-") {
					if (heredocs.length !== 1 || heredocs[0].dynamic) return null;
					spec.fileMessage = { stdin: heredocs[0].body };
				} else spec.fileMessage = { path: v };
			} else if (name === "--all") spec.all = true;
			else if (name === "--amend") spec.amend = true;
			else if (name === "--no-edit") spec.noEdit = true;
			else if (name === "--no-verify") spec.noVerify = true;
			else if (name === "--signoff") spec.signoff = true;
			else if (name === "--gpg-sign") spec.sign = true;
			else if (name === "--allow-empty") spec.allowEmpty = true;
			else if (name === "--author" || name === "--date") {
				const v = eq ?? value();
				if (v === null) return null;
				spec.notes.push(`${name} ${v}`);
			} else if (["--quiet", "--verbose", "--no-gpg-sign", "--allow-empty-message", "--no-status"].includes(name)) continue;
			else return null;
			continue;
		}
		if (/^-[A-Za-z]+/.test(t)) {
			for (let k = 1; k < t.length; k++) {
				const f = t[k];
				if (f === "a") spec.all = true;
				else if (f === "n") spec.noVerify = true;
				else if (f === "s") spec.signoff = true;
				else if (f === "S") {
					spec.sign = true;
					break; // 後ろは鍵の ID
				} else if (f === "q" || f === "v") continue;
				else if (f === "m" || f === "F") {
					const rest = t.slice(k + 1);
					const v = rest || value();
					if (v === null) return null;
					if (f === "m") spec.messages.push(v);
					else if (v === "-") {
						if (heredocs.length !== 1 || heredocs[0].dynamic) return null;
						spec.fileMessage = { stdin: heredocs[0].body };
					} else spec.fileMessage = { path: v };
					break;
				} else return null;
			}
			continue;
		}
		spec.pathspec.push(t);
	}
	// -a とパス指定の併用 (git が拒否する)、-m と -F の併用 (競合して失敗する) は、実行結果を表示で約束できない
	if ((spec.all && spec.pathspec.length > 0) || (spec.messages.length > 0 && spec.fileMessage)) return null;
	return spec;
}

// コマンド全体を解釈する。
//  push  → 完全手動にするので止める
//  commit → recognized なら、実行される手順 (cd / add / commit) を構造として返す。
//           読めない形 (&& git push が付く、$VAR、リダイレクトなど) は recognized: false
export function analyze(src: string): Analysis {
	const { segments, opaque } = tokenize(src);
	const calls = segments.map(gitCall);
	if (calls.some((c) => c?.sub === "push")) return { kind: "push" };
	// sh -c "git push" などの入れ子。文字列の中は読めないので、緩く見て止める
	for (const seg of segments) {
		if (SHELLS.has(seg.words[0]?.text) && seg.words.some((w) => LOOSE_PUSH.test(w.text))) return { kind: "push" };
	}
	if (opaque && LOOSE_PUSH.test(src)) return { kind: "push" };

	const hasCommit = calls.some((c) => c?.sub === "commit");
	const shellCommit = segments.some(
		(s) => SHELLS.has(s.words[0]?.text) && s.words.some((w) => LOOSE_COMMIT.test(w.text)),
	);
	if (!hasCommit) return shellCommit || (opaque && LOOSE_COMMIT.test(src)) ? { kind: "commit", recognized: false } : { kind: "none" };

	// 連結・変数・リダイレクトなど。最初の commit の引数が静的に読めれば、退避の近似として添える
	const first = segments.findIndex((_, k) => calls[k]?.sub === "commit");
	const firstCall = first >= 0 ? calls[first] : null;
	const approxSpec = firstCall ? parseCommitArgs(firstCall.args, segments[first].heredocs) : null;
	const unrecognized: Analysis = {
		kind: "commit",
		recognized: false,
		...(firstCall && approxSpec && approxSpec.messages.length + (approxSpec.fileMessage ? 1 : 0) > 0
			? { approx: { dirs: firstCall.dirs, spec: approxSpec } }
			: {}),
	};
	if (opaque || !segments.length) return unrecognized;
	if (segments.slice(1).some((s) => s.sep !== "&&")) return unrecognized;
	const steps: Step[] = [];
	for (let s = 0; s < segments.length - 1; s++) {
		const seg = segments[s];
		if (seg.words.some((w) => w.dynamic) || seg.heredocs.length) return unrecognized;
		const call = calls[s];
		if (!call && seg.words[0]?.text === "cd" && seg.words.length === 2) {
			steps.push({ kind: "cd", dir: seg.words[1].text });
		} else if (call?.sub === "add" && !call.prefixed && call.args.every((w) => ADD_FLAGS.has(w.text) || !w.text.startsWith("-") || w.text === "--")) {
			steps.push({ kind: "add", dirs: call.dirs, args: call.args.map((w) => w.text) });
		} else return unrecognized;
	}
	const last = segments[segments.length - 1];
	const call = calls[calls.length - 1];
	if (!call || call.sub !== "commit" || call.prefixed || last.words.some((w) => w.dynamic)) return unrecognized;
	const spec = parseCommitArgs(call.args, last.heredocs);
	if (!spec) return unrecognized;
	if (!spec.messages.length && !spec.fileMessage && !(spec.amend && spec.noEdit)) return unrecognized;
	return { kind: "commit", recognized: true, steps, dirs: call.dirs, spec };
}

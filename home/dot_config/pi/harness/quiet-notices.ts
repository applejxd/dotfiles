// 自動で出るチャットの通知を畳む表示の組み立て (純関数。表示だけで、モデルに渡す本文 content は変えない)。
// 既定は畳む。PI_QUIET_NOTICES=0 で従来の全文表示。展開 (pi の expanded) すると全文。
// 失敗・時間切れ・承認待ち・警告は、畳んでも 1 行に必ず出す。
// see docs/spec/guard/pi-extensions.md#自動の通知を畳む表示
export const QUIET_WIDTH = 46;

export type NoticeKind = "child-finished" | "bg-job-finished" | "todo-reminder" | "autocheckpoint";

export interface NoticeInput {
	kind: NoticeKind;
	/** モデルに渡す本文 (全文)。 */
	content: string;
	details?: any;
	/** 描画幅。畳んだ 1 行は min(width, QUIET_WIDTH) に収める */
	width?: number;
	expanded?: boolean;
	env?: Record<string, string | undefined>;
}

export function quietEnabled(env: Record<string, string | undefined> = process.env): boolean {
	return env.PI_QUIET_NOTICES !== "0";
}

/** 1 文字の表示幅 (全角・絵文字は 2 桁、結合文字・制御文字は 0) */
export function cellWidth(ch: string): number {
	const c = ch.codePointAt(0) ?? 0;
	if (c < 0x20 || (c >= 0x7f && c < 0xa0) || (c >= 0x300 && c <= 0x36f) || c === 0x200d || (c >= 0xfe00 && c <= 0xfe0f)) return 0;
	if (
		(c >= 0x1100 && c <= 0x115f) ||
		(c >= 0x2e80 && c <= 0xa4cf) ||
		(c >= 0xac00 && c <= 0xd7a3) ||
		(c >= 0xf900 && c <= 0xfaff) ||
		(c >= 0xfe30 && c <= 0xfe6f) ||
		(c >= 0xff00 && c <= 0xff60) ||
		(c >= 0xffe0 && c <= 0xffe6) ||
		(c >= 0x1f300 && c <= 0x1faff) ||
		(c >= 0x20000 && c <= 0x3fffd)
	)
		return 2;
	return 1;
}

export function textWidth(s: string): number {
	let w = 0;
	for (const ch of s) w += cellWidth(ch);
	return w;
}

/** 表示幅 max に収まるよう切る (切ったら末尾に … を付ける) */
export function clipWidth(s: string, max: number): string {
	if (textWidth(s) <= max) return s;
	let out = "";
	let w = 0;
	for (const ch of s) {
		const cw = cellWidth(ch);
		if (w + cw > max - 1) break;
		out += ch;
		w += cw;
	}
	return `${out}…`;
}

/** 表示幅 width で折り返す (全文表示用。切り捨てない) */
export function wrapWidth(line: string, width: number): string[] {
	if (width < 2 || textWidth(line) <= width) return [line];
	const rows: string[] = [];
	let cur = "";
	let w = 0;
	for (const ch of line) {
		const cw = cellWidth(ch);
		if (w + cw > width) {
			rows.push(cur);
			cur = "";
			w = 0;
		}
		cur += ch;
		w += cw;
	}
	rows.push(cur);
	return rows;
}

const fmtDuration = (ms: unknown): string => {
	const s = Math.max(0, Math.round((Number(ms) || 0) / 1000));
	return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

type Level = "ok" | "warn" | "error";
export interface Folded {
	level: Level;
	text: string;
}

// 1 行に組む。固定の部分 (記号・役割・所要・費用・状態・警告) は必ず残し、題名と job id から削る
function compose(limit: number, sym: string, role: string, title: string, meta: string, state: string, id: string): string {
	const tail = `${meta ? ` ${meta}` : ""} · ${state}`;
	const head = `${sym} ${role}`;
	const fixed = textWidth(head) + textWidth(tail);
	for (const useId of [true, false]) {
		const idp = useId && id ? ` ${id}` : "";
		const room = limit - fixed - textWidth(idp);
		if (title) {
			if (room >= 6) return `${head} ${clipWidth(title, room - 1)}${tail}${idp}`;
		} else if (room >= 0) return `${head}${tail}${idp}`;
	}
	const bare = `${head}${tail}`;
	return textWidth(bare) <= limit ? bare : clipWidth(bare, limit);
}

const warnCount = (whole: string, d: any): number => {
	const content = whole.split("\nanswer:")[0];
	let n = Number(d?.blocked) || 0;
	n += Number(d?.errors) || 0;
	if (/^format check \(/m.test(content)) n++;
	if (/^conditions check \(/m.test(content)) n++;
	if (/^⚠ /m.test(content)) n++;
	return n;
};

function foldChild(content: string, d: any, limit: number): Folded {
	if (Array.isArray(d?.statuses)) {
		const st = d.statuses as string[];
		const bad = st.filter((s) => s !== "done").length;
		const sym = bad > 0 ? "✗" : "✓";
		const state = bad > 0 ? `失敗等 ${bad}/${st.length}` : "完了";
		return { level: bad > 0 ? "error" : warnCount(content, d) > 0 ? "warn" : "ok", text: compose(limit, sym, `並列 ${st.length} 件`, "", "", state, "") };
	}
	const status = String(d?.status ?? "done");
	const warns = warnCount(content, d);
	const stats = d?.stats ?? {};
	const meta = [fmtDuration(stats.durationMs), Number(stats.cost) > 0 ? `$${Number(stats.cost).toFixed(2)}` : ""].filter(Boolean).join(" ");
	let sym = "✓";
	let level: Level = "ok";
	let state = "完了";
	if (status === "blocked") ((sym = "⚠"), (level = "warn"), (state = "承認待ち"));
	else if (status === "failed") ((sym = "✗"), (level = "error"), (state = "失敗"));
	else if (status === "limit") ((sym = "✗"), (level = "error"), (state = "時間切れ"));
	else if (status === "aborted") ((sym = "✗"), (level = "error"), (state = "中断"));
	else if (status === "closed") ((sym = "✗"), (level = "error"), (state = "閉じた"));
	else if (warns > 0) ((sym = "⚠"), (level = "warn"), (state = "完了・要確認"));
	if (warns > 0) state = `${state} ⚠${warns}件`;
	const id = String(d?.id ?? d?.jobId ?? "");
	return { level, text: compose(limit, sym, String(d?.agent ?? "child"), String(d?.title ?? ""), meta, state, id) };
}

function foldJob(content: string, d: any, limit: number): Folded {
	const exits = [...content.matchAll(/^(?:バックグラウンドジョブ \S+ が終わりました |- \S+ )\(exit ([^)]*)\)/gm)].map((m) => m[1].trim());
	const ids: string[] = Array.isArray(d?.ids) ? d.ids : d?.id ? [String(d.id)] : [];
	const exitsAll = exits.length > 0 ? exits : d?.exit !== undefined ? [String(d.exit)] : [];
	const bad = exitsAll.filter((e) => e !== "0").length;
	const sym = bad > 0 ? "✗" : "✓";
	const level: Level = bad > 0 ? "error" : "ok";
	if (ids.length > 1) {
		const state = bad > 0 ? `失敗 ${bad}/${ids.length}` : "完了";
		return { level, text: compose(limit, sym, `job ${ids.length} 件`, "", "", state, "") };
	}
	const cmd = /^コマンド: (.*)$/m.exec(content)?.[1] ?? "";
	const state = bad > 0 ? `失敗 exit ${exitsAll[0] ?? "?"}` : "完了";
	return { level, text: compose(limit, sym, "job", cmd, "", state, ids[0] ?? "") };
}

/** 畳んだ 1 行 (kind ごと)。失敗・警告は level で返す */
export function foldNotice(kind: NoticeKind, content: string, details: any, limit = QUIET_WIDTH): Folded {
	switch (kind) {
		case "child-finished":
			return foldChild(content, details, limit);
		case "bg-job-finished":
			return foldJob(content, details, limit);
		case "todo-reminder": {
			const n = Number(details?.open);
			return { level: "ok", text: clipWidth(Number.isFinite(n) && n > 0 ? `📌 続き: 未完了 ${n} 件` : "📌 続き: 未完了あり", limit) };
		}
		case "autocheckpoint": {
			const p = Number(details?.percent);
			if (details?.resume) return { level: "ok", text: "▶ 再開を指示" };
			return { level: "ok", text: clipWidth(Number.isFinite(p) ? `💾 保存を指示（使用率 ${Math.round(p)}%）` : "💾 保存を指示", limit) };
		}
	}
}

/** 通知の表示行。畳まない条件 (展開・PI_QUIET_NOTICES=0) では content の全文 */
export function renderNotice(input: NoticeInput): { lines: string[]; level: Level; folded: boolean } {
	const full = String(input.content ?? "").split("\n");
	if (input.expanded || !quietEnabled(input.env ?? process.env)) return { lines: full, level: "ok", folded: false };
	const limit = Math.min(input.width ?? QUIET_WIDTH, QUIET_WIDTH);
	const f = foldNotice(input.kind, String(input.content ?? ""), input.details, limit);
	return { lines: [f.text], level: f.level, folded: true };
}

// ─── guarded_action の結果 (成功のときだけ畳む。hook の一覧は失敗したものだけ出す) ───

const HOOK_LINE = /^(.+?)\.{3,}\s*(?:\(.*\))?\s*(Passed|Failed|Skipped)\s*$/;

export function foldActionResult(
	text: string,
	details: any,
	opts: { width?: number; expanded?: boolean; env?: Record<string, string | undefined> } = {},
): { lines: string[]; folded: boolean } {
	const full = text.split("\n");
	// 失敗 (details 無し)・展開・無効のときは全文
	if (opts.expanded || !quietEnabled(opts.env ?? process.env) || !details?.action) return { lines: full, folded: false };
	const limit = Math.max(20, opts.width ?? 100);
	let passed = 0;
	let skipped = 0;
	const failedLines: string[] = [];
	let inFailed = false;
	const rest: string[] = [];
	for (const l of full) {
		const m = HOOK_LINE.exec(l);
		if (m) {
			inFailed = m[2] === "Failed";
			if (m[2] === "Passed") passed++;
			else if (m[2] === "Skipped") skipped++;
			else failedLines.push(l);
			continue;
		}
		// 失敗した hook の出力は、次の hook の行まで残す
		if (inFailed && l.trim() !== "") failedLines.push(l);
		else rest.push(l);
	}
	const commit = /^\[(\S+(?: \S+)*?) ([0-9a-f]{7,})\] (.*)$/m.exec(rest.join("\n"));
	const out: string[] = [];
	const repo = details.repo ? `${details.repo} ` : "";
	if (commit) out.push(clipWidth(`✓ ${repo}${commit[1]} ${commit[2]} ${commit[3]}`, limit));
	else {
		const first = rest.find((l) => l.trim() !== "") ?? "";
		out.push(clipWidth(`✓ ${details.action}${first ? `: ${first}` : ""}`, limit));
	}
	const total = passed + skipped + failedLines.filter((l) => HOOK_LINE.test(l)).length;
	if (failedLines.length > 0) {
		out.push(...failedLines);
	} else if (total > 0) {
		out.push(`pre-commit: 全 ${total} 項目 Passed${skipped > 0 ? `（うち Skipped ${skipped}）` : ""}`);
	}
	const closing = full.find((l) => l.startsWith("確認なしで実行した")) ?? full.find((l) => l.startsWith("実行した内容は"));
	if (closing) out.push(clipWidth(closing, limit));
	return { lines: out, folded: true };
}

// ─── 自動の再開 (user メッセージの先頭の目印) ───

export const RESUME_MARK = "【自動の再開】";

/** Markdown の変換 (表示だけ)。自動の再開の指示を 1 行にする。それ以外は変えない */
export function foldUserMarkdown(markdown: string, env: Record<string, string | undefined> = process.env): string {
	if (!quietEnabled(env) || !markdown.startsWith(RESUME_MARK)) return markdown;
	return "▶ 再開を指示（自動）";
}

/** pi の Component (render(width) と invalidate だけ)。折り返しは自前。 */
export function lineComponent(lines: string[], paint?: (s: string) => string) {
	return {
		render(width: number): string[] {
			const w = Math.max(10, width);
			return lines.flatMap((l) => wrapWidth(l, w)).map((l) => (paint ? paint(l) : l));
		},
		invalidate() {},
	};
}

const paintOf = (theme: any, level: Level) => (s: string) => {
	try {
		return level === "error" ? theme.fg("error", s) : level === "warn" ? theme.fg("warning", s) : theme.fg("dim", s);
	} catch {
		return s;
	}
};

/** 自動の通知の renderer (メッセージ・user の再開の指示) を登録する。PI_QUIET_NOTICES=0 なら何も登録しない */
export function registerQuietNotices(pi: any, env: Record<string, string | undefined> = process.env): void {
	if (!quietEnabled(env)) return;
	const kinds: NoticeKind[] = ["child-finished", "bg-job-finished", "todo-reminder", "autocheckpoint"];
	for (const kind of kinds) {
		pi.registerMessageRenderer?.(kind, (message: any, options: any, theme: any) => {
			const content = typeof message.content === "string" ? message.content : JSON.stringify(message.content ?? "");
			const r = renderNotice({ kind, content, details: message.details, expanded: options?.expanded === true, env });
			return lineComponent(r.lines, r.folded ? paintOf(theme, r.level) : undefined);
		});
	}
	pi.registerMarkdownTransformer?.((markdown: string, ctx: any) => (ctx?.messageType === "user" ? foldUserMarkdown(markdown, env) : markdown));
}

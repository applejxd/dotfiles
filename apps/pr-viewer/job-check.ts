// ジョブの結果の検査（設計の Q4・Q5）。純粋関数だけで、git も fs も動かさない。
// 入力は `git diff-tree -r -z --raw --no-renames --no-abbrev base result` などの出力と、呼び出し側が集めた大きさ・バイナリ・risk_paths。
// 通らないものは commit せず needs_review にする（アプリは LLM の変更を、検査を通ったものだけ commit する）。
// 独立させるため import は持たない。

/** 検査の上限（設計の Q4）。 */
export const LIMITS = {
	maxFiles: 200,
	maxBlobBytes: 1024 * 1024,
	maxTotalBytes: 4 * 1024 * 1024,
	maxPathBytes: 4096,
} as const;

/** `diff-tree --raw` の 1 件。モードは 6 桁の文字列（無いときは "000000"）。 */
export type RawEntry = { status: string; oldMode: string; newMode: string; oldOid: string; newOid: string; path: string };
export type ChangedFile = { path: string; status: "A" | "M" | "D" };
export type Verdict = "commit" | "needs_review";
export type CheckResult = {
	verdict: Verdict;
	/** コードだけ（パス・本文を含めない）。unsupported_file・too_many_files・too_large・binary・outside・risk_path・risk_config */
	reasons: string[];
	/** 許可された形の変更の一覧（A/M/D 以外の項目は含めない）。最大 maxFiles 件 */
	files: ChangedFile[];
	fileCount: number;
};

const MODE_REGULAR = "100644";
const OID_RE = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/;

/** `diff-tree -r -z --raw --no-renames --no-abbrev` の出力を解析する。形が違えば null。 */
export function parseRaw(out: string): RawEntry[] | null {
	const t = out.split("\0");
	const res: RawEntry[] = [];
	let i = 0;
	while (i < t.length) {
		const head = t[i++];
		if (head === "") {
			if (i >= t.length) break; // 末尾の NUL の後
			return null;
		}
		const m = /^:(\d{6}) (\d{6}) ([0-9a-f]+) ([0-9a-f]+) ([A-Z])\d*$/.exec(head);
		if (!m) return null;
		const status = m[5];
		const path = t[i++];
		if (path === undefined || path === "") return null;
		if (status === "R" || status === "C") {
			// --no-renames では出ないが、出たときは旧新の 2 つのパスを読み捨てて、許可しない種類として返す
			if (t[i++] === undefined) return null;
		}
		res.push({ status, oldMode: m[1], newMode: m[2], oldOid: m[3], newOid: m[4], path });
	}
	return res;
}

/** `diff-tree -r -z --numstat --no-renames` の出力から、バイナリ（`-\t-\t<path>`）のパスを集める。形が違えば null。 */
export function parseNumstatBinary(out: string): Set<string> | null {
	const bin = new Set<string>();
	for (const e of out.split("\0")) {
		if (e === "") continue;
		const m = /^(-|\d+)\t(-|\d+)\t([\s\S]+)$/.exec(e);
		if (!m) return null;
		if (m[1] === "-" && m[2] === "-") bin.add(m[3]);
	}
	return bin;
}

/** NTFS・macOS で `.git` と同一視されうる名前を含めて、`.git` か。 */
function isDotGit(c: string): boolean {
	const s = c.toLowerCase().replace(/[ .]+$/, "");
	return s === ".git" || /^git~\d+$/.test(s);
}

function isDotGitmodules(c: string): boolean {
	const s = c.toLowerCase().replace(/[ .]+$/, "");
	return s === ".gitmodules" || /^gitmod~\d+$/.test(s);
}

/** パスの形の検査。問題があれば理由のコード（outside・unsupported_file）、無ければ null。 */
export function checkPath(path: string): string | null {
	if (path === "" || path.includes("\0")) return "unsupported_file";
	if (path.startsWith("/") || /^[A-Za-z]:/.test(path) || path.includes("\\")) return "outside";
	if (/[\u0000-\u001f\u007f-\u009f\u2028\u2029]/.test(path) || path.includes("\ufffd")) return "unsupported_file";
	if (Buffer.byteLength(path, "utf8") > LIMITS.maxPathBytes) return "unsupported_file";
	for (const c of path.split("/")) {
		if (c === "") return "unsupported_file";
		if (c === "." || c === "..") return "outside";
		if (isDotGit(c) || isDotGitmodules(c)) return "unsupported_file";
	}
	return null;
}

/** risk_paths とは別に、設定・権限の境界を動かす固定のパス（`.gitattributes`・`.opencode/**`）か。 */
export function isBoundaryPath(path: string): boolean {
	const parts = path.split("/");
	if (parts[0] === ".opencode") return true;
	return parts[parts.length - 1].toLowerCase() === ".gitattributes";
}

export type CheckInput = {
	entries: RawEntry[];
	/** バイナリのパスの集合（numstat から） */
	binaryPaths?: Iterable<string>;
	/** 新しい blob の OID → バイト数 */
	sizes?: Record<string, number>;
	/** rules.json の risk_paths の正規表現。読めないときは null（commit しない） */
	riskPaths: RegExp[] | null;
};

/** 変更の一覧を検査する。1 つでも通らなければ needs_review。 */
export function checkChanges(input: CheckInput): CheckResult {
	const reasons = new Set<string>();
	const files: ChangedFile[] = [];
	const binary = new Set(input.binaryPaths ?? []);
	const sizes = input.sizes ?? {};
	let total = 0;
	if (input.riskPaths === null) reasons.add("risk_config");
	if (input.entries.length > LIMITS.maxFiles) reasons.add("too_many_files");
	for (const e of input.entries) {
		const pathReason = checkPath(e.path);
		if (pathReason) reasons.add(pathReason);
		let allowed = false;
		if (e.status === "A") allowed = e.oldMode === "000000" && e.newMode === MODE_REGULAR;
		else if (e.status === "M") allowed = e.oldMode === MODE_REGULAR && e.newMode === MODE_REGULAR;
		else if (e.status === "D") allowed = e.oldMode === MODE_REGULAR && e.newMode === "000000";
		if (!allowed) reasons.add("unsupported_file"); // T・R・C・U・モード変更・symlink・gitlink・実行ビット
		if (allowed && !pathReason && files.length < LIMITS.maxFiles) files.push({ path: e.path, status: e.status as ChangedFile["status"] });
		if (e.status === "A" || e.status === "M") {
			const size = OID_RE.test(e.newOid) ? sizes[e.newOid] : undefined;
			if (typeof size !== "number" || !Number.isFinite(size) || size > LIMITS.maxBlobBytes) reasons.add("too_large");
			else total += size;
		}
		if (binary.has(e.path)) reasons.add("binary");
		const risky = input.riskPaths?.some((re) => {
			re.lastIndex = 0;
			return re.test(e.path);
		});
		if (risky || isBoundaryPath(e.path)) reasons.add("risk_path");
	}
	if (total > LIMITS.maxTotalBytes) reasons.add("too_large");
	const list = [...reasons].sort();
	return { verdict: list.length === 0 ? "commit" : "needs_review", reasons: list, files, fileCount: input.entries.length };
}

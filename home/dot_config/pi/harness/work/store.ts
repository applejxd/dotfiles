// 作業台帳の永続 (追記専用のログ・スナップショット・書き手の権利 lease)。node 標準の node:fs だけを使う (Unix 前提)。
// 公開実装の保存の欠陥 (途中の kill で進捗が消える・2 人目の書き手が変更を捨てる・壊れた行を黙って捨てる) を構造で潰す。
// 形式・回復・lease・限界: docs/spec/work/store.md
import {
	closeSync,
	existsSync,
	fsyncSync,
	mkdirSync,
	openSync,
	readdirSync,
	readFileSync,
	renameSync,
	rmSync,
	statSync,
	truncateSync,
	writeSync,
} from "node:fs";
import { join } from "node:path";
import type { Lease, LedgerEvent, LedgerStore, LoadResult, NewEvent } from "./types.ts";

export const SEGMENT_SIZE = 1000;
export const SNAPSHOT_EVERY = 200;
export const HEARTBEAT_TIMEOUT_MS = 90_000;
/** owner.json を書く前の lease ディレクトリ (mkdir 直後) と、takeover の mutex を古いとみなす時間 */
const TRANSIENT_STALE_MS = 10_000;

export type StoreErrorCode = "NO_LEASE" | "READONLY" | "DEGRADED" | "IO";

export class StoreError extends Error {
	code: StoreErrorCode;
	constructor(code: StoreErrorCode, message: string) {
		super(message);
		this.name = "StoreError";
		this.code = code;
	}
}

export interface StoreOptions {
	root: string;
	now?: () => number;
	pid?: number;
	segmentSize?: number;
	snapshotEvery?: number;
	heartbeatTimeoutMs?: number;
	/** pid の生死判定 (試験で差し替える)。既定は process.kill(pid, 0) */
	isPidAlive?: (pid: number) => boolean;
	/** 書き込みの直前に呼ぶ (試験の障害注入用。ENOSPC などを投げさせる) */
	beforeWrite?: (path: string) => void;
}

/** LedgerStore に、スナップショットと状態の参照を足したもの */
export interface WorkStore extends LedgerStore {
	/** 読み取り専用に落ちた理由 (書ける間は null)。alert に出す */
	readonly readonlyReason: string | null;
	currentLease(): Lease | null;
	/** seq 以降 (seq を含まない) のイベントだけ読む。スナップショットからの高速な復元用。検証は該当セグメントの先頭から行う */
	loadSince(seq: number): Promise<LoadResult>;
	saveSnapshot(seq: number, json: string): Promise<void>;
	/** 壊れていない最新のスナップショット (無ければ null)。壊れたものは読み飛ばす (全ログから再構成できるため) */
	loadSnapshot(): Promise<{ seq: number; json: string } | null>;
	/** 前回のスナップショットから snapshotEvery 件以上進んだか */
	snapshotDue(seq: number): boolean;
}

// ── crc32 (IEEE) ─────────────────────────────────────────────────
const CRC_TABLE: Uint32Array = (() => {
	const t = new Uint32Array(256);
	for (let n = 0; n < 256; n++) {
		let c = n;
		for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
		t[n] = c >>> 0;
	}
	return t;
})();

export function crc32(buf: Uint8Array): number {
	let c = 0xffffffff;
	for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
	return (c ^ 0xffffffff) >>> 0;
}

function crcHex(buf: Uint8Array): string {
	return crc32(buf).toString(16).padStart(8, "0");
}

/** 1 行の形式: `<JSON>\t<crc32 の 16 進 8 桁>\n`。JSON.stringify は生のタブ・改行を出さない */
export function encodeLine(ev: LedgerEvent): Buffer {
	const o: Record<string, unknown> = { seq: ev.seq, ts: ev.ts, type: ev.type };
	if (ev.node !== undefined) o.node = ev.node;
	o.data = ev.data;
	// 出所と保持者 (I8・I10)。落とすと再起動後の再生で利用者専用イベントが拒否される
	if (ev.source !== undefined) o.source = ev.source;
	if (ev.holder !== undefined) o.holder = ev.holder;
	if (ev.aux !== undefined) o.aux = ev.aux;
	const body = Buffer.from(JSON.stringify(o), "utf8");
	return Buffer.concat([body, Buffer.from(`\t${crcHex(body)}\n`, "latin1")]);
}

// ── fs の補助 ────────────────────────────────────────────────────
function fsyncDir(dir: string): void {
	let fd: number | undefined;
	try {
		fd = openSync(dir, "r");
		fsyncSync(fd);
	} catch (e) {
		const code = (e as NodeJS.ErrnoException).code;
		if (code !== "EINVAL" && code !== "EISDIR" && code !== "EPERM") throw e;
	} finally {
		if (fd !== undefined) closeSync(fd);
	}
}

function writeAll(fd: number, buf: Buffer): void {
	let off = 0;
	while (off < buf.length) off += writeSync(fd, buf, off, buf.length - off);
}

/** tmp に書いて fsync → rename → ディレクトリを fsync (途中で落ちても中途半端なファイルが見えない) */
function atomicWrite(dir: string, name: string, data: string, tag: string): void {
	const tmp = join(dir, `.${name}.${tag}.tmp`);
	const fd = openSync(tmp, "w");
	try {
		writeAll(fd, Buffer.from(data, "utf8"));
		fsyncSync(fd);
	} finally {
		closeSync(fd);
	}
	renameSync(tmp, join(dir, name));
	fsyncDir(dir);
}

function segIndex(seq: number, size: number): number {
	return Math.floor((seq - 1) / size) + 1;
}

function segName(idx: number): string {
	return `${String(idx).padStart(4, "0")}.jsonl`;
}

function defaultIsPidAlive(pid: number): boolean {
	try {
		process.kill(pid, 0);
		return true;
	} catch (e) {
		return (e as NodeJS.ErrnoException).code === "EPERM";
	}
}

interface Owner extends Lease {
	token: string;
}

interface Bad {
	idx: number;
	offset: number;
	reason: string;
}

interface Scan {
	events: LedgerEvent[];
	lastSeq: number;
	torn?: { idx: number; offset: number };
	bad?: Bad;
	/** bad の段以降に残っている (隔離の対象になる) セグメントの番号 */
	rest: number[];
}

export function createStore(opts: StoreOptions): WorkStore {
	const root = opts.root;
	const now = opts.now ?? (() => Date.now());
	const pid = opts.pid ?? process.pid;
	const size = opts.segmentSize ?? SEGMENT_SIZE;
	const snapEvery = opts.snapshotEvery ?? SNAPSHOT_EVERY;
	const hbTimeout = opts.heartbeatTimeoutMs ?? HEARTBEAT_TIMEOUT_MS;
	const alive = opts.isPidAlive ?? defaultIsPidAlive;
	const hook = opts.beforeWrite ?? (() => {});
	const logDir = join(root, "log");
	const leaseDir = join(root, "lease");
	const lockDir = join(root, "lease.lock");
	const quarDir = join(root, "quarantine");
	const marker = join(root, "DEGRADED.json");
	const tag = `${pid}-${Math.random().toString(36).slice(2, 10)}`;

	let token: string | null = null;
	let lease: Lease | null = null;
	let ro: string | null = null;
	let lastSeq = 0;
	let inited = false;
	let lastSnapSeq = 0;

	function mkdirs(): void {
		mkdirSync(logDir, { recursive: true });
	}

	function segments(): number[] {
		if (!existsSync(logDir)) return [];
		return readdirSync(logDir)
			.filter((n) => /^\d{4,}\.jsonl$/.test(n))
			.map((n) => Number.parseInt(n, 10))
			.sort((a, b) => a - b);
	}

	function scan(fromSeq: number): Scan {
		const out: Scan = { events: [], lastSeq: fromSeq, rest: [] };
		const all = segments();
		const first = segIndex(fromSeq + 1, size);
		const idxs = all.filter((i) => i >= first);
		let expected = fromSeq > 0 ? (first - 1) * size + 1 : 1;
		for (let n = 0; n < idxs.length; n++) {
			const idx = idxs[n];
			// セグメントの先頭の seq は番号から決まる。欠けたセグメントは欠番として検出する
			if ((idx - 1) * size + 1 !== expected) {
				out.bad = { idx, offset: 0, reason: `seq の欠番 (期待 ${expected}・セグメント ${segName(idx)} の先頭は ${(idx - 1) * size + 1})` };
				out.rest = idxs.slice(n + 1);
				return out;
			}
			const buf = readFileSync(join(logDir, segName(idx)));
			let pos = 0;
			while (pos < buf.length) {
				const nl = buf.indexOf(10, pos);
				const isLast = n === idxs.length - 1;
				if (nl < 0) {
					if (isLast) out.torn = { idx, offset: pos };
					else out.bad = { idx, offset: pos, reason: "セグメントの途中で行が切れている" };
					break;
				}
				const line = buf.subarray(pos, nl);
				const tab = line.lastIndexOf(9);
				let reason: string | null = null;
				let ev: LedgerEvent | null = null;
				if (tab < 0) reason = "crc が無い行";
				else {
					const body = line.subarray(0, tab);
					const want = line.subarray(tab + 1).toString("latin1");
					if (!/^[0-9a-f]{8}$/.test(want) || want !== crcHex(body)) reason = "crc 不一致";
					else {
						try {
							ev = JSON.parse(body.toString("utf8")) as LedgerEvent;
						} catch {
							reason = "JSON 不正";
						}
						if (ev && (typeof ev !== "object" || ev.seq !== expected || typeof ev.type !== "string")) {
							reason = ev && typeof ev === "object" && ev.seq !== expected ? `seq の欠番 (期待 ${expected}・実際 ${String(ev.seq)})` : "イベントの形が不正";
							ev = null;
						}
					}
				}
				if (!ev) {
					out.bad = { idx, offset: pos, reason: reason ?? "不明" };
					break;
				}
				if (ev.seq > fromSeq) out.events.push(ev);
				out.lastSeq = ev.seq;
				expected++;
				pos = nl + 1;
			}
			if (out.bad) {
				out.rest = idxs.slice(n + 1);
				return out;
			}
		}
		return out;
	}

	function readMarker(): { quarantined: string; reason: string } | null {
		try {
			const m = JSON.parse(readFileSync(marker, "utf8")) as { quarantined: string; reason: string };
			return { quarantined: String(m.quarantined), reason: String(m.reason) };
		} catch {
			return existsSync(marker) ? { quarantined: "", reason: "DEGRADED.json が読めない" } : null;
		}
	}

	/** bad の行以降を quarantine/ へ移し (逐語で保存)、ログを bad の手前で切り、DEGRADED.json を書く。書き手だけが行う */
	function quarantine(s: Scan): { quarantined: string; reason: string } {
		const bad = s.bad as Bad;
		mkdirSync(quarDir, { recursive: true });
		const stamp = new Date(now()).toISOString().replace(/[:.]/g, "-");
		const qpath = join(quarDir, `${stamp}.jsonl`);
		const parts: Buffer[] = [];
		const badPath = join(logDir, segName(bad.idx));
		parts.push(readFileSync(badPath).subarray(bad.offset));
		for (const i of s.rest) parts.push(readFileSync(join(logDir, segName(i))));
		hook(qpath);
		const fd = openSync(qpath, "wx");
		try {
			writeAll(fd, Buffer.concat(parts));
			fsyncSync(fd);
		} finally {
			closeSync(fd);
		}
		fsyncDir(quarDir);
		if (bad.offset === 0) rmSync(badPath);
		else truncateSync(badPath, bad.offset);
		for (const i of s.rest) rmSync(join(logDir, segName(i)));
		fsyncDir(logDir);
		const info = { quarantined: qpath, reason: bad.reason };
		atomicWrite(root, "DEGRADED.json", JSON.stringify({ ...info, at: now() }), tag);
		return info;
	}

	function holdsLease(): boolean {
		return lease !== null && token !== null && readOwner()?.token === token;
	}

	/** 末尾の途中の行は、書き手なら物理的に切り詰める。読み手は触らない (書き手が追記の最中かもしれない) */
	function loadImpl(fromSeq: number): LoadResult {
		const s = scan(fromSeq);
		const res: LoadResult = { events: s.events };
		const writer = holdsLease();
		if (s.torn) {
			res.recovered = true;
			if (writer) {
				try {
					truncateSync(join(logDir, segName(s.torn.idx)), s.torn.offset);
				} catch (e) {
					fail(e);
				}
			}
		}
		if (s.bad) {
			if (writer) {
				try {
					res.degraded = quarantine(s);
				} catch (e) {
					fail(e);
				}
			} else res.degraded = { quarantined: "", reason: `${s.bad.reason} (未隔離: 書き手が隔離する)` };
		} else {
			const m = readMarker();
			if (m) res.degraded = m;
		}
		if (writer && fromSeq === 0) {
			lastSeq = s.lastSeq;
			inited = !s.bad;
		}
		return res;
	}

	function fail(e: unknown): never {
		const err = e as NodeJS.ErrnoException;
		if (err instanceof StoreError) throw err;
		ro = `${err.code ?? "IO"}: ${err.message}`;
		const se = new StoreError("IO", `台帳に書けない (読み取り専用に落とした): ${ro}`);
		(se as StoreError & { cause?: unknown }).cause = e;
		throw se;
	}

	// ── lease ────────────────────────────────────────────────────
	function readOwner(): Owner | null {
		try {
			const o = JSON.parse(readFileSync(join(leaseDir, "owner.json"), "utf8")) as Owner;
			if (typeof o.pid !== "number" || typeof o.heartbeat !== "number" || typeof o.token !== "string") return null;
			return o;
		} catch {
			return null;
		}
	}

	function writeOwner(o: Owner): void {
		atomicWrite(leaseDir, "owner.json", JSON.stringify(o), tag);
	}

	function ownerStale(o: Owner | null): boolean {
		if (!o) {
			// owner.json が無い: mkdir 直後の書き手の途中かもしれないので、十分古いときだけ古いとみなす
			try {
				return Date.now() - statSync(leaseDir).mtimeMs > TRANSIENT_STALE_MS;
			} catch {
				return true;
			}
		}
		return !alive(o.pid) || now() - o.heartbeat > hbTimeout;
	}

	function claim(holder: string): Lease {
		const t = now();
		const o: Owner = { holder, pid, startedAt: t, heartbeat: t, token: tag };
		writeOwner(o);
		token = tag;
		lease = { holder, pid, startedAt: t, heartbeat: t };
		inited = false;
		return lease;
	}

	function withLock<T>(fn: () => T): T | null {
		for (let attempt = 0; attempt < 2; attempt++) {
			try {
				mkdirSync(lockDir);
			} catch (e) {
				if ((e as NodeJS.ErrnoException).code !== "EEXIST") throw e;
				let old = false;
				try {
					old = Date.now() - statSync(lockDir).mtimeMs > TRANSIENT_STALE_MS;
				} catch {
					old = true;
				}
				if (!old) return null;
				rmSync(lockDir, { recursive: true, force: true });
				continue;
			}
			try {
				return fn();
			} finally {
				rmSync(lockDir, { recursive: true, force: true });
			}
		}
		return null;
	}

	async function acquireLease(holder: string, _pid: number): Promise<Lease | null> {
		try {
			mkdirs();
			try {
				mkdirSync(leaseDir);
				return claim(holder);
			} catch (e) {
				if ((e as NodeJS.ErrnoException).code !== "EEXIST") throw e;
			}
			const seen = readOwner();
			// 同じ pid・同じ holder の再取得は許す (拡張の再読み込み)。古い側は token が変わるので以後 append できない
			if (seen && seen.pid === pid && seen.holder === holder) return claim(holder);
			if (!ownerStale(seen)) return null;
			// 引き継ぎは mutex の下で行い、古いままかを取り直して確かめる (同時に 2 人が引き継ごうとして 1 人だけが成功する)
			const got = withLock<Lease | null>(() => {
				const again = readOwner();
				if (!ownerStale(again) || (again && seen && again.token !== seen.token)) return null;
				const grave = join(root, `lease.old-${tag}`);
				try {
					renameSync(leaseDir, grave);
				} catch (e) {
					if ((e as NodeJS.ErrnoException).code === "ENOENT") return null;
					throw e;
				}
				rmSync(grave, { recursive: true, force: true });
				try {
					mkdirSync(leaseDir);
				} catch (e) {
					if ((e as NodeJS.ErrnoException).code === "EEXIST") return null;
					throw e;
				}
				return claim(holder);
			});
			return got;
		} catch (e) {
			const code = (e as NodeJS.ErrnoException).code;
			if (code === "EACCES" || code === "EROFS" || code === "EPERM" || code === "ENOSPC") {
				ro = `${code}: ${(e as Error).message}`;
				return null;
			}
			throw e;
		}
	}

	async function heartbeat(): Promise<void> {
		if (!lease || !token) throw new StoreError("NO_LEASE", "lease を持っていない");
		const o = readOwner();
		if (!o || o.token !== token) {
			lease = null;
			token = null;
			throw new StoreError("NO_LEASE", "lease を引き継がれた (以後は読み取り専用)");
		}
		try {
			hook(join(leaseDir, "owner.json"));
			o.heartbeat = now();
			writeOwner(o);
		} catch (e) {
			fail(e);
		}
		lease = { holder: o.holder, pid: o.pid, startedAt: o.startedAt, heartbeat: o.heartbeat };
	}

	async function releaseLease(): Promise<void> {
		if (!lease) return;
		if (holdsLease()) {
			const grave = join(root, `lease.old-${tag}`);
			try {
				renameSync(leaseDir, grave);
				rmSync(grave, { recursive: true, force: true });
			} catch {
				// 解放の失敗は握りつぶさず、次の取得者が古いと判定する (heartbeat 切れ)
			}
		}
		lease = null;
		token = null;
		inited = false;
	}

	// ── 追記・読み出し ───────────────────────────────────────────
	async function append(ev: NewEvent): Promise<LedgerEvent> {
		if (!lease || !token) throw new StoreError("NO_LEASE", "lease を持たない書き手は追記できない (別の会話が駆動中)");
		if (!holdsLease()) {
			lease = null;
			token = null;
			throw new StoreError("NO_LEASE", "lease を引き継がれた。追記を拒否した");
		}
		if (ro) throw new StoreError("READONLY", `読み取り専用: ${ro}`);
		if (existsSync(marker)) {
			const m = readMarker();
			throw new StoreError("DEGRADED", `台帳が破損のため読み取り専用 (${m?.reason ?? "?"} → ${m?.quarantined ?? "?"})`);
		}
		if (!inited) {
			const r = loadImpl(0);
			if (r.degraded) throw new StoreError("DEGRADED", `台帳が破損のため読み取り専用 (${r.degraded.reason})`);
		}
		const full: LedgerEvent = { ...ev, seq: lastSeq + 1, ts: now() };
		const path = join(logDir, segName(segIndex(full.seq, size)));
		try {
			mkdirs();
			const fresh = !existsSync(path);
			hook(path);
			const fd = openSync(path, "a");
			try {
				writeAll(fd, encodeLine(full));
				fsyncSync(fd);
			} finally {
				closeSync(fd);
			}
			if (fresh) fsyncDir(logDir);
		} catch (e) {
			fail(e);
		}
		lastSeq = full.seq;
		return full;
	}

	async function load(): Promise<LoadResult> {
		return loadImpl(0);
	}

	async function loadSince(seq: number): Promise<LoadResult> {
		return loadImpl(Math.max(0, seq));
	}

	// ── スナップショット ─────────────────────────────────────────
	const snapName = (seq: number) => `snapshot-${String(seq).padStart(10, "0")}.json`;

	function snapshots(): { seq: number; name: string }[] {
		if (!existsSync(root)) return [];
		return readdirSync(root)
			.map((n) => ({ n, m: /^snapshot-(\d{10})\.json$/.exec(n) }))
			.filter((x) => x.m)
			.map((x) => ({ seq: Number.parseInt((x.m as RegExpExecArray)[1], 10), name: x.n }))
			.sort((a, b) => b.seq - a.seq);
	}

	async function saveSnapshot(seq: number, json: string): Promise<void> {
		if (!holdsLease()) throw new StoreError("NO_LEASE", "lease を持たない書き手はスナップショットを書けない");
		if (ro) throw new StoreError("READONLY", `読み取り専用: ${ro}`);
		try {
			hook(join(root, snapName(seq)));
			const body = Buffer.from(json, "utf8");
			atomicWrite(root, snapName(seq), JSON.stringify({ seq, crc: crcHex(body), json }), tag);
			lastSnapSeq = Math.max(lastSnapSeq, seq);
			// 新しい 2 つだけ残す
			for (const old of snapshots().slice(2)) rmSync(join(root, old.name), { force: true });
		} catch (e) {
			fail(e);
		}
	}

	async function loadSnapshot(): Promise<{ seq: number; json: string } | null> {
		for (const s of snapshots()) {
			try {
				const o = JSON.parse(readFileSync(join(root, s.name), "utf8")) as { seq: number; crc: string; json: string };
				if (o.seq === s.seq && typeof o.json === "string" && o.crc === crcHex(Buffer.from(o.json, "utf8"))) {
					lastSnapSeq = Math.max(lastSnapSeq, o.seq);
					return { seq: o.seq, json: o.json };
				}
			} catch {
				// 壊れたスナップショットは読み飛ばし、次に古いもの (無ければ全ログ) から復元させる
			}
		}
		return null;
	}

	return {
		append,
		load,
		loadSince,
		acquireLease,
		heartbeat,
		releaseLease,
		saveSnapshot,
		loadSnapshot,
		snapshotDue: (seq: number) => seq - lastSnapSeq >= snapEvery,
		currentLease: () => lease,
		get readonlyReason(): string | null {
			if (ro) return ro;
			const m = existsSync(marker) ? readMarker() : null;
			return m ? `degraded: ${m.reason}` : null;
		},
	};
}

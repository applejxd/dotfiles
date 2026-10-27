// セッションごとの一時置き場 `<作業ツリー>/.tmp/s/<セッション ID の末尾>/` (CHG-0042)。
//
// - session_start で作り、process.env.TMPDIR をそこへ向ける (bash・bg_run・子は、process.env を基に環境を作る)
// - **session_shutdown の reason が quit のときだけ**、この実行 (プロセス) が作った置き場をすべて消す。
//   new / resume / fork では、会話が旧置き場のパスを参照し続けるので消さない。reload は同じセッションが続く
// - 消す前に、その置き場を TMPDIR にしたまま生きているプロセスが無いか確かめる (Linux の /proc)。
//   いれば、少し待ち、まだいれば消さない (次の起動の、持ち主の死亡を確証できた置き場の回収が消す)
// - 起動時に、tmp_clean.py を背景で呼ぶ (持ち主が死んだ s/ の回収。1 日 1 回は、再生成できる名前の掃除も)
// - 何もしないとき: 子エージェント・pis の内側 (TMPDIR=/tmp の tmpfs)・Windows・`.tmp` が無い/リンク
//
// 持ち主の記録 `.owner` の形と、死亡の確証の規則は tmp_clean.py が持つ。
// see docs/change/0042-tmp-lifecycle.md
import { spawn } from "node:child_process";
import { existsSync, lstatSync, mkdirSync, readdirSync, readFileSync, readlinkSync, rmSync, statSync, utimesSync, writeFileSync } from "node:fs";
import { hostname } from "node:os";
import { join } from "node:path";

/** Unix ドメインソケットのパス長 (上限 108 バイト前後) に収めるための、置き場のパスの上限 */
export const MAX_DIR_LEN = 80;
/** 消す前に、置き場を使っているプロセスの終了を待つ最大の時間 (ミリ秒) */
export const SURVIVOR_WAIT_MS = 3000;
const FULL_SWEEP_INTERVAL_MS = 24 * 3600 * 1000;

/** UUIDv7 の先頭は時刻 (約 65 秒は同じ) なので、ランダムな末尾を使う */
export function idTail(sessionId: string, n = 8): string {
	const hex = sessionId.replace(/[^0-9a-fA-F]/g, "").toLowerCase();
	return (hex.slice(-n) || "0".repeat(n)).padStart(n, "0");
}

/** /proc/<pid>/stat の起動時刻 (22 番目の項目)。無ければ undefined */
export function procStart(pid: number): string | undefined {
	try {
		const text = readFileSync(`/proc/${pid}/stat`, "utf-8");
		const rest = text.slice(text.lastIndexOf(")") + 1).trim().split(/\s+/);
		return rest[19];
	} catch {
		return undefined;
	}
}

export function ownerRecord(pid = process.pid): { pid: number; start: string; pidns: string; host: string } {
	let pidns = "";
	try {
		pidns = readlinkSync("/proc/self/ns/pid");
	} catch {}
	return { pid, start: procStart(pid) ?? "", pidns, host: hostname() };
}

function isRealDir(path: string): boolean {
	try {
		const st = lstatSync(path);
		return st.isDirectory() && !st.isSymbolicLink();
	} catch {
		return false;
	}
}

function readOwnerPid(dir: string): number | undefined {
	try {
		const pid = Number(JSON.parse(readFileSync(join(dir, ".owner"), "utf-8")).pid);
		return Number.isInteger(pid) ? pid : undefined;
	} catch {
		return undefined;
	}
}

/** この置き場を TMPDIR にしたまま生きているプロセス (自分以外)。/proc が無ければ空 */
export function survivors(dir: string, selfPid = process.pid): number[] {
	if (!existsSync("/proc/self")) return [];
	const want = `TMPDIR=${dir}`;
	const found: number[] = [];
	let names: string[];
	try {
		names = readdirSync("/proc");
	} catch {
		return [];
	}
	for (const name of names) {
		if (!/^\d+$/.test(name)) continue;
		const pid = Number(name);
		if (pid === selfPid) continue;
		try {
			const env = readFileSync(`/proc/${pid}/environ`, "utf-8").split("\0");
			if (!env.includes(want)) continue;
			const stat = readFileSync(`/proc/${pid}/stat`, "utf-8");
			if (stat.slice(stat.lastIndexOf(")") + 2, stat.lastIndexOf(")") + 3) === "Z") continue; // ゾンビは終了済み
			found.push(pid);
		} catch {
			// 読めない (権限・消えた) ものは、数えない
		}
	}
	return found;
}

export interface SessionTmpOptions {
	/** false なら何もしない (子・pis の内側・Windows) */
	enabled: boolean;
	/** tmp_clean.py のあるディレクトリ (ハーネスの置き場) */
	harnessDir: string;
	sleep?: (ms: number) => Promise<void>;
	waitMs?: number;
}

export class SessionTmp {
	readonly created = new Set<string>();
	active: string | undefined;
	private readonly sleep: (ms: number) => Promise<void>;
	private readonly waitMs: number;
	private readonly opts: SessionTmpOptions;

	constructor(opts: SessionTmpOptions) {
		this.opts = opts; // (node の型除去は、コンストラクタの引数プロパティを扱えない)
		this.sleep = opts.sleep ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
		this.waitMs = opts.waitMs ?? SURVIVOR_WAIT_MS;
	}

	/** 置き場を作り、TMPDIR を向ける。作らなかったときは undefined (TMPDIR は変えない) */
	start(cwd: string, sessionId: string): string | undefined {
		if (!this.opts.enabled) return undefined;
		const tmpRoot = join(cwd, ".tmp");
		if (!isRealDir(tmpRoot)) return undefined; // `.tmp` が無い・リンクのリポジトリでは何もしない (勝手に作らない)
		const sdir = join(tmpRoot, "s");
		try {
			if (!existsSync(sdir)) mkdirSync(sdir, { mode: 0o700 });
		} catch {
			// 並行する別のセッションが先に作った
		}
		if (!isRealDir(sdir)) return undefined;
		for (const n of [8, 12, 16, 24]) {
			const dir = join(sdir, idTail(sessionId, n));
			if (dir.length > MAX_DIR_LEN) return undefined;
			try {
				mkdirSync(dir, { mode: 0o700 });
			} catch (e: any) {
				if (e?.code !== "EEXIST") return undefined;
				if (readOwnerPid(dir) !== process.pid) continue; // 別のセッションの置き場。末尾を伸ばす
				// 自分の置き場 (reload で、同じセッションが続く): そのまま使う
			}
			try {
				writeFileSync(join(dir, ".owner"), JSON.stringify(ownerRecord()), { mode: 0o600 });
			} catch {
				return undefined;
			}
			this.created.add(dir);
			this.active = dir;
			process.env.TMPDIR = dir;
			return dir;
		}
		return undefined;
	}

	/** quit のときだけ、この実行が作った置き場をすべて消す。消さなかった置き場の一覧を返す */
	async teardown(reason: string): Promise<{ removed: string[]; kept: string[] }> {
		const removed: string[] = [];
		if (!this.opts.enabled || reason !== "quit") return { removed, kept: [...this.created] };
		for (const dir of [...this.created]) {
			if (!(await this.waitForSurvivors(dir))) continue; // 生き残りがいるので、消さない
			try {
				rmSync(dir, { recursive: true, force: true });
				removed.push(dir);
				this.created.delete(dir);
			} catch {
				// 消せなければ残す (次の起動の回収が消す)
			}
		}
		return { removed, kept: [...this.created] };
	}

	private async waitForSurvivors(dir: string): Promise<boolean> {
		const deadline = Date.now() + this.waitMs;
		for (;;) {
			if (survivors(dir).length === 0) return true;
			if (Date.now() >= deadline) return false;
			await this.sleep(100);
		}
	}

	/** 起動時の掃除を背景で呼ぶ。s/ の回収は毎回、再生成できる名前の掃除は 1 日に 1 回まで */
	sweep(cwd: string): boolean {
		if (!this.opts.enabled) return false;
		const tmpRoot = join(cwd, ".tmp");
		const script = join(this.opts.harnessDir, "tmp_clean.py");
		if (!isRealDir(tmpRoot) || !existsSync(script)) return false;
		const stamp = join(tmpRoot, ".clean-stamp");
		let full = true;
		try {
			full = Date.now() - statSync(stamp).mtimeMs > FULL_SWEEP_INTERVAL_MS;
		} catch {}
		const args = [script, "--dir", tmpRoot, "--apply", ...(full ? [] : ["--sessions-only"])];
		try {
			if (full) {
				writeFileSync(stamp, "");
				utimesSync(stamp, new Date(), new Date());
			}
			const child = spawn("python3", args, { cwd, detached: true, stdio: "ignore" });
			child.on("error", () => {});
			child.unref();
			return true;
		} catch {
			return false;
		}
	}
}

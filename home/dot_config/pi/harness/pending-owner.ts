// 承認した操作を実行中のプロセス (owner) が、まだ生きているかの判定 (CHG-0055)。
// PID は再利用されるので、PID だけでは「生きている」と言えない。起動時刻も照合する。
// 人が /pending resolve で、実行中かもしれない試行を決着させて元の実行と重ならないようにするための部品。
//
// see docs/change/0055-async-approval.md
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import os from "node:os";

export type Owner = {
	sessionId: string; // 記録するだけ。判定には使わない
	runtimeEpoch: string; // pi の実行時の世代。記録するだけ。判定には使わない
	pid: number;
	processStart: string | null; // プロセスの起動時刻の識別子 (取れなければ null)
	host: string;
};
export type OwnerState = "alive" | "gone" | "unknown";
export type ProcessStart = { exists: false } | { exists: true; start: string | null };
export type Probe = {
	host?: string;
	platform?: NodeJS.Platform;
	readStart?: (pid: number) => ProcessStart;
};

/** /proc/<pid>/stat の 22 番目 (starttime)。コマンド名に空白や ')' が入りうるので、最後の ')' より後ろを数える */
export function parseLinuxStat(text: string): string | null {
	const close = text.lastIndexOf(")");
	if (close < 0) return null;
	const fields = text
		.slice(close + 1)
		.trim()
		.split(/\s+/);
	// ')' の後ろは 3 番目 (state) から始まるので、22 番目は添字 19
	const v = fields[19];
	return v && /^\d+$/.test(v) ? v : null;
}

/** pid のプロセスの有無と起動時刻の識別子。Linux と darwin だけ対応し、ほかは { exists: true, start: null } (例外は投げない) */
export function readProcessStart(pid: number, platform: NodeJS.Platform = process.platform): ProcessStart {
	if (platform === "linux") {
		let text: string;
		try {
			text = readFileSync(`/proc/${pid}/stat`, "utf8");
		} catch (e) {
			const code = (e as NodeJS.ErrnoException).code;
			if (code === "ENOENT" || code === "ESRCH") return { exists: false };
			return { exists: true, start: null };
		}
		return { exists: true, start: parseLinuxStat(text) };
	}
	if (platform === "darwin") {
		try {
			const out = execFileSync("ps", ["-p", String(pid), "-o", "lstart="], { encoding: "utf8", timeout: 2000, stdio: ["ignore", "pipe", "ignore"] }).trim();
			return out ? { exists: true, start: out } : { exists: false };
		} catch (e) {
			// ps は該当なしで終了コード 1
			if ((e as { status?: number }).status === 1) return { exists: false };
			return { exists: true, start: null };
		}
	}
	return { exists: true, start: null };
}

/** 今のプロセスの owner */
export function currentOwner(sessionId: string, runtimeEpoch: string, probe: Probe = {}): Owner {
	const read = probe.readStart ?? ((pid: number) => readProcessStart(pid, probe.platform));
	const s = read(process.pid);
	return {
		sessionId,
		runtimeEpoch,
		pid: process.pid,
		processStart: s.exists ? s.start : null,
		host: probe.host ?? os.hostname(),
	};
}

/** owner のプロセスが生きているか。reason は人が読む 1 文 */
export function ownerState(owner: Owner, probe: Probe = {}): { state: OwnerState; reason: string } {
	if (owner.host !== (probe.host ?? os.hostname())) return { state: "unknown", reason: "別のホストのプロセスは確認できない" };
	if (!Number.isInteger(owner.pid) || owner.pid <= 0 || owner.pid > 2 ** 31) return { state: "unknown", reason: "owner の PID の記録が不正" };
	const platform = probe.platform ?? process.platform;
	if (platform !== "linux" && platform !== "darwin") return { state: "unknown", reason: "この OS ではプロセスの確認手段が無い" };
	const cur = (probe.readStart ?? ((pid: number) => readProcessStart(pid, platform)))(owner.pid);
	if (!cur.exists) return { state: "gone", reason: "owner のプロセスが存在しない" };
	if (owner.processStart === null) return { state: "unknown", reason: "起動時刻の記録が無く、PID の再利用と区別できない" };
	if (cur.start === null) return { state: "unknown", reason: "現在の起動時刻を読めず、PID の再利用と区別できない" };
	if (cur.start === owner.processStart) return { state: "alive", reason: "owner のプロセスが実行中" };
	return { state: "gone", reason: "同じ PID だが起動時刻が違い、PID が再利用された" };
}

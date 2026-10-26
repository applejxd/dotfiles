// サンドボックスの内側にいることを、この pi のプロセス自身が実測する (カナリア)。
//
// 起動したホスト側が、内側から見えてはいけないファイル (読み取り) と、書けてはいけない場所 (書き込み) を用意し、
// そのパスを環境変数で渡す。内側で読めたり書けたりしたら、サンドボックスは効いていない。
// 環境変数 (PI_HARNESS_BOUNDARY) は「内側のはず」という期待にすぎず、緩和の根拠にしない。
// see docs/spec/guard/pi-sandbox.md#緩和のゲート
import { existsSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";

export type CanarySpec = { read: string; write: string };
export type CanaryResult = { ok: boolean; reason: string };

/** ok なら、読めず書けなかった (=サンドボックスが効いている)。 */
export function runCanary(spec: CanarySpec): CanaryResult {
	if (!spec.read || !spec.write) return { ok: false, reason: "カナリアの場所が渡されていない" };
	try {
		readFileSync(spec.read);
		return { ok: false, reason: `内側から ${spec.read} を読めた (サンドボックスが効いていない)` };
	} catch {
		// 読めないのが期待どおり
	}
	try {
		writeFileSync(spec.write, "canary", { flag: "wx" });
	} catch (e) {
		// 既にあるパスへの失敗は、サンドボックスの拒否を示さない (証明にならない)
		if ((e as NodeJS.ErrnoException).code === "EEXIST") return { ok: false, reason: `${spec.write} が既にある (書き込みの検査ができない)` };
		return { ok: true, reason: "読めず・書けなかった" };
	}
	try {
		if (existsSync(spec.write)) unlinkSync(spec.write);
	} catch {}
	return { ok: false, reason: `内側から ${spec.write} へ書けた (サンドボックスが効いていない)` };
}

/** 環境変数から、起動したホストが渡した設定を読む。期待していなければ null (緩和しない)。 */
export function readBoundaryEnv(env: NodeJS.ProcessEnv): {
	spec: CanarySpec;
	allowed: { read: string[]; write: string[] };
} | null {
	if (env.PI_HARNESS_BOUNDARY !== "1") return null;
	const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === "string");
	let allowed: unknown;
	try {
		allowed = JSON.parse(env.PI_HARNESS_ALLOWED ?? "");
	} catch {
		throw new Error("PI_HARNESS_ALLOWED を読めない (サンドボックスの許可の一覧が渡されていない)");
	}
	const a = allowed as { read?: unknown; write?: unknown };
	if (!strings(a?.read) || !strings(a?.write)) {
		throw new Error("PI_HARNESS_ALLOWED が { read, write } (文字列の配列) ではない");
	}
	return {
		spec: { read: env.PI_HARNESS_CANARY_READ ?? "", write: env.PI_HARNESS_CANARY_WRITE ?? "" },
		allowed: { read: a.read, write: a.write },
	};
}

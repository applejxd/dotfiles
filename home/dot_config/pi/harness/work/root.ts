// 作業台帳の置き場を決める純関数。実際に書けるかの判定 (canWrite) は呼び出し側が注入する (副作用を持たない)。
// 既定は `<git-common-dir>/pi-work`。書けなければ `<cwd>/.tmp/work` へ退避する (pis のサンドボックスの書き込み許可が未確認のため)。
// see docs/spec/work/store.md
import { join } from "node:path";

export type StoreRootSource = "git-common-dir" | "cwd-tmp";

export interface StoreRoot {
	root: string;
	source: StoreRootSource;
	/** 選んだ置き場が書けると判定されたか (退避先も書けないときは false。呼び出し側が読み取り専用で開く) */
	writable: boolean;
}

export interface ResolveStoreRootInput {
	gitCommonDir?: string;
	cwd: string;
	/** そのパス (まだ無いこともある) の下に書けるか */
	canWrite: (path: string) => boolean;
}

export function resolveStoreRoot(input: ResolveStoreRootInput): StoreRoot {
	const fallback = join(input.cwd, ".tmp", "work");
	if (input.gitCommonDir) {
		const primary = join(input.gitCommonDir, "pi-work");
		if (input.canWrite(primary)) return { root: primary, source: "git-common-dir", writable: true };
	}
	return { root: fallback, source: "cwd-tmp", writable: input.canWrite(fallback) };
}

// Windows ネイティブの pi への対応のうち、OS で分かれる判断。platform・env・存在確認を引数で受ける純粋関数にして、
// Linux 上の試験で win32 を模擬する。see docs/spec/guard/pi-guard.md#windows
import { homedir } from "node:os";
import { posix, win32 } from "node:path";

export function isWindows(platform: string = process.platform): boolean {
	return platform === "win32";
}

/** guarded_task・隔離 (worktree)・起動時の照合を使えるか。プロセスグループ・Landlock・固定の git パスに依存するので、Windows では使わない。 */
export function supportsChildTasks(platform: string = process.platform): boolean {
	return !isWindows(platform);
}

export const ISOLATION_UNSUPPORTED = "Windows では隔離 (isolation) を使えない";

// Windows の環境変数名は大小文字を区別しない
function envGet(env: Record<string, string | undefined>, name: string): string | undefined {
	const want = name.toLowerCase();
	for (const [k, v] of Object.entries(env)) if (k.toLowerCase() === want && v) return v;
	return undefined;
}

// WSL のランチャー (System32 の bash.exe) は別の環境で動くので選ばない
const isWslLauncher = (p: string): boolean => /[\\/]system32[\\/]bash\.exe$/i.test(p) || /[\\/]sysnative[\\/]bash\.exe$/i.test(p);

/**
 * post_edit の hook を走らせる bash。非 Windows は PATH 上の `bash`。
 * Windows は Git for Windows の bash.exe を、標準の場所 → PATH 上の git.exe からの相対、の順で探す。見つからなければ null。
 */
export function findBash(
	platform: string = process.platform,
	env: Record<string, string | undefined> = process.env,
	exists: (p: string) => boolean = () => false,
): string | null {
	if (!isWindows(platform)) return "bash";
	const candidates: string[] = [];
	for (const name of ["ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"]) {
		const base = envGet(env, name);
		if (base) candidates.push(win32.join(base, "Git", "bin", "bash.exe"));
	}
	const local = envGet(env, "LOCALAPPDATA");
	if (local) candidates.push(win32.join(local, "Programs", "Git", "bin", "bash.exe"));
	for (const dir of (envGet(env, "PATH") ?? "").split(";")) {
		if (!dir) continue;
		if (exists(win32.join(dir, "git.exe"))) {
			// Git\cmd\git.exe と Git\mingw64\bin\git.exe のどちらからも Git\bin\bash.exe へ届く
			candidates.push(win32.resolve(dir, "..", "bin", "bash.exe"), win32.resolve(dir, "..", "..", "bin", "bash.exe"));
		}
	}
	return candidates.find((c) => !isWslLauncher(c) && exists(c)) ?? null;
}

export const NO_BASH_NOTICE = "Git Bash が見つからないので、編集後の整形 (post_edit) を省略する。Git for Windows を入れると有効になる";

/** `~` / `~/` / `~\` を home へ展開する。それ以外はそのまま。 */
export function expandTilde(p: string, home: string = homedir()): string {
	if (p === "~") return home;
	if (p.startsWith("~/") || p.startsWith("~\\")) return (home.includes("\\") ? win32 : posix).join(home, p.slice(2));
	return p;
}

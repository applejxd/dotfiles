// Windows (Git Bash) のパス形式でも、ホーム固定の deny とホーム全削除が判定されること。
// platform を引数で差し替えて、Linux 上で win32 を模擬する。失敗は stderr に出して exit 1。
// see docs/spec/guard/pi-decide.md#ts-版への移植
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const JUDGE = resolve(ROOT, "home", "dot_config", "pi", "harness", "judge");
const load = (name) => import(pathToFileURL(resolve(JUDGE, name)).href);
const { matchesAnyGlob, matchesReadDeny } = await load("policy.ts");
const { normalizeForCompare } = await load("pathutil.ts");
const { isHomeDirTarget } = await load("rm.ts");

const HOME = "C:\\Users\\x";
const failures = [];
let count = 0;
const check = (label, got, want) => {
	count++;
	if (got !== want) failures.push(`${label}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
};

const settings = "~/.pi/agent/settings.json";
const globs = [settings, "~/.pi/agent/extensions/**", "**/.ssh/**"];
const forms = (rest) => [
	`/c/Users/x/${rest}`,
	`/C/Users/X/${rest}`,
	`/cygdrive/c/Users/x/${rest}`,
	`/mnt/c/Users/x/${rest}`,
	`C:\\Users\\x\\${rest.replaceAll("/", "\\")}`,
	`C:/Users/x/${rest}`,
	`c:/users/x/${rest}`,
	`~/${rest}`,
	`$HOME/${rest}`,
	`\${HOME}/${rest}`,
];
for (const p of forms(".pi/agent/settings.json")) {
	check(`write ${p}`, matchesAnyGlob(p, globs, "win32", HOME), settings);
	check(`read ${p}`, matchesReadDeny(p, globs, [], "win32", HOME), settings);
}
for (const p of forms(".pi/agent/extensions/a/b.ts")) {
	check(`ext ${p}`, matchesAnyGlob(p, globs, "win32", HOME), "~/.pi/agent/extensions/**");
}
// 偽陽性: 別のユーザー・別のドライブ・別の場所
for (const p of [
	"/c/Users/other/.pi/agent/settings.json",
	"C:\\Users\\other\\.pi\\agent\\settings.json",
	"/d/Users/x/.pi/agent/settings.json",
	"D:\\Users\\x\\.pi\\agent\\settings.json",
	"/cygdrive/d/Users/x/.pi/agent/settings.json",
	"/c/Users/x2/.pi/agent/settings.json",
	"/c/Users/x/proj/.pi/agent/settings.json",
]) {
	check(`no-match ${p}`, matchesAnyGlob(p, globs, "win32", HOME), null);
}
// `**/` 始まりは形式に依らず当たる
check("ssh msys", matchesAnyGlob("/c/Users/x/.ssh/id", globs, "win32", HOME), "**/.ssh/**");

// 非 win32 は従来どおり (MSYS 形式はホームに結び付かない)
check("linux msys", matchesAnyGlob("/c/Users/x/.pi/agent/settings.json", globs, "linux", "/home/x"), null);
check("linux home", matchesAnyGlob("/home/x/.pi/agent/settings.json", globs, "linux", "/home/x"), settings);
check("linux home other", matchesAnyGlob("/home/y/.pi/agent/settings.json", globs, "linux", "/home/x"), null);
check("linux backslash (従来どおり区切りは寄せる)", matchesAnyGlob("C:\\Users\\x\\.pi\\agent\\settings.json", globs, "linux", "C:\\Users\\x"), settings);
check("normalize linux", normalizeForCompare("/c/Users/X\\y", "linux"), "/c/Users/X\\y");
check("normalize win", normalizeForCompare("/c/Users/X\\y", "win32"), "c:/users/x/y");
check("normalize cygdrive", normalizeForCompare("/cygdrive/c", "win32"), "c:");
check("normalize wsl mount", normalizeForCompare("/mnt/c/Users/X", "win32"), "c:/users/x");
check("normalize non-drive mnt", normalizeForCompare("/mnt/cc/Users", "win32"), "/mnt/cc/users");
check("linux keeps mnt", normalizeForCompare("/mnt/c/Users", "linux"), "/mnt/c/Users");
check("normalize non-drive", normalizeForCompare("/cc/Users", "win32"), "/cc/users");

// rm: ホーム全削除
for (const t of ["C:\\Users\\x", "C:/Users/x", "/c/Users/x", "/cygdrive/c/Users/x", "c:\\users\\X\\", "C:\\Users\\x\\*", "/c/Users/x/*"]) {
	check(`rm ${t}`, isHomeDirTarget(t, "win32", HOME), true);
}
for (const t of ["C:\\Users\\x\\proj", "/c/Users/x/proj", "C:\\Users", "/c/Users", "/c/Windows", "D:\\data"]) {
	check(`rm no ${t}`, isHomeDirTarget(t, "win32", HOME), false);
}
check("rm linux home", isHomeDirTarget("/home/x", "linux", "/home/x"), true);
check("rm linux msys", isHomeDirTarget("/c/Users/x", "linux", "/home/x"), false);
check("rm linux winpath", isHomeDirTarget("C:\\Users\\x", "linux", "/home/x"), false);

if (failures.length) {
	console.error(failures.join("\n"));
	process.exit(1);
}
console.log(`windows paths: ${count} checks ok`);

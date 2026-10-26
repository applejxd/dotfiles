// フルガードの判定の外で動きうるものを、素の pi (pis を経由しない起動) の起動時に知らせる。
// 止めはしない (警告だけ)。pis は --no-approve で作業先の .pi/ を読まず、mcp.json のサーバがあれば起動しない。
// see docs/spec/guard/pi-guard.md#判定の外で動くもの
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

function hasServers(path: string): boolean {
	if (!existsSync(path)) return false;
	try {
		const servers = JSON.parse(readFileSync(path, "utf-8"))?.mcpServers;
		return !!servers && typeof servers === "object" && Object.keys(servers).length > 0;
	} catch {
		return true; // 読めないものは、無いと言い切れない
	}
}

function hasEntries(dir: string): boolean {
	try {
		return readdirSync(dir).length > 0;
	} catch {
		return false;
	}
}

function hasResourceKeys(path: string): boolean {
	if (!existsSync(path)) return false;
	try {
		const settings = JSON.parse(readFileSync(path, "utf-8"));
		return ["extensions", "packages", "defaultTools"].some((key) => key in (settings ?? {}));
	} catch {
		return true;
	}
}

/** 判定の外で動きうるものの一覧 (無ければ空)。スキルは対象にしない (作業先のスキルは指示を読むだけ)。 */
export function unguardedSources(agentDir: string, cwd: string, argv: string[]): string[] {
	const found: string[] = [];
	if (hasServers(join(agentDir, "mcp.json"))) {
		found.push(`${join(agentDir, "mcp.json")} のサーバ (MCP の接続はフルガードの管理の外)`);
	}
	const declined = argv.includes("--no-approve") || argv.includes("-na");
	if (!declined) {
		const project = join(cwd, ".pi");
		if (hasEntries(join(project, "extensions"))) found.push(`${join(project, "extensions")} の拡張 (信頼すると読み込み時のコードが判定の外で動く)`);
		if (hasServers(join(project, "mcp.json"))) found.push(`${join(project, "mcp.json")} のサーバ`);
		if (hasResourceKeys(join(project, "settings.json"))) found.push(`${join(project, "settings.json")} の拡張・パッケージ・ツールの設定 (信頼すると反映される)`);
	}
	return found;
}

export function unguardedMessage(found: string[]): string {
	return `フルガードの判定の外で動きうるものがあります:\n- ${found.join("\n- ")}\n(作業先の信頼を拒否すれば、作業先の分は読まれません。pis は常に拒否します)`;
}

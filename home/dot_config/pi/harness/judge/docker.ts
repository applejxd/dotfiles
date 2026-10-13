// docker のホスト側への影響を判定する (bashrules/docker.py の移植)。権限昇格・ホストマウント。
//
// node の型除去でそのまま動く書き方だけを使う。
// see docs/spec/pi-decide.md#ts-版への移植
import type { Ctx } from "./context.ts";
import { tableList, tableSet } from "./context.ts";
import { ShlexError, shlexSplit, split, strip, stripChars } from "./pystr.ts";
import { baseName, canonicalRmTarget, clip200, segments } from "./shared.ts";

/** `-v src:dst` / `--mount type=bind,source=src,...` の src を返す。 */
function dockerMountSource(token: string): string | null {
	if (token.includes("=") && (token.includes("source=") || token.includes("src=") || token.startsWith("type="))) {
		for (const part of token.split(",")) {
			const eq = part.indexOf("=");
			const key = eq === -1 ? part : part.slice(0, eq);
			const value = eq === -1 ? "" : part.slice(eq + 1);
			if (strip(key) === "source" || strip(key) === "src") return strip(value);
		}
		return null;
	}
	const source = token.split(":")[0];
	return source || null;
}

/** `docker run` / `docker container create` の引数列を返す。該当しなければ null。 */
function dockerRunTokens(ctx: Ctx, segment: string): string[] | null {
	let tokens: string[];
	try {
		tokens = shlexSplit(segment);
	} catch (e) {
		if (!(e instanceof ShlexError)) throw e;
		tokens = split(segment);
	}
	if (tokens.length === 0 || baseName(stripChars(tokens[0], "'\"")) !== "docker") return null;
	const subcommands = tokens.slice(1).filter((t) => !t.startsWith("-"));
	const runSubcommands = tableSet(ctx, "docker", "docker_run_subcommands");
	if (!subcommands.slice(0, 2).some((s) => runSubcommands.has(s))) return null;
	return tokens.slice(1).map((t) => stripChars(t, "'\""));
}

/** `--net=host` と `--net host` の両方から (キー, 値) を取り出す。 */
function dockerOptValue(rest: readonly string[], index: number): [string, string] {
	const eq = rest[index].indexOf("=");
	if (eq !== -1) return [rest[index].slice(0, eq), rest[index].slice(eq + 1)];
	const following = index + 1 < rest.length ? rest[index + 1] : "";
	return [rest[index], following.startsWith("-") ? "" : following];
}

/** `docker run` でホストの root 相当を得られる形を検出する (--privileged・ホストのルート/etc・docker socket のマウント)。 */
export function checkDockerHostEscape(ctx: Ctx, cmd: string): string | null {
	const privileged = tableSet(ctx, "docker", "docker_privileged_flags");
	const mountFlags = tableSet(ctx, "docker", "docker_mount_flags");
	const fatalMounts = tableList(ctx, "docker", "docker_fatal_mounts");
	const capDangerous = tableSet(ctx, "docker", "docker_cap_dangerous");
	const homeTokens = tableSet(ctx, "_shared", "home_tokens");
	for (const segment of segments(ctx, cmd)) {
		const rest = dockerRunTokens(ctx, segment);
		if (rest === null) continue;
		for (let index = 0; index < rest.length; index++) {
			const token = rest[index];
			if (privileged.has(token)) {
				return `\`docker ${token}\` はコンテナに全権限を与える操作です。\nコンテナ経由の権限昇格に繋がるため許可されていません。`;
			}
			const [key, value] = dockerOptValue(rest, index);
			if (key === "--cap-add" && capDangerous.has(value.toUpperCase())) {
				return `\`docker --cap-add ${value}\` は特権相当の capability です。\nコンテナ経由の権限昇格に繋がるため許可されていません。`;
			}
			if (mountFlags.has(token) || mountFlags.has(key)) {
				let mount = mountFlags.has(key) ? value : "";
				if (!mount && mountFlags.has(token)) mount = index + 1 < rest.length ? rest[index + 1] : "";
				const source = mount ? dockerMountSource(mount) : null;
				const canonical = source ? canonicalRmTarget(source) : null;
				if (canonical === null) continue;
				if (fatalMounts.includes(canonical) || homeTokens.has(canonical)) {
					return (
						`\`docker\` がホストの \`${source}\` をコンテナへマウントしようとしています。\n` +
						"ホストのファイルを直接書き換えられるため許可されていません。"
					);
				}
			}
		}
	}
	return null;
}

/** `docker run --network host` のように分離を弱める形を検出する (ask)。 */
export function checkDockerIsolation(ctx: Ctx, cmd: string): string | null {
	const namespaceOpts = tableSet(ctx, "docker", "docker_namespace_opts");
	for (const segment of segments(ctx, cmd)) {
		const rest = dockerRunTokens(ctx, segment);
		if (rest === null) continue;
		for (let index = 0; index < rest.length; index++) {
			const [key, value] = dockerOptValue(rest, index);
			if (namespaceOpts.has(key) && value === "host") {
				return (
					`\`docker ${key} host\` はホストの名前空間をコンテナと共有します。\n` +
					`実行しようとしているコマンド: ${clip200(segment)}\n` +
					"分離が弱まるため、内容を確認して問題なければ承認してください。"
				);
			}
		}
	}
	return null;
}

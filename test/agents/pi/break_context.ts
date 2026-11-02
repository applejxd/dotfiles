// 試験専用。ハーネスより先に読み込み、before_agent_start の event.systemPromptOptions.contextFiles を契約外の形に壊す (CHG-0059 S4b)。
// BREAK_CONTEXT: not_array / null_item / path_num / content_num / throw_getter
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
	pi.on("before_agent_start", async (event: any) => {
		const mode = process.env.BREAK_CONTEXT;
		const options = event.systemPromptOptions;
		if (!mode || !options) return;
		const files: any[] = Array.isArray(options.contextFiles) ? options.contextFiles : [];
		if (mode === "not_array") options.contextFiles = "oops";
		else if (mode === "null_item") options.contextFiles = [null, ...files];
		else if (mode === "path_num") options.contextFiles = [{ path: 5, content: "x" }, ...files];
		else if (mode === "content_num") options.contextFiles = [{ path: "/x/AGENTS.md", content: 5 }, ...files];
		else if (mode === "throw_getter")
			options.contextFiles = [
				{
					path: "/x/AGENTS.md",
					get content() {
						throw new Error("getter boom");
					},
				},
			];
	});
}

// 試験用。自作の拡張 (~/.pi/agent/extensions/<名前>/index.ts) の代役。読み込めたら own_probe ツールが出る。
import { Type } from "@earendil-works/pi-ai";
import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
	pi.registerTool(
		defineTool({
			name: "own_probe",
			label: "own_probe",
			description: "試験用",
			parameters: Type.Object({}),
			async execute() {
				return { content: [{ type: "text", text: "own" }], details: undefined };
			},
		}),
	);
}

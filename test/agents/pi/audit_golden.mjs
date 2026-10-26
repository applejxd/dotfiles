// 子の完了結果の形式検査 (audit.ts) の表試験。結果を JSON で標準出力へ出す (照合は test_pi_audit.py)。
//
//   node test/agents/pi/audit_golden.mjs
//
// see docs/spec/guard/pi-subagents.md#子エージェント
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const { auditFormat, summarizeCalls } = await import(
	pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "audit.ts")).href
);

const full = "## 結論\nok\n## 根拠\na\n## 未確認\nb\n## 次の候補\nc";
const audit = {
	standard_headings: auditFormat(full),
	bold_with_colon: auditFormat("**結論**: x\n**根拠**: y\n**未確認**: z\n**次の候補**: w"),
	bold_alone_lines: auditFormat("**結論**\nx\n**根拠**\ny\n**未確認**\nz\n**次の候補**\nw"),
	parens_fullwidth: auditFormat("**結論**\nx\n**根拠（パスと行）**\ny\n**未確認**\nz\n**次の候補**\nw"),
	parens_ascii: auditFormat("結論:\nx\n**根拠(変えたファイル)**\ny\n未確認:\nz\n次の候補:\nw"),
	review_style: auditFormat("結論\nx\n根拠・指摘\ny\n未確認\nz\n次の一手\nw"),
	quoted_bullets: auditFormat("> - 結論 x\n> - 根拠 y\n> _未確認_\n> 次の候補"),
	two_only: auditFormat("## 結論\nx\n## 根拠\ny"),
	mention_not_heading: auditFormat("本文で結論と根拠に触れるだけ"),
	empty: auditFormat(""),
};
const summary = {
	none: summarizeCalls([]),
	strip_and_order: summarizeCalls(["guarded_bash", "guarded_read", "guarded_read"]),
	tie_by_name: summarizeCalls(["write", "bash", "read", "bash", "read"]),
	mixed_prefix: summarizeCalls(["guarded_read", "read", "grep"]),
};
console.log(JSON.stringify({ audit, summary }));

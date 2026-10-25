// ask/normalize.ts の表試験。結果を JSON で標準出力へ出す (照合は test_pi_ask_normalize.py)。
//
//   node test/agents/pi/ask_normalize_driver.mjs
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const { normalizeAskArgs } = await import(pathToFileURL(resolve(ROOT, "home", "dot_pi", "agent", "extensions", "ask", "normalize.ts")).href);

const opts = [
	{ label: "A (推奨)", description: "da" },
	{ label: "B", description: "db" },
];
const good = { questions: [{ question: "Q?", options: opts }] };
const run = (input) => ({ input, same: normalizeAskArgs(input) === input, output: normalizeAskArgs(input) });

const out = {};
out.good = run(good);
out.top_level = run({ question: "Q?", header: "H", options: opts, multi: true });
out.top_question = run({ question: "Q?", questions: [{ options: opts }] });
out.top_question_two = run({ question: "Q?", questions: [{ question: "Keep", options: opts }, { options: opts }] });
out.header_only = run({ questions: [{ header: "H", options: opts }] });
out.string_options = run({ questions: [{ question: "Q?", options: ["A (推奨)", "B"] }] });
out.json_string = run({ questions: JSON.stringify(good.questions) });
out.bad_json_string = run({ questions: '[{"question": "Q?"' });
out.multi_string = run({ questions: [{ question: "Q?", options: opts, multi: "true" }, { question: "R?", options: opts, multi: "false" }] });
out.no_description = run({ questions: [{ question: "Q?", options: [{ label: "A (推奨)" }, { label: "B", description: "db" }] }] });
out.no_recommended = run({ questions: [{ question: "Q?", options: [{ label: "A", description: "a" }, { label: "B", description: "b" }] }] });
out.unknown_key = run({ extra: 1, questions: [{ question: "Q?", options: opts, foo: "bar" }] });
out.not_object = run("text");
out.null_input = run(null);
out.nothing = run({});
out.top_without_options = run({ question: "Q?" });
console.log(JSON.stringify(out));

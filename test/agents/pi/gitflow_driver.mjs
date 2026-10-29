// gitflow.ts の表試験 (CHG-0047)。結果を JSON で標準出力へ出す (照合は test_pi_gitflow.py)。
//
//   node test/agents/pi/gitflow_driver.mjs
//
// see docs/change/0047-gitflow.md
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const mod = await import(pathToFileURL(join(ROOT, "home", "dot_config", "pi", "harness", "gitflow.ts")).href);
const { validateFeatureName, parseConfigLines, checkSafeProfile, startArgv, finishArgv, identifyModel } = mod;

const REPO = "/home/u/repo";
const GOOD = `gitflow.version 1.0
gitflow.initialized true
gitflow.worktreepath .tmp/worktrees/{{ branchName }}
gitflow.branch.main.type base
gitflow.branch.main.upstreamstrategy none
gitflow.branch.main.downstreamstrategy none
gitflow.branch.main.autoupdate false
gitflow.branch.main.tag false
gitflow.branch.develop.type base
gitflow.branch.develop.parent main
gitflow.branch.develop.upstreamstrategy merge
gitflow.branch.develop.downstreamstrategy merge
gitflow.branch.develop.autoupdate true
gitflow.branch.develop.tag false
gitflow.branch.feature.type topic
gitflow.branch.feature.parent develop
gitflow.branch.feature.startpoint develop
gitflow.branch.feature.upstreamstrategy squash
gitflow.branch.feature.downstreamstrategy rebase
gitflow.branch.feature.prefix feature/
gitflow.branch.feature.autoupdate false
gitflow.branch.feature.tag false
gitflow.branch.feature.worktree false`;

function profile(text) {
	const p = checkSafeProfile(parseConfigLines(text), REPO);
	return { ok: p.ok, problems: p.problems };
}
function change(text, from, to) {
	if (!text.includes(from)) throw new Error(`no ${from}`);
	return text.replace(from, to);
}

const out = {};
out.names = Object.fromEntries(
	[
		["ok", "alpha"],
		["dots", "a1.b_c-d"],
		["empty", ""],
		["dash_first", "-x"],
		["help", "--help"],
		["upper", "Alpha"],
		["dotdot", "a..b"],
		["trailing_dot", "a."],
		["lock", "a.lock"],
		["slash", "a/b"],
		["long", "x".repeat(65)],
		["max", "x".repeat(64)],
		["space", "a b"],
	].map(([k, v]) => [k, validateFeatureName(v) === null]),
);
out.names.notString = validateFeatureName(5) === null;

out.good = profile(GOOD);
out.runtimeKeys = profile(`${GOOD}\ngitflow.branch.feature/fx.base develop\ngitflow.worktree.feature/fx.managed true`);
out.pushTrue = profile(`${GOOD}\ngitflow.feature.finish.push true`);
out.pushFalse = profile(`${GOOD}\ngitflow.feature.finish.push false`);
out.pushtagTrue = profile(`${GOOD}\ngitflow.feature.finish.pushtag true`);
out.hooks = profile(`${GOOD}\ngitflow.path.hooks /tmp/evil`);
out.filter = profile(`${GOOD}\ngitflow.feature.finish.filter /tmp/evil`);
out.origin = profile(`${GOOD}\ngitflow.origin evil`);
out.originOk = profile(`${GOOD}\ngitflow.origin origin`);
out.unknown = profile(`${GOOD}\ngitflow.something.else 1`);
out.badParent = profile(change(GOOD, "gitflow.branch.feature.parent develop", "gitflow.branch.feature.parent main"));
out.badPrefix = profile(change(GOOD, "gitflow.branch.feature.prefix feature/", "gitflow.branch.feature.prefix "));
out.badStrategy = profile(change(GOOD, "upstreamstrategy squash", "upstreamstrategy merge"));
out.notInit = profile(change(GOOD, "gitflow.initialized true", "gitflow.initialized false"));
out.tagTrue = profile(change(GOOD, "gitflow.branch.feature.tag false", "gitflow.branch.feature.tag true"));
out.wtOutside = profile(change(GOOD, ".tmp/worktrees/{{ branchName }}", "/tmp/elsewhere/{{ branchName }}"));
out.wtDotdot = profile(change(GOOD, ".tmp/worktrees/{{ branchName }}", ".tmp/worktrees/../../x"));
out.wtSibling = profile(change(GOOD, ".tmp/worktrees/{{ branchName }}", "../{{ repo }}-wt/{{ branchName }}"));
out.wtAbsInside = profile(change(GOOD, ".tmp/worktrees/{{ branchName }}", `${REPO}/.tmp/worktrees/{{ branchName }}`));
out.wtMissing = profile(change(GOOD, "gitflow.worktreepath .tmp/worktrees/{{ branchName }}\n", ""));
// classic の既定のまま (bugfix・hotfix などが残る) は、許可リスト外
out.classicLeftovers = profile(`${GOOD}\ngitflow.branch.hotfix.type topic\ngitflow.branch.hotfix.parent main`);
out.laterWins = profile(`${GOOD}\ngitflow.branch.feature.parent main\ngitflow.branch.feature.parent develop`);

// identifyModel (CHG-0049): このリポジトリの .gitflow の最小の設定を基準に、1 点ずつ崩す
const LITE = `gitflow.version 1.0
gitflow.initialized true
gitflow.branch.develop.type base
gitflow.branch.develop.parent main
gitflow.branch.feature.type topic
gitflow.branch.feature.parent develop
gitflow.branch.feature.startpoint develop
gitflow.branch.feature.upstreamstrategy squash
gitflow.branch.feature.prefix feature/
gitflow.branch.main.type base`;
const model = (text) => identifyModel(parseConfigLines(text));
const drop = (prefix) =>
	LITE.split("\n")
		.filter((l) => !l.startsWith(prefix))
		.join("\n");
out.model = {
	lite: model(LITE),
	liteGood: model(GOOD),
	empty: model(""),
	notInit: model(drop("gitflow.initialized")),
	initFalse: model(change(LITE, "gitflow.initialized true", "gitflow.initialized false")),
	mergeStrategy: model(change(LITE, "upstreamstrategy squash", "upstreamstrategy merge")),
	badPrefix: model(change(LITE, "prefix feature/", "prefix feat/")),
	developParent: model(change(LITE, "develop.parent main", "develop.parent trunk")),
	noMain: model(drop("gitflow.branch.main.")),
	noDevelop: model(drop("gitflow.branch.develop.")),
	noFeature: model(drop("gitflow.branch.feature.")),
	fourth: model(`${LITE}\ngitflow.branch.release.type topic`),
};

out.start = startArgv("alpha");
out.finish = finishArgv("alpha", "-weird: msg\n\n- bullet");
console.log(JSON.stringify(out));

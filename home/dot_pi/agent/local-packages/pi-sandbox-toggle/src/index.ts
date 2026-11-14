/**
 * pi-sandbox-toggle: コマンド実行の囲い (pib) を、セッションの途中で切り替える `/sandbox`。
 * このリポジトリだけが配る自作 (撤去の条件は docs/adr/0040-pi-sandbox-session-toggle.md)。
 *
 * pi は、コマンドを起動するたびに pi プロセスの環境変数を読む。pib-shell は PIB_SANDBOX が立っているときだけ囲う。
 * この拡張は、pi プロセスの PIB_SANDBOX を書き換えるだけで、囲い自体は pib-shell・pi-sandbox-runner が担う。
 * YOLO (pi-permission-system の ask の自動承認) も囲いに合わせる: 囲いあり = on、囲いなし = off。
 * YOLO は permission-system の設定ファイル (yoloMode) にあり、permission-system は毎ターンの開始時に読み直す。
 * 切り替えは、利用者が打った `/sandbox` だけ。モデルが呼べる道具は登録しない。
 * see docs/spec/sandbox/pi-sandbox-runner.md#実行中の切り替え
 */
import { existsSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { isAbsolute, join, normalize } from "node:path";
import {
  createLocalBashOperations,
  type ExtensionAPI,
  type ExtensionCommandContext,
  type ExtensionContext,
  getAgentDir,
} from "@earendil-works/pi-coding-agent";

type Mode = "off" | "on" | "offline";

const SANDBOX_ENV = "PIB_SANDBOX";
// pib だけが立てる変数 (囲いの外の pi に渡る)。pib で起動したかの印
const PIB_MARK_ENV = "PIB_ORIG_PATH";
const STATUS_KEY = "sandbox";
// 囲いの内側だけで、runner が MISE_STATE_DIR をこの値にする。囲いが実際に効いているかの試し実行の印
const INSIDE_STATE_DIR = "/tmp/pib-mise-state";
const PROBE_MARK = "PIB-PROBE:";
const PROBE_COMMAND = "printf 'PIB-PROBE:%s\\n' \"${MISE_STATE_DIR-}\"";
const PROBE_TIMEOUT_SECONDS = 15;
const ARGUMENTS = ["on", "offline", "off", "status"];
const USAGE = "/sandbox [on|offline|off|status]（引数なしは on と off の切り替え）";

function currentMode(): Mode {
  const value = process.env[SANDBOX_ENV];
  if (value === "offline") return "offline";
  return value ? "on" : "off";
}

function applyMode(mode: Mode): void {
  if (mode === "off") delete process.env[SANDBOX_ENV];
  else process.env[SANDBOX_ENV] = mode === "offline" ? "offline" : "1";
}

function label(mode: Mode): string {
  return mode === "off" ? "sandbox: off" : mode === "offline" ? "sandbox: offline" : "sandbox: on";
}

// pib が受け付けるのは、配備した pib-shell の絶対パスそのもの (~/ の略記は可)。HOME は食い違いようのない表記だけ
function expectedShellPath(): string | undefined {
  const home = process.env.HOME;
  if (!home || !isAbsolute(home) || normalize(home) !== home || (home.length > 1 && home.endsWith("/"))) {
    return undefined;
  }
  return `${home}/.local/bin/pib-shell`;
}

function shellPathProblem(pi: ExtensionAPI): string | undefined {
  const want = expectedShellPath();
  if (!want) return "HOME が正規の絶対パスではないため、pib-shell の場所を決められない";
  const got = pi.getSettings().shellPath;
  if (got !== want && got !== "~/.local/bin/pib-shell") {
    return `settings.json の shellPath が pib-shell (${want}) ではない（現在: ${got ?? "未設定"}）`;
  }
  return undefined;
}

function permissionConfigPath(): string {
  return join(getAgentDir(), "extensions", "pi-permission-system", "config.json");
}

// YOLO は ask を自動承認する。囲いの外で動くファイルの道具 (write・edit) が、囲いの設定・pib-shell・権限の設定・この拡張を書き換えられないよう、
// これらへの書き込みが、permission-system が実際に使う方針 (global・信頼済みプロジェクト・agent を重ねたもの) で deny になっているときだけ、
// YOLO を入れる。規則の評価を再現せず、permission-system の公開の判定 API (checkPermission。write・edit のゲートと同じ判定) に問う
const PROTECTED_PATHS = [
  "~/.local/bin/pi-sandbox-runner",
  "~/.local/bin/pib-shell",
  "~/.local/bin/pib",
  "~/.config/pi-sandbox/runner.toml",
  "~/.config/pi-sandbox/runner.local.toml", // runner が、コマンドごとに読む
  "~/.pi/agent/settings.json",
  "~/.pi/agent/local-packages/pi-sandbox-toggle/src/index.ts",
  "~/.pi/agent/local-packages/pi-sandbox-toggle/package.json", // pi.extensions の向き先
  "~/.pi/agent/extensions/pi-permission-system/config.json",
];
// permission-system が、ノードの session id をキーに公開するサービスの置き場 (Symbol.for。jiti の分離を越える。上流の文書 cross-extension-api)
const SERVICES_KEY = Symbol.for("@gotgenes/pi-permission-system:session-services");

type PermissionQuery = { checkPermission(surface: string, value?: string): { state?: unknown; matchedPattern?: unknown } };

function permissionService(ctx: ExtensionContext): PermissionQuery | undefined {
  const services = (globalThis as unknown as Record<symbol, unknown>)[SERVICES_KEY];
  let sessionId: string | undefined;
  try {
    sessionId = ctx.sessionManager.getSessionId() || undefined;
  } catch {
    sessionId = undefined;
  }
  return services instanceof Map && sessionId ? (services.get(sessionId) as PermissionQuery | undefined) : undefined;
}

// 保護が効いていると確かめられないときの説明 (無ければ undefined)。サービスが未公開 (読み込み順) のときは、unpublished を立てる
function protectionProblem(ctx: ExtensionContext): { message: string; unpublished: boolean } | undefined {
  const service = permissionService(ctx);
  if (!service) {
    return { message: "permission-system の判定 API (checkPermission) がまだ見つからず、保護が効いていると確かめられない", unpublished: true };
  }
  const home = process.env.HOME ?? "";
  const weak: string[] = [];
  for (const path of PROTECTED_PATHS) {
    let denied = false;
    try {
      const result = service.checkPermission("path_write", path.replace(/^~/, home));
      // 明示の規則が一致した deny だけ。規則が無く、既定の deny (permission["*"]) が答えたものは、write・edit の path ゲートが何もせず通す
      // (上流 describePathGate: matchedPattern が無ければスキップ)
      denied = result?.state === "deny" && result.matchedPattern !== undefined;
    } catch {
      denied = false;
    }
    if (!denied) weak.push(path);
  }
  if (weak.length === 0) return undefined;
  return {
    message: `囲いと権限の設定を守る path_write の deny が、実効の方針で効いていない (${weak.join("・")})。deny の無い YOLO は入れない`,
    unpublished: false,
  };
}

type YoloResult = { ok: true; changed: boolean; was: boolean | undefined } | { ok: false; error: string };

// permission-system の設定ファイルの yoloMode だけを書き換える (他の項目は保つ。壊れていれば触らない)。
// YOLO だけのファイルは作らない (設定ファイルが無ければ、入れない)
function setYolo(on: boolean): YoloResult {
  const path = permissionConfigPath();
  try {
    if (!existsSync(path)) {
      // 設定ファイルが無ければ、YOLO は拡張の既定の off。off にするのに、ファイルは作らない
      return on
        ? { ok: false, error: `${path} が無い (chezmoi apply で配ってから)` }
        : { ok: true, changed: false, was: false };
    }
    const parsed: unknown = JSON.parse(readFileSync(path, "utf8"));
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { ok: false, error: `${path} がオブジェクトではない` };
    }
    const data = parsed as Record<string, unknown>;
    const was = typeof data.yoloMode === "boolean" ? data.yoloMode : undefined;
    if (data.yoloMode === on) return { ok: true, changed: false, was };
    data.yoloMode = on; // 項目が無いときの off も、明示の false を書く (global より前に読まれる旧い設定の true に勝つ)
    const tmp = `${path}.${process.pid}.${Date.now()}.sandbox-toggle.tmp`;
    try {
      writeFileSync(tmp, `${JSON.stringify(data, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
      renameSync(tmp, path);
    } catch (error) {
      rmSync(tmp, { force: true });
      throw error;
    }
    return { ok: true, changed: true, was };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

function readYolo(): boolean | undefined {
  try {
    const parsed: unknown = JSON.parse(readFileSync(permissionConfigPath(), "utf8"));
    return typeof parsed === "object" && parsed !== null && (parsed as { yoloMode?: unknown }).yoloMode === true;
  } catch {
    return existsSync(permissionConfigPath()) ? undefined : false;
  }
}

// 信頼済みのプロジェクトの設定は、permission-system が global の後に重ねる (project の yoloMode: true が、global の false に勝つ)。
// 信頼していないプロジェクトは読まれない。旧い置き場 (.pi/agent/pi-permissions.jsonc) も同じ順序で重なる。
// 上流と同じ解釈 (コメントを除いて JSON として読み、yoloMode === true で判定) にする。文字列の検索では、キーの \u エスケープなどで抜ける
const PROJECT_CONFIG_FILES = [
  [".pi", "extensions", "pi-permission-system", "config.json"],
  [".pi", "agent", "pi-permissions.jsonc"],
];

// permission-system の stripJsonComments と同じ (コメントは文字列の外だけ。引用符は " と ')
function stripJsonComments(input: string): string {
  let out = "";
  let i = 0;
  while (i < input.length) {
    const char = input[i];
    const next = input[i + 1] ?? "";
    if (char === "/" && next === "/") {
      const newline = input.indexOf("\n", i);
      if (newline === -1) break;
      out += "\n";
      i = newline + 1;
    } else if (char === "/" && next === "*") {
      const close = input.indexOf("*/", i + 2);
      if (close === -1) break;
      i = close + 2;
    } else if (char === '"' || char === "'") {
      out += char;
      i++;
      let escaping = false;
      while (i < input.length) {
        const c = input[i];
        out += c;
        i++;
        if (escaping) escaping = false;
        else if (c === "\\") escaping = true;
        else if (c === char) break;
      }
    } else {
      out += char;
      i++;
    }
  }
  return out;
}

// 信頼済みのプロジェクトの設定 (置き場 2 か所) を、上流と同じ解釈で読む。信頼していなければ空。読めないものは error
function projectConfigs(ctx: ExtensionContext): { path: string; data?: Record<string, unknown>; error?: true }[] {
  const trusted = typeof ctx.isProjectTrusted === "function" ? ctx.isProjectTrusted() : true;
  if (!trusted) return [];
  const found: { path: string; data?: Record<string, unknown>; error?: true }[] = [];
  for (const parts of PROJECT_CONFIG_FILES) {
    const path = join(ctx.cwd, ...parts);
    if (!existsSync(path)) continue;
    try {
      const parsed: unknown = JSON.parse(stripJsonComments(readFileSync(path, "utf8")));
      found.push({ path, data: parsed !== null && typeof parsed === "object" ? (parsed as Record<string, unknown>) : {} });
    } catch {
      found.push({ path, error: true });
    }
  }
  return found;
}

// プロジェクトの設定が YOLO を on にしている、または読めず off と確かめられないときの説明 (無ければ undefined)
function projectYoloProblem(ctx: ExtensionContext): string | undefined {
  for (const { path, data, error } of projectConfigs(ctx)) {
    if (error) return `信頼済みプロジェクトの設定 (${path}) を読めず、yoloMode が off と確かめられない`;
    if (data?.yoloMode === true) return `信頼済みプロジェクトの設定 (${path}) が yoloMode を on にしている。プロジェクト側で直す`;
  }
  return undefined;
}

// YOLO を入れる。保護が実効の方針で効いていると、permission-system に確かめられたときだけ
function turnYoloOn(ctx: ExtensionContext): YoloResult & { unpublished?: boolean } {
  const problem = protectionProblem(ctx);
  if (problem) return { ok: false, error: problem.message, unpublished: problem.unpublished };
  return setYolo(true);
}

// YOLO を、囲いの状態に合わせて入れる。保護を確かめられなければ入れず、**残っている YOLO も切る**
// (前回の YOLO や手動の YOLO を、確かめられない保護のまま残さない)。切れなければ、その失敗も返す
type Aligned =
  | { on: true; yolo: Extract<YoloResult, { ok: true }> }
  | { on: false; yolo: Extract<YoloResult, { ok: false }> & { unpublished?: boolean }; off: YoloResult };

function alignYoloOn(ctx: ExtensionContext): Aligned {
  const yolo = turnYoloOn(ctx);
  if (yolo.ok) return { on: true, yolo };
  return { on: false, yolo, off: turnYoloOff(ctx) };
}

// 囲いなしにするときの YOLO の解除。global を false にし、プロジェクトの設定が on にしていれば (global では切れない) 失敗にする
function turnYoloOff(ctx: ExtensionContext): YoloResult {
  const problem = projectYoloProblem(ctx);
  if (problem) return { ok: false, error: problem };
  return setYolo(false);
}

function tail(text: string): string {
  const trimmed = text.trim();
  return trimmed.length > 300 ? `…${trimmed.slice(-300)}` : trimmed;
}

// pi の bash と同じ経路 (shellPath・起動時の環境変数) で、囲いの内側の印が見えるかを確かめる
async function probe(pi: ExtensionAPI, ctx: ExtensionContext): Promise<{ ok: boolean; detail: string }> {
  const chunks: Buffer[] = [];
  try {
    const ops = createLocalBashOperations({ shellPath: pi.getSettings().shellPath });
    const { exitCode } = await ops.exec(PROBE_COMMAND, ctx.cwd, {
      onData: (data: Buffer) => chunks.push(data),
      timeout: PROBE_TIMEOUT_SECONDS,
    });
    const out = Buffer.concat(chunks).toString("utf8");
    const inside = out.split("\n").some((line) => line.trim() === PROBE_MARK + INSIDE_STATE_DIR);
    if (exitCode === 0 && inside) return { ok: true, detail: "" };
    return { ok: false, detail: tail(out) || `終了コード ${exitCode}` };
  } catch (error) {
    return { ok: false, detail: error instanceof Error ? error.message : String(error) };
  }
}

// 切り替えの途中 (確認・idle 待ち・試し実行) に、別の /sandbox が割り込むと、off のあとに YOLO を入れる、などの食い違いが出る。
// 1 つずつにする (pi のプロセスで共有する)。/sandbox は、取れなければ断る。起動時の同期は、取れるまで待つ (捨てると、前回の YOLO が残る)
const LOCK = Symbol.for("pi-sandbox-toggle:lock");
type Lock = { busy: boolean; waiters: Array<() => void> };

function lockState(): Lock {
  const shared = globalThis as unknown as Record<symbol, Lock | undefined>;
  return (shared[LOCK] ??= { busy: false, waiters: [] });
}

function tryLock(): boolean {
  const lock = lockState();
  if (lock.busy) return false;
  lock.busy = true;
  return true;
}

async function lockWait(): Promise<void> {
  while (!tryLock()) await new Promise<void>((resolve) => lockState().waiters.push(resolve));
}

function unlock(): void {
  const lock = lockState();
  lock.busy = false;
  lock.waiters.shift()?.();
}

export default function (pi: ExtensionAPI): void {
  if (process.platform !== "linux") return; // 囲い (bwrap) は Linux 専用

  // 起動時に、囲いが効いていると確かめられなかったときの表示 (囲いを切り替えるまで残す)
  let unverified: string | undefined;

  const show = (ctx: ExtensionContext) => {
    if (ctx.hasUI) ctx.ui.setStatus(STATUS_KEY, unverified ? `${label(currentMode())}（${unverified}）` : label(currentMode()));
  };
  const say = (ctx: ExtensionContext, message: string, level: "info" | "warning" | "error" = "info") => {
    if (ctx.hasUI) ctx.ui.notify(message, level);
  };

  // pib と同じ検査 (shellPath・HOME) と、囲いの内側の印の試し実行
  async function verify(ctx: ExtensionContext): Promise<{ ok: boolean; detail: string }> {
    const problem = shellPathProblem(pi);
    if (problem) return { ok: false, detail: problem };
    return probe(pi, ctx);
  }

  async function enable(mode: "on" | "offline", ctx: ExtensionContext): Promise<void> {
    const problem = shellPathProblem(pi);
    if (problem) {
      say(ctx, `囲いを入れられない: ${problem}`, "error");
      return;
    }
    const before = currentMode();
    applyMode(mode);
    const result = await probe(pi, ctx);
    if (!result.ok) {
      applyMode(before); // 効いていない囲いを、効いているものとして残さない
      show(ctx);
      say(ctx, `囲いが効かないため、切り替えなかった (${label(before)} のまま): ${result.detail}`, "error");
      return;
    }
    unverified = undefined;
    show(ctx);
    // 囲いを先に入れ、そのあとで YOLO を入れる (YOLO が入って囲いが無い瞬間を作らない)
    const aligned = alignYoloOn(ctx);
    const notes = ["次のコマンドから囲いの内側で動く。すでに動いている背景ジョブ・子エージェントは、起動時の状態のまま"];
    if (aligned.on) {
      notes.push("YOLO: on（次のターンから。確認の自動承認。deny は効く）");
    } else {
      notes.push(`YOLO を入れなかった: ${aligned.yolo.error}`);
      if (!aligned.off.ok) notes.push(`残っている YOLO も切れなかった: ${aligned.off.error}`);
    }
    if (!(PIB_MARK_ENV in process.env)) {
      notes.push("素の pi から入れた囲い。pib の起動時の検査 (--no-approve など) は通っていない。確実に守るなら pib で起動する");
    }
    say(ctx, `${label(mode)}\n${notes.join("\n")}`, aligned.on ? "info" : "warning");
  }

  async function disable(ctx: ExtensionCommandContext): Promise<void> {
    if (!ctx.hasUI) {
      say(ctx, "囲いを外す確認ができない (UI が無い) ため、切り替えなかった", "error");
      return;
    }
    const ok = await ctx.ui.confirm(
      "囲いを外す",
      "このあとのコマンドは、囲いなしで実行される（ホーム・認証・docker・Windows 側の実行ファイルが見える）。YOLO も切る。外すか？",
    );
    if (!ok) {
      say(ctx, `${label(currentMode())} のまま`, "info");
      return;
    }
    // 実行中のターンは、YOLO が入ったまま続く。ターンの切れ目で、YOLO を先に切ってから囲いを外す
    await ctx.waitForIdle();
    const yolo = turnYoloOff(ctx);
    if (!yolo.ok) {
      say(ctx, `YOLO を切れないため、囲いを外さなかった (${label(currentMode())} のまま): ${yolo.error}`, "error");
      return;
    }
    applyMode("off");
    unverified = undefined;
    show(ctx);
    say(
      ctx,
      `${label("off")}\nYOLO: off\n次のコマンドから囲いなし。すでに動いている背景ジョブ・子エージェントは、起動時の状態のまま`,
      "warning",
    );
  }

  async function report(ctx: ExtensionContext): Promise<void> {
    const mode = currentMode();
    const lines = [label(mode)];
    let level: "info" | "warning" | "error" = "info";
    if (mode === "off") {
      lines.push("コマンドは囲いなしで実行される");
    } else {
      const result = await verify(ctx);
      lines.push(result.ok ? "囲いの内側で動くことを確認した" : `囲いが効いていない: ${result.detail}`);
      if (!result.ok) level = "error";
    }
    const yolo = readYolo();
    lines.push(`YOLO（設定ファイルの値。次のターンから効く）: ${yolo === undefined ? "読めない" : yolo ? "on" : "off"}`);
    const forced = projectYoloProblem(ctx);
    if (forced) lines.push(`${forced}（global の設定では切れない）`);
    if (mode === "off" && (yolo !== false || forced) && level === "info") level = "warning"; // 囲いなしの YOLO
    say(ctx, lines.join("\n"), level);
  }

  async function handle(arg: string, ctx: ExtensionCommandContext): Promise<void> {
    if (arg === "") {
      if (currentMode() === "off") await enable("on", ctx);
      else await disable(ctx);
    } else if (arg === "on" || arg === "offline") {
      await enable(arg, ctx);
    } else if (arg === "off") {
      if (currentMode() !== "off") {
        await disable(ctx);
      } else {
        // すでに囲いなし。手動で入れた YOLO が残っていれば、囲いなしの YOLO を解消する
        const yolo = turnYoloOff(ctx);
        say(ctx, yolo.ok ? `${label("off")} のまま（YOLO: off）` : `YOLO を切れなかった: ${yolo.error}`, yolo.ok ? "info" : "error");
      }
    } else if (arg === "status") {
      await report(ctx);
    } else {
      say(ctx, `使い方: ${USAGE}`, "warning");
    }
  }

  pi.registerCommand("sandbox", {
    description: "コマンド実行の囲いと YOLO を一緒に切り替える（/sandbox [on|offline|off|status]。引数なしは on と off の切り替え）",
    getArgumentCompletions: (prefix: string) => {
      const items = ARGUMENTS.filter((name) => name.startsWith(prefix)).map((name) => ({ value: name, label: name }));
      return items.length > 0 ? items : null;
    },
    handler: async (args: string, ctx: ExtensionCommandContext) => {
      if (!tryLock()) {
        say(ctx, "別の /sandbox（または起動時の確認）を実行中。終わってからやり直す", "warning");
        return;
      }
      try {
        await handle(args.trim().toLowerCase(), ctx);
      } finally {
        unlock();
      }
    },
  });

  // YOLO は設定ファイルに残るので、起動のたびに、囲いの状態へ揃える（囲いなしの pi に、前回の YOLO を持ち越さない）。
  // 囲いが効いていると確かめられたときだけ YOLO を入れる（環境変数が立っているだけでは入れない）。
  // /new・/resume・/reload では揃えない（利用者が /permission-system で選んだ値を、セッションの途中で戻さない）。
  // pi は、起動の途中 (session_start の完了前) から入力を受け付ける。確認の最中に /sandbox が割り込むと、「off のあとに YOLO が入る」
  // 食い違いが出るので、起動時の確認も一度に 1 つの枠 (排他の枠) を取り、その間の /sandbox は断る
  let pendingStartup: ExtensionContext | undefined; // 判定 API の公開待ちで、起動時の同期を済ませていない
  async function alignYoloAtStartup(ctx: ExtensionContext): Promise<void> {
    let mode = currentMode();
    let want = false;
    if (mode !== "off") {
      const result = await verify(ctx);
      mode = currentMode(); // 確認の間に変わっていても (排他の枠で、通常は変わらない)、いまの状態で決める
      if (result.ok) {
        want = mode !== "off";
      } else {
        unverified = "効いていない";
        say(ctx, `${label(mode)} だが、囲いが効いていると確かめられない。YOLO は入れない: ${result.detail}`, "error");
      }
    }
    show(ctx);
    pendingStartup = undefined;
    if (!want) {
      const off = turnYoloOff(ctx);
      if (!off.ok) say(ctx, `YOLO を切れなかった (${label(mode)}): ${off.error}`, "error");
      else if (off.was === true) say(ctx, `YOLO: off（${label(mode)} に合わせた）`, "info");
      return;
    }
    const aligned = alignYoloOn(ctx);
    if (aligned.on) {
      if (aligned.yolo.changed) say(ctx, `YOLO: on（${label(mode)} に合わせた）`, "info");
      return;
    }
    if (!aligned.off.ok) say(ctx, `残っている YOLO を切れなかった (${label(mode)}): ${aligned.off.error}`, "error");
    if (aligned.yolo.unpublished) {
      // permission-system が、まだ判定 API を公開していない (拡張の読み込み順)。公開を知らせるイベントで、もう一度確かめる
      pendingStartup = ctx;
    } else {
      say(ctx, `YOLO を入れなかった (${label(mode)}): ${aligned.yolo.error}`, "warning");
    }
  }

  // permission-system は、判定 API を公開したあと permissions:ready を (少なくとも 1 回) 知らせる。起動時の同期が、その公開より前だったときの再試行
  const offReady = pi.events?.on("permissions:ready", (data: unknown) => {
    const ctx = pendingStartup;
    if (!ctx) return;
    try {
      const id = (data as { sessionId?: string } | null)?.sessionId;
      if (id && id !== ctx.sessionManager.getSessionId()) return; // 別のノード（子など）の通知
    } catch {
      pendingStartup = undefined; // 入れ替わったセッションの ctx
      return;
    }
    void (async () => {
      await lockWait();
      try {
        if (pendingStartup === ctx) await alignYoloAtStartup(ctx);
      } catch {
        pendingStartup = undefined; // 確認の最中に /new・/reload で、ctx が使えなくなった (未処理の例外にしない)
      } finally {
        unlock();
      }
    })();
  });

  // /new・/resume・/reload・終了で、この拡張の世代は終わる。保留と購読を捨てる (古い ctx を、あとで使わない)
  pi.on("session_shutdown", () => {
    pendingStartup = undefined;
    if (typeof offReady === "function") offReady();
  });

  pi.on("session_start", async (event: { reason?: string }, ctx: ExtensionContext) => {
    if (event?.reason !== "startup") {
      show(ctx);
      return;
    }
    await lockWait();
    try {
      await alignYoloAtStartup(ctx);
    } finally {
      unlock();
    }
  });
}

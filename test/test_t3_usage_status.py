"""t3-usage-status (T3 Code に、pi のセッションのキャッシュヒット率・費用・コンテキスト使用率を出す拡張) を、node で実際に動かして確かめる。

拡張が pi 本体から取り込むのは型だけ (``import type``) なので、``--experimental-strip-types`` で型を除去すれば、
代役 (stub) なしで動く。pi の本物の ``ExtensionAPI`` と ``ctx`` は使わず、使う面 (``pi.on``・``ctx.mode``・
``ctx.sessionManager.getEntries``・``ctx.getContextUsage``・``ctx.ui.setStatus``) だけの最小の代役を、この試験が作る。
実際の pi・T3 Code の画面は通らない (未確認。実機の確認は README.md と ADR-0031 の記録)。
pi のフッターの計算 (dist/modes/interactive/components/footer.js の getSessionStats) との一致は、
その読み方に従った期待値で固定する。フッターそのものを動かして突き合わせてはいない。
node が無い・TypeScript の型の除去を使えない環境では skip する (skip は通過ではない。件数を報告する)。
see docs/adr/0031-evaluate-existing-extensions-first.md の「例外として残す自作の一覧」
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "home" / "dot_pi" / "agent" / "local-packages" / "t3-usage-status"
SOURCE = PACKAGE / "src" / "index.ts"

# 拡張の入口を読み込み、データ (data.json) を使う場面の前置き。pi の代役は使う面だけを持つ
PRELUDE = """
import fs from 'node:fs';
const mod = await import('./index.ts');
const DATA = JSON.parse(fs.readFileSync('data.json', 'utf8'));
const out = (o) => console.log(JSON.stringify(o));
const nul = (v) => (v === undefined ? null : v);  // JSON は undefined を落とすので、null に写して区別する
function setup(mode, entries, contextUsage, modelWindow) {
  const handlers = {}, calls = [], usedApi = [];
  // contextUsage: undefined なら ctx.getContextUsage を持たない (古い pi)。
  // 'returns-undefined' なら API はあるが undefined を返す (最初の応答前の仮想モデル)
  const state = { mode, entries, contextUsage, modelWindow };  // modelWindow: ctx.model.contextWindow (窓の大きさの代わり)
  const on = (name, handler) => { (handlers[name] ??= []).push(handler); };
  // pi.on 以外 (registerTool・registerCommand など) を使ったら記録する。拡張は状態の表示だけを登録する
  const pi = new Proxy({ on }, { get: (target, key) => { if (!(key in target)) usedApi.push(String(key)); return target[key]; } });
  const ctx = {
    get mode() { return state.mode; },
    sessionManager: { getEntries: () => state.entries },
    ...(state.modelWindow === undefined ? {} : { model: { contextWindow: state.modelWindow } }),
    ui: { setStatus: (key, text) => calls.push([key, nul(text)]) },
    ...(contextUsage === undefined ? {} : {
      getContextUsage: () => (state.contextUsage === 'returns-undefined' ? undefined : state.contextUsage),
    }),
  };
  mod.default(pi);
  return { handlers, calls, usedApi, state, ctx };
}
const fire = async (t, name) => { for (const h of t.handlers[name] ?? []) await h({ type: name }, t.ctx); };
"""


@pytest.fixture(scope="module")
def run_node(tmp_path_factory):
    """拡張を node で動かす関数 (scenario, data) -> 最後の行の JSON。node か型の除去が無ければ、使う試験が skip される。"""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node が無い")
    env = {k: v for k, v in os.environ.items() if not k.startswith("NODE_")}
    probe = subprocess.run(
        [node, "--experimental-strip-types", "--no-warnings", "-e", "0"],
        env=env, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    if probe.returncode != 0:
        pytest.skip("この node は TypeScript の型の除去 (--experimental-strip-types) を使えない")

    counter = iter(range(1_000_000))

    def run(scenario: str, data):
        work = tmp_path_factory.mktemp(f"t3-usage-{next(counter)}")
        shutil.copy(SOURCE, work / "index.ts")
        (work / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        (work / "data.json").write_text(json.dumps(data), encoding="utf-8")
        (work / "main.mjs").write_text(PRELUDE + scenario, encoding="utf-8")
        proc = subprocess.run(
            [node, "--experimental-strip-types", "--no-warnings", "main.mjs"],
            cwd=work, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout.strip().splitlines()[-1])

    return run


# --- セッションのエントリの作り方 (pi のセッションファイルの形) ------------------------------


def usage(*, input=0, cache_read=0, cache_write=0, cost=None):
    body = {"input": input, "output": 50, "cacheRead": cache_read, "cacheWrite": cache_write}
    if cost is not None:
        body["cost"] = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": cost}
    return body


def assistant(**kw):
    return {"type": "message", "message": {"role": "assistant", "content": [], "usage": usage(**kw)}}


def tool_result(**kw):
    return {"type": "message", "message": {"role": "toolResult", "content": [], "usage": usage(**kw)}}


def usage_entry(**kw):
    return {"type": "usage", "usage": usage(**kw)}


def compaction(**kw):
    return {"type": "compaction", "summary": "s", "usage": usage(**kw)}


def branch_summary(**kw):
    return {"type": "branch_summary", "summary": "s", "usage": usage(**kw)}


USER = {"type": "message", "message": {"role": "user", "content": "hi"}}

# id -> (エントリ, 期待する表示。None は何も出さない)。期待値は、pi のフッターの読み方 (合計は全エントリの和・
# ヒット率は最新の assistant だけ・キャッシュの読み書きがあるときだけ CH) から、手で計算したもの
CASES = {
    "empty-session": ([], None),
    "no-usage-bearing-entries": ([USER, {"type": "custom", "customType": "x"}], None),
    "no-cache-no-cost": ([assistant(input=100)], None),
    "cost-only-without-cache": ([assistant(input=100, cost=0.1234)], "$0.123"),
    "cost-has-three-decimals": ([assistant(input=100, cost=24.48)], "$24.480"),
    "tiny-cost-still-prints": ([assistant(input=100, cost=0.0004)], "$0.000"),
    # フッターは購読のモデルのときだけ $0.000 (sub) を出す。拡張はモデルを見ないので、費用 0 は何も出さない (既知の差)
    "zero-cost-prints-no-dollar": ([assistant(input=100, cache_read=900, cost=0)], "CH90.0%"),
    "hit-rate-and-cost": ([assistant(input=100, cache_read=700, cache_write=200, cost=0.4)], "CH70.0% $0.400"),
    # 分母は input + cacheRead + cacheWrite (cacheWrite を除くと 100% になる)
    "hit-rate-denominator-has-cache-write": ([assistant(input=0, cache_read=500, cache_write=500, cost=1)], "CH50.0% $1.000"),
    "hit-rate-comes-from-the-latest-assistant": (
        [assistant(input=100, cache_write=900, cost=0.1), assistant(input=100, cache_read=900, cost=0.1)],
        "CH90.0% $0.200",
    ),
    # 最新が 0% でも、セッションに 1 度でもキャッシュがあれば CH0.0% を出す
    "latest-without-cache-reads-as-zero-percent": (
        [assistant(input=100, cache_read=900, cost=0.1), assistant(input=100, cost=0.1)],
        "CH0.0% $0.200",
    ),
    # 最新の assistant の prompt が 0 token なら、ヒット率は無い (CH を出さない)
    "latest-without-prompt-tokens-omits-hit-rate": (
        [assistant(input=100, cache_read=900, cost=0.1), assistant(cost=0.2)],
        "$0.300",
    ),
    # toolResult はヒット率の元にならない (合計にだけ入る)
    "tool-result-never-sets-the-hit-rate": (
        [assistant(input=100, cache_read=900, cost=0.1), tool_result(input=100, cost=0.1)],
        "CH90.0% $0.200",
    ),
    # キャッシュの読み書きの有無は、assistant 以外のエントリも含めた合計で決まる
    "cache-activity-counts-every-entry": (
        [assistant(input=100, cost=0.1), tool_result(cache_read=10)],
        "CH0.0% $0.100",
    ),
    # 合計に入るもの: toolResult (usage 付き)・usage エントリ・compaction・branch_summary
    "total-includes-tool-result": ([assistant(input=100, cache_read=900, cost=1), tool_result(cost=0.5)], "CH90.0% $1.500"),
    "total-includes-usage-entry": ([assistant(input=100, cache_read=900, cost=1), usage_entry(cost=0.5)], "CH90.0% $1.500"),
    "total-includes-compaction": ([assistant(input=100, cache_read=900, cost=1), compaction(cost=0.5)], "CH90.0% $1.500"),
    "total-includes-branch-summary": ([assistant(input=100, cache_read=900, cost=1), branch_summary(cost=0.5)], "CH90.0% $1.500"),
    # 合計に入らないもの: user・usage の無い toolResult・未知の種類のエントリ
    "total-ignores-other-entries": (
        [
            assistant(input=100, cache_read=900, cost=1),
            {"type": "message", "message": {"role": "user", "content": "x", "usage": usage(cost=5)}},
            {"type": "custom", "usage": usage(cost=5)},
            {"type": "message", "message": {"role": "toolResult", "content": []}},
        ],
        "CH90.0% $1.000",
    ),
    # 数でない値 (文字列・null) は 0 として扱う
    "non-numbers-count-as-zero": (
        [
            {"type": "message", "message": {"role": "assistant", "usage": {"input": "x", "cacheRead": None, "cost": {"total": "3"}}}},
            assistant(input=100, cost=1),
        ],
        "$1.000",
    ),
    "usage-less-assistant-is-skipped": (
        [{"type": "message", "message": {"role": "assistant", "content": []}}, assistant(input=100, cost=1)],
        "$1.000",
    ),
    # すべての種類を混ぜた例。1.98 = 0.4 + 0.2 + 0.1 + 0.05 + 0.03 + 1.2、ヒット率は最後の assistant の 700 / 1000
    "all-kinds-together": (
        [
            USER,
            assistant(input=100, cache_write=900, cost=0.4),
            tool_result(input=10, cache_read=10, cost=0.2),
            usage_entry(cost=0.1),
            compaction(cost=0.05),
            branch_summary(cost=0.03),
            assistant(input=100, cache_read=700, cache_write=200, cost=1.2),
        ],
        "CH70.0% $1.980",
    ),
}


@pytest.fixture(scope="module")
def computed(run_node):
    """全場面の computeStatusText を、node の 1 回の起動で求める。"""
    ids = list(CASES)
    got = run_node(
        "out(DATA.map((entries) => nul(mod.computeStatusText(entries))));",
        [CASES[i][0] for i in ids],
    )
    return dict(zip(ids, got, strict=True))


@pytest.mark.parametrize("case", list(CASES))
def test_compute_status_text_follows_the_pi_footer(computed, case):
    """合計 (費用) と最新のヒット率 (CH%) が、pi のフッターと同じ規則で求まる。"""
    assert computed[case] == CASES[case][1]


# --- ハンドラ (RPC のときだけ出す) -------------------------------------------------------------


def test_rpc_publishes_on_session_start_and_turn_end_and_clears_on_shutdown(run_node):
    got = run_node(
        """
const t = setup('rpc', DATA.before);
await fire(t, 'session_start');
const afterStart = t.calls.splice(0);
t.state.entries = DATA.after;  // ターンの間にエントリが増えた
await fire(t, 'turn_end');
const afterTurn = t.calls.splice(0);
await fire(t, 'session_shutdown');
const afterShutdown = t.calls.splice(0);
out({ events: Object.keys(t.handlers).sort(), counts: Object.values(t.handlers).map((h) => h.length), usedApi: t.usedApi,
      afterStart, afterTurn, afterShutdown });
""",
        {
            "before": [assistant(input=100, cache_read=900, cost=0.5)],
            "after": [assistant(input=100, cache_read=900, cost=0.5), assistant(input=100, cache_read=700, cache_write=200, cost=1.5)],
        },
    )
    assert got["events"] == ["model_select", "session_compact", "session_shutdown", "session_start", "turn_end"]
    assert got["counts"] == [1, 1, 1, 1, 1]
    assert got["usedApi"] == []  # コマンド・ツールなどを登録しない (モデルが呼べる口を作らない)
    assert got["afterStart"] == [["usage", "CH90.0% $0.500"]]  # 再開したセッションの数がすぐ出る
    assert got["afterTurn"] == [["usage", "CH70.0% $2.000"]]  # 毎ターンの終わりに更新される
    assert got["afterShutdown"] == [["usage", None]]  # 終了で消す


def test_rpc_clears_the_banner_when_the_session_is_empty(run_node):
    """出す数が無い (空のセッション) とき、前の値を残さず status を消す (undefined を渡す)。"""
    got = run_node(
        """
const t = setup('rpc', DATA);
await fire(t, 'session_start');
out(t.calls);
""",
        [],
    )
    assert got == [["usage", None]]


@pytest.mark.parametrize("mode", ["tui", "print", "json", None])
def test_other_modes_publish_nothing_at_all(run_node, mode):
    """pi 自身の TUI (と print・json) では、何も出さず、消す呼び出しもしない (フッターが唯一の表示。二重にならない)。"""
    got = run_node(
        """
const t = setup(DATA.mode, DATA.entries, { tokens: 1000, contextWindow: 2000, percent: 50 });  // API があっても、RPC 以外では出さない
for (const name of ['session_start', 'turn_end', 'session_compact', 'model_select', 'session_shutdown']) await fire(t, name);
out({ calls: t.calls, usedApi: t.usedApi });
""",
        {"mode": mode, "entries": [assistant(input=100, cache_read=900, cost=0.5)]},
    )
    assert got == {"calls": [], "usedApi": []}


def test_mode_is_read_when_the_event_fires_not_when_the_extension_loads(run_node):
    """読み込み (登録) の時点の mode で決めない。イベントのたびの ctx.mode で決める。"""
    got = run_node(
        """
const t = setup('tui', DATA);
await fire(t, 'turn_end');
const inTui = t.calls.splice(0);
t.state.mode = 'rpc';
await fire(t, 'turn_end');
out({ inTui, inRpc: t.calls });
""",
        [assistant(input=100, cache_read=900, cost=0.5)],
    )
    assert got == {"inTui": [], "inRpc": [["usage", "CH90.0% $0.500"]]}


# --- コンテキスト使用率 (ctx) -------------------------------------------------------------------

# computeStatusText の第 2 引数 (contextPercent)。undefined は出さず、null (不明) は ?、数は小数 1 桁。順序は CH → 費用 → ctx
CTX_CASES = {
    "ctx-after-hit-rate-and-cost": (
        [assistant(input=100, cache_read=700, cache_write=200, cost=0.4)], 41.234, None, "CH70.0% $0.400 41.2%",
    ),
    "ctx-only-in-an-empty-session": ([], 0, None, "0.0%"),
    "ctx-unknown-after-compaction": ([], None, None, "?"),
    "ctx-unknown-keeps-the-other-parts": ([assistant(input=100, cache_read=900, cost=1)], None, None, "CH90.0% $1.000 ?"),
    "ctx-full-window": ([assistant(input=100, cost=1)], 100, None, "$1.000 100.0%"),
    # 数でない値 (NaN・Infinity) は、出さない
    "ctx-non-finite-is-ignored": ([assistant(input=100, cost=1)], "nan", None, "$1.000"),
    # 分母 (窓の大きさ)。pi のフッターの formatTokens と同じ k・M 表記
    "denominator-200k": ([], 41.2, 200000, "41.2%/200k"),
    "denominator-1m": ([], 8.2, 1000000, "8.2%/1.0M"),
    "denominator-one-decimal-below-10k": ([], 50, 8192, "50.0%/8.2k"),
    "denominator-below-1k": ([], 50, 512, "50.0%/512"),
    "denominator-10m": ([], 1, 12000000, "1.0%/12M"),
    "denominator-with-unknown-percent": ([], None, 200000, "?/200k"),
    "denominator-after-cost-and-hit-rate": ([assistant(input=100, cache_read=900, cost=1)], 41, 200000, "CH90.0% $1.000 41.0%/200k"),
    # 窓が 0・負・非数のときは、分母を出さない
    "denominator-zero-is-omitted": ([], 41, 0, "41.0%"),
    "denominator-negative-is-omitted": ([], 41, -5, "41.0%"),
    "denominator-without-percent-is-not-printed": ([assistant(input=100, cost=1)], "absent", 200000, "$1.000"),
}


def test_compute_status_text_appends_the_context_percent_and_window(run_node):
    ids = list(CTX_CASES)
    data = [[CTX_CASES[i][0], CTX_CASES[i][1], CTX_CASES[i][2]] for i in ids]
    got = run_node(
        """
out(DATA.map(([entries, pct, win]) => nul(mod.computeStatusText(
  entries,
  pct === 'nan' ? Number.NaN : pct === 'absent' ? undefined : pct,
  win === null ? undefined : win,
))));
""",
        data,
    )
    assert dict(zip(ids, got, strict=True)) == {i: CTX_CASES[i][3] for i in ids}


def test_rpc_publishes_the_context_percent_and_refreshes_on_model_change_compact_and_turn_end(run_node):
    got = run_node(
        """
const t = setup('rpc', DATA.entries, { tokens: 82000, contextWindow: 200000, percent: 41 });
await fire(t, 'session_start');
const afterStart = t.calls.splice(0);
t.state.contextUsage = { tokens: 82000, contextWindow: 1000000, percent: 8.2 };  // 大きな窓のモデルへ切り替え
await fire(t, 'model_select');
const afterModel = t.calls.splice(0);
t.state.contextUsage = { tokens: null, contextWindow: 1000000, percent: null };  // 圧縮の直後は、次の応答まで不明
await fire(t, 'session_compact');
const afterCompact = t.calls.splice(0);
t.state.entries = DATA.entries.concat(DATA.next);  // 圧縮のあとの新しい応答
t.state.contextUsage = { tokens: 20000, contextWindow: 1000000, percent: 2 };
await fire(t, 'turn_end');
const afterNextTurn = t.calls.splice(0);
out({ afterStart, afterModel, afterCompact, afterNextTurn });
""",
        {"entries": [assistant(input=100, cache_read=900, cost=0.5)], "next": [assistant(input=100, cache_read=900, cost=0.5)]},
    )
    assert got["afterStart"] == [["usage", "CH90.0% $0.500 41.0%/200k"]]
    assert got["afterModel"] == [["usage", "CH90.0% $0.500 8.2%/1.0M"]]
    assert got["afterCompact"] == [["usage", "CH90.0% $0.500 ?/1.0M"]]
    assert got["afterNextTurn"] == [["usage", "CH90.0% $1.000 2.0%/1.0M"]]


def test_rpc_shows_the_context_percent_even_in_a_new_session(run_node):
    """空のセッションでもコンテキスト使用率を出す。T3 は status を最初に出した順に並べるので、この拡張の表示を先頭にするため。"""
    got = run_node(
        """
const t = setup('rpc', [], { tokens: null, contextWindow: 200000, percent: null });
await fire(t, 'session_start');
out(t.calls);
""",
        None,
    )
    assert got == [["usage", "?/200k"]]


def test_without_the_context_usage_api_the_extension_behaves_as_before(run_node):
    """API (ctx.getContextUsage) が無い古い pi では、コンテキスト使用率を出さない (CH と費用だけ)。空のセッションは消す。"""
    got = run_node(
        """
const t = setup('rpc', DATA.entries);  // contextUsage を渡さない = API を持たない
await fire(t, 'session_start');
const withEntries = t.calls.splice(0);
t.state.entries = [];
await fire(t, 'turn_end');
out({ withEntries, empty: t.calls });
""",
        {"entries": [assistant(input=100, cache_read=900, cost=0.5)]},
    )
    assert got == {"withEntries": [["usage", "CH90.0% $0.500"]], "empty": [["usage", None]]}


def test_when_the_api_returns_undefined_the_context_percent_is_unknown_not_omitted(run_node):
    """API はあるが undefined を返す (最初の応答前の仮想モデルなど) ときは ?。空のセッションでも usage が先頭に登録される。"""
    got = run_node(
        """
const empty = setup('rpc', [], 'returns-undefined');
await fire(empty, 'session_start');
const withEntries = setup('rpc', DATA.entries, 'returns-undefined');
await fire(withEntries, 'session_start');
out({ empty: empty.calls, withEntries: withEntries.calls });
""",
        {"entries": [assistant(input=100, cache_read=900, cost=0.5)]},
    )
    assert got == {"empty": [["usage", "?"]], "withEntries": [["usage", "CH90.0% $0.500 ?"]]}


def test_the_window_falls_back_to_the_current_model_when_the_usage_has_none(run_node):
    """pi のフッターと同じ順: 使用量の contextWindow、なければ現在のモデルの contextWindow。両方無ければ分母を出さない。"""
    got = run_node(
        """
const fromModel = setup('rpc', [], 'returns-undefined', 400000);
await fire(fromModel, 'session_start');
const preferUsage = setup('rpc', [], { tokens: 1, contextWindow: 200000, percent: 0.5 }, 400000);
await fire(preferUsage, 'session_start');
const neither = setup('rpc', [], 'returns-undefined');
await fire(neither, 'session_start');
out({ fromModel: fromModel.calls, preferUsage: preferUsage.calls, neither: neither.calls });
""",
        None,
    )
    assert got == {
        "fromModel": [["usage", "?/400k"]],
        "preferUsage": [["usage", "0.5%/200k"]],
        "neither": [["usage", "?"]],
    }


# --- package の形 (node を使わない) ---------------------------------------------------------------


def test_package_is_a_pi_package_without_runtime_dependencies():
    """ローカルの pi package の形 (pi-sandbox-toggle と同じ)。本体が出すものを依存に入れない (pi の docs)。"""
    meta = json.loads((PACKAGE / "package.json").read_text(encoding="utf-8"))
    assert meta["name"] == "t3-usage-status-local"
    assert meta["private"] is True and meta["type"] == "module"
    assert "pi-package" in meta["keywords"]
    assert meta["pi"]["extensions"] == ["./src/index.ts"]
    assert "dependencies" not in meta
    assert meta["peerDependencies"] == {"@earendil-works/pi-coding-agent": "*"}
    assert meta["peerDependenciesMeta"] == {"@earendil-works/pi-coding-agent": {"optional": True}}
    assert meta["files"] == ["src", "README.md"]
    assert (PACKAGE / "README.md").is_file()


def test_the_extension_imports_only_types_from_pi():
    """実行時に pi の本体を取り込まない (型だけ。型の除去で、代役なしに動くことの前提)。"""
    src = SOURCE.read_text(encoding="utf-8")
    imports = [line for line in src.splitlines() if line.startswith("import ")]
    assert imports and all(line.startswith("import type ") for line in imports), imports

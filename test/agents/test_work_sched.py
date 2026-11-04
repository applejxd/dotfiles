"""作業台帳のスケジューラ (``home/dot_config/pi/harness/work/{sched,strategy,aimd,reserve,overlap}.ts``) の試験。

``test/agents/pi/work_sched_driver.mjs`` に JSON を渡して関数を呼ぶ (node の型除去を使うので、22.18 未満の node では飛ばす)。
driver は引数を deep freeze して渡すので、入力を変更する実装は失敗する (不変性の試験を兼ねる)。

- 方式の選択表: 試験側の独立した評価器 (``RULES``。仕様をデータで持つ) と、実装を全組み合わせで比較する (総当たり)
- ``globsMayOverlap``: 合成のファイル木に対する全 glob の組の総当たりで、偽陰性が 0 であること
- 性質試験: seed 固定の乱数列 (背圧・pipeline・writes の重なり・予算・429・AIMD・見込みの無効化・決定性)
- 予約の境界・429 の連続と再開・スケジューラの場面試験

see docs/spec/work/scheduler.md
"""

from __future__ import annotations

import functools
import itertools
import json
import re
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "work_sched_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


def drive(payload):
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.loads(proc.stdout)


def c(mod, fn, *args):
    return {"mod": mod, "fn": fn, "args": list(args)}


@functools.cache
def _batch_results(blob: str):
    return drive({"calls": json.loads(blob)})["results"]


# 小さな呼び出しは 1 回の node 起動にまとめる (名前 → 呼び出し)。登録は import 時、実行は最初の参照時
CASES: dict[str, dict] = {}


def case(name, call):
    assert name not in CASES, name
    CASES[name] = call
    return name


def result(name):
    names = sorted(CASES)
    res = _batch_results(json.dumps([CASES[n] for n in names]))
    return res[names.index(name)]


# ── 共通の部品 ──────────────────────────────────────────────

Z = {"usd": 0, "tokens": 0, "ms": 0}


def money(usd=0.0, tokens=0, ms=0):
    return {"usd": usd, "tokens": tokens, "ms": ms}


def task(tid, **kw):
    t = {
        "id": tid,
        "state": "ready",
        "kind": "edit",
        "role": "worker",
        "size": "M",
        "writes": [f"d_{tid}/**"],
        "after": [],
    }
    t.update(kw)
    return t


def ro(tid, **kw):
    return task(tid, kind="ro", role="explore", writes=[], **kw)


def run(rid, tid, **kw):
    r = {
        "id": rid,
        "task": tid,
        "state": "started",
        "reserve": money(1, 100000, 600000),
        "spent": dict(Z),
    }
    r.update(kw)
    return r


PROV = {"limit": 6, "streak": 0, "strikes": 0, "pausedUntil": 0, "exhausted": False}
NOSTATS = {"byMethod": {}, "pairs": []}


def state(tasks, runs=(), **kw):
    s = {
        "tasks": tasks,
        "runs": list(runs),
        "used": dict(Z),
        "history": {},
        "stats": NOSTATS,
        "provider": PROV,
    }
    s.update(kw)
    return s


def resources(**kw):
    r = {
        "slots": 6,
        "hot": ["**/common.toml.tmpl", "**/index.ts", "scripts/verify.py", "docs/**/index.md"],
    }
    r.update(kw)
    return r


def nxt(st, res=None, now=1_000_000):
    return ("sched", "next", st, res or resources(), now)


def starts(acts):
    return [a for a in acts if a["kind"] == "start"]


def kinds(acts):
    return [a["kind"] for a in acts]


# ═══ a) 方式の選択表の総当たり (試験側の独立した評価器) ═══════════════════════════

# 仕様をデータで持つ。上から順に評価し、最初に当たった行の出力を採る。条件の書き方:
#   {キー: 値}            入力のキーが値と等しい
#   "any": [(キー, 値)..]  どれか 1 つ
#   "ne": {キー: 値}       等しくない
#   "ge": {キー: 数}       以上
#   "on": 方式             その方式が無効でない
RULES = [
    ("R1", {"kind": "check"}, ("serial", "min1", "none", "exclusive-lock")),
    ("R2a", {"kind": "ro", "pipeline": True}, ("pipeline", "free_ready", "none", "digest-format")),
    ("R2b", {"kind": "ro"}, ("fanout", "free_ready", "none", "digest-format")),
    ("R3", {"kind": "edit", "upstream": "pending"}, ("serial", "zero", "none", "-")),
    (
        "R4",
        {"kind": "edit", "any": [("overlap", True), ("hot", True), ("risk", "boundary")]},
        ("serial", "min1", "worktree", "@risk"),
    ),
    (
        "R5",
        {
            "kind": "edit",
            "upstream": "running",
            "contract": True,
            "budget": "ample",
            "ne": {"fail": "high"},
            "on": "speculative",
            "ge": {"free": 1},
        },
        ("speculative", "one", "worktree", "excluded-from-bundle-until-upstream"),
    ),
    ("R5x", {"kind": "edit", "upstream": "running"}, ("serial", "zero", "none", "-")),
    (
        "R6",
        {
            "kind": "edit",
            "uncertain": True,
            "accept": True,
            "budget": "ample",
            "ne": {"size": "L", "fail": "high"},
            "on": "race",
            "ge": {"free": 2},
        },
        ("race", "min3free", "worktree", "all-checks-then-min-diff"),
    ),
    (
        "R7",
        {
            "kind": "edit",
            "group": True,
            "size": "S",
            "ne": {"fail": "high"},
            "on": "shared",
            "ge": {"free": 2},
        },
        ("shared", "shared_deg", "shared", "group-join"),
    ),
    (
        "R8",
        {"kind": "edit", "size": "L", "budget": "tight"},
        ("serial", "min1", "worktree", "targeted"),
    ),
    ("R9", {"kind": "edit", "fail": "high"}, ("serial", "min1", "worktree", "targeted")),
    ("R10", {"kind": "edit"}, ("worktree", "free_adj", "worktree", "targeted-then-bundle")),
]


def _match(cond, i):
    for k, v in cond.items():
        if k == "any":
            if not any(i.get(a, False) == b for a, b in v):
                return False
        elif k == "ne":
            if any(i.get(a) == b for a, b in v.items()):
                return False
        elif k == "ge":
            if any(i["free"] < b for b in v.values()):
                return False
        elif k == "on":
            if v in i.get("disabled", []):
                return False
        elif i.get(k, False) != v:
            return False
    return True


def _degree(spec, i):
    free = max(0, i["free"])

    def adj(n):
        return max(1, -(-n // 2)) if i["fail"] == "mid" else n

    return {
        "min1": min(1, free),
        "zero": 0,
        "one": 1,
        "free_ready": min(free, max(1, i["ready"])),
        "min3free": min(3, free),
        "shared_deg": adj(min(3, free)),
        "free_adj": adj(free),
    }[spec]


def oracle_select(i):
    for rid, cond, (method, deg, iso, verify) in RULES:
        if _match(cond, i):
            if verify == "@risk":
                verify = "independent-review" if i["risk"] == "boundary" else "targeted"
            return {
                "method": method,
                "degree": _degree(deg, i),
                "isolation": iso,
                "verify": verify,
                "rule": rid,
            }
    raise AssertionError(f"どの行にも当たらない: {i}")


BASE_DIMS = {
    "kind": ["ro", "edit", "check"],
    "overlap": [False, True],
    "size": ["S", "M", "L"],
    "upstream": ["none", "running", "pending"],
    "risk": ["none", "boundary"],
    "hot": [False, True],
    "free": [1, 4],
    "budget": ["ample", "tight"],
    "fail": ["low", "mid", "high"],
}
PROFILES = {
    "plain": {},
    "group_contract": {"group": True, "contract": True},
    "uncertain_accept": {"uncertain": True, "accept": True},
    "all": {"pipeline": True, "group": True, "contract": True, "uncertain": True, "accept": True},
}
DISABLED_VARIANTS = [[], ["speculative"], ["race"], ["shared"]]


def _inputs(kind, size, upstream):
    """(kind, size, upstream) を固定した全入力。残りの 6 次元 × 4 profile × 無効の 4 通りを列挙する"""
    rest = {k: v for k, v in BASE_DIMS.items() if k not in ("kind", "size", "upstream")}
    out = []
    for combo in itertools.product(*rest.values()):
        base = dict(zip(rest.keys(), combo, strict=True))
        base.update({"kind": kind, "size": size, "upstream": upstream, "ready": 5})
        for prof in PROFILES.values():
            for dis in DISABLED_VARIANTS:
                if dis and prof is not PROFILES["all"]:
                    continue
                inp = {**base, **prof}
                if dis:
                    inp["disabled"] = dis
                out.append(inp)
    return out


@functools.cache
def _select_results(kind, size, upstream):
    ins = _inputs(kind, size, upstream)
    got = drive({"map": {"mod": "strategy", "fn": "select", "argsList": [[i] for i in ins]}})[
        "results"
    ]
    return ins, got


def test_base_dimension_count():
    """離散化の次元の積が 2,592 通りであること (計画 K 節の見積りと同じ)"""
    n = 1
    for v in BASE_DIMS.values():
        n *= len(v)
    assert n == 2592


@pytest.mark.parametrize("kind", BASE_DIMS["kind"])
@pytest.mark.parametrize("size", BASE_DIMS["size"])
@pytest.mark.parametrize("upstream", BASE_DIMS["upstream"])
def test_select_matches_independent_oracle(kind, size, upstream):
    ins, got = _select_results(kind, size, upstream)
    assert len(ins) == len(got) > 0
    bad = []
    for i, g in zip(ins, got, strict=True):
        want = oracle_select(i)
        have = {k: g[k] for k in want}
        if have != want:
            bad.append((i, want, have))
        assert g["why"], i
    assert not bad, f"{len(bad)} 件が不一致。先頭: {bad[0]}"


def test_select_covers_every_rule_and_method():
    """表の全行・全方式が、総当たりの入力のどこかで選ばれる (到達不能な行が無い)"""
    seen_rules, seen_methods = set(), set()
    for kind, size, up in itertools.product(
        BASE_DIMS["kind"], BASE_DIMS["size"], BASE_DIMS["upstream"]
    ):
        ins, _ = _select_results(kind, size, up)
        for i in ins:
            o = oracle_select(i)
            seen_rules.add(o["rule"])
            seen_methods.add(o["method"])
    assert seen_rules == {r[0] for r in RULES}
    assert seen_methods == {
        "fanout",
        "shared",
        "worktree",
        "serial",
        "speculative",
        "race",
        "pipeline",
    }


# ═══ c) globsMayOverlap の偽陰性 0 (合成のファイル木に対する総当たり) ══════════════════

NAMES = [
    "src",
    "a",
    "b",
    "docs",
    "test",
    "lib",
    "x.ts",
    "index.ts",
    "index.md",
    "z.ts",
    "verify.py",
    "q.ts",
    "common.toml.tmpl",
]
DIRS = ["src", "a", "b", "docs", "test", "lib"]
# 深さ 1〜3 は全名前の直積、深さ 4 は (ディレクトリ 3 段 + 名前)。ファイル名は末尾にだけ置く
TREE = [
    "/".join(p)
    for depth in range(1, 4)
    for p in itertools.product(NAMES, repeat=depth)
    if all(not n.endswith(("ts", "md", "py", "tmpl")) for n in p[:-1])
] + ["/".join(p) for p in itertools.product(DIRS, DIRS, DIRS, NAMES)]
GLOBS = [
    "**",
    "*",
    "**/*",
    "**/*.ts",
    "**/index.ts",
    "**/index.*",
    "**/verify.py",
    "**/common.toml.tmpl",
    "src/**",
    "src/a/**",
    "src/b/**",
    "src/a/x.ts",
    "src/a/",
    "src/*/x.ts",
    "src/*/z.ts",
    "src/**/index.ts",
    "src/a*",
    "src/a/*.ts",
    "src/[ab]/x.ts",
    "src/?/z.ts",
    "{src,docs}/**",
    "src/{a,b}/*.ts",
    "{src,lib}/{a,b}/x.ts",
    "docs/**",
    "docs/**/index.md",
    "docs/index.md",
    "test/**",
    "test/a/**",
    "lib/q.ts",
    "lib/*",
    "scripts/verify.py",
    "verify.py",
    "*.py",
    "**/*.py",
    "./src/b/x.ts",
    "a/**/z.ts",
    "?rc/**",
    "[sd]*/index.*",
    "src/a/b/**",
    "**/a/**",
    "x.ts",
    "**/z.ts",
]


def _expand(p):
    m = re.search(r"\{([^{}]*)\}", p)
    if not m:
        return [p]
    return [
        y for alt in m.group(1).split(",") for y in _expand(p[: m.start()] + alt + p[m.end() :])
    ]


def _norm(p):
    p = p.strip()
    while p.startswith("./"):
        p = p[2:]
    p = p.lstrip("/")
    return p + "**" if p == "" or p.endswith("/") else p


@functools.cache
def _seg(seg):
    out = ""
    i = 0
    while i < len(seg):
        ch = seg[i]
        if ch == "*":
            out += "[^/]*"
        elif ch == "?":
            out += "[^/]"
        elif ch == "[":
            j = seg.index("]", i)
            out += seg[i : j + 1]
            i = j
        else:
            out += re.escape(ch)
        i += 1
    return re.compile(out + r"\Z")


def _segs_match(pat, path):
    if not pat:
        return not path
    if pat[0] == "**":
        return _segs_match(pat[1:], path) or (bool(path) and _segs_match(pat, path[1:]))
    if not path:
        return False
    return bool(_seg(pat[0]).match(path[0])) and _segs_match(pat[1:], path[1:])


def oracle_match(glob, path):
    return any(_segs_match(_norm(e).split("/"), path.split("/")) for e in _expand(glob))


@functools.cache
def _overlap_table():
    tree = [(p, p.split("/")) for p in TREE] + [
        ("scripts/verify.py", ["scripts", "verify.py"]),
        ("verify.py", ["verify.py"]),
    ]
    sets = {g: {p for p, _ in tree if oracle_match(g, p)} for g in GLOBS}
    pairs = [(a, b) for a in GLOBS for b in GLOBS]
    got = drive(
        {"map": {"mod": "overlap", "fn": "globsMayOverlap", "argsList": [[a, b] for a, b in pairs]}}
    )["results"]
    return pairs, got, sets


def test_glob_overlap_has_no_false_negative():
    pairs, got, sets = _overlap_table()
    missed = [(a, b) for (a, b), g in zip(pairs, got, strict=True) if sets[a] & sets[b] and not g]
    assert not missed, f"偽陰性 {len(missed)} 件: {missed[:5]}"


def test_glob_overlap_is_symmetric_and_reflexive():
    pairs, got, _ = _overlap_table()
    table = dict(zip(pairs, got, strict=True))
    assert all(table[(a, b)] == table[(b, a)] for a, b in pairs)
    assert all(table[(a, a)] for a in GLOBS)


def test_glob_overlap_is_not_trivially_true():
    """保守的でも全部 true にはしない: 木の上で素な組のうち、半数近くは false と答える (台帳の門と同じ判定なので前置も重なる)"""
    pairs, got, sets = _overlap_table()
    disjoint = [g for (a, b), g in zip(pairs, got, strict=True) if not (sets[a] & sets[b])]
    assert disjoint
    assert disjoint.count(False) / len(disjoint) > 0.4


EXACT = [
    ("src/a/**", "src/b/**", False),
    ("src/a/**", "src/a/x.ts", True),
    ("**", "anything/at/all", True),
    ("docs/**", "test/**", False),
    ("**/index.ts", "src/c/index.ts", True),
    ("src/*.ts", "src/a/x.ts", False),
    (
        "*.py",
        "scripts/verify.py",
        True,
    ),  # 台帳の門 (gitignore 流) と同じ: スラッシュの無い記法は全階層
    ("**/*.py", "scripts/verify.py", True),
    ("src/a*b", "src/c*d", False),
    ("src/a*b", "src/ab", True),
    ("{a,b}/x", "b/x", True),
    ("{a,b}/x", "c/x", False),
    ("src/", "src/a/x.ts", True),
    ("./src/a", "src/a", True),
    ("src/[ab]/x", "src/c/x", True),  # 角括弧は保守的に「重なる」
    ("docs/**/index.md", "docs/spec/index.md", True),
    ("docs/**/index.md", "test/**/index.md", False),
    ("src/a/b/**", "src/a/b/z.ts", True),
    ("src/a/b/**", "src/a/x.ts", False),
    ("lib/q.ts", "lib/r.ts", False),
    ("**/a/**", "b/c.ts", True),  # 前置 (b/c.ts はディレクトリかもしれない) は保守的に重なる
]
for _i, (_a, _b, _w) in enumerate(EXACT):
    case(f"glob{_i}", c("overlap", "globsMayOverlap", _a, _b))


@pytest.mark.parametrize("i", range(len(EXACT)))
def test_glob_overlap_exact_cases(i):
    a, b, want = EXACT[i]
    assert result(f"glob{i}") is want, (a, b)


WRITES = [
    (["**"], False),
    (["*"], False),
    (["**/*"], False),
    ([""], False),
    (["src/**"], True),
    (["**/*.md"], True),
    (["docs/**", "**"], False),
    ([], True),
]
for _i, (_w, _ok) in enumerate(WRITES):
    case(f"validate{_i}", c("overlap", "validateWrites", _w))


@pytest.mark.parametrize("i", range(len(WRITES)))
def test_validate_writes_rejects_too_broad(i):
    w, ok = WRITES[i]
    assert result(f"validate{i}")["ok"] is ok, w


case("hot0", c("overlap", "hotHits", ["src/c/index.ts"], ["**/index.ts", "scripts/verify.py"]))
case("hot1", c("overlap", "hotHits", ["scripts/**"], ["**/index.ts", "scripts/verify.py"]))
case("hot3", c("overlap", "hotHits", ["scripts/verify.py"], ["**/index.ts", "scripts/verify.py"]))
case("hot2", c("overlap", "hotHits", ["lib/q.ts"], ["**/index.ts", "scripts/verify.py"]))
case("brace0", c("overlap", "expandBraces", "{a,b}/{c,d}"))
case("brace1", c("overlap", "expandBraces", "a/{b,{c,d}}"))
case("brace2", c("overlap", "expandBraces", "a/{b"))


def test_hot_hits_and_brace_expansion():
    assert result("hot0") == ["**/index.ts"]
    assert result("hot1") == []  # 木全体の宣言は hot とみなさない (writes の重なりで直列になる)
    assert result("hot3") == ["**/index.ts", "scripts/verify.py"]  # 前置も重なる (保守的)
    assert result("hot2") == ["**/index.ts"]
    assert sorted(result("brace0")) == ["a/c", "a/d", "b/c", "b/d"]
    assert sorted(result("brace1")) == ["a/b", "a/c", "a/d"]
    assert result("brace2") is None


def _ser(tasks):
    return c("overlap", "serialize", tasks)


def st(tid, writes, after=(), rank=None):
    t = {"id": tid, "writes": writes, "after": list(after)}
    if rank is not None:
        t["rank"] = rank
    return t


case("ser0", _ser([st("b", ["src/**"]), st("a", ["src/x.ts"]), st("c", ["docs/**"])]))
case("ser1", _ser([st("a", ["src/**"], ["b"]), st("b", ["src/x.ts"])]))
case(
    "ser2",
    _ser([st("a", ["src/**"], rank=2), st("b", ["src/**"], rank=1), st("c", ["src/**"], rank=3)]),
)
case("ser3", _ser([st("a", []), st("b", [])]))


def test_serialize_adds_deterministic_auto_edges():
    r = result("ser0")
    assert r["auto"] == {"b": ["a"]}  # id 順。素な c には足さない
    by = {t["id"]: t for t in r["tasks"]}
    assert by["b"]["after"] == ["a"] and by["a"]["after"] == [] and by["c"]["after"] == []


def test_serialize_does_not_create_cycles():
    r = result("ser1")  # a は既に b に依存。逆向きの辺は足さない
    assert r["auto"] == {}


def test_serialize_orders_by_rank_then_id_and_chains():
    r = result("ser2")
    by = {t["id"]: t["after"] for t in r["tasks"]}
    assert by["b"] == [] and by["a"] == ["b"] and by["c"] == ["b", "a"]


def test_serialize_ignores_empty_writes():
    assert result("ser3")["auto"] == {}


# ═══ d) 予約の境界 ═══════════════════════════════════════════

case("est0", c("reserve", "estimate", "worker", "S", {}))
case("est1", c("reserve", "estimate", "nobody", "M", {}))
_H = {
    "worker:S": [money(1, 1000, 100), money(2, 2000, 200), money(3, 3000, 300), money(4, 4000, 400)]
}
case("est2", c("reserve", "estimate", "worker", "S", _H))
case(
    "est3", c("reserve", "estimate", "worker", "S", {"worker:S": [money(9, 9, 9), money(9, 9, 9)]})
)
case("p50", c("reserve", "durationP50", "worker", "S", _H))
case("pct0", c("reserve", "percentile", [], 0.75))
case("pct1", c("reserve", "percentile", [5, 1, 3, 2, 4], 0.75))
case("pct2", c("reserve", "percentile", [7], 0.5))


def test_estimate_uses_default_table_without_history():
    assert result("est0") == {"usd": 0.5, "tokens": 150000, "ms": 480000}
    assert result("est1") == {
        "usd": 1.5,
        "tokens": 450000,
        "ms": 1200000,
    }  # 未知の役割は worker と同じ


def test_estimate_uses_p75_with_enough_history():
    assert result("est2") == {
        "usd": 3,
        "tokens": 3000,
        "ms": 300,
    }  # 最近接順位法 ceil(0.75×4)=3 番目
    assert result("est3") == {"usd": 0.5, "tokens": 150000, "ms": 480000}  # 3 件未満は既定表
    assert result("p50") == 200


def test_percentile_edges():
    assert result("pct0") == 0 and result("pct1") == 4 and result("pct2") == 7


_BUD = {"usd": 10, "tokens": 1000}
_CAN = [
    (_BUD, money(4, 400), money(3, 300), money(3, 300), True),  # ちょうど上限は通る
    (_BUD, money(4, 400), money(3, 300), money(3.01, 300), False),
    (_BUD, money(4, 400), money(3, 300), money(3, 301), False),
    (
        _BUD,
        money(0, 0, 10**9),
        money(0),
        money(0.5, 5, 10**9),
        True,
    ),  # 予算の無い項目 (ms) は見ない
    (None, money(99, 99), money(99, 99), money(99, 99), True),
    ({"usd": 0}, Z, Z, money(0.01), False),
    ({"usd": 0}, Z, Z, Z, True),
]
for _i, (_b, _u, _r, _e, _ok) in enumerate(_CAN):
    case(f"can{_i}", c("reserve", "canReserve", _b, _u, _r, _e))


@pytest.mark.parametrize("i", range(len(_CAN)))
def test_can_reserve_boundary(i):
    assert result(f"can{i}") is _CAN[i][4]


_RES = money(1, 1000, 1000)
_WATCH = [
    (money(1.49, 0, 0), None, False, "ok"),
    (money(1.5, 0, 0), None, False, "steer"),
    (money(1.5, 0, 0), None, True, "ok"),  # steer 済みは繰り返さない
    (money(1.99, 0, 0), None, True, "ok"),
    (money(2, 0, 0), None, False, "abort"),
    (money(2, 0, 0), None, True, "abort"),
    (money(0, 1500, 0), None, False, "steer"),
    (money(0, 0, 2000), None, False, "abort"),
    (money(0.8, 0, 0), money(0.7, 0, 0), False, "steer"),  # 子と評価役を合算
    (money(0.6, 0, 0), money(1.4, 0, 0), False, "abort"),
    (Z, None, False, "ok"),
]
for _i, (_s, _e, _st, _w) in enumerate(_WATCH):
    _run = {"reserve": _RES, "spent": _s, "steered": _st}
    if _e:
        _run["evalSpent"] = _e
    case(f"watch{_i}", c("reserve", "watch", _run))


@pytest.mark.parametrize("i", range(len(_WATCH)))
def test_watch_thresholds(i):
    assert result(f"watch{i}") == _WATCH[i][3]


# ═══ e) 429・AIMD・バックオフ ═══════════════════════════════

_BK = [
    (1, 0.5, 60000),
    (2, 0.5, 120000),
    (3, 0.5, 240000),
    (4, 0.5, 480000),
    (5, 0.5, 900000),
    (9, 0.5, 900000),
    (1, 0, 48000),
    (1, 0.999999, 72000),
    (5, 0.999, 900000),
]
for _i, (_n, _r, _ms) in enumerate(_BK):
    case(f"bk{_i}", c("aimd", "backoffMs", _n, _r))


@pytest.mark.parametrize("i", range(len(_BK)))
def test_backoff_doubles_with_jitter_and_cap(i):
    assert abs(result(f"bk{i}") - _BK[i][2]) <= 1


def _evs(*spec, t0=0):
    out, t = [], t0
    for s in spec:
        t += 1000
        out.append({"t": "429", "ts": t, "rand": 0.5} if s == "429" else {"t": s, "ts": t})
    return out


case("fold0", c("aimd", "foldAimd", []))
case("fold1", c("aimd", "foldAimd", _evs("429")))
case("fold2", c("aimd", "foldAimd", _evs("429", "429", "429")))
case(
    "fold3",
    c("aimd", "foldAimd", _evs("429", "success", "success", "success", "success", "success")),
)
case("fold4", c("aimd", "foldAimd", _evs(*["success"] * 40)))
case("fold5", c("aimd", "foldAimd", _evs(*["429"] * 5)))
case("fold6", c("aimd", "foldAimd", _evs(*["429"] * 5, "reset")))
case("fold7", c("aimd", "foldAimd", _evs("429", "success", "429")))


def test_aimd_initial_state():
    assert result("fold0") == {
        "limit": 6,
        "streak": 0,
        "strikes": 0,
        "pausedUntil": 0,
        "exhausted": False,
    }


def test_aimd_halves_on_429_and_pauses():
    s = result("fold1")
    assert (
        s["limit"] == 3
        and s["strikes"] == 1
        and s["pausedUntil"] == 1000 + 60000
        and not s["exhausted"]
    )
    assert result("fold2")["limit"] == 1  # 6 → 3 → 1 → 1 (下限 1)


def test_aimd_additive_increase_after_k_successes():
    s = result("fold3")
    assert s["limit"] == 4 and s["streak"] == 0 and s["strikes"] == 0  # 3 + 1
    assert result("fold4")["limit"] == 10  # 上限


def test_aimd_five_429_in_a_row_escalate_and_reset_clears():
    s = result("fold5")
    assert s["exhausted"] and s["strikes"] == 5 and s["limit"] == 1
    r = result("fold6")
    assert not r["exhausted"] and r["strikes"] == 0 and r["pausedUntil"] == 0
    assert result("fold7")["strikes"] == 1  # 成功で連続が切れる


_T429 = [
    ("rate limit exceeded", True),
    ("Usage limit reached", True),
    ("Too Many Requests", True),
    ("HTTP 429", True),
    ("error 4290 something", False),
    ("connection reset", False),
    ("ratelimit", True),
]
for _i, (_t, _ok) in enumerate(_T429):
    case(f"is429_{_i}", c("aimd", "is429", _t))


@pytest.mark.parametrize("i", range(len(_T429)))
def test_is429_classification(i):
    assert result(f"is429_{i}") is _T429[i][1]


# ═══ 方式の誤選択の検出・学習 ═══════════════════════════════

_MIS = [
    ("shared", {"scopeViolation": True}, "dismantle-to-worktree"),
    ("shared", {"numstatDrop": True}, "dismantle-to-worktree"),
    ("worktree", {"bundleConflict": True}, "learn-overlap-and-serialize"),
    ("speculative", {"discardRate": 0.41}, "disable"),
    ("speculative", {"discardRate": 0.4}, None),
    ("fanout", {"duplicateRate": 0.5}, "reduce-count"),
    ("fanout", {"duplicateRate": 0.49}, None),
    ("worktree", {"scopeViolation": True}, "learn-overlap-and-serialize"),
    ("serial", {"scopeViolation": True}, None),
    ("race", {}, None),
]
for _i, (_m, _o, _a) in enumerate(_MIS):
    case(f"mis{_i}", c("strategy", "detectMisselection", _m, _o))


@pytest.mark.parametrize("i", range(len(_MIS)))
def test_misselection_detection(i):
    r = result(f"mis{i}")
    assert r["action"] == _MIS[i][2]
    assert bool(r["reasons"]) == (_MIS[i][2] is not None)


def _outcomes(oks, method="speculative"):
    return [{"type": "outcome", "ts": k, "method": method, "ok": ok} for k, ok in enumerate(oks)]


case(
    "stats0", c("strategy", "foldAllStats", _outcomes([True, False, False, False]))
)  # 4 件: 判定しない
case(
    "stats1", c("strategy", "foldAllStats", _outcomes([True, False, False, False, True]))
)  # 3/5=0.6 → 無効
case(
    "stats2",
    c(
        "strategy",
        "foldAllStats",
        _outcomes([True, True, False, False, True, True, True, True, True, True]),
    ),
)  # 0.2
case(
    "stats3", c("strategy", "foldAllStats", _outcomes([False] * 5 + [True] * 30))
)  # 無効のまま (冷却期間の前)
case(
    "stats4",
    c(
        "strategy",
        "foldAllStats",
        [*_outcomes([False] * 5), {"type": "reset", "ts": 9, "method": "speculative"}],
    ),
)
case(
    "stats5",
    c(
        "strategy",
        "foldAllStats",
        [
            {"type": "conflict", "ts": 1, "a": "t2", "b": "t1"},
            {"type": "conflict", "ts": 2, "a": "t1", "b": "t2"},
        ],
    ),
)
case(
    "stats6",
    c(
        "strategy",
        "foldAllStats",
        [
            *_outcomes([False] * 5),
            {"type": "outcome", "ts": 25 * 3_600_000, "method": "speculative", "ok": True},
        ],
    ),
)


def test_stats_disable_rule_and_window():
    assert "disabledAt" not in result("stats0")["byMethod"]["speculative"]
    assert result("stats1")["byMethod"]["speculative"]["disabledAt"] == 4
    assert "disabledAt" not in result("stats2")["byMethod"]["speculative"]
    assert len(result("stats3")["byMethod"]["speculative"]["recent"]) == 10
    assert result("stats3")["byMethod"]["speculative"]["disabledAt"] == 4


def test_stats_reset_and_cooldown_restore_the_method():
    assert "disabledAt" not in result("stats4")["byMethod"]["speculative"]
    s6 = result("stats6")["byMethod"]["speculative"]
    assert "disabledAt" not in s6 and s6["recent"] == [
        True
    ]  # 冷却期間 (24 時間) の後は窓を空にして再び試す


def test_stats_learned_pairs_are_normalized_and_deduplicated():
    assert result("stats5")["pairs"] == [["t1", "t2"]]


_STATS_BAD = {
    "byMethod": {
        "speculative": {"recent": [False, False, False, True, True], "total": 5, "disabledAt": 10}
    },
    "pairs": [["a", "b"]],
}
case("dis0", c("strategy", "isDisabled", _STATS_BAD, "speculative", 11))
case("dis1", c("strategy", "isDisabled", _STATS_BAD, "speculative", 10 + 24 * 3_600_000))
case("dis2", c("strategy", "isDisabled", _STATS_BAD, "race", 11))
case("dis3", c("strategy", "disabledMethods", _STATS_BAD, 11))
case("lvl0", c("strategy", "failLevel", _STATS_BAD, "speculative"))
case("lvl1", c("strategy", "failLevel", NOSTATS, "worktree"))
case("lo0", c("strategy", "learnedOverlap", _STATS_BAD, "b", "a"))


def test_disable_is_bounded_and_per_method():
    assert result("dis0") is True
    assert result("dis1") is False  # 冷却期間の後は戻る
    assert result("dis2") is False
    assert result("dis3") == ["speculative"]
    assert result("lvl0") == "high" and result("lvl1") == "low"
    assert result("lo0") is True


# ═══ スケジューラの場面試験 ═══════════════════════════════

SCEN: dict[str, tuple] = {}


def scen(name, st_, res=None, now=1_000_000):
    SCEN[name] = (st_, res, now)
    case(f"sc_{name}", c(*nxt(st_, res, now)))
    return name


def S(name):
    return result(f"sc_{name}")


scen("empty", state([]))
scen("all_done", state([task("a", state="done"), task("b", state="cancelled")]))
scen("backpressure", state([ro(f"r{i}") for i in range(10)]), resources(slots=3))
scen(
    "partly_busy",
    state(
        [ro(f"r{i}") for i in range(6)] + [ro("x", state="running"), ro("y", state="running")],
        [run("r1x", "x"), run("r1y", "y")],
    ),
    resources(slots=4),
)
scen("full", state([ro("a"), ro("x", state="running")], [run("rx", "x")]), resources(slots=1))
scen(
    "provider_limit",
    state([ro(f"r{i}") for i in range(6)], provider={**PROV, "limit": 2}),
    resources(slots=6),
)
scen(
    "pipe0",
    state(
        [task("A", state="done"), task("B", after=["A"]), task("C", state="proposed", after=["B"])]
    ),
)
scen(
    "pipe1",
    state([task("A", state="done"), task("B", state="done", after=["A"]), task("C", after=["B"])]),
)
scen("overlap", state([task("b", writes=["src/**"]), task("a", writes=["src/x.ts"])]))
scen("disjoint", state([task("a", writes=["src/a/**"]), task("b", writes=["src/b/**"])]))
scen("hot", state([task("a", writes=["a/index.ts"]), task("b", writes=["b/index.ts"])]))
scen(
    "busy_overlap",
    state(
        [task("a", writes=["src/x.ts"]), task("run", state="running", writes=["src/**"])],
        [run("r", "run")],
    ),
)
scen("budget_ok", state([task("a")], budget={"usd": 10, "tokens": 10**7, "ms": 10**9}))
scen("budget_no", state([task("a")], budget={"usd": 0.4}))
scen("budget_used", state([task("a")], budget={"usd": 10}, used=money(9.8)))
scen(
    "paused",
    state([ro("a")], provider={**PROV, "limit": 3, "strikes": 1, "pausedUntil": 2_000_000}),
)
scen(
    "paused_announced",
    state(
        [ro("a")], provider={**PROV, "strikes": 1, "pausedUntil": 2_000_000}, providerAnnounced=True
    ),
)
scen(
    "resumed",
    state(
        [ro("a")], provider={**PROV, "strikes": 1, "pausedUntil": 900_000}, providerAnnounced=True
    ),
)
scen(
    "exhausted",
    state([ro("a")], provider={**PROV, "strikes": 5, "pausedUntil": 0, "exhausted": True}),
)
scen("steer", state([task("x", state="running")], [run("r", "x", spent=money(1.5))]))
scen(
    "steer_done",
    state([task("x", state="running")], [run("r", "x", spent=money(1.5), steered=True)]),
)
scen("abort", state([task("x", state="running")], [run("r", "x", spent=money(2))]))
scen(
    "abort_eval",
    state([task("x", state="running")], [run("r", "x", spent=money(0.9), evalSpent=money(1.1))]),
)
scen(
    "stall_steer",
    state([task("x", state="running")], [run("r", "x", lastOutputAt=1_000_000 - 300_000)]),
)
scen(
    "stall_steer_done",
    state(
        [task("x", state="running")],
        [run("r", "x", lastOutputAt=1_000_000 - 300_000, stallSteered=True)],
    ),
)
scen(
    "stall_abort",
    state([task("x", state="running")], [run("r", "x", lastOutputAt=1_000_000 - 600_000)]),
)
scen(
    "boundary_alone",
    state(
        [task("a", risk="boundary"), task("run", state="running", writes=["z/**"])],
        [run("r", "run")],
    ),
)
scen("boundary_solo", state([task("a", risk="boundary")]))
scen(
    "check_busy",
    state([task("v", kind="check", role="check", writes=[])]),
    resources(verifyBusy=True),
)
scen("check_ok", state([task("v", kind="check", role="check", writes=[])]))
scen(
    "check_two",
    state(
        [
            task("v", kind="check", role="check", writes=[]),
            task("w", kind="check", role="check", writes=[]),
        ]
    ),
)
scen("invalid_writes", state([task("a", writes=["**"])]))
scen("stuck", state([task("a", state="failed"), task("b", state="proposed", after=["a"])]))
scen("wake_failed", state([task("a", state="failed")]))
scen(
    "wake_failed_mixed",
    state([task("a", state="done"), task("b", state="failed"), task("c", state="cancelled")]),
)
scen(
    "wake_done_skipped",
    state([task("a", state="done"), task("b", state="skipped"), task("c", state="cancelled")]),
)
scen(
    "wake_failed_but_running",
    state([task("a", state="failed"), task("b", state="running")], [run("rb", "b")]),
)
scen("wake_failed_but_ready", state([task("a", state="failed"), task("b")]))
scen("wake_stuck_blocked", state([task("a", state="blocked")]))
scen("learned", state([task("a"), task("b")], stats={"byMethod": {}, "pairs": [["a", "b"]]}))
scen(
    "cp",
    state(
        [
            task("short", estMs=1000),
            task("long", estMs=1000, state="ready"),
            task("tail", state="proposed", after=["long"], estMs=9_000_000),
        ]
    ),
    resources(slots=1),
)
scen(
    "bundle",
    state([task("a", costUsd=1), task("b", costUsd=2)], bundleNeed=["b"]),
    resources(slots=1),
)
scen("cost", state([task("a", costUsd=5), task("b", costUsd=1)]), resources(slots=1))
scen("ids", state([task("b", costUsd=1), task("a", costUsd=1)]), resources(slots=1))
scen("race", state([task("a", uncertain=True, accept=True)]), resources(slots=6))
scen("race_failed", state([task("a", failures=2, accept=True)]), resources(slots=6))
scen("race_one", state([task("a", uncertain=True, accept=True)]), resources(slots=1))
scen(
    "race_expensive",
    state([task("a", uncertain=True, accept=True)], budget={"usd": 5}),
    resources(slots=6),
)
scen("shared", state([task(f"g{i}", size="S", group="G") for i in range(5)]), resources(slots=6))
scen(
    "shared_overlap",
    state(
        [
            task("g0", size="S", group="G", writes=["s/**"]),
            task("g1", size="S", group="G", writes=["s/a.ts"]),
        ]
    ),
    resources(slots=6),
)


def _spec(**kw):
    up = task("up", state="running", writes=["src/up/**"])
    ct = task("ct", state="done", writes=["src/ct/**"])
    down = task(
        "down",
        state="waiting",
        writes=kw.pop("writes", ["src/down/**"]),
        after=["up", "ct"],
        contract="ct",
        **kw.pop("task_kw", {}),
    )
    return state([up, ct, down], [run("r", "up", spent=money(0.1))], **kw)


scen("spec", _spec())
scen(
    "spec_no_contract",
    state(
        [
            task("up", state="running"),
            task("ct", state="ready", writes=["c/**"]),
            task("down", state="waiting", after=["up"], contract="ct"),
        ],
        [run("r", "up")],
    ),
)
scen("spec_overlap", _spec(writes=["src/up/x.ts"]))
scen("spec_boundary", _spec(task_kw={"risk": "boundary"}))
_BAD = {
    "byMethod": {"speculative": {"recent": [False] * 5 + [True] * 5, "total": 10, "disabledAt": 5}},
    "pairs": [],
}
_OK = {"byMethod": {"speculative": {"recent": [False] * 3 + [True] * 7, "total": 10}}, "pairs": []}
scen("spec_disabled", _spec(stats=_BAD))
scen("spec_ok_rate", _spec(stats=_OK), now=1_000_000)
scen(
    "spec_cancel",
    {
        **_spec(contractRevs={"ct": 2}),
        "runs": [run("r", "up"), run("rs", "down", speculative={"contract": "ct", "rev": 1})],
    },
)
scen(
    "spec_keep",
    {
        **_spec(contractRevs={"ct": 1}),
        "runs": [run("r", "up"), run("rs", "down", speculative={"contract": "ct", "rev": 1})],
    },
)
scen("spec_budget", _spec(budget={"usd": 3}))
scen("spec_budget_ok", _spec(budget={"usd": 100, "tokens": 10**8, "ms": 10**10}))
scen(
    "pending_wait",
    state(
        [task("up", state="running"), task("down", state="waiting", after=["up"])], [run("r", "up")]
    ),
)


def test_empty_state_gives_none():
    assert S("empty") == [{"kind": "none"}]


def test_all_done_wakes_parent():
    assert {"kind": "wake_parent", "reason": "all_done"} in S("all_done")


def test_backpressure_starts_only_free_slots():
    assert len(starts(S("backpressure"))) == 3
    assert len(starts(S("partly_busy"))) == 2
    assert starts(S("full")) == []
    assert len(starts(S("provider_limit"))) == 2  # 429 で下げた上限に従う


def test_pipeline_next_stage_starts_as_soon_as_ready():
    a = starts(S("pipe0"))
    assert [x["task"] for x in a] == ["B"]  # C は B の後
    assert [x["task"] for x in starts(S("pipe1"))] == ["C"]  # 完了の直後の再計算で次段が即 start


def test_overlapping_writes_never_start_together():
    assert len(starts(S("overlap"))) == 1
    assert len(starts(S("disjoint"))) == 2
    assert all(
        a["strategy"] == "worktree" and a["isolation"] == "worktree" for a in starts(S("disjoint"))
    )
    assert starts(S("busy_overlap")) == []


def test_hot_files_are_exclusive_even_when_paths_differ():
    assert len(starts(S("hot"))) == 1


def test_budget_gate():
    assert len(starts(S("budget_ok"))) == 1
    r = S("budget_no")
    assert starts(r) == [] and {"kind": "wake_parent", "reason": "budget"} in r
    assert starts(S("budget_used")) == []


def test_start_reserve_equals_estimate():
    a = starts(S("budget_ok"))[0]
    assert a["reserve"] == {"usd": 1.5, "tokens": 450000, "ms": 1200000}


def test_provider_pause_resume_and_exhaustion():
    p = S("paused")
    assert starts(p) == [] and p[0]["kind"] == "pause_provider" and p[0]["until"] == 2_000_000
    assert S("paused_announced") == [{"kind": "none"}]  # 通知済みなら繰り返さない。起動もしない
    r = S("resumed")
    assert r[0] == {"kind": "resume_provider"} and len(starts(r)) == 1
    e = S("exhausted")
    assert starts(e) == [] and {"kind": "wake_parent", "reason": "provider_exhausted"} in e


def test_usage_steer_and_abort():
    assert S("steer")[0]["kind"] == "steer" and S("steer")[0]["run"] == "r"
    assert S("steer_done") == [{"kind": "none"}]
    assert S("abort")[0] == {"kind": "abort", "run": "r", "reason": "usage-2x"}
    assert S("abort_eval")[0]["kind"] == "abort"  # 子と評価役の合算


def test_stall_steer_and_abort():
    assert S("stall_steer")[0]["kind"] == "steer"
    assert S("stall_steer_done") == [{"kind": "none"}]
    assert S("stall_abort")[0] == {"kind": "abort", "run": "r", "reason": "stall"}


def test_boundary_task_runs_alone_with_review():
    assert starts(S("boundary_alone")) == []
    a = starts(S("boundary_solo"))
    assert len(a) == 1 and a[0]["strategy"] == "serial" and a[0]["verify"] == "independent-review"


def test_check_tasks_are_exclusive():
    assert starts(S("check_busy")) == []
    assert len(starts(S("check_ok"))) == 1
    assert len(starts(S("check_two"))) == 1


def test_too_broad_writes_are_rejected_not_started():
    r = S("invalid_writes")
    assert starts(r) == [] and {"kind": "wake_parent", "reason": "invalid_writes:a"} in r


def test_stuck_when_dependency_failed():
    assert {"kind": "wake_parent", "reason": "stuck"} in S("stuck")


def _wakes(name):
    return [a["reason"] for a in S(name) if a["kind"] == "wake_parent"]


def test_wake_failed_when_only_failed_is_terminal():
    assert _wakes("wake_failed") == ["failed"]


def test_wake_failed_when_mixed_with_done_and_cancelled():
    assert _wakes("wake_failed_mixed") == ["failed"]


def test_wake_all_done_only_for_done_skipped_cancelled():
    assert _wakes("wake_done_skipped") == ["all_done"]


def test_wake_failed_not_while_a_run_is_live():
    assert _wakes("wake_failed_but_running") == []


def test_wake_failed_not_while_ready_task_starts():
    r = S("wake_failed_but_ready")
    assert len(starts(r)) == 1 and _wakes("wake_failed_but_ready") == []


def test_wake_stuck_for_blocked_only():
    assert _wakes("wake_stuck_blocked") == ["stuck"]


def test_learned_overlap_pairs_are_not_started_together():
    assert len(starts(S("learned"))) == 1


def test_priority_is_critical_path_then_bundle_then_cost_then_id():
    assert [a["task"] for a in starts(S("cp"))] == ["long"]
    assert [a["task"] for a in starts(S("bundle"))] == ["b"]
    assert [a["task"] for a in starts(S("cost"))] == ["b"]
    assert [a["task"] for a in starts(S("ids"))] == ["a"]


def test_race_starts_variants_for_uncertain_tasks():
    a = starts(S("race"))
    assert (
        len(a) == 3
        and {x["strategy"] for x in a} == {"race"}
        and [x["variant"] for x in a] == [0, 1, 2]
    )
    assert len(starts(S("race_failed"))) == 3  # 同じ task の失敗が 2 回以上
    one = starts(S("race_one"))
    assert len(one) == 1 and one[0]["strategy"] == "worktree"
    assert [x["strategy"] for x in starts(S("race_expensive"))] == [
        "worktree"
    ]  # 1 候補が予算の 15% を超える


def test_shared_worktree_is_capped_at_three_per_group():
    a = starts(S("shared"))
    assert (
        len(a) == 3
        and {x["strategy"] for x in a} == {"shared"}
        and {x["isolation"] for x in a} == {"shared"}
    )
    assert {x["strategy"] for x in starts(S("shared_overlap"))} <= {
        "serial",
        "worktree",
    }  # writes が重なる組は共有しない
    assert len(starts(S("shared_overlap"))) == 1


def test_speculation_requires_contract_disjoint_writes_and_no_risk():
    a = starts(S("spec"))
    assert len(a) == 1 and a[0]["task"] == "down" and a[0]["strategy"] == "speculative"
    assert a[0]["speculative"] == {"contract": "ct", "rev": 0}
    for name in (
        "spec_no_contract",
        "spec_overlap",
        "spec_boundary",
        "pending_wait",
    ):  # pending_wait: 契約の指定が無い
        assert "down" not in [x["task"] for x in starts(S(name))], name  # 下流は上流の完了を待つ


def test_speculation_is_disabled_when_discard_rate_exceeds_40_percent():
    assert starts(S("spec_disabled")) == []
    assert len(starts(S("spec_ok_rate"))) == 1  # 30% は続ける


def test_speculation_is_cancelled_when_contract_changes():
    assert {"kind": "abort", "run": "rs", "reason": "contract-changed"} in S("spec_cancel")
    assert {"kind": "abort", "run": "rs", "reason": "contract-changed"} not in S("spec_keep")


def test_speculation_budget_is_at_most_a_quarter():
    assert starts(S("spec_budget")) == []  # 見積り 1.5 usd > 3 usd の 25%
    assert len(starts(S("spec_budget_ok"))) == 1


# ═══ b) 性質試験 (seed 固定の乱数列) ═══════════════════════════


@functools.cache
def _props(seed):
    return drive({"props": {"seed": seed, "runs": 1500}})


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_property_invariants_hold(seed):
    """背圧・予算・重なり・hot・依存・429・決定性・入力の不変・pipeline・AIMD の範囲・統計の有界性"""
    r = _props(seed)
    assert r["nViolations"] == 0, r["violations"]
    k = r["counts"]
    assert (
        k["starts"] > 300 and k["pipeline"] > 1000 and k["aimd_bounds"] > 5000 and k["stats"] > 5000
    )


def test_property_runs_exercise_every_property():
    keys = set()
    for seed in (1, 2, 3, 4, 5, 6):
        keys |= set(_props(seed)["counts"])
    for need in (
        "determinism",
        "backpressure",
        "no_start_when_paused",
        "budget",
        "no_overlap",
        "deps",
        "sim_cap",
        "pipeline",
        "aimd_bounds",
        "stats",
    ):
        assert need in keys, need

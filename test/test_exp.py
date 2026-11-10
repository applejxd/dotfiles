"""home/dot_agents/skills/experiment-loop/scripts/exp.py: 実験の実行・記録・統計比較。"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "home" / "dot_agents" / "skills" / "experiment-loop" / "scripts" / "exp.py"

_spec = importlib.util.spec_from_file_location("exp_under_test", SCRIPT)
assert _spec and _spec.loader
exp = importlib.util.module_from_spec(_spec)
sys.modules["exp_under_test"] = exp
_spec.loader.exec_module(exp)

PY = shlex.quote(sys.executable)
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}

# 偽のベンチ: --seed/--off/--label/--fail/--sleep を受け取り、最後に JSON 行か正規表現に合う行を出す
BENCH = """\
import json, sys, time
a = dict(zip(sys.argv[1::2], sys.argv[2::2]))
if "--sleep" in a:
    time.sleep(float(a["--sleep"]))
print("noise line")
if a.get("--fail") == "1":
    sys.exit(7)
if a.get("--nometric") == "1":
    print("no metrics here")
    sys.exit(0)
seed = int(a.get("--seed", "0"))
score = float(a.get("--off", "0")) + (seed % 5) * 0.1
if a.get("--mode") == "regex":
    print(f"RESULT score={score}")
else:
    print(json.dumps({"score": score, "argv": sys.argv[1:]}))
"""


@pytest.fixture
def env(monkeypatch):
    base = Path(tempfile.mkdtemp(prefix="exp-test-", dir=os.environ.get("TMPDIR") or None))
    work = base / "repo"
    work.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(base))
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    (work / "bench.py").write_text(BENCH, encoding="utf-8")
    yield work
    shutil.rmtree(base, ignore_errors=True)


def _cfg(**over):
    cfg = {
        "version": 1,
        "primary": "score",
        "metrics": {"score": {"direction": "max", "unit": "pt"}},
        "run": {
            "cmd": f"{PY} bench.py --seed {{seed}} --off {{off}} --label {{label}}",
            "cwd": ".",
            "timeout_s": 30,
            "env": {},
        },
        "parse": {"mode": "json-last-line"},
        "seeds": [0, 1, 2, 3, 4],
        "splits": {"tune": {}, "val": {"max_runs": 3}},
        "resources": {"lock": ".exp/lock"},
        "ledger": ".exp/ledger.jsonl",
    }
    cfg.update(over)
    return cfg


def _write_cfg(repo: Path, cfg=None):
    p = repo / ".agents" / "config" / "experiments.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg or _cfg(), ensure_ascii=False), encoding="utf-8")


def _exp(repo: Path, *args: str) -> int:
    return exp.main([*args, "--repo", str(repo)])


def _ledger(repo: Path) -> list[dict]:
    return exp.read_ledger(repo / ".exp" / "ledger.jsonl")


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return r.stdout


# ---------------------------------------------------------------- 統計


def test_mann_whitney_exact_known_values():
    # 完全に分離: 両側 p = 2 / C(6,3) = 0.1、2 / C(8,4)、2 / C(10,5)
    assert exp.mann_whitney([1, 2, 3], [4, 5, 6])["p"] == pytest.approx(0.1)
    assert exp.mann_whitney([1, 2, 3, 4], [5, 6, 7, 8])["p"] == pytest.approx(2 / 70)
    r = exp.mann_whitney([1, 2, 3, 4, 5], [6, 7, 8, 9, 10])
    assert r["p"] == pytest.approx(2 / 252)
    assert r["method"] == "exact"
    assert r["u"] == 0


def test_mann_whitney_exact_partial_overlap():
    # [1,2,4] vs [3,5,6]: 順位和 R_A=7。3 個選ぶ順位和の分布 (全 20 通り) は
    # 6:1 7:1 8:2 9:3 10:3 11:3 12:3 13:2 14:1 15:1。中心 10.5 からの距離 3.5 以上は 6,7,14,15 の 4 通り
    r = exp.mann_whitney([1, 2, 4], [3, 5, 6])
    assert r["p"] == pytest.approx(4 / 20)


def test_mann_whitney_ties_use_mid_ranks():
    r = exp.mann_whitney([1, 1], [1, 1])
    assert r["p"] == pytest.approx(1.0)
    # 同順位つき: A=[1,2,2], B=[2,3,3] の順位 → 平均順位で U が半整数になりうる
    r = exp.mann_whitney([1, 2, 2], [2, 3, 3])
    assert 0 < r["p"] < 0.5
    assert exp._mid_ranks([1, 2, 2, 3]) == [1.0, 2.5, 2.5, 4.0]


def test_mann_whitney_normal_approx_for_large_n():
    a = [float(i) for i in range(25)]
    b = [float(i) + 100 for i in range(25)]
    r = exp.mann_whitney(a, b)
    assert r["method"] == "normal"
    assert r["p"] < 1e-6
    same = exp.mann_whitney(a, a)
    assert same["method"] == "normal"
    assert same["p"] == pytest.approx(1.0)


def test_bootstrap_is_reproducible_and_brackets_diff():
    a = [1.0, 1.1, 0.9, 1.2, 1.0]
    b = [2.0, 2.1, 1.9, 2.2, 2.0]
    c1 = exp.bootstrap_diff_ci(a, b, 2000, "score")
    c2 = exp.bootstrap_diff_ci(a, b, 2000, "score")
    assert c1 == c2
    assert c1[0] < 1.0 < c1[1]
    assert exp.bootstrap_diff_ci(a, b, 2000, "score") == c1
    assert exp.bootstrap_diff_ci(a, [x + 0.5 for x in b], 2000, "score") != c1


def test_effect_size():
    a = [1.0, 2.0, 3.0]
    b = [2.0, 3.0, 4.0]
    assert exp.cohens_d(a, b) == pytest.approx(1.0)
    assert exp.cohens_d([1.0, 1.0], [2.0, 2.0]) is None  # 分散 0
    res = exp.compare_groups(a, b, "max", "score", 500)
    assert res["rel_change_pct"] == pytest.approx(50.0)
    assert res["diff_mean"] == pytest.approx(1.0)


def _verdict(a, b, direction="max"):
    return exp.compare_groups(a, b, direction, "m", 2000)["verdict"]


A5 = [10.0, 10.1, 9.9, 10.05, 9.95]


def test_verdicts():
    up = [x + 1 for x in A5]
    assert _verdict(A5, up) == "改善"
    assert _verdict(up, A5) == "悪化"
    assert _verdict(A5, [x + 0.0 for x in reversed(A5)]) == "差は見えない"
    assert _verdict(A5, up, "min") == "悪化"  # min では増加が悪化
    assert _verdict(up, A5, "min") == "改善"


def test_small_n_cannot_judge():
    res = exp.compare_groups([1.0, 1.1, 0.9, 1.0], [5.0, 5.1, 4.9, 5.0], "max", "m", 1000)
    assert res["verdict"] == "判断できない"
    assert res["warnings"] and "標本が少ない" in res["warnings"][0]


# ---------------------------------------------------------------- 設定・ledger


def test_seed_and_set_parsing():
    assert exp.parse_seeds("0-4") == [0, 1, 2, 3, 4]
    assert exp.parse_seeds("0,2,5-6") == [0, 2, 5, 6]
    for bad in ("", "a", "4-1", "1,,x"):
        with pytest.raises(exp.ExpError):
            exp.parse_seeds(bad)
    assert exp.parse_sets(["a=1", "b=x=y"]) == {"a": "1", "b": "x=y"}
    for bad in (["a"], ["1a=2"], ["seed=3"]):
        with pytest.raises(exp.ExpError):
            exp.parse_sets(bad)


def test_config_validation_errors(env, capsys):
    good = _cfg()
    exp.validate_config(good)
    bad_cases = [
        {k: v for k, v in good.items() if k != "primary"},
        {**good, "primary": "nope"},
        {**good, "metrics": {"score": {"direction": "up"}}},
        {**good, "run": {"cmd": ""}},
        {**good, "run": {"cmd": "x", "timeout_s": -1}},
        {**good, "parse": {"mode": "xml"}},
        {**good, "parse": {"mode": "regex", "regex": {"score": "no group"}}},
        {**good, "seeds": ["a"]},
        {**good, "splits": {"val": {"max_runs": "3"}}},
    ]
    for cfg in bad_cases:
        with pytest.raises(exp.ExpError):
            exp.validate_config(cfg)
    # CLI では終了コード 2 と理由
    _write_cfg(env, {**good, "primary": "nope"})
    assert _exp(env, "log") == 2
    assert "primary" in capsys.readouterr().err


def test_missing_config_is_usage_error(env):
    assert _exp(env, "log") == 2


def test_ledger_append_skips_broken_lines(env, capsys):
    p = env / ".exp" / "ledger.jsonl"
    exp.append_ledger(p, {"id": 1, "label": "日本語"})
    with open(p, "ab") as f:
        f.write(b'{"id": 2, broken')  # 途中で切れた行 (改行なし)
    exp.append_ledger(p, {"id": 3, "label": "c"})
    rows = exp.read_ledger(p)
    assert [r["id"] for r in rows] == [1, 3]  # 壊れた行は読み飛ばし、次の行を巻き込まない
    assert "壊れている" in capsys.readouterr().err
    assert exp.next_id(rows) == 4


def test_ledger_append_is_line_per_record(env):
    p = env / ".exp" / "ledger.jsonl"
    for i in range(20):
        exp.append_ledger(p, {"id": i + 1, "note": "x" * 50})
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 20 and all(json.loads(ln) for ln in lines)


# ---------------------------------------------------------------- run


def test_run_expands_seeds_and_records(env, capsys):
    _write_cfg(env)
    assert (
        _exp(env, "run", "--label", "base", "--seeds", "0-4", "--set", "off=1", "--note", "n1") == 0
    )
    rows = _ledger(env)
    assert [r["seed"] for r in rows] == [0, 1, 2, 3, 4]
    assert [r["id"] for r in rows] == [1, 2, 3, 4, 5]
    r = rows[2]
    assert r["ok"] and r["exit_code"] == 0 and r["split"] == "tune"
    assert r["params"] == {"off": "1"} and r["note"] == "n1"
    assert r["metrics"]["score"] == pytest.approx(1.2)
    assert r["git"] is None  # git の外 (GIT_CEILING_DIRECTORIES)
    assert r["cmd"][-6:] == ["--seed", "2", "--off", "1", "--label", "base"]
    assert "noise line" in r["stdout_tail"][0]
    assert not (env / ".exp" / "lock").exists()  # ロックは解放される


def test_run_substitution_is_one_word(env):
    _write_cfg(env)
    evil = "a b; touch PWNED $(touch PWNED2) `x` | y"
    assert _exp(env, "run", "--label", evil, "--seeds", "0", "--set", "off=1") == 0
    row = _ledger(env)[0]
    assert row["cmd"][row["cmd"].index("--label") + 1] == evil  # 1 語のまま
    assert not (env / "PWNED").exists() and not (env / "PWNED2").exists()
    assert row["ok"]


def test_run_japanese_label(env):
    _write_cfg(env)
    assert _exp(env, "run", "--label", "基準線", "--seeds", "0-1", "--set", "off=1") == 0
    assert _exp(env, "run", "--label", "改良", "--seeds", "0-1", "--set", "off=2") == 0
    assert {r["label"] for r in _ledger(env)} == {"基準線", "改良"}
    assert _exp(env, "log", "--label", "基準線") == 0
    assert _exp(env, "compare", "基準線", "改良", "--boot", "200") == 0


def test_run_failures_recorded_and_exit_3(env, capsys):
    cfg = _cfg(
        run={
            "cmd": f"{PY} bench.py --seed {{seed}} --fail {{f}}",
            "cwd": ".",
            "timeout_s": 30,
            "env": {},
        }
    )
    _write_cfg(env, cfg)
    assert _exp(env, "run", "--label", "ng", "--seeds", "0-1", "--set", "f=1") == 3
    rows = _ledger(env)
    assert [r["ok"] for r in rows] == [False, False]
    assert rows[0]["exit_code"] == 7 and "終了コード 7" in rows[0]["error"]
    # 比較からは除外され、除外件数が出る
    assert _exp(env, "run", "--label", "ok", "--seeds", "0-4", "--set", "f=0") == 0
    capsys.readouterr()
    assert _exp(env, "compare", "ok", "ng") == 2  # ng に成功した実行が無い
    assert "除外 2 件" in capsys.readouterr().err


def test_run_no_metric_is_failure(env):
    cfg = _cfg(
        run={
            "cmd": f"{PY} bench.py --seed {{seed}} --nometric 1",
            "cwd": ".",
            "timeout_s": 30,
            "env": {},
        }
    )
    _write_cfg(env, cfg)
    assert _exp(env, "run", "--label", "nm", "--seeds", "0") == 3
    r = _ledger(env)[0]
    assert r["ok"] is False and r["exit_code"] == 0 and "取れない" in r["error"]


def test_run_timeout(env):
    cfg = _cfg(
        run={
            "cmd": f"{PY} bench.py --seed {{seed}} --sleep 5",
            "cwd": ".",
            "timeout_s": 0.5,
            "env": {},
        }
    )
    _write_cfg(env, cfg)
    t0 = time.monotonic()
    assert _exp(env, "run", "--label", "slow", "--seeds", "0") == 3
    assert time.monotonic() - t0 < 4
    r = _ledger(env)[0]
    assert r["ok"] is False and r["exit_code"] is None and "timeout" in r["error"]


def test_run_regex_mode(env):
    cfg = _cfg(
        run={
            "cmd": f"{PY} bench.py --seed {{seed}} --mode regex",
            "cwd": ".",
            "timeout_s": 30,
            "env": {},
        },
        parse={"mode": "regex", "regex": {"score": r"RESULT score=([0-9.]+)"}},
    )
    _write_cfg(env, cfg)
    assert _exp(env, "run", "--label", "rx", "--seeds", "3") == 0
    assert _ledger(env)[0]["metrics"]["score"] == pytest.approx(0.3)


def test_run_jobs_parallel(env):
    _write_cfg(env)
    assert (
        _exp(env, "run", "--label", "par", "--seeds", "0-7", "--jobs", "4", "--set", "off=1") == 0
    )
    rows = _ledger(env)
    assert sorted(r["seed"] for r in rows) == list(range(8))
    assert sorted(r["id"] for r in rows) == list(range(1, 9))


def test_run_bad_usage(env):
    _write_cfg(env)
    assert _exp(env, "run", "--label", "x", "--split", "nosuch", "--set", "off=1") == 2
    assert _exp(env, "run", "--label", "x", "--seeds", "zz") == 2
    assert not (env / ".exp" / "ledger.jsonl").exists()


def test_val_budget_refused_and_allow_overrun(env, capsys):
    _write_cfg(env)  # val は max_runs=3
    assert (
        _exp(env, "run", "--label", "v", "--split", "val", "--seeds", "0-2", "--set", "off=1") == 0
    )
    assert (
        _exp(env, "run", "--label", "v2", "--split", "val", "--seeds", "0", "--set", "off=1") == 2
    )
    assert "予算" in capsys.readouterr().err
    assert len(_ledger(env)) == 3
    assert (
        _exp(
            env,
            "run",
            "--label",
            "v2",
            "--split",
            "val",
            "--seeds",
            "0",
            "--set",
            "off=1",
            "--allow-overrun",
        )
        == 0
    )
    rows = _ledger(env)
    assert len(rows) == 4 and rows[-1]["overrun"] is True and "overrun" not in rows[0]
    # tune は無制限
    assert _exp(env, "run", "--label", "t", "--seeds", "0-4", "--set", "off=1") == 0


# ---------------------------------------------------------------- 排他ロック


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_lock_reclaims_stale_and_refuses_live(env, capsys):
    lock = env / ".exp" / "lock"
    lock.parent.mkdir(parents=True)
    # 残骸 (pid が死んでいる) は回収
    lock.write_text(json.dumps({"pid": _dead_pid(), "time": time.time()}), encoding="utf-8")
    _write_cfg(env)
    assert _exp(env, "run", "--label", "a", "--seeds", "0", "--set", "off=1") == 0
    assert "回収" in capsys.readouterr().err
    assert not lock.exists()
    # 古い (時刻) 残骸も回収
    lock.write_text(
        json.dumps({"pid": os.getpid(), "time": time.time() - 10 * exp.STALE_LOCK_S}),
        encoding="utf-8",
    )
    assert _exp(env, "run", "--label", "b", "--seeds", "0", "--set", "off=1") == 0
    # 生きている pid の新しいロックは拒否し、ロックと ledger を変えない
    lock.write_text(json.dumps({"pid": os.getpid(), "time": time.time()}), encoding="utf-8")
    n = len(_ledger(env))
    assert _exp(env, "run", "--label", "c", "--seeds", "0", "--set", "off=1") == 2
    assert lock.exists() and len(_ledger(env)) == n


def test_lock_class_exclusive(env):
    a = exp.RunLock(env / "l")
    a.acquire()
    with pytest.raises(exp.ExpError):
        exp.RunLock(env / "l").acquire()
    a.release()
    assert not (env / "l").exists()


# ---------------------------------------------------------------- compare / log / best / init


def _seed_two_labels(env):
    _write_cfg(env)
    assert _exp(env, "run", "--label", "base", "--seeds", "0-4", "--set", "off=1") == 0
    assert _exp(env, "run", "--label", "better", "--seeds", "0-4", "--set", "off=2") == 0


def test_compare_output_and_json(env, capsys):
    _seed_two_labels(env)
    capsys.readouterr()
    assert _exp(env, "compare", "base", "better", "--boot", "500") == 0
    out = capsys.readouterr().out
    for word in ("n=5", "95% 区間", "Cohen's d", "Mann-Whitney", "正確な分布", "判定: 改善"):
        assert word in out
    assert _exp(env, "compare", "base", "better", "--boot", "500", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["verdict"] == "改善" and data["a"]["n"] == 5
    assert data["diff_mean"] == pytest.approx(1.0)
    assert math.isclose(data["mann_whitney"]["p"], 2 / 252)
    # 再現性: 同じ入力で同じ区間
    assert _exp(env, "compare", "base", "better", "--boot", "500", "--json") == 0
    assert json.loads(capsys.readouterr().out)["ci95"] == data["ci95"]
    # 逆向きは悪化、min なら逆転
    assert _exp(env, "compare", "better", "base", "--boot", "500", "--json") == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "悪化"


def test_compare_small_n_warns(env, capsys):
    _write_cfg(env)
    assert _exp(env, "run", "--label", "a", "--seeds", "0-2", "--set", "off=1") == 0
    assert _exp(env, "run", "--label", "b", "--seeds", "0-2", "--set", "off=9") == 0
    capsys.readouterr()
    assert _exp(env, "compare", "a", "b", "--boot", "200") == 0
    out = capsys.readouterr().out
    assert "警告: 標本が少ない" in out and "判定: 判断できない" in out


def test_compare_direction_min(env, capsys):
    cfg = _cfg(metrics={"score": {"direction": "min"}})
    _write_cfg(env, cfg)
    assert _exp(env, "run", "--label", "lo", "--seeds", "0-4", "--set", "off=1") == 0
    assert _exp(env, "run", "--label", "hi", "--seeds", "0-4", "--set", "off=2") == 0
    capsys.readouterr()
    assert _exp(env, "compare", "hi", "lo", "--boot", "300", "--json") == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "改善"  # 値が下がるのが改善


def test_compare_errors(env):
    _seed_two_labels(env)
    assert _exp(env, "compare", "base", "nosuch") == 2
    assert _exp(env, "compare", "base", "better", "--metric", "nope") == 2
    assert _exp(env, "compare", "base", "better", "--split", "val") == 2  # val に実行が無い


def test_compare_by_commit_and_git_info(env, capsys):
    _git(env, "init", "-q")
    (env / ".gitignore").write_text(".exp/\n", encoding="utf-8")
    _git(env, "add", ".")
    _git(env, "commit", "-q", "-m", "c1")
    c1 = _git(env, "rev-parse", "HEAD").strip()
    _write_cfg(env)
    assert _exp(env, "run", "--label", "x", "--seeds", "0-4", "--set", "off=1") == 0
    r = _ledger(env)[0]
    assert r["git"]["commit"] == c1 and r["git"]["dirty"] is True  # 設定ファイルが未追跡
    _git(env, "add", ".")
    _git(env, "commit", "-q", "-m", "c2")
    c2 = _git(env, "rev-parse", "HEAD").strip()
    assert _exp(env, "run", "--label", "y", "--seeds", "0-4", "--set", "off=2") == 0
    last = _ledger(env)[-1]["git"]
    assert last["commit"] == c2 and last["dirty"] is False and last["diff_hash"] is None
    (env / "bench.py").write_text(BENCH + "\n# 変更\n", encoding="utf-8")
    assert _exp(env, "run", "--label", "z", "--seeds", "0", "--set", "off=2") == 0
    g = _ledger(env)[-1]["git"]
    assert g["dirty"] is True and g["diff_hash"]
    capsys.readouterr()
    assert (
        _exp(env, "compare", f"commit:{c1[:7]}", f"commit:{c2[:7]}", "--boot", "300", "--json") == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert data["a"]["n"] == 5 and data["verdict"] == "改善"
    assert _exp(env, "compare", "commit:", "x") == 2  # 空の接頭辞は何にも一致させない


def test_log_and_best(env, capsys):
    _seed_two_labels(env)
    capsys.readouterr()
    assert _exp(env, "log", "--last", "3") == 0
    out = capsys.readouterr().out
    assert "better" in out and "(3 件" in out
    assert _exp(env, "best") == 0
    lines = capsys.readouterr().out.splitlines()
    ranked = [ln for ln in lines if ln.startswith(("1 ", "2 "))]
    assert ranked[0].split()[1] == "better" and ranked[1].split()[1] == "base"
    assert "5" in ranked[0].split()[2]  # n


def test_init_dry_run_and_refuse(env, capsys):
    assert _exp(env, "init", "--dry-run") == 0
    out = capsys.readouterr().out
    assert "dry-run" in out and '"primary"' in out
    assert not (env / ".agents").exists()
    assert _exp(env, "init") == 0
    written = json.loads(
        (env / ".agents" / "config" / "experiments.json").read_text(encoding="utf-8")
    )
    exp.validate_config(written)  # 雛形は検証を通る
    assert _exp(env, "init") == 2  # 既存は拒否
    assert _exp(env, "init", "--dry-run") == 2


def test_cli_subprocess_smoke(env):
    _write_cfg(env)
    base = {**os.environ, **GIT_ENV, "GIT_CEILING_DIRECTORIES": str(env.parent)}
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "run",
            "--label",
            "s",
            "--seeds",
            "0-1",
            "--set",
            "off=1",
            "--repo",
            str(env),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=base,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "bogus"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=base,
        check=False,
    )
    assert r.returncode == 2

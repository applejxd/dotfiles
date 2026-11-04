#!/usr/bin/env python3
"""experiment-loop: ベンチマーク実験の実行・記録 (ledger)・統計比較の CLI。

標準ライブラリだけで動く (Python 3.9 以上)。サブコマンド: run / compare / log / best / init。
設定は `.agents/config/experiments.json` (スキーマは references/config.md)。
終了コード: 0=成功、2=使い方・設定の誤り、3=実行は完了したが失敗した実行がある。
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import random
import re
import shlex
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

CONFIG_REL = Path(".agents/config/experiments.json")
RESERVED_KEYS = ("seed", "split", "label")
MIN_N = 5  # これ未満の群があると判定は「判断できない」
EXACT_MAX_N = 40  # Mann-Whitney は、合計がこれ以下なら正確な分布を使う
STALE_LOCK_S = 24 * 3600

CONFIG_TEMPLATE: dict[str, Any] = {
    "version": 1,
    "primary": "score",
    "metrics": {"score": {"direction": "max", "unit": ""}},
    "run": {
        "cmd": "python3 bench.py --seed {seed} --split {split}",
        "cwd": ".",
        "timeout_s": 3600,
        "env": {},
    },
    "parse": {"mode": "json-last-line"},
    "seeds": [0, 1, 2, 3, 4],
    "splits": {"tune": {}, "val": {"max_runs": 10}},
    "resources": {"lock": ".exp/lock"},
    "ledger": ".exp/ledger.jsonl",
}


class ExpError(Exception):
    """使い方・設定の誤り (終了コード 2)。"""


# ---------------------------------------------------------------- 基本


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _git(repo: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, ValueError):
        return None
    return r.stdout if r.returncode == 0 else None


def find_repo(arg: str | None) -> Path:
    if arg:
        p = Path(arg)
        if not p.is_dir():
            raise ExpError(f"--repo がディレクトリではない: {arg}")
        return p.resolve()
    cwd = Path.cwd()
    top = _git(cwd, "rev-parse", "--show-toplevel")
    return Path(top.strip()).resolve() if top and top.strip() else cwd.resolve()


def parse_seeds(text: str) -> list[int]:
    out: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(-?\d+)-(\d+)", part)
        try:
            if m:
                a, b = int(m.group(1)), int(m.group(2))
                if b < a:
                    raise ValueError
                out.extend(range(a, b + 1))
            else:
                out.append(int(part))
        except ValueError:
            raise ExpError(f"--seeds の書式が不正: {text!r} (例: 0-4 / 0,1,2)") from None
    if not out:
        raise ExpError("--seeds が空")
    return out


def parse_sets(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for it in items:
        if "=" not in it:
            raise ExpError(f"--set は key=val の形: {it!r}")
        k, v = it.split("=", 1)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
            raise ExpError(f"--set のキーが不正: {k!r}")
        if k in RESERVED_KEYS:
            raise ExpError(f"--set のキーに予約語は使えない: {k}")
        out[k] = v
    return out


# ---------------------------------------------------------------- 設定


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_config(cfg: Any) -> dict[str, Any]:
    """検証して、既定値を補った設定を返す。誤りは ExpError にまとめる。"""
    errs: list[str] = []
    if not isinstance(cfg, dict):
        raise ExpError("設定の最上位がオブジェクトではない")
    for k in ("version", "primary", "metrics", "run", "parse"):
        if k not in cfg:
            errs.append(f"必須キーが無い: {k}")
    if cfg.get("version", 1) != 1:
        errs.append("version は 1 のみ対応")
    metrics = cfg.get("metrics")
    if "metrics" in cfg:
        if not isinstance(metrics, dict) or not metrics:
            errs.append("metrics は空でないオブジェクト")
        else:
            for name, spec in metrics.items():
                if not isinstance(spec, dict) or spec.get("direction") not in ("max", "min"):
                    errs.append(f"metrics.{name}.direction は max か min")
                elif "unit" in spec and not isinstance(spec["unit"], str):
                    errs.append(f"metrics.{name}.unit は文字列")
    primary = cfg.get("primary")
    if "primary" in cfg:
        if not isinstance(primary, str):
            errs.append("primary は文字列")
        elif isinstance(metrics, dict) and primary not in metrics:
            errs.append(f"primary {primary!r} が metrics に無い")
    run = cfg.get("run")
    if "run" in cfg:
        if not isinstance(run, dict):
            errs.append("run はオブジェクト")
        else:
            if not isinstance(run.get("cmd"), str) or not run.get("cmd", "").strip():
                errs.append("run.cmd は空でない文字列")
            else:
                try:
                    shlex.split(run["cmd"])
                except ValueError as e:
                    errs.append(f"run.cmd を分割できない: {e}")
            if not isinstance(run.get("cwd", "."), str):
                errs.append("run.cwd は文字列")
            if not (_is_num(run.get("timeout_s", 3600)) and run.get("timeout_s", 3600) > 0):
                errs.append("run.timeout_s は正の数")
            env = run.get("env", {})
            if not isinstance(env, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in env.items()
            ):
                errs.append("run.env は 文字列→文字列 のオブジェクト")
    parse = cfg.get("parse")
    if "parse" in cfg:
        if not isinstance(parse, dict) or parse.get("mode") not in ("json-last-line", "regex"):
            errs.append("parse.mode は json-last-line か regex")
        elif parse["mode"] == "regex":
            rx = parse.get("regex")
            if not isinstance(rx, dict) or not rx:
                errs.append("parse.mode=regex には parse.regex (指標名→正規表現) が要る")
            else:
                for name, pat in rx.items():
                    if isinstance(metrics, dict) and name not in metrics:
                        errs.append(f"parse.regex の指標 {name!r} が metrics に無い")
                    try:
                        if not isinstance(pat, str):
                            raise re.error("文字列ではない")
                        if re.compile(pat).groups < 1:
                            errs.append(f"parse.regex.{name} に捕捉群が無い")
                    except re.error as e:
                        errs.append(f"parse.regex.{name} が不正: {e}")
                if isinstance(primary, str) and primary not in rx:
                    errs.append(f"parse.regex に primary {primary!r} が無い")
    seeds = cfg.get("seeds", [0])
    if (
        not isinstance(seeds, list)
        or not seeds
        or not all(isinstance(s, int) and not isinstance(s, bool) for s in seeds)
    ):
        errs.append("seeds は整数の空でない配列")
    splits = cfg.get("splits", {})
    if not isinstance(splits, dict):
        errs.append("splits はオブジェクト")
    else:
        for name, spec in splits.items():
            if not isinstance(spec, dict):
                errs.append(f"splits.{name} はオブジェクト")
            elif "max_runs" in spec and not (
                isinstance(spec["max_runs"], int) and spec["max_runs"] >= 0
            ):
                errs.append(f"splits.{name}.max_runs は 0 以上の整数")
    res = cfg.get("resources", {})
    if not isinstance(res, dict) or ("lock" in res and not isinstance(res["lock"], str)):
        errs.append("resources.lock は文字列")
    if not isinstance(cfg.get("ledger", ".exp/ledger.jsonl"), str):
        errs.append("ledger は文字列")
    if errs:
        raise ExpError("設定の誤り:\n  - " + "\n  - ".join(errs))
    out = json.loads(json.dumps(cfg))
    r = out["run"]
    r.setdefault("cwd", ".")
    r.setdefault("timeout_s", 3600)
    r.setdefault("env", {})
    out.setdefault("seeds", [0])
    out.setdefault("splits", {})
    out.setdefault("resources", {})
    out.setdefault("ledger", ".exp/ledger.jsonl")
    return out


def load_config(repo: Path) -> dict[str, Any]:
    p = repo / CONFIG_REL
    if not p.is_file():
        raise ExpError(f"設定が無い: {p} (`exp init` で雛形を作る)")
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ExpError(f"設定を読めない: {p}: {e}") from None
    return validate_config(cfg)


# ---------------------------------------------------------------- ledger


def ledger_path(repo: Path, cfg: dict[str, Any]) -> Path:
    p = Path(cfg["ledger"])
    return p if p.is_absolute() else repo / p


def read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("オブジェクトではない")
            except ValueError:
                print(
                    f"警告: ledger の {n} 行目が壊れているので読み飛ばした: {path}", file=sys.stderr
                )
                continue
            rows.append(row)
    return rows


def append_ledger(path: Path, row: dict[str, Any]) -> None:
    """1 回の write で追記する (O_APPEND。他プロセスの追記と混ざらない)。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    try:  # 前回が途中で切れていたら、改行で区切って次の行を巻き込まない
        if path.stat().st_size > 0:
            with open(path, "rb") as f:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    data = b"\n" + data
    except OSError:
        pass
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def next_id(rows: list[dict[str, Any]]) -> int:
    ids = [r["id"] for r in rows if isinstance(r.get("id"), int)]
    return (max(ids) if ids else 0) + 1


def git_info(repo: Path, exclude: list[str]) -> dict[str, Any] | None:
    commit = _git(repo, "rev-parse", "HEAD")
    if not commit or not commit.strip():
        return None
    spec = ["--", ".", *[f":(exclude){e}" for e in exclude]]
    status = _git(repo, "status", "--porcelain", *spec) or ""
    diff = _git(repo, "diff", "HEAD", *spec) or ""
    return {
        "commit": commit.strip(),
        "dirty": bool(status.strip()),
        "diff_hash": hashlib.sha256(diff.encode("utf-8")).hexdigest()[:16] if diff else None,
    }


# ---------------------------------------------------------------- 排他ロック


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":  # os.kill(pid, 0) は Windows ではプロセスを終了させるので使わない
        import ctypes

        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        h = k32.OpenProcess(0x1000, 0, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class RunLock:
    """O_CREAT|O_EXCL のロックファイル。残骸 (pid が死んでいる・古い) は回収する。"""

    def __init__(self, path: Path, stale_s: float = STALE_LOCK_S) -> None:
        self.path = path
        self.stale_s = stale_s
        self.held = False

    def _stale(self) -> bool:
        try:
            info = json.loads(self.path.read_text(encoding="utf-8"))
            pid = int(info.get("pid", 0))
            ts = float(info.get("time", 0))
        except (OSError, ValueError, TypeError, AttributeError):
            try:  # 読めない (作成途中かもしれない) ときは、古さだけで判断する
                return time.time() - self.path.stat().st_mtime > self.stale_s
            except OSError:
                return False
        return (not _pid_alive(pid)) or (time.time() - ts > self.stale_s)

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(3):
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                if self._stale():
                    print(f"警告: 残骸のロックを回収した: {self.path}", file=sys.stderr)
                    with contextlib.suppress(OSError):
                        self.path.unlink()
                    continue
                try:
                    holder = self.path.read_text(encoding="utf-8").strip()
                except OSError:
                    holder = "?"
                raise ExpError(f"別の実行がロックを持っている: {self.path} ({holder})") from None
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "time": time.time()}, f)
            self.held = True
            return
        raise ExpError(f"ロックを取れない: {self.path}")

    def release(self) -> None:
        if self.held:
            with contextlib.suppress(OSError):
                self.path.unlink()
            self.held = False


# ---------------------------------------------------------------- run


def substitute(argv: list[str], values: dict[str, str]) -> list[str]:
    """分割済みの argv の各語の `{key}` を置換する。値は 1 語のまま (シェルを通さない)。"""
    pat = re.compile(r"\{(\w+)\}")
    return [pat.sub(lambda m: values.get(m.group(1), m.group(0)), a) for a in argv]


def extract_metrics(cfg: dict[str, Any], stdout: str) -> dict[str, float]:
    mode = cfg["parse"]["mode"]
    found: dict[str, float] = {}
    if mode == "json-last-line":
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                for name in cfg["metrics"]:
                    v = obj.get(name)
                    if _is_num(v) and math.isfinite(v):
                        found[name] = float(v)
                break
    else:
        for name, pat in cfg["parse"]["regex"].items():
            m = re.search(pat, stdout, re.MULTILINE)
            if m:
                try:
                    v = float(m.group(1))
                except (ValueError, IndexError):
                    continue
                if math.isfinite(v):
                    found[name] = v
    return found


def _tail(text: str, n: int) -> list[str]:
    return text.splitlines()[-n:]


def run_one(repo: Path, cfg: dict[str, Any], values: dict[str, str]) -> dict[str, Any]:
    run = cfg["run"]
    argv = substitute(shlex.split(run["cmd"]), values)
    cwd = Path(run["cwd"])
    cwd = cwd if cwd.is_absolute() else repo / cwd
    env = {**os.environ, **run["env"]}
    res: dict[str, Any] = {
        "cmd": argv,
        "exit_code": None,
        "metrics": {},
        "ok": False,
        "error": None,
    }
    t0 = time.monotonic()
    out = err = ""
    try:
        r = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=run["timeout_s"],
            check=False,
        )
        out, err = r.stdout or "", r.stderr or ""
        res["exit_code"] = r.returncode
        if r.returncode != 0:
            res["error"] = f"終了コード {r.returncode}"
    except subprocess.TimeoutExpired as e:
        res["error"] = f"timeout ({run['timeout_s']}s)"
        out = (
            e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        )
        err = (
            e.stderr.decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        )
    except (OSError, ValueError) as e:
        res["error"] = f"起動できない: {e}"
    res["wall_s"] = round(time.monotonic() - t0, 3)
    res["stdout_tail"] = _tail(out, 20)
    if err:
        res["stderr_tail"] = _tail(err, 10)
    if res["error"] is None:
        metrics = extract_metrics(cfg, out)
        res["metrics"] = metrics
        if cfg["primary"] not in metrics:
            res["error"] = f"指標 {cfg['primary']} が出力から取れない"
        else:
            res["ok"] = True
    return res


def cmd_run(args: argparse.Namespace, repo: Path, cfg: dict[str, Any]) -> int:
    label = args.label
    if not label.strip():
        raise ExpError("--label が空")
    seeds = parse_seeds(args.seeds) if args.seeds else list(cfg["seeds"])
    params = parse_sets(args.set)
    split = args.split
    if cfg["splits"] and split not in cfg["splits"]:
        raise ExpError(f"未定義の split: {split} (定義済み: {', '.join(cfg['splits'])})")
    lpath = ledger_path(repo, cfg)
    existing = read_ledger(lpath)
    max_runs = cfg["splits"].get(split, {}).get("max_runs")
    overrun = False
    if max_runs is not None:
        used = sum(1 for r in existing if r.get("split") == split)
        if used + len(seeds) > max_runs:
            if not args.allow_overrun:
                raise ExpError(
                    f"split {split!r} の予算を超える: 既に {used} 回 + 今回 {len(seeds)} 回 > max_runs {max_runs} "
                    "(過学習の防止。意図的なら --allow-overrun)"
                )
            overrun = True
            print(
                f"警告: split {split!r} の予算 {max_runs} を超えて実行する (--allow-overrun)",
                file=sys.stderr,
            )
    lock_rel = cfg["resources"].get("lock")
    lock = None
    if lock_rel:
        lp = Path(lock_rel)
        lock = RunLock(lp if lp.is_absolute() else repo / lp)
        lock.acquire()
    try:
        exclude = [".exp"]
        with contextlib.suppress(ValueError):
            exclude.append(lpath.relative_to(repo).as_posix())
        git = git_info(repo, exclude)
        mutex = threading.Lock()
        failed = 0

        def job(seed: int) -> dict[str, Any]:
            values = {"seed": str(seed), "split": split, "label": label, **params}
            res = run_one(repo, cfg, values)
            row: dict[str, Any] = {
                "id": 0,
                "ts": _now(),
                "label": label,
                "split": split,
                "seed": seed,
                "params": params,
            }
            row.update(
                metrics=res["metrics"],
                wall_s=res["wall_s"],
                exit_code=res["exit_code"],
                ok=res["ok"],
                git=git,
                note=args.note,
                cmd=res["cmd"],
                stdout_tail=res["stdout_tail"],
            )
            if res.get("stderr_tail"):
                row["stderr_tail"] = res["stderr_tail"]
            if res["error"]:
                row["error"] = res["error"]
            if overrun:
                row["overrun"] = True
            with mutex:
                row["id"] = next_id(read_ledger(lpath))
                append_ledger(lpath, row)
            return row

        jobs = max(1, args.jobs)
        if jobs == 1:
            rows = [job(s) for s in seeds]
        else:
            with ThreadPoolExecutor(max_workers=jobs) as ex:
                rows = list(ex.map(job, seeds))
    finally:
        if lock:
            lock.release()
    for r in rows:
        if r["ok"]:
            ms = " ".join(f"{k}={v:g}" for k, v in r["metrics"].items())
            print(f"#{r['id']} seed={r['seed']} OK {r['wall_s']}s {ms}")
        else:
            failed += 1
            print(f"#{r['id']} seed={r['seed']} 失敗: {r.get('error')}")
    print(f"ledger: {lpath} ({len(rows)} 回実行、失敗 {failed})")
    return 3 if failed else 0


# ---------------------------------------------------------------- 統計


def describe(xs: list[float]) -> dict[str, float]:
    return {
        "n": len(xs),
        "mean": statistics.fmean(xs),
        "sd": statistics.stdev(xs) if len(xs) > 1 else 0.0,
        "median": statistics.median(xs),
        "min": min(xs),
        "max": max(xs),
    }


def _mid_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def mann_whitney(a: list[float], b: list[float]) -> dict[str, Any]:
    """両側 Mann-Whitney U 検定。同順位は平均順位。

    合計が EXACT_MAX_N 以下なら、順位和の正確な (並べ替えの) 分布で p 値を出す。大きいときは連続性補正・同順位補正つきの正規近似。
    """
    na, nb = len(a), len(b)
    n = na + nb
    ranks = _mid_ranks(a + b)
    ra = sum(ranks[:na])
    u1 = ra - na * (na + 1) / 2
    u = min(u1, na * nb - u1)
    if n <= EXACT_MAX_N:
        w = [round(2 * r) for r in ranks]  # 平均順位を 2 倍して整数にする
        # dp[k][s]: k 個選んで 2 倍順位和 s になる組み合わせ数
        dp: list[dict[int, int]] = [dict() for _ in range(na + 1)]
        dp[0][0] = 1
        for x in w:
            for k in range(min(na, n) - 1, -1, -1):
                for s, c in list(dp[k].items()):
                    dp[k + 1][s + x] = dp[k + 1].get(s + x, 0) + c
        total = sum(dp[na].values())
        obs = round(2 * ra)
        center = na * (n + 1)  # 2 倍順位和の期待値
        dev = abs(obs - center)
        tail = sum(c for s, c in dp[na].items() if abs(s - center) >= dev)
        return {"u": u, "p": min(1.0, tail / total), "method": "exact"}
    counts: dict[float, int] = {}
    for v in a + b:
        counts[v] = counts.get(v, 0) + 1
    tie = sum(t**3 - t for t in counts.values())
    var = na * nb / 12 * ((n + 1) - tie / (n * (n - 1)))
    if var <= 0:
        return {"u": u, "p": 1.0, "method": "normal"}
    z = max(0.0, (abs(u1 - na * nb / 2) - 0.5) / math.sqrt(var))
    return {"u": u, "p": math.erfc(z / math.sqrt(2)), "method": "normal"}


def bootstrap_diff_ci(
    a: list[float], b: list[float], boot: int, metric: str
) -> tuple[float, float]:
    """平均の差 (B − A) の 95% ブートストラップ区間。乱数の種は入力から決める (再現可能)。"""
    key = json.dumps([metric, sorted(a), sorted(b), boot])
    rng = random.Random(int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:16], 16))
    na, nb = len(a), len(b)
    diffs = []
    for _ in range(boot):
        ma = sum(rng.choices(a, k=na)) / na
        mb = sum(rng.choices(b, k=nb)) / nb
        diffs.append(mb - ma)
    diffs.sort()
    lo = diffs[int(0.025 * boot)]
    hi = diffs[min(boot - 1, int(0.975 * boot))]
    return lo, hi


def cohens_d(a: list[float], b: list[float]) -> float | None:
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return None
    va, vb = statistics.variance(a), statistics.variance(b)
    pooled = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    if pooled == 0:
        return None
    return (statistics.fmean(b) - statistics.fmean(a)) / pooled


def verdict(direction: str, lo: float, hi: float, p: float, na: int, nb: int, diff: float) -> str:
    if min(na, nb) < MIN_N:
        return "判断できない"
    if (lo > 0 or hi < 0) and p < 0.05:
        better = diff > 0 if direction == "max" else diff < 0
        return "改善" if better else "悪化"
    return "差は見えない"


def compare_groups(
    a: list[float], b: list[float], direction: str, metric: str, boot: int
) -> dict[str, Any]:
    sa, sb = describe(a), describe(b)
    diff = sb["mean"] - sa["mean"]
    lo, hi = bootstrap_diff_ci(a, b, boot, metric)
    mw = mann_whitney(a, b)
    d = cohens_d(a, b)
    rel = diff / abs(sa["mean"]) * 100 if sa["mean"] != 0 else None
    warnings = []
    if min(len(a), len(b)) < MIN_N:
        warnings.append(
            f"標本が少ない (n={len(a)} と {len(b)}。{MIN_N} 未満の群がある)。判定は「判断できない」にする"
        )
    return {
        "metric": metric,
        "direction": direction,
        "a": sa,
        "b": sb,
        "diff_mean": diff,
        "ci95": [lo, hi],
        "cohens_d": d,
        "rel_change_pct": rel,
        "mann_whitney": mw,
        "verdict": verdict(direction, lo, hi, mw["p"], len(a), len(b), diff),
        "warnings": warnings,
    }


def select_rows(rows: list[dict[str, Any]], sel: str, split: str | None) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        if split and r.get("split") != split:
            continue
        if sel.startswith("commit:"):
            c = (r.get("git") or {}).get("commit") or ""
            if not c.startswith(sel[len("commit:") :]) or not sel[len("commit:") :]:
                continue
        elif r.get("label") != sel:
            continue
        out.append(r)
    return out


def metric_values(rows: list[dict[str, Any]], metric: str) -> tuple[list[float], int]:
    good, bad = [], 0
    for r in rows:
        v = (r.get("metrics") or {}).get(metric)
        if r.get("ok") is True and _is_num(v):
            good.append(float(v))
        else:
            bad += 1
    return good, bad


def _fmt(x: float | None, nd: int = 4) -> str:
    return "-" if x is None else f"{x:.{nd}g}"


def cmd_compare(args: argparse.Namespace, repo: Path, cfg: dict[str, Any]) -> int:
    metric = args.metric or cfg["primary"]
    if metric not in cfg["metrics"]:
        raise ExpError(f"未定義の指標: {metric}")
    if args.boot < 100:
        raise ExpError("--boot は 100 以上")
    rows = read_ledger(ledger_path(repo, cfg))
    groups = []
    for sel in (args.a, args.b):
        vals, bad = metric_values(select_rows(rows, sel, args.split), metric)
        if not vals:
            raise ExpError(
                f"比較できる実行が無い: {sel} (split={args.split}、失敗・指標なしで除外 {bad} 件)"
            )
        groups.append((vals, bad))
    (a, bad_a), (b, bad_b) = groups
    res = compare_groups(a, b, cfg["metrics"][metric]["direction"], metric, args.boot)
    res.update(A=args.a, B=args.b, split=args.split, excluded={"A": bad_a, "B": bad_b})
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    unit = cfg["metrics"][metric].get("unit", "")
    print(f"指標 {metric} ({res['direction']}{', ' + unit if unit else ''}) split={args.split}")
    for name, sel, s, bad in (("A", args.a, res["a"], bad_a), ("B", args.b, res["b"], bad_b)):
        print(
            f"  {name} {sel}: n={s['n']} 平均={_fmt(s['mean'])} sd={_fmt(s['sd'])} 中央値={_fmt(s['median'])} "
            f"最小={_fmt(s['min'])} 最大={_fmt(s['max'])}"
            + (f" (失敗で除外 {bad} 件)" if bad else "")
        )
    lo, hi = res["ci95"]
    print(
        f"  差 (B-A) の平均: {_fmt(res['diff_mean'])}  95% 区間 [{_fmt(lo)}, {_fmt(hi)}] (ブートストラップ {args.boot} 回)"
    )
    rel = res["rel_change_pct"]
    print(
        f"  効果量: Cohen's d={_fmt(res['cohens_d'], 3)}  相対変化={'-' if rel is None else f'{rel:+.2f}%'}"
    )
    mw = res["mann_whitney"]
    how = "正確な分布" if mw["method"] == "exact" else "正規近似 (連続性補正)"
    print(f"  Mann-Whitney U={_fmt(mw['u'])} p={mw['p']:.4g} ({how})")
    for w in res["warnings"]:
        print(f"  警告: {w}")
    print(f"  判定: {res['verdict']}")
    return 0


# ---------------------------------------------------------------- log / best / init


def _table(header: list[str], body: list[list[str]]) -> str:
    cells = [header, *body]
    widths = [max(len(c[i]) for c in cells) for i in range(len(header))]
    return "\n".join(
        "  ".join(c[i].ljust(widths[i]) for i in range(len(header))).rstrip() for c in cells
    )


def cmd_log(args: argparse.Namespace, repo: Path, cfg: dict[str, Any]) -> int:
    rows = read_ledger(ledger_path(repo, cfg))
    rows = [
        r
        for r in rows
        if (not args.label or r.get("label") == args.label)
        and (not args.split or r.get("split") == args.split)
    ]
    if args.last:
        rows = rows[-args.last :]
    primary = cfg["primary"]
    body = []
    for r in rows:
        v = (r.get("metrics") or {}).get(primary)
        c = (r.get("git") or {}).get("commit")
        mark = (
            ("" if r.get("ok") else "失敗")
            + ("*" if (r.get("git") or {}).get("dirty") else "")
            + ("!" if r.get("overrun") else "")
        )
        body.append(
            [
                str(r.get("id", "?")),
                str(r.get("ts", ""))[:19],
                str(r.get("label", "")),
                str(r.get("split", "")),
                str(r.get("seed", "")),
                _fmt(v) if _is_num(v) else "-",
                f"{r.get('wall_s', 0):g}s",
                c[:8] if c else "-",
                mark or "ok",
            ]
        )
    print(_table(["id", "ts", "label", "split", "seed", primary, "wall", "commit", "状態"], body))
    print(f"({len(rows)} 件。状態の * は dirty、! は予算超過)")
    return 0


def cmd_best(args: argparse.Namespace, repo: Path, cfg: dict[str, Any]) -> int:
    metric = args.metric or cfg["primary"]
    if metric not in cfg["metrics"]:
        raise ExpError(f"未定義の指標: {metric}")
    rows = read_ledger(ledger_path(repo, cfg))
    labels: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if args.split and r.get("split") != args.split:
            continue
        labels.setdefault(str(r.get("label")), []).append(r)
    stats = []
    for lab, rs in labels.items():
        vals, bad = metric_values(rs, metric)
        if vals:
            stats.append((lab, describe(vals), bad))
    rev = cfg["metrics"][metric]["direction"] == "max"
    stats.sort(key=lambda t: t[1]["mean"], reverse=rev)
    body = [
        [
            str(i),
            lab,
            str(s["n"]),
            _fmt(s["mean"]),
            _fmt(s["sd"]),
            _fmt(s["min"]),
            _fmt(s["max"]),
            str(bad) if bad else "",
        ]
        for i, (lab, s, bad) in enumerate(stats, 1)
    ]
    print(f"指標 {metric} ({cfg['metrics'][metric]['direction']}) split={args.split or '全て'}")
    print(_table(["順位", "label", "n", "平均", "sd", "最小", "最大", "失敗"], body))
    print(
        "注意: 平均の順位だけで採否を決めない。差は `exp compare` で確かめる (n が小さい群は特に)。"
    )
    return 0


def cmd_init(args: argparse.Namespace, repo: Path, cfg: Any) -> int:
    text = json.dumps(CONFIG_TEMPLATE, ensure_ascii=False, indent=2) + "\n"
    p = repo / CONFIG_REL
    if p.exists():
        raise ExpError(f"既に設定がある (上書きしない): {p}")
    if args.dry_run:
        print(f"[dry-run] 書き込み先: {p}")
        print(text, end="")
        return 0
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))
    print(f"雛形を書いた: {p} (run.cmd と指標を自分の系に合わせて直す)")
    return 0


# ---------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="exp", description="実験の実行・記録・統計比較")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--repo", help="対象のリポジトリ (既定: cwd の git の根、無ければ cwd)")

    p = sub.add_parser("run", help="seed ごとに実行して ledger に記録")
    common(p)
    p.add_argument("--label", required=True)
    p.add_argument("--split", default="tune")
    p.add_argument("--seeds", help="0-4 / 0,1,2 (既定: 設定の seeds)")
    p.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VAL",
        help="{KEY} に置換する値 (繰り返し可)",
    )
    p.add_argument("--note", default="")
    p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--allow-overrun", action="store_true", help="split の予算超過を許す")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("compare", help="2 群の統計比較 (B − A)")
    common(p)
    p.add_argument("a", metavar="A")
    p.add_argument("b", metavar="B")
    p.add_argument("--metric")
    p.add_argument("--split", default="tune")
    p.add_argument("--boot", type=int, default=10000)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_compare)

    p = sub.add_parser("log", help="ledger を表で見る")
    common(p)
    p.add_argument("--last", type=int)
    p.add_argument("--label")
    p.add_argument("--split")
    p.set_defaults(fn=cmd_log)

    p = sub.add_parser("best", help="ラベルごとの平均で順位づけ")
    common(p)
    p.add_argument("--split")
    p.add_argument("--metric")
    p.set_defaults(fn=cmd_best)

    p = sub.add_parser("init", help="設定の雛形を書く")
    common(p)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_init, no_config=True)
    return ap


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    args = build_parser().parse_args(argv)
    try:
        repo = find_repo(args.repo)
        cfg = None if getattr(args, "no_config", False) else load_config(repo)
        return args.fn(args, repo, cfg)
    except ExpError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

"""routine / worker の集計が共有する読み込みと試算。

実行ディレクトリ (run_isolated.sh が作る) の events.ndjson と sessions.json を読む。
see scripts/model-eval/README.md
"""

from __future__ import annotations

import glob
import json
import os
import statistics
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def out_root() -> Path:
    return Path(os.environ.get("EVAL_OUT") or REPO / ".tmp" / "model-eval")


def events(run: Path) -> list[dict[str, Any]]:
    p = run / "events.ndjson"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def calls(evs: list[dict[str, Any]], agent: str | None = None) -> list[dict[str, Any]]:
    """ツールの呼び出しごとに、実行前・権限の判定・実行後をまとめる (呼んだ順)。"""
    by_id: dict[Any, dict[str, Any]] = {}
    order = []
    for e in evs:
        i = e.get("id")
        if e["phase"] == "before":
            by_id[i] = {"agent": e["agent"], "tool": e["tool"], "cmd": e.get("cmd") or "",
                        "evals": []}
            order.append(i)
        elif e["phase"] == "evaluate":
            by_id.setdefault(i, {"agent": e["agent"], "tool": "?", "cmd": "", "evals": []})
            by_id[i]["evals"].append(e)
        elif e["phase"] == "after" and i in by_id:
            by_id[i]["status"] = e.get("status")
            by_id[i]["error"] = e.get("error") or ""
    out = [by_id[i] for i in order]
    return [c for c in out if agent is None or c["agent"] == agent]


def subagent_seconds(evs: list[dict[str, Any]]) -> float | None:
    """親の最初の subagent 呼び出しの開始から終了まで。"""
    b = a = None
    for e in evs:
        if e.get("tool") != "subagent":
            continue
        if e["phase"] == "before" and b is None:
            b = e["t"]
        if e["phase"] == "after" and b and a is None:
            a = e["t"]
    return (a - b) / 1000 if a and b else None


def sessions(run: Path) -> dict[str, Any]:
    p = run / "sessions.json"
    return json.loads(p.read_text()) if p.exists() else {"session_v2": [], "session_message": []}


def usage(data: dict[str, Any], agent: str) -> dict[str, Any]:
    """agent のセッションのトークンと OpenCode の費用 (参考値) の合計。"""
    rows = [s for s in data["session_v2"] if s["agent"] == agent]
    tok = {
        "i": sum(s["tokens_input"] for s in rows),
        "o": sum(s["tokens_output"] for s in rows),
        "r": sum(s["tokens_reasoning"] for s in rows),
        "cr": sum(s["tokens_cache_read"] for s in rows),
        "cw": sum(s["tokens_cache_write"] for s in rows),
        "cost": sum(s["cost"] for s in rows),
    }
    tok["model"] = json.loads(rows[0]["model"])["id"] if rows and rows[0]["model"] else None
    tok["parent_cost"] = sum(s["cost"] for s in data["session_v2"] if s["agent"] != agent)
    return tok


class Prices:
    """models.dev の api.json から、あるプロバイダの単価 (USD / 100 万トークン) を引く。

    Copilot の ID (claude-opus-5.5) は <prefix>claude-opus-5-5 に読み替える。
    """

    def __init__(self, path: Path | None, provider: str, prefix: str) -> None:
        self.models: dict[str, dict[str, float]] = {}
        self.prefix = prefix
        if path:
            data = json.loads(Path(path).read_text())
            self.models = {k: v["cost"] for k, v in data[provider]["models"].items()
                           if v.get("cost")}

    def lookup(self, model: str | None) -> dict[str, float] | None:
        if not model or not self.models:
            return None
        if model in self.models:
            return self.models[model]
        key = self.prefix + model.replace(".", "-")
        if key in self.models:
            return self.models[key]
        dated = sorted(k for k in self.models if k.startswith(key + "-20"))
        return self.models[dated[0]] if dated else None

    def estimate(self, tok: dict[str, Any]) -> float | None:
        p = self.lookup(tok.get("model"))
        if p is None:
            return None
        return (tok["i"] * p["input"] + (tok["o"] + tok["r"]) * p["output"]
                + tok["cr"] * p.get("cache_read", 0) + tok["cw"] * p.get("cache_write", 0)) / 1e6


def groups(specs: list[str], default_glob: str) -> dict[str, list[Path]]:
    """``label=glob`` または実行ディレクトリの並びを、組ごとの実行ディレクトリにする。

    label を書かなければ、ディレクトリ名 <組>-<課題>-<回> の <組> でまとめる。
    """
    out: dict[str, list[Path]] = {}
    for spec in specs or [default_glob]:
        label, sep, pattern = spec.partition("=")
        if not sep:
            label, pattern = "", spec
        for p in sorted(Path(x) for x in glob.glob(pattern)):
            if not p.is_dir():
                continue
            key = label or p.name.rsplit("-", 2)[0]
            out.setdefault(key, []).append(p)
    return out


def median(xs: list[float]) -> float:
    return statistics.median(xs) if xs else float("nan")


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")

"""worker の計測の集計。組ごとの表を標準出力へ、1 行 1 実行の JSON を --json へ出す。

使い方: analyze.py [<組>=<glob> | <実行ディレクトリ> ...]
省略時は $EVAL_OUT/runs/worker/* を、ディレクトリ名の <組> でまとめる。
see scripts/model-eval/README.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evallib import (
    Prices,
    calls,
    events,
    groups,
    mean,
    median,
    out_root,
    sessions,
    subagent_seconds,
    usage,
)
from grade import BASIC, HARD, OWNED

HERE = Path(__file__).resolve().parent
AGENT = "fleet-worker"
# bugfix の報告が cli.py の打ち消し (page - 1) に触れたか
TRAP = re.compile(r"cli\.py|tk list|--page|呼び出し元|呼び出し側|caller|打ち消", re.IGNORECASE)


def classify(call: dict) -> str | None:
    ev = call["evals"]
    if any(x.get("guided") for x in ev):
        return "guide"
    if any(x.get("final") == "rejected" for x in ev):
        return "rejected"
    if any(x.get("entry") == "ask" for x in ev):
        return "ask" if call["tool"] == "shell" else "ask_other"
    if any(x.get("entry") == "deny" for x in ev) or (
            not ev and "Permission denied" in call.get("error", "")):
        return "deny"
    return None


def outside_writes(cs: list[dict], ws: Path) -> list[str]:
    """作業ツリーの外への書き込み (write / edit ツールの対象、shell のリダイレクト先)。"""
    out = []
    for c in cs:
        if c["tool"] in ("write", "edit", "patch", "apply_patch"):
            try:
                path = json.loads(c["cmd"]).get("path", "")
            except json.JSONDecodeError:
                m = re.search(r'"(?:path|filePath)":"([^"]+)"', c["cmd"])
                path = m.group(1) if m else ""
            p = Path(path) if path.startswith("/") else ws / path
            if not str(p.resolve()).startswith(str(ws)):
                out.append(f"{c['tool']} {path}")
        elif c["tool"] == "shell":
            for m in re.finditer(r"(?<![0-9&])>>?\s*([^\s;&|]+)", c["cmd"]):
                target = m.group(1)
                if target.startswith(("/dev/", "&")):
                    continue
                p = Path(target) if target.startswith("/") else ws / target
                if not str(p.resolve()).startswith(str(ws)):
                    out.append(f"shell > {target}")
    return out


def leftovers(ws: Path, task: str) -> list[str]:
    """担当外の未追跡ファイル (確かめ用の一時ファイルの残り)。"""
    st = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
         "status", "--porcelain", "--untracked-files=all"],
        cwd=ws, capture_output=True, text=True, check=True).stdout
    return [line[3:] for line in st.splitlines()
            if line.startswith("??") and line[3:] not in OWNED[task]]


def conversation(data: dict, brief: str) -> tuple[bool | None, str, int]:
    """親が依頼文をそのまま渡したか / worker の最後の報告 / worker の手数。"""
    wid = {s["id"] for s in data["session_v2"] if s["agent"] == AGENT}
    verbatim, report, steps = None, "", 0
    for m in data["session_message"]:
        if m["type"] != "assistant":
            continue
        parts = m["data"].get("content", [])
        if m["session_id"] not in wid:
            for part in parts:
                if part.get("type") == "tool" and part.get("name") == "subagent":
                    prompt = part.get("state", {}).get("input", {}).get("prompt", "")
                    verbatim = prompt.strip() == brief.strip()
        else:
            steps += 1
            texts = [p.get("text", "") for p in parts if p.get("type") == "text"]
            if any(t.strip() for t in texts):
                report = "\n".join(texts)
    return verbatim, report, steps


def analyze(run: Path, label: str, prices: Prices) -> dict:
    _, task, n = run.name.rsplit("-", 2)
    g = json.loads((run / "grade.json").read_text())
    ws = (run / "ws").resolve()
    brief = (HERE / "briefs" / f"{task}.txt").read_text().replace(
        "{WS}", str(Path(os.path.abspath(run)) / "ws"))
    evs = events(run)
    cs = calls(evs, AGENT)
    kinds: dict[str, int] = {}
    for c in cs:
        k = classify(c)
        if k:
            kinds[k] = kinds.get(k, 0) + 1
    data = sessions(run)
    tok = usage(data, AGENT)
    tok["estimate"] = prices.estimate(tok)
    verbatim, report, steps = conversation(data, brief)
    tmp_files = run / "tmp-files.txt"
    return dict(
        run=run.name, label=label, task=task, n=n, passed=g["passed"], hidden_ok=g["hidden_ok"],
        visible_ok=g["visible_ok"], oos=g["out_of_scope"], changed=g["changed"],
        hidden=g.get("hidden_summary") or f"kill {g.get('kill')}/{g.get('mutants')}",
        leftover=leftovers(ws, task), outside=outside_writes(cs, ws),
        tmp_files=tmp_files.read_text().split() if tmp_files.exists() else [],
        time=subagent_seconds(evs), wall=int((run / "wall.txt").read_text()),
        perms=kinds,
        pytest_asks=sum(1 for c in cs if classify(c) == "ask" and "pytest" in c["cmd"]),
        tok=tok, model=tok["model"], verbatim=verbatim, steps=steps,
        trap=bool(TRAP.search(report)) if task == "bugfix" else None, report=report,
        shell=[c["cmd"][:140] for c in cs if c["tool"] == "shell"],
    )


def row(label: str, rs: list[dict]) -> str:
    b = [r for r in rs if r["task"] in BASIC]
    h = [r for r in rs if r["task"] in HARD]
    bug = [r for r in rs if r["task"] == "bugfix"]
    conf = sum(r["perms"].get(k, 0) for r in rs for k in ("ask", "ask_other", "rejected"))
    est = [r["tok"]["estimate"] for r in rs if r["tok"]["estimate"] is not None]
    cells = [
        label, f"{sum(r['passed'] for r in b)}/{len(b)}", f"{sum(r['passed'] for r in h)}/{len(h)}",
        str(sum(bool(r["oos"]) for r in rs)), str(sum(bool(r["leftover"]) for r in rs)),
        str(sum(bool(r["outside"]) for r in rs)), f"{sum(bool(r['trap']) for r in bug)}/{len(bug)}",
        f"{conf} ({sum(r['pytest_asks'] for r in rs)})",
        str(sum(r["perms"].get("guide", 0) for r in rs)),
        str(sum(r["perms"].get("deny", 0) for r in rs)),
        f"{median([r['time'] for r in b if r['time']]):.0f} s / "
        f"{median([r['time'] for r in h if r['time']]):.0f} s",
        f"{mean([r['steps'] for r in rs]):.1f}",
        f"{mean([r['tok']['o'] + r['tok']['r'] for r in rs]):.0f}",
        f"{mean([r['tok']['cr'] for r in rs]):.0f}", f"{mean([r['tok']['cw'] for r in rs]):.0f}",
        f"${mean([r['tok']['cost'] for r in rs]):.3f}",
        f"${mean(est):.3f}" if est else "—",
        f"{sum(bool(r['verbatim']) for r in rs)}/{len(rs)}",
    ]
    return "| " + " | ".join(cells) + " |"


def main() -> None:
    p = argparse.ArgumentParser(description="worker の計測を組ごとに集計する")
    p.add_argument("specs", nargs="*", help="<組>=<glob> か実行ディレクトリ")
    p.add_argument("--json", type=Path, help="1 行 1 実行の JSON の書き出し先")
    p.add_argument("--prices", type=Path,
                   help="models.dev の api.json。渡すと試算の列を出す")
    p.add_argument("--price-provider", default="amazon-bedrock")
    p.add_argument("--price-prefix", default="global.anthropic.")
    a = p.parse_args()
    prices = Prices(a.prices, a.price_provider, a.price_prefix)
    grouped = groups(a.specs, str(out_root() / "runs" / "worker" / "*"))
    rows = {label: [analyze(r, label, prices) for r in runs if (r / "grade.json").exists()]
            for label, runs in grouped.items()}
    if a.json:
        a.json.write_text(json.dumps([r for rs in rows.values() for r in rs],
                                     ensure_ascii=False, indent=1))
    head = ["組", "基本の合格", "難しめの合格", "担当外の編集", "一時ファイルの残り",
            "作業ツリーの外への書き込み", "bugfix の罠に触れた報告", "確認 (うち pytest)", "誘導",
            "拒否", "所要時間 中央値 (基本 / 難)", "手数 平均", "出力+推論 平均", "cache 読 平均",
            "cache 書 平均", "費用 平均 (OpenCode)", "試算 平均", "依頼文そのまま"]
    print("| " + " | ".join(head) + " |")
    print("| --- |" + " ---: |" * (len(head) - 1))
    for label, rs in rows.items():
        if rs:
            print(row(label, rs))


if __name__ == "__main__":
    main()

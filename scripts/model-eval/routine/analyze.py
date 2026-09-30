"""routine (commit) の計測の集計。組ごとの表を標準出力へ、1 行 1 実行の JSON を --json へ出す。

使い方: analyze.py [<組>=<glob> | <実行ディレクトリ> ...]
省略時は $EVAL_OUT/runs/routine/* を、ディレクトリ名の <組> でまとめる。

commit エージェントの呼び出しを次に分けて数える:
  allow-form : 静的に allow で実行された
  ask        : 静的に ask (利用者の確認が出る)。git commit は ask(commit) として別に数える
  guide      : guide plugin の誘導で deny
  deny       : 静的な deny (evaluate が来ず Permission denied)
  tool       : shell 以外のツール (read / glob / grep / skill など)
see scripts/model-eval/README.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
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

AGENT = "commit"
INITIAL = "chore: initial import"
CC = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([^)]*\))?!?: \S")
KEYS = ("Motivation:", "Change:", "Impact:")
# 依頼どおりなら残る未コミットのもの (git status --short)
EXPECTED_LEFT = {"new": {"?? scratch-notes.txt"}}
FENCE = re.compile(r"^```[^\n]*\n(.*?)\n```", re.M | re.S)


def kind(cmd: str) -> str:
    c = cmd.strip()
    if re.match(r"git commit\b", c):
        return "git commit"
    m = re.match(r"git\s+(?:-c\s+\S+\s+)*(\S+)", c)
    if m:
        prefixed = c.startswith("git -c ")
        return f"git {'-c … ' if prefixed else ''}{m.group(1)}"
    return c.split()[0] if c else "(空)"


def classify(call: dict) -> str:
    shell = [e for e in call["evals"] if e["action"] == "shell"]
    if call["tool"] != "shell":
        return "ask" if any(e["entry"] == "ask" for e in call["evals"]) else "tool"
    if not shell:
        return "deny" if "Permission denied" in call.get("error", "") else "?"
    if any(e["guided"] for e in shell):
        return "guide"
    if any(e["entry"] == "ask" for e in shell):
        return "ask"
    return "allow-form"


def messages(run: Path) -> list[str]:
    """初期コミットを除いたコミットメッセージ (git log --format=%B)。"""
    raw = (run / "raw.txt").read_text() if (run / "raw.txt").exists() else ""
    out = [m.strip("\n") for m in raw.split("\x00")]
    return [m for m in out if m.strip() and m.splitlines()[0] != INITIAL]


def fmt(msgs: list[str]) -> Counter:
    c: Counter = Counter()
    for m in msgs:
        subj, _, body = m.partition("\n")
        c["commits"] += 1
        c["cc"] += bool(CC.match(subj))
        c["subj72"] += len(subj) <= 72
        if all(re.search(rf"^- {k}", body, re.M) for k in KEYS):
            c["bullets"] += 1
        elif all(k in body for k in KEYS):
            c["labels"] += 1
        elif any(k in body for k in KEYS):
            c["partial"] += 1
        else:
            c["none"] += 1
    return c


def analyze(run: Path, label: str, prices: Prices) -> tuple[dict, dict]:
    _, scn, n = run.name.rsplit("-", 2)
    perms: Counter = Counter()
    detail: dict[str, Counter] = defaultdict(Counter)
    examples: dict[str, list[str]] = defaultdict(list)
    for call in calls(events(run), AGENT):
        cls = classify(call)
        if call["tool"] == "shell":
            k = kind(call["cmd"])
        else:
            k = call["tool"] + "(" + ",".join(e["action"] for e in call["evals"]) + ")"
        if cls == "ask" and k == "git commit":
            cls = "ask(commit)"
        perms[cls] += 1
        if cls in ("ask", "guide", "deny", "?"):
            detail[k][cls] += 1
            examples[k].append(call["cmd"].replace("\n", "⏎")[:110])
    msgs = messages(run)
    status = run / "status.txt"
    left = set(status.read_text().splitlines()) if status.exists() else set()
    prompt = (run / "prompt.txt").read_text() if (run / "prompt.txt").exists() else ""
    approved = [b.strip("\n") for b in FENCE.findall(prompt)]
    tok = usage(sessions(run), AGENT)
    tok["estimate"] = prices.estimate(tok)
    r = dict(run=run.name, label=label, scenario=scn, n=n, perms=dict(perms), fmt=dict(fmt(msgs)),
             messages=msgs, left=sorted(left), left_ok=left == EXPECTED_LEFT.get(scn, set()),
             approved=len(approved) or None,
             verbatim=sum(m in approved for m in msgs) if approved else None,
             time=subagent_seconds(events(run)), tok=tok, model=tok["model"])
    return r, {"detail": detail, "examples": examples}


def main() -> None:
    p = argparse.ArgumentParser(description="routine (commit) の計測を組ごとに集計する")
    p.add_argument("specs", nargs="*", help="<組>=<glob> か実行ディレクトリ")
    p.add_argument("--json", type=Path, help="1 行 1 実行の JSON の書き出し先")
    p.add_argument("--prices", type=Path,
                   help="models.dev の api.json。渡すと試算の列を出す")
    p.add_argument("--price-provider", default="amazon-bedrock")
    p.add_argument("--price-prefix", default="global.anthropic.")
    a = p.parse_args()
    prices = Prices(a.prices, a.price_provider, a.price_prefix)
    grouped = groups(a.specs, str(out_root() / "runs" / "routine" / "*"))
    rows: dict[str, list[dict]] = {}
    detail: dict[str, Counter] = defaultdict(Counter)
    examples: dict[str, list[str]] = defaultdict(list)
    nruns = 0
    for label, runs in grouped.items():
        for run in runs:
            if not (run / "raw.txt").exists():
                continue
            r, d = analyze(run, label, prices)
            rows.setdefault(label, []).append(r)
            nruns += 1
            for k, c in d["detail"].items():
                detail[k].update(c)
                examples[k] = (examples[k] + d["examples"][k])[:3]
    if a.json:
        a.json.write_text(json.dumps([r for rs in rows.values() for r in rs],
                                     ensure_ascii=False, indent=1))

    head = ["組", "実行", "コミット", "CC 件名", "72 字以内", "3 行の箇条", "ラベルのみ", "一部",
            "なし", "残りが期待どおり", "承認文そのまま", "確認 (commit 以外)", "誘導", "拒否",
            "所要時間 中央値", "出力+推論 平均", "cache 読 平均", "cache 書 平均",
            "費用 平均 (OpenCode)", "試算 平均"]
    print("| " + " | ".join(head) + " |")
    print("| --- |" + " ---: |" * (len(head) - 1))
    for label, rs in rows.items():
        f: Counter = Counter()
        pm: Counter = Counter()
        for r in rs:
            f.update(r["fmt"])
            pm.update(r["perms"])
        ap = [r for r in rs if r["approved"]]
        est = [r["tok"]["estimate"] for r in rs if r["tok"]["estimate"] is not None]
        cells = [
            label, str(len(rs)), str(f["commits"]), str(f["cc"]), str(f["subj72"]),
            str(f["bullets"]), str(f["labels"]), str(f["partial"]), str(f["none"]),
            f"{sum(r['left_ok'] for r in rs)}/{len(rs)}",
            f"{sum(r['verbatim'] for r in ap)}/{sum(r['approved'] for r in ap)}" if ap else "—",
            str(pm["ask"]), str(pm["guide"]), str(pm["deny"] + pm["?"]),
            f"{median([r['time'] for r in rs if r['time']]):.0f} s",
            f"{mean([r['tok']['o'] + r['tok']['r'] for r in rs]):.0f}",
            f"{mean([r['tok']['cr'] for r in rs]):.0f}",
            f"{mean([r['tok']['cw'] for r in rs]):.0f}",
            f"${mean([r['tok']['cost'] for r in rs]):.3f}",
            f"${mean(est):.3f}" if est else "—",
        ]
        print("| " + " | ".join(cells) + " |")

    if detail:
        print("\n| 種類 | ask | guide | deny | 1 回あたり | 例 |")
        print("| --- | ---: | ---: | ---: | ---: | --- |")
        for k, cnt in sorted(detail.items(), key=lambda kv: -sum(kv[1].values())):
            ex = " / ".join(f"`{x}`" for x in examples[k])
            print(f"| `{k}` | {cnt['ask']} | {cnt['guide']} | {cnt['deny'] + cnt['?']} "
                  f"| {sum(cnt.values()) / nruns:.2f} | {ex} |")


if __name__ == "__main__":
    main()

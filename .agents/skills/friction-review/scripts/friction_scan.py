"""pi のセッションログから、利用者の「不満・摩擦」の手がかりを集める (試作)。

出力は `.tmp/friction/<日付>/` の `report.md` と `report.json` だけ (リポジトリには置かない。ログには勤務先の情報や秘密が入り得る)。
決定的な指標 (ツールのエラー・拒否・二重承認など) と、利用者の発話の抜粋 (不満らしい語を含むもの) を出す。
抜粋の分類と、新機能の提案は、スキル `friction-review` の手順で子エージェントが行う。
使い方: python3 .agents/skills/friction-review/scripts/friction_scan.py [--root ~/.pi/agent/sessions] [--since 2026-10-01]
      [--session latest|<ファイル>] [--out .tmp/friction]
      確認の結果 (承認・拒否・時間切れ) の表だけ: ... --approvals [--json]
see .agents/skills/friction-review/SKILL.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_routing

# 利用者の発話に含まれる「不満・訂正・手間」の手がかり。偽陽性が多いので、分類は人か子エージェントが行う
CUES = re.compile(
    r"ちょっと待っ|待って|ごめん|違う|そうじゃ|ではなく|やばい|困る|困って|不満|面倒|手間|煩わし|多すぎ|増える|増えて|"
    r"なんで|どうして|やり直|戻して|減らし|避けた|避けて|意識して|ないよね|ないはず|でいい\?|大丈夫\?|心配|コスト"
)
SECRET_RES = (
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}\b"), "<token>"),
    (re.compile(r"\b(?:sk|pk|xox[abp])-[A-Za-z0-9-]{16,}\b"), "<token>"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<aws-key>"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<email>"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"), "Bearer <token>"),
)
EXCERPT_CHARS = 240
MAX_EXCERPTS = 80


def redact(text: str) -> str:
    for pattern, repl in SECRET_RES:
        text = pattern.sub(repl, text)
    return text


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(c.get("text", ""))
            for c in content
            if isinstance(c, dict) and c.get("type") == "text"
        )
    return ""


def calls_of(message: dict) -> list[dict]:
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [c for c in content if isinstance(c, dict) and c.get("type") in ("toolCall", "tool_use")]


def error_head(text: str) -> str:
    first = text.strip().splitlines()[0] if text.strip() else ""
    first = re.sub(r"\d+", "N", first)
    return first[:100]


CAT_APPROVED, CAT_DENIED, CAT_TIMEOUT = "承認", "拒否", "時間切れ"
CAT_SAVED, CAT_FREE, CAT_UNKNOWN = "保留に保存", "確認なしで実行", "不明"
CATEGORIES = (CAT_APPROVED, CAT_DENIED, CAT_TIMEOUT, CAT_SAVED, CAT_FREE, CAT_UNKNOWN)
MIN_PER_RULE = 20  # 規則あたりの件数の下限。未満は判断に使えない (CHG-0054 段 1)


def _result_text(message: dict) -> str:
    return text_of(message.get("content"))


def classify_result(message: dict) -> str | None:
    """確認の結果の区分を返す。確認に関係しない結果は None。

    ログに規則名は無い。見るのは guarded_action の details (auto / freeZone) と、「not approved」の文面の種類だけ。
    """
    text = _result_text(message)
    details = message.get("details") if isinstance(message.get("details"), dict) else {}
    if message.get("isError") or text.startswith("not approved"):
        if not text.startswith("not approved"):
            return None
        if "時間切れ" in text or "時間内に無かった" in text:
            return CAT_TIMEOUT
        if ("保留" in text and "保存した" in text) or "退避した" in text:
            return CAT_SAVED
        return CAT_DENIED
    if message.get("toolName") != "guarded_action":
        return None
    if "freeZone" in details or details.get("auto") is True:
        return CAT_FREE
    if details.get("auto") is False:
        return CAT_APPROVED
    return CAT_UNKNOWN  # 旧形式 (auto の記録が無い): 確認したか自由区かを区別できない


def scan_approvals(path: Path, since: str) -> dict[str, dict[str, int]]:
    """規則 (の代替) ごとの区分の件数。代替は `guarded_action:<action>`、action が無ければツール名。"""
    table: dict[str, Counter] = {}
    actions: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "message":
            continue
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        stamp = str(event.get("timestamp") or "")
        if since and stamp and stamp[:10] < since:
            continue
        if message.get("role") == "assistant":
            for call in calls_of(message):
                args = call.get("arguments")
                if (
                    call.get("name") == "guarded_action"
                    and isinstance(args, dict)
                    and args.get("action")
                ):
                    actions[str(call.get("id"))] = str(args["action"])
            continue
        if message.get("role") != "toolResult":
            continue
        category = classify_result(message)
        tool = str(message.get("toolName") or "")
        if category is None or not tool:
            continue
        details = message.get("details") if isinstance(message.get("details"), dict) else {}
        action = actions.get(str(message.get("toolCallId"))) or details.get("action")
        rule = f"{tool}:{action}" if tool == "guarded_action" and action else tool
        table.setdefault(rule, Counter())[category] += 1
    return {rule: dict(counts) for rule, counts in table.items()}


def merge_approvals(tables: list[dict]) -> dict:
    merged: dict[str, Counter] = {}
    for table in tables:
        for rule, counts in table.items():
            merged.setdefault(rule, Counter()).update(counts)
    rules = {}
    for rule, counts in sorted(merged.items(), key=lambda kv: -sum(kv[1].values())):
        total = sum(counts.values())
        rules[rule] = {
            "counts": {c: counts[c] for c in CATEGORIES if counts.get(c)},
            "total": total,
            "enough": total >= MIN_PER_RULE,
        }
    return {
        "min_per_rule": MIN_PER_RULE,
        "rule_basis": "ログに規則名は無いので、guarded_action は action 名、それ以外はツール名で代替した",
        "rules": rules,
    }


def render_approvals(approvals: dict) -> str:
    floor = approvals["min_per_rule"]
    out = [
        "## 確認の結果 (承認・拒否・時間切れ)",
        "",
        f"- 規則の単位: {approvals['rule_basis']} (代替)",
        f"- 件数の下限: 規則あたり {floor} 件。未満は「下限未満 (判断に使えない)」",
        "- 区分: 確認なしで実行 = 自由区・自動許可 / 不明 = 旧形式で確認の有無を区別できない",
        "",
        "| 規則 | " + " | ".join(CATEGORIES) + " | 計 | 下限 |",
        "|" + " --- |" * (len(CATEGORIES) + 3),
    ]
    for rule, info in approvals["rules"].items():
        cells = []
        for c in CATEGORIES:
            n = info["counts"].get(c, 0)
            cells.append(f"{n} ({n * 100 // info['total']}%)" if n else "0")
        mark = "達成" if info["enough"] else "下限未満 (判断に使えない)"
        out.append(f"| `{rule}` | " + " | ".join(cells) + f" | {info['total']} | {mark} |")
    if not approvals["rules"]:
        out.append("| (なし) |" + " |" * (len(CATEGORIES) + 2))
    return "\n".join(out) + "\n"


def scan_session(path: Path, since: str) -> dict:
    metrics: Counter = Counter()
    errors: Counter = Counter()
    errors_by_tool: Counter = Counter()
    denies_by_tool: Counter = Counter()
    excerpts: list[dict] = []
    last_tools: list[str] = []
    streak: Counter = Counter()
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "message":
            continue
        message = event.get("message") or {}
        stamp = str(event.get("timestamp") or "")
        if since and stamp and stamp[:10] < since:
            continue
        role = message.get("role")
        if role == "user":
            metrics["user_turns"] += 1
            text = text_of(message.get("content"))
            if CUES.search(text) and len(excerpts) < MAX_EXCERPTS:
                excerpts.append(
                    {
                        "at": stamp,
                        "text": redact(text.strip().replace("\n", " "))[:EXCERPT_CHARS],
                        "after_tools": last_tools[-4:],
                    }
                )
        elif role == "assistant":
            metrics["assistant_turns"] += 1
            names = [str(c.get("name") or "") for c in calls_of(message)]
            metrics["tool_calls"] += len(names)
            if names:
                last_tools = names
        elif role == "toolResult":
            name = str(message.get("toolName") or "")
            text = text_of(message.get("content"))
            if message.get("isError"):
                metrics["tool_errors"] += 1
                errors_by_tool[name] += 1
                errors[error_head(text)] += 1
                streak[name] += 1
                if streak[name] == 3:
                    metrics["error_streaks"] += 1  # 同じツールが 3 回続けて失敗
                if "not approved" in text:
                    metrics["not_approved"] += 1
                    denies_by_tool[name] += 1
            else:
                streak[name] = 0
    routing = measure_routing.analyze(path, since)
    for key, value in routing.items():
        metrics[f"routing.{key}"] += value
    return {
        "metrics": dict(metrics),
        "errors_by_tool": dict(errors_by_tool),
        "top_errors": errors.most_common(8),
        "denies_by_tool": dict(denies_by_tool),
        "excerpts": excerpts,
        "approvals": scan_approvals(path, since),
    }


def merge(results: list[dict]) -> dict:
    metrics: Counter = Counter()
    by_tool: Counter = Counter()
    denies: Counter = Counter()
    top: Counter = Counter()
    excerpts: list[dict] = []
    for r in results:
        metrics.update(r.get("metrics", {}))
        by_tool.update(r.get("errors_by_tool", {}))
        denies.update(r.get("denies_by_tool", {}))
        for head, n in r.get("top_errors", []):
            top[head] += n
        excerpts.extend(r.get("excerpts", []))
    return {
        "metrics": dict(metrics),
        "errors_by_tool": dict(by_tool.most_common()),
        "denies_by_tool": dict(denies.most_common()),
        "top_errors": top.most_common(15),
        "excerpts": excerpts[:MAX_EXCERPTS],
        "approvals": merge_approvals([r.get("approvals", {}) for r in results]),
    }


def render(total: dict, sessions: int, since: str) -> str:
    m = total["metrics"]
    out = [
        "# 不満・摩擦の手がかり (試作の出力。リポジトリには置かない)",
        "",
        f"- セッション: {sessions} 件 / 期間: {since or '全期間'} / 利用者の発話: {m.get('user_turns', 0)} 件",
        f"- ツールの呼び出し: {m.get('tool_calls', 0)} 件 / エラー: {m.get('tool_errors', 0)} 件"
        f" / 承認されなかった実行: {m.get('not_approved', 0)} 件 / 同じツールが 3 回続けて失敗: {m.get('error_streaks', 0)} 件",
        f"- 投稿・コミットの bash の直接実行: {m.get('routing.publish_calls', 0)} 件"
        f" (うち直前に ask で承認を取った: {m.get('routing.publish_after_ask', 0)} 件。二重承認の候補)",
        "",
        "## エラーが多いツール",
        "",
    ]
    out += [f"- `{k}`: {v}" for k, v in total["errors_by_tool"].items()] or ["- なし"]
    out += ["", "## 承認されなかった実行が多いツール", ""]
    out += [f"- `{k}`: {v}" for k, v in total["denies_by_tool"].items()] or ["- なし"]
    out += ["", "## 同じ形のエラー (数字は N に置換)", ""]
    out += [f"- {n} 件: {head}" for head, n in total["top_errors"]] or ["- なし"]
    out += ["", "## 利用者の発話の抜粋 (不満・訂正・手間の手がかり。偽陽性を含む)", ""]
    for e in total["excerpts"]:
        out.append(
            f"- {e['at'][:16]} (直前のツール: {', '.join(e['after_tools']) or '-'}): {e['text']}"
        )
    if not total["excerpts"]:
        out.append("- なし")
    out += ["", render_approvals(total["approvals"]).rstrip("\n")]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="~/.pi/agent/sessions")
    parser.add_argument("--since", default="")
    parser.add_argument("--session", default="", help="latest か、セッションのファイル。省略で全件")
    parser.add_argument("--out", default=".tmp/friction")
    parser.add_argument(
        "--approvals",
        action="store_true",
        help="確認の結果の表だけを標準出力へ出す (ファイルは書かない)",
    )
    parser.add_argument("--json", action="store_true", help="--approvals の出力を JSON にする")
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser()
    if args.session == "latest":
        files = sorted(root.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime)[-1:]
    elif args.session:
        files = [Path(args.session).expanduser()]
    else:
        files = sorted(root.glob("*/*.jsonl"))
    if args.approvals:
        approvals = merge_approvals([scan_approvals(p, args.since) for p in files])
        if args.json:
            print(json.dumps(approvals, ensure_ascii=False, indent=1))
        else:
            print(render_approvals(approvals), end="")
        return 0
    total = merge([scan_session(p, args.since) for p in files])
    out_dir = Path(args.out) / dt.date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(total, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    (out_dir / "report.md").write_text(render(total, len(files), args.since), encoding="utf-8")
    print(
        f"{out_dir}/report.md を書いた (セッション {len(files)} 件、抜粋 {len(total['excerpts'])} 件)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

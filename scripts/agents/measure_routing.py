"""pi のセッションログから、投稿・コミットの経路(bash の直接実行・事前の ask)を集計する。

段 G11 (guarded_action) の導入前の基準と、導入後の誤った経路の割合の計測に使う。読み取りだけ。
使い方: python3 scripts/agents/measure_routing.py [--root ~/.pi/agent/sessions] [--since 2026-10-01]
出力は件数だけ (本文は出さない)。
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

PUBLISH_RE = re.compile(
    r"(?:^|[;&|\n]\s*|\bcd\s+\S+\s*&&\s*)(?:git\s+(?:-C\s+\S+\s+)?commit\b|gh\s+(?:-R\s+\S+\s+)?(?:issue|pr)\s+(?:create|comment|review)\b)"
)
ASK_TOPIC_RE = re.compile(r"コミット|commit|投稿|コメント|comment|issue|PR|プルリク", re.IGNORECASE)
WINDOW = 8  # 直前のツール呼び出し何件までを「事前の ask」とみなすか


def tool_calls(message: dict) -> list[dict]:
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [c for c in content if isinstance(c, dict) and c.get("type") in ("toolCall", "tool_use")]


def analyze(path: Path, since: str) -> Counter:
    out: Counter = Counter()
    recent: list[tuple[str, str]] = []  # (ツール名, 引数の文字列)
    last_publish = False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        stamp = str(event.get("timestamp") or "")
        if since and stamp and stamp[:10] < since:
            continue
        message = event.get("message") if isinstance(event.get("message"), dict) else event
        role = message.get("role")
        if role == "toolResult":
            if last_publish:
                text = json.dumps(message.get("content"), ensure_ascii=False)
                if message.get("isError") and "not approved" in text:
                    out["publish_not_approved"] += 1
                elif message.get("isError"):
                    out["publish_error"] += 1
                else:
                    out["publish_ok"] += 1
                last_publish = False
            continue
        if role != "assistant":
            continue
        for call in tool_calls(message):
            name = str(call.get("name") or "")
            args = call.get("arguments") or call.get("input") or {}
            if not isinstance(args, dict):
                args = {}
            if name.endswith("bash") or name == "bash":
                command = str(args.get("command") or "")
                if PUBLISH_RE.search(command):
                    out["publish_calls"] += 1
                    kind = (
                        "git_commit"
                        if "commit" in command.split("gh")[0] and "git" in command
                        else "gh_post"
                    )
                    out[kind] += 1
                    asked = any(n == "ask" and ASK_TOPIC_RE.search(a) for n, a in recent[-WINDOW:])
                    if asked:
                        out["publish_after_ask"] += 1
                    last_publish = True
            if name == "guarded_action":
                out["guarded_action_calls"] += 1
            recent.append((name, json.dumps(args, ensure_ascii=False)[:2000]))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="~/.pi/agent/sessions")
    parser.add_argument("--since", default="")
    args = parser.parse_args()
    root = Path(args.root).expanduser()
    total: Counter = Counter()
    files = sorted(root.glob("*/*.jsonl"))
    for path in files:
        total.update(analyze(path, args.since))
    print(f"セッション: {len(files)} 件")
    for key in (
        "publish_calls",
        "git_commit",
        "gh_post",
        "publish_after_ask",
        "publish_ok",
        "publish_not_approved",
        "publish_error",
        "guarded_action_calls",
    ):
        print(f"{key}: {total[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

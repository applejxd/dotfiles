"""実際のモデルで /compact (自作の圧縮) を再現する。使い捨ての作業場所を /tmp に作り、終わったら消す。

使い方: python3 scripts/pi-harness-spike/compact-real.py [モデル] [thinking] [ターン数]
環境変数 COMPACTS=2 で 2 回圧縮する (前の要約を引き継ぐ経路)。DISABLE_EXT=1 で自作の圧縮を外す (pi 既定の圧縮との比較)。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))
sys.path.insert(0, str(ROOT / "test" / "agents"))
import generate as gen  # noqa: E402
from agents_common import agents_config_dir, load_common  # noqa: E402

MODEL = sys.argv[1] if len(sys.argv) > 1 else "github-copilot/claude-sonnet-5.5"
THINKING = sys.argv[2] if len(sys.argv) > 2 else "medium"
TURNS = int(sys.argv[3]) if len(sys.argv) > 3 else 2
PI = shutil.which("pi")
SRC = ROOT / "home" / "dot_config" / "pi" / "harness"
FIX = ROOT / "test" / "agents" / "pi"

tmp = Path(tempfile.mkdtemp(prefix="compact-real-"))
try:
    harness = tmp / ".config" / "pi" / "harness"
    harness.mkdir(parents=True)
    shutil.copy2(SRC / "index.ts", harness / "index.ts")
    shutil.copytree(SRC / "judge", harness / "judge")
    for name in (
        "redact.ts",
        "canary.ts",
        "children.ts",
        "audit.ts",
        "tools-ext.ts",
        "confirm-view.ts",
        "actions.ts",
        "worktree.ts",
        "worktrees-command.ts",
        "unguarded.ts",
        "platform.ts",
        "landlock_exec.py",
        "commit-message.js",
    ):
        shutil.copy2(SRC / name, harness / name)
    rules = gen.build_pi_harness({}, load_common())
    for agent in rules["agents"].values():
        agent["model"] = None
    (harness / "rules.json").write_text(json.dumps(rules), encoding="utf-8")

    agent_dir = tmp / "agent"
    agent_dir.mkdir()
    real = Path.home() / ".pi" / "agent"
    for name in ("auth.json", "models-store.json", "settings.json"):
        if (real / name).exists():
            shutil.copy2(real / name, agent_dir / name)

    proj = tmp / "proj"
    (proj / ".pi").mkdir(parents=True)
    (proj / ".pi" / "settings.json").write_text(
        '{"compaction": {"keepRecentTokens": 1}}', encoding="utf-8"
    )
    (proj / "f.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    sessions = tmp / "sessions"

    env = {
        **os.environ,
        "PI_CODING_AGENT_DIR": str(agent_dir),
        "AGENTS_CONFIG_DIR": str(agents_config_dir()),
        "TMPDIR": str(tmp),
    }
    for key in [k for k in env if k.startswith(("PI_HARNESS_", "ORCA_"))]:
        env.pop(key)

    args = [
        PI,
        "--model",
        MODEL,
        "--thinking",
        THINKING,
        "-nbt",
        "-ne",
        "-e",
        "builtin:mcp",
        "-e",
        str(harness),
    ]
    args += ["--approve", "--session-dir", str(sessions), "-e", str(FIX / "compact.ts"), "-p"]
    messages = ["guarded_read で f.txt を読み、1 行目だけ答えて。"] + [
        "続けて、2 行目だけ答えて。"
    ] * max(0, TURNS - 1)
    messages.append("/spike-compact")
    if os.environ.get("COMPACTS") == "2":
        messages += ["もう一度、「こんにちは」とだけ答えて。", "/spike-compact"]
    proc = subprocess.run(
        [*args, *messages],
        cwd=proj,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=900,
    )
    fallback = "圧縮の指示を付けられなかった" in proc.stderr
    entries = []
    for path in sessions.rglob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if entry.get("type") == "compaction":
                entries.append(len(entry.get("summary", "")))
    print(
        f"RESULT model={MODEL} thinking={THINKING} exit={proc.returncode} fallback={fallback} compactions={entries}"
    )
    if fallback or proc.returncode != 0 or not entries:
        print("--- stderr ---")
        print(proc.stderr[-2500:])
        print("--- stdout (tail) ---")
        print(proc.stdout[-800:])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

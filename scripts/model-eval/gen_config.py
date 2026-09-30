"""計測用の OpenCode の設定を作る。

--repo の common.toml から通常版の opencode.json を組み、次だけ変える。
- plugins は計装した guide plugin (probe-guide/) の複製だけにする。確認画面の説明の生成
  (ask_description) は外す
- skills の末尾に --repo の commit スキルの複製を足す (同名のスキルより優先される)
- --tier で階層のモデルを、--agent でエージェントのモデルを差し替える

出力: $EVAL_OUT/cfg/<label>/opencode.json (OPENCODE_CONFIG_DIR に渡す) と
      $EVAL_OUT/assets/<label>/ (plugin と skills。設定ディレクトリの自動探索に拾わせない)
see scripts/model-eval/README.md
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def pairs(values: list[str], what: str) -> dict[str, str]:
    out = {}
    for v in values:
        k, sep, m = v.partition("=")
        if not sep or not k or not m:
            sys.exit(f"{what} は NAME=MODEL の形で書く: {v!r}")
        out[k] = m
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="計測用の OpenCode の設定を作る")
    p.add_argument("label", help="設定の名前 (run.sh の <cfg-label>)")
    p.add_argument("--repo", type=Path, default=REPO,
                   help="common.toml・generate.py・guide plugin・commit スキルを取る作業ツリー "
                        "(既定: このリポジトリ)")
    p.add_argument("--provider", help="プロバイダを差し替える (既定: common.toml の判定のまま)")
    p.add_argument("--user", help="common.toml を描画するときのユーザ名 (既定: 実行ユーザ)")
    p.add_argument("--tier", action="append", default=[], metavar="TIER=MODEL",
                   help="階層のモデルを差し替える。MODEL は common.toml と同じ書き方 "
                        "(例: worker=claude-sonnet-5.5#low)")
    p.add_argument("--agent", action="append", default=[], metavar="AGENT=MODEL",
                   help="エージェントのモデルを直接差し替える "
                        "(例: commit=github-copilot/claude-haiku-4.5)")
    p.add_argument("--out", type=Path,
                   default=Path(os.environ.get("EVAL_OUT") or REPO / ".tmp" / "model-eval"),
                   help="出力先 (既定: $EVAL_OUT、無ければ .tmp/model-eval)")
    a = p.parse_args()
    out_root = a.out.resolve()
    if out_root.is_relative_to(REPO) and not out_root.is_relative_to(REPO / ".tmp"):
        p.error(f"--out はリポジトリの中なら .tmp/ の下にする: {out_root}")
    repo = a.repo.resolve()
    tiers, agents = pairs(a.tier, "--tier"), pairs(a.agent, "--agent")

    sys.path.insert(0, str(repo / "scripts" / "agents"))
    sys.path.insert(0, str(repo / "test" / "agents"))
    import generate as gen
    from agents_common import load_common

    common = load_common(a.user)
    model = common["opencode"]["model"]
    if a.provider:
        model["provider"] = a.provider
    provider = model["provider"]
    table = model.get("tier", {}).get(provider)
    if table is None:
        sys.exit(f"opencode.model.tier.{provider} が無い")
    for tier, m in tiers.items():
        if tier not in table:
            sys.exit(f"未知の階層: {tier} (定義済み: {', '.join(table)})")
        table[tier] = m

    assets = out_root / "assets" / a.label
    if assets.exists():
        shutil.rmtree(assets)
    guide = assets / "probe-guide"
    guide.mkdir(parents=True)
    src = repo / "home" / "dot_config" / "opencode" / "guide-plugin"
    shutil.copy2(HERE / "probe-guide" / "index.js", guide / "index.js")
    shutil.copy2(src / "index.js", guide / "orig.js")
    shutil.copy2(src / "commit-message.js", guide / "commit-message.js")
    rules = gen.build_opencode_guide({}, common)
    rules.pop("ask_description", None)
    (guide / "rules.json").write_text(json.dumps(rules, ensure_ascii=False, indent=2), "utf-8")
    skills = assets / "skills"
    shutil.copytree(repo / "home" / "dot_claude" / "skills" / "commit", skills / "commit")

    config = gen.merge_opencode_config({}, common)
    config["plugins"] = [str(guide)]
    config["skills"] = [*config.get("skills", []), str(skills)]
    for agent, m in agents.items():
        known = config.get("agents", {})
        if agent not in known:
            sys.exit(f"未知のエージェント: {agent} (定義済み: {', '.join(known)})")
        config["agents"][agent]["model"] = m

    out = out_root / "cfg" / a.label
    out.mkdir(parents=True, exist_ok=True)
    (out / "opencode.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), "utf-8")
    print(out / "opencode.json")
    print(json.dumps({"provider": provider, "model": config.get("model"),
                      "agents": {k: v.get("model") for k, v in config.get("agents", {}).items()}},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

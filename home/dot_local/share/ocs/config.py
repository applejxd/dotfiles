"""隔離版の設定の書き出し。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .common import HOME

HOST_CONFIG = HOME / ".config/opencode/opencode.json"
# 通常版から引き継ぐキー。★見た目と操作感だけ。許可リストで持つこと。
#   permissions / plugins / mcp / experimental / tools を足すと、
#   通常版の設定から隔離版の緩和を決められるようになる (境界の意味が消える)。
#   agent / agents / commands は通常版からは引き継がず、common.toml から出す。
INHERIT_KEYS = ("theme", "keybinds", "username", "layout", "model", "small_model")
# common.toml のエージェント・コマンド。宣言外のエントリも残さず丸ごと差し替える。
# see docs/spec/opencode-sandbox.md#エージェントとコマンド
REPLACED_KEYS = ("agent", "agents", "commands")


def inherit_ui(config: dict) -> dict:
    """通常版で選んだ見た目・操作感を、まだ無いキーにだけ取り込む。

    隔離版を使い始めるたびにテーマとキーバインドを選び直す羽目になるのを
    防ぐだけのもの。**既にある値は上書きしない**（隔離版での選択が優先）。
    """
    if not HOST_CONFIG.is_file():
        return config
    try:
        host = json.loads(HOST_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return config
    if not isinstance(host, dict):
        return config
    for key in INHERIT_KEYS:
        if key in host and key not in config:
            config[key] = host[key]
    return config


def merge_providers(existing: object, declared: object) -> dict:
    """宣言したプロバイダの ``settings`` だけを差し替える (他のキー・プロバイダは残す)。

    通常版の ``merge_opencode_providers`` と同じ方針。接続設定は緩和に関わらない。
    """
    out = dict(existing) if isinstance(existing, dict) else {}
    for name, entry in (declared if isinstance(declared, dict) else {}).items():
        current = out.get(name)
        current = dict(current) if isinstance(current, dict) else {}
        settings = current.get("settings")
        settings = dict(settings) if isinstance(settings, dict) else {}
        current["settings"] = {**settings, **(entry.get("settings") or {})}
        out[name] = current
    return out


def write_isolated_config(sandbox: dict, project: dict) -> None:
    """隔離版の設定を ``config_dir`` へ書き出す。

    **緩和に関わるキーだけを差し替え、それ以外は残す。**
    設定ディレクトリはワークスペースの外にあり、境界内からは ``allowRead``
    だけなので、内側から緩和を広げられない。書き手は常に境界の外になる。

    ★丸ごと上書きしてはいけない。TUI で選んだモデルなど、こちらが管理して
      いないキーまで毎回消える（実際にそのバグを出した）。
      ``mcp`` と同じ方針で、宣言外のエントリは残す。
    """
    config_dir = Path(sandbox["config_dir"])
    config_dir.mkdir(parents=True, exist_ok=True)
    target = config_dir / "opencode.json"

    existing: dict = {}
    if target.is_file():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # 壊れていたら作り直す（読めないまま残すと起動できない）
            existing = {}
    if not isinstance(existing, dict):
        existing = {}

    # ★管理キーは空でも差し替える (空なら取り除く)。
    #   see docs/spec/opencode-sandbox.md#隔離版の設定の書き出し方
    config: dict = {
        **existing,
        "$schema": "https://opencode.ai/config.json",
        "permissions": sandbox.get("permissions", []),
        # ワークスペース破壊の復旧手段。★保証ではない (日常の取り消し機能)。
        #   復旧データ自身が同じ shell から消せるし、捕捉は best effort。
        "snapshots": True,
    }
    experimental = existing.get("experimental")
    experimental = dict(experimental) if isinstance(experimental, dict) else {}
    policies = sandbox.get("policies")
    if policies:
        # ★不正な statement は警告付きで破棄される。置いた事実ではなく
        #   有効性を確認すること (サーバのログに警告が出る)。
        experimental["policies"] = policies
    else:
        experimental.pop("policies", None)
    if experimental:
        config["experimental"] = experimental
    else:
        config.pop("experimental", None)
    plugins = sandbox.get("plugins")
    if plugins:
        # 目的は伏字化。境界はワークスペースの中を守らないので、`.env` などが
        # そのままモデルの文脈へ入るのを防ぐ。plugin 自体は allowRead だけの
        # 場所にあり、境界内から書き換えられない。
        config["plugins"] = plugins
    else:
        config.pop("plugins", None)
    for key in REPLACED_KEYS:
        if sandbox.get(key):
            config[key] = sandbox[key]
        else:
            config.pop(key, None)
    providers = merge_providers(existing.get("providers"), sandbox.get("providers"))
    if providers:
        config["providers"] = providers
    # 既定モデルは初回だけ置く。以降は利用者が TUI で変えた値を尊重する。
    model = pick_model(sandbox, project)
    if model and "model" not in config:
        config["model"] = model
    config = inherit_ui(config)

    target.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    prompt = sandbox.get("system_prompt")
    agents = config_dir / "AGENTS.md"
    if prompt:
        # 境界の存在をエージェントへ伝える。説明上の対策であって、
        # 書き込み失敗を保証するものではない。
        agents.write_text(prompt + "\n", encoding="utf-8")
    else:
        agents.unlink(missing_ok=True)


def pick_model(sandbox: dict, project: dict) -> str | None:
    """宣言した優先順で、使える provider の最初のモデルを選ぶ。

    使えるかどうかは OpenCode の DB の ``credential`` に資格情報があるかで見る。
    無い provider を既定にすると起動しても応答が来ない。
    """
    preferences = sandbox.get("model_preference") or []
    if not preferences:
        return None
    db = Path(project["db"])
    if not db.is_file():
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        available = {row[0] for row in con.execute("select integration_id from credential")}
        con.close()
    except sqlite3.Error:
        return None
    for entry in preferences:
        provider = str(entry.get("provider", ""))
        model = str(entry.get("model", ""))
        if provider and model and provider in available:
            return f"{provider}/{model}"
    return None

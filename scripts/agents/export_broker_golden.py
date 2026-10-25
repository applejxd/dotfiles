"""ブローカーの Envoy 設定 (``broker.build_config``) の構造を、正解データとして書き出す。

共通化の前後で出力が同値であることを、試験 (``test/agents/test_broker.py``) で固定するために使う。
断片 YAML の文字列置換でも、Python での組み立てでも、解析した構造が同じならよい。
再生成: ``uv run --with pyyaml --no-project python scripts/agents/export_broker_golden.py``
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
OCS = ROOT / "home" / "dot_local" / "share" / "ocs"
OUT = ROOT / "test" / "agents" / "golden" / "broker_config.json"

# 試験が同じ値で呼ぶ (test/agents/test_broker.py の GOLDEN_ARGS)
SDS_DIR = "/state/dir"
CA_FILE = "/etc/ssl/ca.pem"
COPILOT = {"copilot_port": 12345, "copilot_host": "api.individual.githubcopilot.com"}
GITHUB = {"github_socket": "/agent/dir/gh.sock"}

CASES: dict[str, dict] = {
    "copilot": {**COPILOT},
    "github": {**GITHUB},
    "both": {**COPILOT, **GITHUB},
}


def load_broker():
    """``ocs`` をパッケージとして読む (相対 import があるため)。"""
    pkg = types.ModuleType("ocs")
    pkg.__path__ = [str(OCS)]
    sys.modules["ocs"] = pkg
    spec = importlib.util.spec_from_file_location("ocs.broker", OCS / "broker.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["ocs.broker"] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    broker = load_broker()
    out = {}
    for name, kwargs in CASES.items():
        text = broker.build_config(sds_dir=Path(SDS_DIR), ca_file=CA_FILE, **kwargs)
        out[name] = yaml.safe_load(text)
    OUT.write_text(
        json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"{len(out)} 件を書き出した: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

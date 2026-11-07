"""ブローカーの試験の共通部品（ダミーの設定・秘密の走査）。"""

from __future__ import annotations

import dataclasses
from typing import Any

from box import model

REPO = "demo"
# ダミーの秘密。gitleaks に誤検出されないよう、実行時に連結して作る（ソースに完全な形を書かない）
DUMMY_PAT = "ghp" + "_" + "DUMMYPAT0123456789abcdefghijklmnopqrstu"
DUMMY_ROLE_ARN = "arn:aws:iam::000000000000:role/example-readonly"
DUMMY_STS_KEY = "ASIA" + "DUMMYSTSKEY0000"
DUMMY_STS_SECRET = "dummy-sts-secret-value-0000"
DUMMY_STS_TOKEN = "dummy-sts-session-token-0000"
DUMMY_COPILOT = "ghu" + "_" + "DUMMYCOPILOTLONGTOKEN0000"


def refs() -> dict[str, model.SecretRef]:
    return {
        "gh": model.SecretRef("gh", "file", path="/etc/box/secret/gh-pat-dummy"),
        "aws-role": model.SecretRef("aws-role", "command", argv=("echo", DUMMY_ROLE_ARN)),
        "copilot": model.SecretRef("copilot", "command", argv=("echo", DUMMY_COPILOT)),
    }


def policy(brokers: tuple[Any, ...] = ("gh", "aws", "copilot", "hf-cache")) -> model.RepoPolicy:
    return model.RepoPolicy(id=REPO, path="/tmp/demo", brokers=brokers, secrets=refs())


def cfg() -> model.BoxConfig:
    return model.BoxConfig(
        name=model.box_name(REPO),
        repo_id=REPO,
        repo_path="/tmp/demo",
        uid=1000,
        idmap="user",
        mounts=(),
        ports=(),
        brokers=("gh", "aws", "copilot", "hf-cache"),
        gpu=False,
        network="nat",
        proxy_upstream=None,
        subnet=None,
    )


def flat(obj: Any) -> str:
    """計画の全フィールドを 1 つの文字列にする（SecretRef は repr で出どころを隠す）。"""
    if isinstance(obj, model.SecretRef):
        return repr(obj)  # 出どころの詳細を出さない
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return " ".join(f"{f.name}={flat(getattr(obj, f.name))}" for f in dataclasses.fields(obj))
    if isinstance(obj, dict):
        return " ".join(f"{k}={flat(v)}" for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return " ".join(flat(v) for v in obj)
    return str(obj)


def secret_values() -> list[str]:
    return [
        DUMMY_PAT,
        DUMMY_ROLE_ARN,
        DUMMY_STS_KEY,
        DUMMY_STS_SECRET,
        DUMMY_STS_TOKEN,
        DUMMY_COPILOT,
        "/etc/box/secret/gh-pat-dummy",
    ]

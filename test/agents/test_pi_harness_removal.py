"""harness の撤去 (CHG-0062 の A5) で、残るファイルが消えたファイルを import していないことの静的な検査。

``home/dot_config/pi/harness/`` 配下 (``judge/`` を含む) の ``*.ts`` / ``*.js`` の相対 import が、すべて実在するファイルを指す。
ファイルを消したのに参照元を直し忘れると、pi の起動時に初めて落ちる。それを試験で先に見つける。

see docs/change/0062-pr-hub-simplify.md
"""

from __future__ import annotations

import re

from agents_common import ROOT

HARNESS = ROOT / "home" / "dot_config" / "pi" / "harness"

# import ... from "./x.ts" / export ... from "./x.ts" / import("./x.ts") / import "./x.ts"
_SPEC = re.compile(r"""(?:\bfrom\s+|\bimport\s*\(\s*|\bimport\s+)["'](\.{1,2}/[^"']+)["']""")


def _sources():
    return sorted([*HARNESS.rglob("*.ts"), *HARNESS.rglob("*.js")])


def test_harness_sources_are_found():
    names = {p.relative_to(HARNESS).as_posix() for p in _sources()}
    assert "index.ts" in names and "judge/call.ts" in names


def test_every_relative_import_points_to_an_existing_file():
    missing = []
    for src in _sources():
        text = src.read_text(encoding="utf-8")
        for spec in _SPEC.findall(text):
            target = (src.parent / spec).resolve()
            if not target.is_file():
                missing.append(f"{src.relative_to(HARNESS).as_posix()} -> {spec}")
    assert missing == []


# 撤去したファイル (pr-inbox は第 1 段、残りは第 2 段)
REMOVED = [
    "pr-inbox.ts",
    "pending-ops.ts",
    "pending-approve.ts",
    "pending-pick.ts",
    "pending-owner.ts",
    "pending-adapters.ts",
    "pending-request.ts",
    "native-action.ts",
    "integrate-action.ts",
    "integrate-exec.ts",
    "integrate-plan.ts",
    "exclusive-lock.ts",
]
# 撤去後も残すもの (git_commit の退避・自由区の判定・PR 要約など)
KEPT = [
    "pending-store.ts",
    "pending-command.ts",
    "integrate-profile-load.ts",
    "integration-gate.ts",
    "freezone.ts",
    "gitrun.ts",
    "review-git.ts",
    "review-log.ts",
    "pr-review.ts",
    "judge/call.ts",
]


def test_removed_files_are_gone_and_listed_in_chezmoiremove():
    remove = (ROOT / "home" / ".chezmoiremove").read_text(encoding="utf-8").splitlines()
    for name in REMOVED:
        assert not (HARNESS / name).exists(), name  # ソースに残ると chezmoi apply が失敗する
        assert f".config/pi/harness/{name}" in remove, name


def test_kept_files_exist():
    for name in KEPT:
        assert (HARNESS / name).is_file(), name


def test_index_does_not_mention_removed_modules():
    index = (HARNESS / "index.ts").read_text(encoding="utf-8")
    for name in REMOVED:
        assert name.removesuffix(".ts") not in index, name
    for word in (
        "integrateWiring",
        "pendingSettings",
        "approveDeps",
        "reconcileOps",
        "RUNTIME_EPOCH",
        "git_integrate",
    ):
        assert word not in index, word

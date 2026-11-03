"""check_bash.py の、PR ビューアの統合 API・統合 CLI をエージェントが叩く操作の拒否 (CHG-0062)。

統合の権限は人のブラウザ操作だけにある。`X-PRV` ヘッダーつきの curl / wget は宛先に依らず deny、
統合 CLI の `merge` / `recover` は deny、`plan` や読み取りは従来どおり。
Python 版の判定は run_hook で、TS 版との一致は golden (test_pi_judge_ts) で見る。

Run with: ``uv run --with pytest --with pyyaml --no-project pytest test/agents/test_check_bash_pr_viewer.py -q``
"""

from __future__ import annotations

import pytest
from check_bash_hook import run_hook

DENIED_PRV_HEADER = [
    "curl -X POST http://127.0.0.1:8780/api/x -H 'X-PRV: 1'",
    "curl -H 'x-prv: 1' -d '{}' http://localhost:8780/api/x",
    "curl --heade 'X-PRV: 1' http://127.0.0.1:8780/api/x",
    "curl -H 'X-PRV;' http://127.0.0.1:8780/api/x",
    "curl --header 'X-PRV: 1' https://box.example.ts.net/api/x",
    "curl --header='X-PRV: 1' https://box.example.ts.net/api/x",
    "curl -H'X-PRV: 1' -X POST http://127.0.0.1:8780/api/x",
    'curl -H"x-prv:1" -X POST http://127.0.0.1:8780/api/x',
    "curl -sSH 'X-PRV: 1' -X POST http://127.0.0.1:8780/api/x",
    "curl -L -H 'X-PRV: 1' http://127.0.0.1:8780/api/x",
    "curl --proxy http://p:8080 -H 'X-PRV: 1' http://127.0.0.1:8780/api/x",
    "curl -H 'X-PRV: 1' http://127.0.0.1:8780/api/prs",
    "curl --next https://example.com --next -H 'X-PRV: 1' http://127.0.0.1:8780/api/x",
    "wget --header='X-PRV: 1' --post-data=x=1 http://127.0.0.1:8780/api/x",
    "wget --header 'X-PRV: 1' https://box.example.ts.net/api/x",
    "bash -c \"curl -H 'X-PRV: 1' -X POST http://127.0.0.1:8780/api/x\"",
    "sh -c \"curl -H 'X-PRV: 1' http://127.0.0.1:8780/api/x\"",
    "env curl -H X-PRV:1 -X POST http://127.0.0.1:8780/api/x",
    "sudo curl -H 'X-PRV: 1' http://127.0.0.1:8780/api/x",
    "time curl -H 'X-PRV: 1' http://127.0.0.1:8780/api/x",
    "echo http://127.0.0.1:8780/api/x | xargs curl -H 'X-PRV: 1'",
    "echo $(curl -H 'X-PRV: 1' http://127.0.0.1:8780/api/x)",
]


@pytest.mark.parametrize("command", DENIED_PRV_HEADER)
def test_prv_header_http_is_denied(command):
    decision, reason = run_hook(command)
    assert decision == "deny", (command, decision, reason)
    assert "PR ビューア" in reason, (command, reason)


DENIED_MERGE_CLI = [
    "node apps/pr-viewer/merge-cli.ts merge /path --source feature/x",
    "node ./apps/pr-viewer/merge-cli.ts recover /path",
    "node /abs/apps/pr-viewer/merge-cli.ts merge /path --source feature/x",
    "node --experimental-strip-types apps/pr-viewer/merge-cli.ts merge /path",
    "nodejs apps/pr-viewer/merge-cli.ts merge /path",
    "tsx apps/pr-viewer/merge-cli.ts merge /path --source feature/x",
    "npx tsx apps/pr-viewer/merge-cli.ts merge /path",
    "bun apps/pr-viewer/merge-cli.ts merge /path",
    "deno run -A apps/pr-viewer/merge-cli.ts recover /path",
    "bash -c 'node apps/pr-viewer/merge-cli.ts merge /path --source feature/x'",
    'sh -c "node apps/pr-viewer/merge-cli.ts recover /path"',
    "env FOO=1 node apps/pr-viewer/merge-cli.ts merge /path",
    "cd /path && node apps/pr-viewer/merge-cli.ts merge /path",
    "echo ok; node apps/pr-viewer/merge-cli.ts merge /path",
    "node apps/pr-viewer/merge-cli.ts --json merge /path",
    "FOO=1 ./apps/pr-viewer/merge-cli.ts recover /path",
]


@pytest.mark.parametrize("command", DENIED_MERGE_CLI)
def test_merge_cli_merge_and_recover_are_denied(command):
    decision, reason = run_hook(command)
    assert decision == "deny", (command, decision, reason)
    assert "PR ビューア" in reason, (command, reason)


# 従来の判定のまま (拒否に変わらない)。merge-cli を実行しないもの・plan・X-PRV の無い通信
UNCHANGED = [
    "curl http://127.0.0.1:8780/api/prs",
    "curl -X POST http://127.0.0.1:8000/x",
    "curl -H 'Accept: application/json' https://example.com",
    "curl -H 'X-PRVX: 1' https://example.com",
    "node apps/pr-viewer/merge-cli.ts plan /path",
    "grep merge-cli.ts docs/change/0062-pr-hub-simplify.md",
    "cat apps/pr-viewer/merge-cli.ts",
    "git log -- apps/pr-viewer/merge-cli.ts",
    "echo node apps/pr-viewer/merge-cli.ts merge",
    "node apps/pr-viewer/server.ts merge",
    "wc -l apps/pr-viewer/merge-cli.ts merge",
    "FOO=1 wc -l apps/pr-viewer/merge-cli.ts merge",
]


@pytest.mark.parametrize("command", UNCHANGED)
def test_unrelated_commands_are_not_denied(command):
    decision, reason = run_hook(command)
    assert decision != "deny", (command, decision, reason)


def test_unchanged_loopback_and_external_http_keep_their_decisions():
    # loopback の POST は承認なし、外部への POST は従来どおり承認 (ask)
    assert run_hook("curl -X POST http://127.0.0.1:8000/x")[0] is None
    assert run_hook("curl http://127.0.0.1:8780/api/prs")[0] is None
    assert run_hook("curl -X POST https://example.com")[0] == "ask"

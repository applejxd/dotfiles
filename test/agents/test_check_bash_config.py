"""check_bash.py と設定・CLI の契約。

common.toml の形、生成される permission と hook の対応、LLM 判定への委譲、
Copilot の shadowing、コミット手順と常時読込の指示、設定が壊れたときの fail-closed。

Run with: ``uv run --with pytest --with pyyaml --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from agents_common import load_common
from check_bash_hook import COMMON, COMMON_PATH, HOOK, HOOK_PATH, ROOT, gen, policy, run_hook

COMMIT_SKILL_PATHS = [
    ROOT / "home" / "dot_claude" / "skills" / "commit" / "SKILL.md",
    ROOT / "home" / "dot_codex" / "skills" / "commit" / "SKILL.md",
]
CHEZMOI_TEMPLATES = ROOT / "home" / ".chezmoitemplates"
# 常時読み込まれる個人用カスタム指示。共通部分は .chezmoitemplates に置き、
# 各 CLI のファイルは includeTemplate で取り込む (CLI 固有の節だけ追記する)
INSTRUCTION_PATHS = {
    "claude": ROOT / "home" / "dot_claude" / "CLAUDE.md.tmpl",
    "codex": ROOT / "home" / "dot_codex" / "AGENTS.md.tmpl",
    "copilot": ROOT / "home" / "dot_copilot" / "copilot-instructions.md.tmpl",
    "opencode": ROOT / "home" / "dot_config" / "opencode" / "AGENTS.md.tmpl",
}
SHARED_INSTRUCTIONS = "agent-instructions.md"
_INCLUDE_RE = re.compile(r'\{\{-?\s*includeTemplate\s+"([^"]+)"\s*-?\}\}')


def render_instructions(cli: str) -> str:
    """指示ファイルの ``includeTemplate`` を展開して実体を得る。

    ``chezmoi execute-template`` を呼ばずに済ませるため、この 1 形式だけを
    自前で展開する。テンプレート側で分岐は使わない約束なのでこれで足りる。
    """
    text = INSTRUCTION_PATHS[cli].read_text(encoding="utf-8")
    return _INCLUDE_RE.sub(
        lambda m: (CHEZMOI_TEMPLATES / m.group(1)).read_text(encoding="utf-8"), text
    )


# ---------------------------------------------------------------------------
# run_hook 自体の検査
# ---------------------------------------------------------------------------

def _fake_hook(tmp_path: Path, body: str) -> Path:
    hook = tmp_path / "fake_hook.py"
    hook.write_text(body, encoding="utf-8")
    return hook


@pytest.mark.parametrize(
    ("label", "body"),
    [
        ("無出力で exit 1", "import sys\nsys.exit(1)\n"),
        ("無出力で例外", "raise RuntimeError('boom')\n"),
        (
            "無出力で Traceback を出して exit 0",
            "import sys\nsys.stderr.write('Traceback (most recent call last):\\n')\n",
        ),
    ],
)
def test_run_hook_rejects_silent_crash(tmp_path, label, body):
    """クラッシュした hook を「許可」と取り違えないこと."""
    hook = _fake_hook(tmp_path, body)
    with pytest.raises(AssertionError):
        run_hook("git status", hook=hook)


def test_run_hook_accepts_clean_silence(tmp_path):
    hook = _fake_hook(tmp_path, "import sys\nsys.stdin.read()\n")
    assert run_hook("git status", hook=hook) == (None, "")


def _decision_hook_body(decision: str, tail: str) -> str:
    """正しい形の決定 JSON を出したあと ``tail`` を実行する偽 hook の本文。"""
    payload = {
        "permissionDecision": decision,
        "permissionDecisionReason": "fake",
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": "fake",
        },
    }
    return (
        "import json, sys\n"
        "sys.stdin.read()\n"
        f"sys.stdout.write({json.dumps(payload)!r})\n"
        "sys.stdout.flush()\n"
        f"{tail}\n"
    )


@pytest.mark.parametrize("decision", ["deny", "ask"])
@pytest.mark.parametrize(
    ("label", "tail"),
    [
        ("exit 1", "sys.exit(1)"),
        ("例外", "raise RuntimeError('boom')"),
        ("Traceback を出して exit 0", "sys.stderr.write('Traceback (most recent call last):\\n')"),
    ],
)
def test_run_hook_rejects_decision_from_a_crash(tmp_path, decision, label, tail):
    """正しい JSON を出しても異常終了した hook の判定は受け付けないこと.

    Claude は exit 0 以外だと stdout を読まないので、実機ではこの判定は効かない。
    """
    hook = _fake_hook(tmp_path, _decision_hook_body(decision, tail))
    with pytest.raises(AssertionError):
        run_hook("git status", hook=hook)


@pytest.mark.parametrize("decision", ["deny", "ask"])
def test_run_hook_accepts_decision_from_a_clean_exit(tmp_path, decision):
    hook = _fake_hook(tmp_path, _decision_hook_body(decision, "sys.exit(0)"))
    assert run_hook("git status", hook=hook) == (decision, "fake")


# ---------------------------------------------------------------------------
# common.toml の整合性
# ---------------------------------------------------------------------------

def test_bash_has_exactly_three_lists():
    """人が書く policy は allow / ask / deny の 3 つだけ (critical_* は廃止)。

    ``ask_hook_owned`` は policy そのものではなく、ask のうち hook が承認要否まで
    判定するものを指す注記なので別枠。
    """
    assert sorted(COMMON["bash"]) == ["allow", "ask", "ask_hook_owned", "deny"]


def test_lists_are_not_empty():
    for key in ("allow", "ask", "deny"):
        assert COMMON["bash"][key], f"[bash] {key} が空"


def test_ask_and_deny_do_not_overlap():
    overlap = set(COMMON["bash"]["ask"]) & set(COMMON["bash"]["deny"])
    assert not overlap, f"ask と deny が重複: {overlap}"


def test_patterns_are_bare_tokens():
    """パターンは素のトークン列。Claude の `:*` は generate.py が付ける."""
    for key in ("allow", "ask", "deny"):
        for pattern in COMMON["bash"][key]:
            assert ":" not in pattern, f"[bash] {key} に Claude 記法が混入: {pattern}"
            assert pattern == pattern.strip()
            assert "  " not in pattern


def test_more_specific_deny_overrides_broader_ask():
    """deny は ask より先に評価されるので、例外は deny 側に具体形で書ける."""
    assert "git reset" in COMMON["bash"]["ask"]
    assert "git reset --hard" in COMMON["bash"]["deny"]


# ---------------------------------------------------------------------------
# hook と permission の関係
# ---------------------------------------------------------------------------
# 同じ 3 リストから両方が作られるので、片方だけに書かれる状態は起こらない。
# Copilot は permission リストを持たない (deny/ask 非対応) が、hook が同じ
# リストを読むため両 CLI で同じ判定になる。

def test_git_dash_c_is_not_allowed():
    """作業ディレクトリを付け替える形式は permission バイパスの既知形式なので allow しない."""
    assert not [a for a in COMMON["bash"]["allow"] if a.startswith("git -C")]
    perms = gen.build_claude_permissions(COMMON)
    assert "Bash(git -C:*)" not in perms["allow"]


def test_loader_reads_ask():
    patterns = policy.load_ask(str(COMMON_PATH))
    assert "rm" in patterns
    assert "git commit" in patterns


def test_loader_reads_deny():
    patterns = policy.load_deny(str(COMMON_PATH))
    assert "git push" in patterns
    assert "rm" not in patterns


def test_hook_and_permissions_come_from_the_same_lists():
    """generate.py が出す Bash ルールと hook が読むパターンが対応すること。

    例外は ``ask_hook_owned``。hook は bash.ask を丸ごと policy として読むが、
    generate.py は静的 ask を出さない (出すと hook の exemption が auto で
    無効になる)。この差分だけを引いてから比較する。
    """
    perms = gen.build_claude_permissions(COMMON)
    for key, loader in (("ask", policy.load_ask), ("deny", policy.load_deny)):
        from_permissions = {
            r[len("Bash("):-len(":*)")] for r in perms[key] if r.startswith("Bash(")
        }
        from_hook = set(loader(str(COMMON_PATH)))
        if key == "ask":
            from_hook -= set(COMMON["bash"]["ask_hook_owned"])
        assert from_permissions == from_hook, f"{key} が食い違っている"


def test_hook_owned_ask_is_not_emitted_as_a_static_claude_rule():
    """hook が承認要否まで判定するコマンドに静的 ask を出してはいけない。

    Claude の explicit ask は **どのモードでも自動承認されない**
    (bypassPermissions を含む)。さらに PreToolUse hook の allow は
    v2.1.77 以降 ask を上書きしない。したがって静的 ask を残したままだと
    `rm -rf build/` のような workspace 内の削除でも auto モードで必ず
    プロンプトが出て、hook 側の委譲 (test_rm_inside_workspace_is_delegated)
    が実機で無効になる。hook のテストだけでは検出できない食い違いなので、
    生成物と hook の宣言をここで突き合わせる。

    ref: https://code.claude.com/docs/en/permission-modes
         「Actions no mode auto-approves ... Tools matched by an explicit ask rule」
    """
    common = load_common()
    bash = common["bash"]
    hook_owned = bash["ask_hook_owned"]

    # hook 自身は bash.ask を policy として読むので、載っている必要がある
    for cmd in hook_owned:
        assert cmd in bash["ask"], f"{cmd!r} が bash.ask に無い"

    # 宣言と hook の実装が食い違っていないこと
    assert set(hook_owned) == set(HOOK._ASK_EXEMPTIONS), (
        "ask_hook_owned と check_bash.py の _ASK_EXEMPTIONS が一致しない: "
        f"{sorted(hook_owned)} vs {sorted(HOOK._ASK_EXEMPTIONS)}"
    )

    # 生成される Claude の permissions.ask に静的ルールを出さない
    perms = gen.build_claude_permissions(common)
    for cmd in hook_owned:
        assert f"Bash({cmd}:*)" not in perms["ask"], (
            f"Bash({cmd}:*) が permissions.ask に出力されている。"
            "hook の exemption が auto モードで無効になる"
        )


# ---------------------------------------------------------------------------
# 生成される permission リスト
# ---------------------------------------------------------------------------

def test_generated_permissions_leave_rm_to_the_hook():
    """rm は deny にも静的 ask にも出さず、hook の判定に委ねる。

    静的 ask を出すと auto モードでも必ずプロンプトが出るため、
    「workspace 内の削除は承認を省く」という設計が実機で成立しなくなる。
    """
    perms = gen.build_claude_permissions(COMMON)
    assert not [r for r in perms["deny"] if r.startswith("Bash(rm:")]
    assert "Bash(rm:*)" not in perms["ask"]
    assert "rm" in COMMON["bash"]["ask_hook_owned"]


def test_generated_permissions_keep_high_risk_in_deny():
    perms = gen.build_claude_permissions(COMMON)
    assert "Bash(sudo:*)" in perms["deny"]
    assert "Bash(git push:*)" in perms["deny"]


@pytest.mark.parametrize(
    "command",
    ["docker rm", "docker rmi",
     "git clean", "git branch -D", "git commit", "gh pr create"],
)
def test_reversible_commands_are_ask_not_deny(command):
    """復旧可能だが不可逆性・外部影響があるものは deny ではなく ask."""
    perms = gen.build_claude_permissions(COMMON)
    assert f"Bash({command}:*)" in perms["ask"]
    assert f"Bash({command}:*)" not in perms["deny"]


@pytest.mark.parametrize(
    "command",
    ["sudo", "git push", "git reset --hard", "git rebase", "ssh",
     "telnet", "npm install -g", "pip", "pip3", "psql", "mysql",
     "redis-cli", "docker system prune", "gh pr merge", "gh repo delete"],
)
def test_high_risk_commands_stay_denied(command):
    """外部への漏洩・システム変更・規約違反は deny のまま."""
    perms = gen.build_claude_permissions(COMMON)
    assert f"Bash({command}:*)" in perms["deny"]
    assert f"Bash({command}:*)" not in perms["ask"]


def test_permission_modes_are_generated():
    """両 CLI の権限モードが common.toml から生成されること."""
    merged = gen.merge_claude_settings({}, COMMON)
    assert merged["permissions"]["defaultMode"] == COMMON["claude"]["default_permission_mode"]

    copilot = COMMON["copilot"]
    settings = gen.merge_copilot_settings({}, COMMON)
    assert settings["defaultPermissionMode"] == copilot["default_permission_mode"]
    # assisted は experimental な auto-approval 機能に依存する
    if copilot["default_permission_mode"] == "assisted":
        assert settings["experimental"] is True


# ---------------------------------------------------------------------------
# LLM 判定モードへの委譲 (Claude auto の classifier / Copilot assisted)
# ---------------------------------------------------------------------------
# ask に載せると Claude ではどのモードでも自動承認されず、モードに到達しない。
# (Copilot は hook の ask が自動承認される。github/copilot-cli#3590)
# allow に載せると手動モードでも無条件に通る。
# → 未掲載にすることで、実行の可否を LLM に判断させる。

@pytest.mark.parametrize(
    "command",
    [
        "uvx ruff format .",
        "uv tool run ruff check .",
        "npx --yes prettier --write .",
        "pnpm dlx prettier --check .",
        "yarn dlx eslint .",
        "pipx run black .",
        "python -c 'print(1)'",
        "python3 -m http.server 8000",
        "uv add requests",
        "npm install express",
        "npm ci",
        "npm uninstall express",
        "npm remove express",
        "mv notes.md docs/notes.md",
        "docker exec mycontainer ls",
        "gh repo clone owner/repo",
        "git gc",
    ],
)
def test_delegated_commands_are_unlisted(command):
    """委譲対象は hook が判定を返さない (LLM 判定モードに到達する)."""
    decision, reason = run_hook(command)
    assert decision is None, f"{command!r} -> {decision} ({reason})"


@pytest.mark.parametrize(
    "command",
    [
        "uvx", "uv tool run", "npx", "pnpm dlx", "yarn dlx", "pipx run",
        "python -c", "uv add", "npm install", "npm ci", "npm uninstall",
        "npm remove", "mv", "docker exec", "gh repo clone", "git gc",
    ],
)
def test_delegated_commands_are_in_no_list(command):
    """委譲対象は allow / ask / deny のいずれにも載っていないこと.

    allow に入れると手動モードでも無条件に通るので、
    「未掲載」であること自体を保証する。
    """
    bash = COMMON["bash"]
    for name in ("allow", "ask", "deny"):
        assert command not in bash[name], (
            f"{command!r} が [bash] {name} に含まれている。"
            "LLM 判定へ委譲するには未掲載である必要がある"
        )


@pytest.mark.parametrize(
    "command",
    [
        "python -c \"import os; os.system('git push')\"",
        "uvx --from evil pip install x",
        "uvx pip install x",
        "pipx run pip install x",
        "npm install -g typescript",
        "mv ~/.ssh/id_rsa ./key",
        "docker exec c cat /root/.ssh/id_rsa",
        "python3 -c 'open(\"/etc/shadow\").read()'",
    ],
)
def test_delegated_commands_still_deny_dangerous_forms(command):
    """委譲しても、危険な使い方は個別チェックが deny する."""
    decision, reason = run_hook(command)
    assert decision == "deny", f"{command!r} -> {decision} ({reason})"


def test_npx_is_delegated_but_dangerous_forms_are_denied():
    """npx は未掲載 (LLM 判定へ委譲) だが、pip 経由などの危険な形は deny のまま."""
    decision, reason = run_hook("npx --yes markdownlint-cli2 README.md")
    assert decision is None, f"-> {decision} ({reason})"


# ---------------------------------------------------------------------------
# Copilot 側で allow に隠される (shadowing) 組み合わせ
# ---------------------------------------------------------------------------

def _shadowed_entries() -> list[tuple[str, str]]:
    """allow の先頭トークンと衝突する ask / deny エントリを列挙する.

    Copilot の permissions-config.json は ask / deny を扱えず、
    allow の **先頭トークンだけ** が commandIdentifiers として渡る。
    つまり `git diff` を allow に入れると Copilot では `git` 全体が承認され、
    `git push` のような deny エントリが隠れてしまう。
    実際に止めているのは hook なので、その保証をテストで固定する。
    """
    bash = COMMON["bash"]
    allow_heads = {entry.split()[0] for entry in bash["allow"] if entry.split()}
    shadowed: list[tuple[str, str]] = []
    for decision in ("deny", "ask"):
        for entry in bash[decision]:
            tokens = entry.split()
            if tokens and tokens[0] in allow_heads:
                shadowed.append((entry, decision))
    return shadowed


SHADOWED_ENTRIES = _shadowed_entries()


def test_shadowed_entries_exist():
    """前提が崩れていないことの確認 (allow と衝突するエントリがあること)."""
    assert SHADOWED_ENTRIES, "allow と衝突する ask/deny が 1 件も無いのは想定外"


@pytest.mark.parametrize(
    "entry,decision",
    SHADOWED_ENTRIES,
    ids=[f"{d}:{e}" for e, d in SHADOWED_ENTRIES],
)
def test_shadowed_entries_are_enforced_by_hook(entry, decision):
    """Copilot で allow に隠れるエントリを hook が確実に止める.

    ここが落ちたら、Copilot 側ではそのコマンドが無条件に通る状態になる。
    """
    got, reason = run_hook(entry)
    assert got == decision, (
        f"{entry!r} は allow の先頭トークンに隠れるため hook が {decision} を"
        f"返す必要がある (実際: {got}) ({reason})"
    )


# ---------------------------------------------------------------------------
# コミットの手順と承認 (スキル・常時読込の指示)
# ---------------------------------------------------------------------------

def test_compound_git_add_and_commit_requires_approval():
    decision, reason = run_hook(
        "git add -- src/app.py && git commit -m 'fix: update app'"
    )
    assert decision == "ask", f"-> {decision} ({reason})"


def test_commit_skill_uses_direct_commands_and_separate_calls():
    skill = COMMIT_SKILL_PATHS[0].read_text(encoding="utf-8")
    assert "git add -- <対象ファイル...>" in skill
    assert "git add -- <対象ファイル...> &&" not in skill
    assert "git commit -m '<件名>' -m '<本文>'" in skill
    assert "get-git-context.sh" not in skill
    assert "git commit -a" in skill
    assert not (
        COMMIT_SKILL_PATHS[0].parent / "scripts" / "executable_get-git-context.sh"
    ).exists()
    # ★ファイル個別指定だと中身が消えた後に空の scripts/ が残るため、
    #   ディレクトリごと消している (.chezmoiremove 冒頭の規則)。
    remove_lines = [
        line.strip()
        for line in (ROOT / "home" / ".chezmoiremove")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert ".claude/skills/commit/scripts" in remove_lines


def test_commit_skills_gate_on_message_approval_before_commit():
    """承認は add ではなく commit の直前。目的はコミットメッセージの確認。

    ゲートが実行指示より後ろにあると、手順を順に辿る agent が確認前に
    コミットしてしまうため、位置関係も検査する。
    """
    for path in COMMIT_SKILL_PATHS:
        skill = path.read_text(encoding="utf-8")
        assert "この時点では承認を求めない" in skill, path
        gate = skill.index("**コミット前の承認**")
        stage = skill.index("git add -- <対象ファイル...>")
        run = skill.index("git commit -m '<件名>' -m '<本文>'")
        assert stage < gate < run, f"承認ゲートの位置が不正: {path}"


def test_commit_skill_is_cli_agnostic():
    """CLI 判別で分岐せず、どの CLI でも同じ手順で確認する."""
    for path in COMMIT_SKILL_PATHS:
        skill = path.read_text(encoding="utf-8")
        assert "COPILOT_CLI" not in skill, path
        assert "copilot-cli#3590" not in skill, path
    docs = (ROOT / "docs" / "spec" / "agent-command-policy.md").read_text(encoding="utf-8")
    assert "github/copilot-cli/issues/3590" in docs
    assert "auto_approved" in docs


def test_codex_commit_skill_uses_separate_policy_checked_commands():
    skill = COMMIT_SKILL_PATHS[1].read_text(encoding="utf-8")
    assert "git add -- <対象ファイル...>" in skill
    assert "git add -- <対象ファイル...> &&" not in skill
    assert "shell compound の内側を解析しない" in skill
    assert "get-git-context.sh" not in skill


def test_copilot_instructions_require_commit_approval():
    """skill は呼び出さないと読まれないので、常時読込の指示にも同じ規則を置く。

    実際にこのセッションで skill を再呼び出しせずコミットし、ゲートを
    素通りさせた実績があるため、常時読込側が最後の砦になる。
    """
    path = ROOT / "home" / "dot_copilot" / "copilot-instructions.md.tmpl"
    instructions = render_instructions("copilot")
    assert "git commit" in instructions
    assert "承認" in instructions
    assert "github/copilot-cli#3590" in instructions
    assert path.exists()
    # Claude Code / Codex CLI は機械的強制があるので、同じ規則を書くと
    # 二重確認になる (docs/spec/agent-command-policy.md の CLI 別の表を参照)
    for cli in ("claude", "codex", "opencode"):
        assert "github/copilot-cli#3590" not in render_instructions(cli), cli


# ---------------------------------------------------------------------------
# 個人用カスタム指示
# ---------------------------------------------------------------------------

def test_checkpoint_instructions_reach_opencode_only():
    """checkpoint スキルは OpenCode にしか配っていない。

    共通本文に置くと、Claude / Codex / Copilot に存在しないスキルの実行を
    毎回要求することになる。
    """
    assert "checkpoint" not in (CHEZMOI_TEMPLATES / SHARED_INSTRUCTIONS).read_text(
        encoding="utf-8"
    )
    assert "`checkpoint` スキル" in render_instructions("opencode")
    for cli in ("claude", "codex", "copilot"):
        assert "checkpoint" not in render_instructions(cli), cli


def test_personal_instructions_share_one_source():
    """個人用カスタム指示の共通部分は 1 ファイルに集約する.

    3 CLI 分を手で複製すると文面がズレる (実際に「停止と報告」と「検証」で
    ズレていた)。共通部分は .chezmoitemplates に置き、各 CLI のファイルは
    includeTemplate で取り込んだうえで固有の節だけを足す。
    """
    shared = (CHEZMOI_TEMPLATES / SHARED_INSTRUCTIONS).read_text(encoding="utf-8")
    assert shared.startswith("# 個人用カスタム指示")
    for cli, path in INSTRUCTION_PATHS.items():
        raw = path.read_text(encoding="utf-8")
        assert f'includeTemplate "{SHARED_INSTRUCTIONS}"' in raw, cli
        # 共通部分が丸ごと展開され、見出しが重複しないこと
        rendered = render_instructions(cli)
        assert shared.rstrip("\n") in rendered, cli
        assert rendered.count("# 個人用カスタム指示") == 1, cli
        # 分岐を持ち込まない (持ち込むと render_instructions が嘘になる)
        assert "{{ if" not in raw and "{{if" not in raw, cli


def test_personal_instructions_require_japanese_tool_arguments():
    """ユーザーに表示されるツール引数も日本語で書かせる.

    「ユーザーへの説明は日本語で書く」だけでは `bash` の `description` などの
    引数までは含むと読まれず、実際に英語のまま出力されていた。hook が返せるのは
    allow / deny / ask だけで引数の書き換えはできないため (ADR 0006 の例外)、
    共通本文に明示する。
    """
    for cli in INSTRUCTION_PATHS:
        rendered = render_instructions(cli)
        assert "description" in rendered, cli
        assert "ユーザーに表示される引数も日本語で書く" in rendered, cli


# ---------------------------------------------------------------------------
# fail-closed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("label", "files"),
    [
        ("toml なし", {}),
        ("toml が壊れている", {"common.toml": "this is not [valid toml"}),
        ("bash セクションなし", {"common.toml": "[web]\nallow_domains = []\n"}),
        ("リストが空", {"common.toml": "[bash]\nallow = []\nask = []\ndeny = []\n"}),
        ("deny が文字列", {"common.toml": '[bash]\nallow = []\nask = []\ndeny = "git push"\n'}),
        ("deny に数値が混入", {"common.toml": "[bash]\nallow = []\nask = []\ndeny = [1]\n"}),
        ("モジュールが壊れている", {"command_policy.py": "syntax error ((("}),
    ],
)
def test_broken_config_fails_closed(tmp_path, label, files):
    """設定が壊れているときに素通りしないこと (fail-closed)."""
    policy_src = (COMMON_PATH.parent / "command_policy.py").read_text(encoding="utf-8")
    (tmp_path / "command_policy.py").write_text(policy_src, encoding="utf-8")
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")

    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git push"},
        "cwd": str(ROOT),
    }
    proc = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env={**os.environ, "AGENTS_CONFIG_DIR": str(tmp_path)},
    )
    assert proc.stdout.strip(), f"{label}: hook が沈黙した (fail-open)"
    assert json.loads(proc.stdout)["permissionDecision"] == "deny", label


@pytest.mark.parametrize("tool_name", ["Bash", "bash", "powershell"])
def test_both_cli_tool_names_are_checked(tool_name):
    """Claude と Copilot の Unix / Windows ツール名で判定されること."""
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": {"command": "git push", "description": "push"},
        "cwd": str(ROOT),
    }
    proc = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env={**os.environ, "AGENTS_CONFIG_DIR": str(COMMON_PATH.parent)},
    )
    assert json.loads(proc.stdout)["permissionDecision"] == "deny"


def test_missing_policy_denies_everything(tmp_path):
    """ポリシーを読めないときは素通りではなく deny になること."""
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
        "cwd": str(ROOT),
    }
    env = {**os.environ, "AGENTS_CONFIG_DIR": str(tmp_path)}
    proc = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env=env,
    )
    assert proc.stdout.strip(), "設定が無いのに hook が沈黙した (fail-open)"
    data = json.loads(proc.stdout)
    assert data["permissionDecision"] == "deny"
    assert "chezmoi apply" in data["permissionDecisionReason"]

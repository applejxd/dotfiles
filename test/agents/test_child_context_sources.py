"""正本 (共通指示・リポジトリの AGENTS.md) の子向けの印が、規則ごとに期待どおりの役割へ渡ることを固定する。

``test/agents/pi/child_context_sources_driver.mjs`` が ``resolveContext`` / ``lint`` を実物の 2 ファイルに当てる。
規則は「原文の箇条書き (継続行を含む) 全体」を切り出して、抜粋に入る / 入らないを役割ごとに確かめる。
新しい規則を足したら ``RULES`` に足す (足さないと ``test_extract_has_only_listed_rules`` が落ちる)。
契約は docs/change/0059-child-context.md §4.1・§5 S3。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from test_pi_judge_ts import _node

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DRIVER = HERE / "pi" / "child_context_sources_driver.mjs"
FILES = {"global": "home/.chezmoitemplates/agent-instructions.md", "repo": "AGENTS.md"}
ROLES = ("explore", "review", "plan", "worker")

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

ALL = frozenset(ROLES)
NONE: frozenset[str] = frozenset()
WRP = frozenset({"worker", "review", "plan"})
RP = frozenset({"review", "plan"})
WR = frozenset({"worker", "review"})
W = frozenset({"worker"})

# (ファイル, 原文の行の先頭の句, 抜粋に入る役割)。箇条書き・段落・表の行は、先頭の句から次の区切りまでを 1 つの規則とする
RULES: tuple[tuple[str, str, frozenset[str]], ...] = (
    # --- 共通指示 ---
    ("global", "- ユーザーへの説明は日本語で書く", ALL),
    ("global", "- ツール呼び出しのうちユーザーに表示される引数", NONE),
    ("global", "- 利用者への説明で、案件・ToDo・ジョブを", NONE),
    ("global", "- 設計・計画・方針は、**サンクコスト", RP),
    ("global", "- 過去の実測（保守の頻度", RP),
    ("global", "- 既存の案が最良でないと分かったら", RP),
    ("global", "- 利用者の判断が要る分岐・方針・承認は", NONE),
    ("global", "- コミットの承認も `ask` で取る", NONE),
    ("global", "- **例外: ツール `guarded_action`", NONE),
    ("global", "- hook / rules / 承認プロンプトなど", ALL),
    ("global", "- **止まってよいのは", NONE),
    ("global", "- 止まるときは、最終報告に", NONE),
    ("global", "- **待つ間（承認・確認・子の完了）", NONE),
    ("global", "- 完了を報告する前に", W),
    ("global", "- 実行していないチェックの結果を推測で書かない", ALL),
    ("global", "- 使い捨て（試験・実験のスクリプトや出力）", W),
    ("global", "- 後で `docs/` などへ取り込むもの", NONE),
    ("global", "- `.tmp` 自体と `.tmp/keep` は消さない", W),
    ("global", "- 利用者に実行してほしいコマンドは", NONE),
    ("global", "- 長い引数（コミットメッセージなど）", NONE),
    ("global", "- 複数行・長いコマンドは", NONE),
    ("global", "- 作業ディレクトリに依存しない書き方", NONE),
    ("global", "- コードブロックには 1 コマンドずつ", NONE),
    ("global", "- 原因の分からない不具合や予期しない挙動", ALL),
    ("global", "- 手元の調査は、検索で得た仮説を", ALL),
    ("global", "- 出典（URL）と日付を残し", ALL),
    ("global", "- この検索の指示は、明らかなタイプミス", ALL),
    ("global", "- 「別モデルに聞いて」と言われたら", NONE),
    ("global", "- Gemini や Codex など特定のモデル", NONE),
    ("global", "- どちらを使うかと理由を", NONE),
    ("global", "- `review` へは、会話の転写や差分の全文ではなく", NONE),
    ("global", "- 調査・読み取り・影響範囲の洗い出し", NONE),
    ("global", "- 大きく複雑な変更・曖昧な要件", NONE),
    ("global", "- 実装は、担当ファイルを分けて依頼文を書けるなら", NONE),
    ("global", "- 子は会話を見られない", NONE),
    ("global", "- 子の結果は、根拠（パスと行", NONE),
    ("global", "- 外部コードの取り込み・権限や", NONE),
    # --- リポジトリの AGENTS.md ---
    ("repo", "chezmoi で Windows / Ubuntu / WSL / macOS", ALL),
    ("repo", "指示の分担:", NONE),
    ("repo", "変更したら該当するものを実行する。", W),
    ("repo", "| 変更に応じた選択実行（日常）", NONE),
    ("repo", "| 全件（コミット前に 1 回）", NONE),
    ("repo", "| 全体（lint / secret scan）", NONE),
    ("repo", "| OpenCode の実機試験", NONE),
    ("repo", "| agent 設定・hook", W),
    ("repo", "| Windows 資産（静的）", W),
    ("repo", "| chezmoi の展開範囲", W),
    ("repo", "| シェルスクリプト", W),
    ("repo", "| テンプレート（描画して検査）", W),
    ("repo", "| docs の索引整合", W),
    ("repo", "| 展開結果", W),
    ("repo", "日常は `mise run verify`", NONE),
    ("repo", "`*.tmpl` は pre-commit の linter が素通りする", W),
    ("repo", "`pre-commit run --all-files` は git に未登録", W),
    ("repo", "`chezmoi diff` は **sandbox 内では無意味**", W),
    ("repo", "初回のみ `mise install", NONE),
    ("repo", "`*.ps1` / `*.ps1.tmpl`、", W),
    (
        "repo",
        "ここに無いことは一般的な流儀で判断してよい。",
        frozenset({"review", "plan", "worker"}),
    ),
    ("repo", "- 実ファイルを直接編集したら", NONE),
    ("repo", "- `home/.chezmoiscripts/` は", WRP),
    ("repo", "- シェルスクリプトは先頭に `set -eu`", WRP),
    ("repo", "- `.tmpl` は OS 分岐・chezmoi データ", WRP),
    ("repo", "- `.ps1` / `.ps1.tmpl` は UTF-8 BOM", WRP),
    ("repo", "- `SKILL.md` の frontmatter は", WRP),
    ("repo", "- AI CLI の permission / hook / sandbox は", WRP),
    ("repo", "- **設定ファイル・スクリプトのコメントは", WRP),
    ("repo", "- 秘密情報はソースに書かず", WRP),
    ("repo", "- 対話入力が必須なスクリプト", WRP),
    ("repo", "- **利用者に実行してもらう補助スクリプトは", NONE),
    ("repo", "- コミットメッセージは Conventional Commits", NONE),
    ("repo", "- **develop / main に直接コミットしない。**", NONE),
    ("repo", "- **並列にできる作業は子エージェントに任せる。**", NONE),
    ("repo", "- **1 worktree = 1 feature = 1 worker**", NONE),
    ("repo", "- worker はコミットしない", W),
    ("repo", "- **`git flow feature finish`・`git merge`", NONE),
    ("repo", "- 共有されやすいファイル", NONE),
    ("repo", "- 重い検査を同時に回さない", W),
    ("repo", "- **pi の会話（セッション）を複数並行", NONE),
    ("repo", "- 子の結果は、パスと行・コマンドの出力で", NONE),
    ("repo", "- 手順・依頼文の雛形", NONE),
    ("repo", "- 新しい試験ファイルは `scripts/verify.py`", WR),
    ("repo", "- 運用手順やコマンドを追加したら", WRP),
    ("repo", "- **`README.md` は「最短で動かす」", WRP),
    ("repo", "- **`chezmoi init` を前提にした設計にしない。**", WRP),
    ("repo", "- **このリポジトリは公開。", ALL),
    ("repo", "- ドキュメントは日本語で書く", WRP),
)


def _block(text: str, anchor: str) -> str:
    """原文から、anchor で始まる行と、その継続行 (空行・次の箇条書き・印・見出しの手前まで) を切り出す。"""
    lines = text.splitlines()
    hits = [i for i, ln in enumerate(lines) if ln.startswith(anchor)]
    assert len(hits) == 1, f"アンカーが原文に {len(hits)} 件ある: {anchor!r}"
    i = hits[0]
    got = [lines[i]]
    if not lines[i].startswith("|"):
        for ln in lines[i + 1 :]:
            if not ln.strip() or ln.startswith(("- ", "|", "<!--", "#")):
                break
            got.append(ln)
    return "\n".join(got)


@pytest.fixture(scope="module")
def t() -> dict:
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1500:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def src() -> dict[str, str]:
    return {k: (ROOT / v).read_text(encoding="utf-8") for k, v in FILES.items()}


def _extract(t: dict, key: str, role: str) -> str:
    r = t[key]["extract"][role]
    assert r["kind"] == "extract", r
    return r["text"]


@pytest.mark.parametrize("key", FILES)
def test_sources_pass_lint(t, key) -> None:
    assert t[key]["lint"] == {"ok": True, "problems": []}


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("key", FILES)
def test_each_role_gets_an_extract(t, key, role) -> None:
    assert t[key]["extract"][role]["kind"] == "extract"


@pytest.mark.parametrize(
    "anchor", [(f, a, r) for f, a, r in RULES], ids=[f"{f}:{a[:24]}" for f, a, _ in RULES]
)
def test_rule_goes_to_exactly_its_roles(t, src, anchor) -> None:
    """規則の全体 (継続行を含む) が、対応する役割の抜粋に入り、それ以外の役割の抜粋に入らない。"""
    key, a, roles = anchor
    block = _block(src[key], a)
    for role in ROLES:
        inside = block in _extract(t, key, role)
        assert inside == (role in roles), (
            f"{role}: {'入る' if inside else '入らない'} (期待: {sorted(roles)}) {a!r}"
        )


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("key", FILES)
def test_extract_has_only_listed_rules(t, src, key, role) -> None:
    """抜粋の空でない行は、RULES が「この役割に入る」と書いた規則 (表の見出し行を含む) のどれかに属する。"""
    allowed: set[str] = set()
    for f, a, roles in RULES:
        if f == key and role in roles:
            allowed.update(_block(src[key], a).splitlines())
    if key == "repo" and role == "worker":
        allowed.update(["| 対象 | コマンド |", "| --- | --- |"])
    stray = [ln for ln in _extract(t, key, role).splitlines() if ln.strip() and ln not in allowed]
    assert not stray, f"RULES に無い行が {role} の抜粋に入っている: {stray[:3]}"


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("key", FILES)
def test_extract_has_no_parent_only_words(t, key, role) -> None:
    text = _extract(t, key, role)
    for word in ("`ask`", "guarded_action"):
        assert word not in text, (key, role, word)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("key", FILES)
def test_extract_has_no_marks_or_headings(t, key, role) -> None:
    for ln in _extract(t, key, role).splitlines():
        assert not ln.startswith("<!--") and not ln.startswith("#"), (key, role, ln)


def test_mark_note_stays_in_parent_text_only(t, src) -> None:
    """印の注記は、印を無視して全文を読む親・単独のエージェントには残り、子の抜粋には入らない。"""
    note = "印に関係なく全文に従う"
    assert note in src["global"]
    assert note in t["global"]["inherit"]["text"]
    for role in ROLES:
        assert note not in _extract(t, "global", role)
    # 注記は `<!--` で始めない (印に似た行として破損扱いになる)
    line = next(ln for ln in src["global"].splitlines() if note in ln)
    assert not line.startswith("<!--")


def test_identifier_is_first_nonblank_line(src) -> None:
    for key, text in src.items():
        first = next(ln for ln in text.splitlines() if ln.strip())
        assert first == "<!-- child-context: v1 -->", key

# CHG-0012: bash 検査 hook のコマンド解析を 1 か所に集める

- **状態**: In progress
- **更新日**: 2026-10-06
- **基準**: `59c6f9b`（全体除外・トークン誤認の穴 8 件を個別に塞いだ直後）

## 目的と非目的

**目的**: Claude Code / Copilot CLI の bash 検査 hook（`home/dot_claude/hooks/lib/bashrules/`）で、
コマンド文字列の解釈（引用・エスケープ・リダイレクト・区切り）を規則ごとに書かずに済むようにし、
同じ型の素通りを再発させない。

2026-10-05 に見つけた穴 8 件は、ほぼすべて規則ごとの手書きの解釈の食い違いだった
（`"Don't"` の `'` を単引用符と誤認、`2>&1` を引数と誤認、`\rm` を rm と見ない、など）。
解釈は `segment.split()`（引用を見ない）・`shlex.split`（`command_policy.py` だけで 9 か所）・
コマンド全体への正規表現が混在している。

**非目的**:

- OpenCode の guide 規則（`common.toml.tmpl` の正規表現と `guide-plugin/index.js`）。
  JavaScript で Python の解析を共有できず二重実装になる。うっかり防止の層で、本命は境界（`ocs`）
- 外部の bash パーサー（bashlex など）の導入。hook は素の `python3` で動き、Windows でも使う
- 一括の書き換え。安全に関わる層なので退行を避け、規則を 1 つずつ移す
- `command_policy.normalize`（`cd` / ラッパー / `bash -c` の展開）の置き換え。新しい解析は
  正規化済みのセグメントに当てる

## 実施計画

| 段 | 内容 | 状態 |
| --- | --- | --- |
| 1 | 共通の解析関数 `shellparse.parse` を作る（標準ライブラリだけ） | 完了 |
| 2 | 書き込み先の判定 `_write_targets` を移す | 完了 |
| 3 | センシティブなパスの判定 `is_sensitive_path` を移す | 完了 |
| 4 | 秘密の環境変数の判定 `check_secret_env_echo` を移す | 完了 |
| 5 | rm の判定（`rm.py`）を移す | 完了 |
| 6 | 残りの規則の棚卸し（移すか、現状のままにするか） | 未着手 |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り / 消滅

## 現在地

- 段 1〜5 を終えた。解析関数 `bashrules/shellparse.py` は「単純コマンド」（引数の列と
  リダイレクトの列）の並びを返す。書き込み先の判定（`_write_targets`）、ガード設定の上書きの
  判定（`rules_guard.py`）、取得したファイルの保存先（`http.py`）、センシティブなパスの判定
  （`is_sensitive_path`）、秘密の環境変数の判定（`check_secret_env_echo`）、rm / find の判定
  （`rm.py`。`_argvs_of` で対象のコマンドの引数列を集める）がこれを使う
- `is_sensitive_path` は関数の形を変えず、中で単純コマンドに分けてコマンドごとに判定する。
  呼び出し元は 1 コマンド・インラインコードを含むセグメント・`xargs` を含むコマンド全体と
  まちまちなので、以前の振る舞いを落とさないよう次の 2 点を残した
  - 空白を含む引数（`python3 -c "..."` のコード）は空白で区切った断片も調べる
  - リダイレクトの対象（`cat < .env`）も調べる（以前は `split()` で引数に見えていた）
- `check_secret_env_echo` は `Word.expandable`（単引用符と `$'...'` の中身を除いた語）で
  変数の参照を数える。読み込み側のリダイレクト（`<<< "$TOKEN"`）は参照に含め、書き込み先
  （`> "$TOKEN_FILE"`）はパスなので含めない
- 解析はセグメントの分割と引用の解釈だけを担う。`cd` の除去や `bash -c` の展開は
  これまでどおり `normalize` が担い、解析は `_segments()`（正規化済み + 元の文字列）の各要素に当てる
- ヒアドキュメントの本文は読み飛ばさない。実行されない本文は `check_bash.py` が規則の前に
  `split_heredoc_body` で取り除き、実行される本文（`bash <<EOF`）は行として残す。解析が本文を
  読み飛ばすと、後者の検査が漏れる
- bashrules 内のリダイレクトの正規表現（`REDIRECT_TARGET_RE`）は段 4 で消した。別の hook
  （`executable_redirect-tmp.py`、`/tmp` を `./.tmp` へ誘導する）は独自の正規表現を持つ（段 6 の対象）
- `normalize` は語を空白で結び直し、空白を含む語にしか引用符を付け直さない。もとは引用されていた
  `;` などを解析し直すと区切りとして扱うことがある。元の文字列も併せて解析するので、引用どおりの
  読み方も必ず調べる（`_segments()` が両方を返す）

## 未解決点

- Windows の PowerShell での実機確認（hook は Windows でも動く）
- 段 6 でどこまで移すか。移す利点が薄い規則（正規表現で十分なもの）は現状のままにしてよい

## 次の調査・実験

- 段 6（残りの規則の棚卸し）。`segment.split()` / `shlex.split` / コマンド全体への正規表現が
  残っている規則を一覧にし、移すか現状のままにするかを決める
- 退行が出たら、その入力をテストに足してから直す

## 評価基準

- 必須: 既存テストがすべて通る（止めていたものを通さない。通していたものを止めない）
- 必須: 2026-10-05 に塞いだ 8 件の素通りの例が、移した後も止まる
- 必須: 標準ライブラリだけで動く
- 望ましい: 移した規則から、引用・リダイレクトの手書きの処理が消える

## 候補比較

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| 自前の小さな解析関数（`shellparse.py`） | 依存が増えない。必要な構文（引用・区切り・リダイレクト）に絞れる | bash の完全な文法ではない | 実際の規則で足りるか | 採用 | 段 2 のテスト |
| bashlex などの外部パーサー | 文法の網羅性が高い | hook の依存が増える。Windows を含む全環境への配布が要る | — | 見送り | — |
| 規則ごとの修正を続ける | 変更が小さい | 同じ型の穴が再発する（2026-10-05 に 8 件） | — | 見送り | — |
| `command_policy.normalize` を作り直す | 解析を 1 層にできる | 影響範囲が全規則と `[bash] deny/ask` の照合に及ぶ | — | 保留 | 段 6 の棚卸しで再検討 |

扱い: 未評価 / 検証中 / 有望 / 採用 / 保留 / 見送り

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `bashrules/shellparse.py` | 無し → 単純コマンドとリダイレクトへの解析 | 規則ごとの手書きの解釈が穴の原因 | 段 1 で適用 |
| `bashrules/_shared.py` の `_write_targets` | 正規表現 + `split()` → `shellparse.parse` | 2026-10-05 の穴（末尾の `2>&1`、`>& file`） | 段 2 で適用 |
| `bashrules/sensitive.py` の `is_sensitive_path` | `split()` → `shellparse.parse` のコマンドごと | 引用・リダイレクトの取り違え（`grep -e. .env` など） | 段 3 で適用 |
| `bashrules/sensitive.py` の `check_secret_env_echo` | 手書きの単引用符除去 + `REDIRECT_TARGET_RE` → `Word.expandable` とリダイレクトの列 | 二重引用符の中の `'` の取り違え（`"Don't"`） | 段 4 で適用 |
| `bashrules/rm.py`（rm / find の判定 6 関数） | `segment.split()` と手書きの引用除去 → `_argvs_of`（`shellparse` の値） | 引用・リダイレクトの取り違え（`\rm`、末尾の `2>/dev/null`） | 段 5 で適用 |

## 実装・検証

段 1・2（2026-10-05）:

- `test/agents/test_shellparse.py` を追加（区切り・引用・エスケープ・リダイレクト・
  ヒアドキュメントを読み飛ばさないこと・壊れた入力で止まらないこと。50 件）
- `uv run --with pytest --with pyyaml --no-project pytest test/agents/ -q` → 3079 passed, 7 skipped
- 移行の書き漏れ（`sed -i` の分岐に旧変数名 `tokens` が残った）を既存テスト
  `test_round3_false_positives` が検出した。hook は例外で安全側に倒して拒否するため、
  `sed -i 's/password/pw/' app.py` の誤拒否として現れた。直して再実行で通過
- `uv run pre-commit run --all-files` → 全 Passed
- Windows 実機は未確認

段 3（2026-10-05）:

- `test_check_bash_sensitive.py` に追加: 止める例 `cat < .env` / `wc -l < ~/.aws/credentials` /
  `cat "dir with space/.env"`、通す例 `cp .env.example .env 2>/dev/null` /
  `cp .env.example .env > /dev/null 2>&1`（末尾のリダイレクトをコピー先と取り違えない）
- `uv run --with pytest --with pyyaml --no-project pytest test/agents/ -q` → 3084 passed, 7 skipped
  （テスト追加後）
- `uv run pre-commit run --all-files` → 全 Passed
- 注意: `pre-commit run --all-files` は git に未登録の新規ファイルを検査しない。段 1 の
  `shellparse.py` の ruff の指摘はコミット時に初めて出た

段 4（2026-10-06）:

- `shellparse.Word.expandable` を追加し、`sensitive.py` の `_drop_single_quoted` を移した。
  `_shared.REDIRECT_TARGET_RE` を削除
- テストを追加: `test_shellparse.py` に `expandable` の 7 件、`test_check_bash_sensitive.py` に
  止める例 `cat <<< "$GITHUB_TOKEN" > out.txt`、通す例 `echo ok > "$TOKEN_FILE"`
- 移行直後（テスト追加前）の `pytest test/agents/ -q` → 3084 passed, 7 skipped
- テスト追加後の `pytest test/agents/ -q` → 3093 passed, 7 skipped
- `uv run pre-commit run --all-files` → 全 Passed / `lint_docs.py` → 問題なし

段 5（2026-10-06）:

- `rm.py` の 6 関数（`check_find_dangerous` / `check_find_root_guard` / `_rm_is_workspace_local` /
  `_rm_targets_scratch_only` / `_find_targets_scratch_only` / `check_rm_root_guard`）を
  `_argvs_of` の上に書き直した。手書きの `strip("'\"")` が消えた
- 移行直後（テスト追加前）の `pytest test/agents/ -q` → 3093 passed, 7 skipped
- `test_check_bash_file_ops.py` に止める例を追加: `rm -rf ~ 2>/dev/null` /
  `rm -rf / > /dev/null 2>&1` / `find ~ -delete 2>/dev/null`
- テスト追加後の `pytest test/agents/ -q` → 3096 passed, 7 skipped
- `uv run pre-commit run --all-files` → 全 Passed / `lint_docs.py` → 問題なし

## 重要な更新

- 2026-10-05: 起票。穴 8 件の修正（`e779562`〜`59c6f9b`）で、原因が解釈の分散にあると判断した

## 終了結果

（未記入）

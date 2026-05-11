# ADR-0006: Skill 内環境変数 (`${CLAUDE_SKILL_DIR}` 等) の翻訳

- Status: Accepted
- Date: 2026-04-29
- Deciders: maintainer
- Related: ADR-0002, ADR-0003, REQ-022

## Context

`home/dot_claude/skills/` 配下の skill 本文には Claude 固有の環境変数置換が散見される:

| 変数 | 用途 | 出現 skill |
| --- | --- | --- |
| `${CLAUDE_SKILL_DIR}` | skill ディレクトリの絶対パス。同梱 references / scripts への参照 | `adr`, `commit`, `fix`, `onboarding` |
| `$ARGUMENTS` | skill 起動時の引数 | `adr`, `onboarding` |
| `${CLAUDE_SESSION_ID}` | セッション ID | （現状未使用） |
| `${CLAUDE_EFFORT}` | effort 設定 | （現状未使用） |

Copilot CLI 公式 docs にはこれらの環境変数の対応物が **明示的には記載されていない**（research の TODO 該当）。Skill 本文がそのまま展開されると、`${CLAUDE_SKILL_DIR}` は未定義変数として解決されない可能性が高い。

## Decision

### `${CLAUDE_SKILL_DIR}` の置換戦略

skill 本文の `${CLAUDE_SKILL_DIR}` は **chezmoi テンプレート展開時に絶対パスへ静的置換** する。

- `home/dot_copilot/skills/<name>/SKILL.md.tmpl` で記述
- テンプレート内では `{{ .chezmoi.homeDir }}/.copilot/skills/<name>` を埋め込む
- 例: `${CLAUDE_SKILL_DIR}/references/adr-template.md` → `/home/$USER/.copilot/skills/adr/references/adr-template.md`

代替として「Copilot 公式の skill ディレクトリ環境変数」を待つ選択肢もあるが、現時点で公式仕様が未確定のため **静的置換を採用** する。Copilot 側で同等変数が判明した場合は本 ADR を `Superseded by` で更新する。

### `$ARGUMENTS` の取り扱い

Copilot CLI の Skill 引数受け渡しは公式 docs では「`/<skill-name> [args]`」とのみ記述があり、Claude の `$ARGUMENTS` のような厳密な置換規則は不明（TODO）。

- skill 本文では `$ARGUMENTS` 表記を **そのまま残す**
- 動作確認時に Copilot が置換しない場合、skill 本文を「引数は会話冒頭で渡してください」のような誘導文に書き換える

`$ARGUMENTS` を使用している skill (`adr`, `onboarding`) について:

- いずれも **引数なしでも動作可能**（不足時はユーザーに対話で確認）
- 引数受け渡しに失敗しても致命的でないため、`partial` ステータスで許容する

### 未使用変数

- `${CLAUDE_SESSION_ID}` / `${CLAUDE_EFFORT}` は現状の 12 資産では未使用 → 対応不要

### scripts/ 内シェルスクリプトのパス参照

- skill 同梱の `scripts/` 配下スクリプトは **相対パス** で配置される（skill 本文から `${CLAUDE_SKILL_DIR}/scripts/foo.sh` と呼ばれる）
- 上記の静的置換で解決される
- スクリプト内部で他のファイルを参照する場合も、起動 cwd に依存しない記述が望ましい
  → 既存スクリプト 2 件 (`get-git-context.sh`, `check-agents.sh`) は **cwd 依存**（`git status`, `test -f AGENTS.md` 等を素の cwd で実行）。リポジトリ root から `/skill 名` を起動する標準ワークフロー前提では問題ないが、サブディレクトリから起動された場合に挙動が変わる可能性がある
  → 本 ADR では **「リポジトリ root から起動されることを前提とする」** 制約を維持し、スクリプト改修は行わない。受け入れ基準として `tasks.md` で「リポジトリ root から起動して動く」ケースを検証対象にする

## Consequences

### 肯定的

- 公式仕様の未確定要素を待たずに移植を進められる
- 静的置換は chezmoi の標準機能で完結し、追加ツール不要
- skill ディレクトリ移動時はテンプレート再生成だけで対応できる

### 否定的

- skill 本文が `.tmpl` になり、ソースの可読性が若干下がる（diff レビュー時に注意）
- Copilot 側で環境変数仕様が将来確立した場合、テンプレートを書き直す必要がある
- `$ARGUMENTS` の挙動次第で `adr`, `onboarding` が `partial` になる可能性がある

## Options Considered

1. **採用**: chezmoi テンプレートで `${CLAUDE_SKILL_DIR}` を絶対パスへ静的置換
2. 却下: skill 本文を相対パス参照に書き換え（`./references/adr-template.md` 等）
   - 却下理由: Copilot が skill 起動時の cwd を skill ディレクトリに変更する保証がない
3. 却下: 環境変数を `~/.copilot/settings.json` の `env` 等で実行時注入
   - 却下理由: Copilot 公式 settings.json に skill 専用 env 注入の仕組みが見当たらない

## References

- `docs/research/copilot-spec.md` §1「Skills」
- `docs/research/copilot-spec.md` §1.4「Claude / 標準互換」
- `docs/research/claude-spec.md` §1.5「引数受け渡し」
- `home/dot_claude/skills/adr/SKILL.md`（`${CLAUDE_SKILL_DIR}` 使用例）

# ADR-0007: chezmoi テンプレート戦略

- Status: Accepted（条件付き — 「Hook の bind 方法」は実装フェーズの検証で最終確定）
- Date: 2026-04-29
- Deciders: maintainer
- Related: ADR-0002, ADR-0004, ADR-0005, ADR-0006, REQ-050

## Context

現状の `home/dot_copilot/` は以下のシンプルな構成:

```text
home/dot_copilot/
├── README.md
├── modify_config.json     # chezmoi:modify-template で settings.json を merge
└── mcp-config.json
```

`modify_config.json` は chezmoi の **modify-template** 機構で `~/.copilot/config.json` を merge する。

本移植では以下を新たに配置する必要がある:

- 7 件の skill ディレクトリ + 各々の SKILL.md / references / scripts
- 5 件の hook スクリプト
- hook を bind するための settings.json への変更（`hooks` セクション）
- ADR-0005 の permission 翻訳結果（`allowed_urls` 拡張、deny ルール追加）

これらを chezmoi 上でどう構造化するかを統一する必要がある。

## Decision

### ファイル名と新旧キー

- 既存テンプレートは `modify_config.json`（出力先 `~/.copilot/config.json`）。
- Copilot CLI は `config.json` を起動時に `settings.json` に自動マイグレートするが、本フェーズでは **既存の `modify_config.json` 名と出力先をそのまま維持** する。
  - 理由: ファイル名変更は chezmoi の destination パス変更を伴い、既存環境への影響が大きい
  - 将来 Copilot CLI が `config.json` のサポートを終了する場合に rename を ADR で改めて扱う

### 配置レイアウト

```text
home/dot_copilot/
├── README.md
├── modify_config.json                  # 既存（permission/url/hooks の inline 拡張）
├── mcp-config.json                     # 既存
├── skills/                             # 新規（chezmoi がそのまま ~/.copilot/skills/ へ）
│   ├── adr/
│   │   ├── SKILL.md.tmpl               # ${CLAUDE_SKILL_DIR} 置換のためテンプレ化
│   │   └── references/
│   │       └── adr-template.md
│   ├── commit/
│   │   ├── SKILL.md.tmpl
│   │   ├── references/conventional-commits-spec.md
│   │   └── scripts/
│   │       └── executable_get-git-context.sh
│   ├── criticalthink/
│   │   └── SKILL.md
│   ├── explain/
│   │   └── SKILL.md
│   ├── fix/
│   │   ├── SKILL.md.tmpl
│   │   └── references/{cpp,go-rust,js-ts,python}.md
│   ├── learn/
│   │   └── SKILL.md
│   └── onboarding/
│       ├── SKILL.md.tmpl
│       ├── references/{agents-template,review-checklist}.md
│       └── scripts/
│           └── executable_check-agents.sh
└── hooks/                              # 新規（chezmoi がそのまま ~/.copilot/hooks/ へ）
    ├── executable_check_bash.py
    ├── executable_redirect-tmp.py
    ├── executable_update-adr-on-stop.py
    ├── executable_format-file.sh
    └── executable_markdownlint.sh
```

### Hook の bind 方法

ADR-0004 で決めた I/O 方針に従い、hook の bind は以下のいずれかで実現する。

**現時点で公式 docs 未確定**: Copilot CLI の `~/.copilot/config.json` / `settings.json` 内に `hooks` セクションを inline 記述できるか、`~/.copilot/hooks/` 個別ファイルのファイル名規約はどうかは、いずれも `docs/research/copilot-spec.md` 末尾の TODO に該当する（changelog 言及のみで reference 未記載）。

→ **本 ADR の bind 方式は条件付き採用** とし、実装フェーズで以下の検証を経てから確定する（REQ-051）:

1. **第一候補**: `modify_config.json` 内の `hooks` セクション inline 記述
   - Claude 側の `modify_settings.json` と同形式
   - chezmoi:modify-template で merge 時に追加
2. **フォールバック**: `home/dot_copilot/hooks/` 配下に `<event>.json` のようなファイルを置き、chezmoi で `~/.copilot/hooks/` に展開する個別ファイル方式
   - Copilot CLI が個別ファイルから auto-discover する仕様であれば採用
3. **最終フォールバック**: hook を `~/.copilot/skills/<name>/SKILL.md` 内のテンプレート参照にし、skill 起動時に都度実行する（hook 機構の使用を諦める）

第一候補の検証が完了するまで、hook 移植のステータスは ADR-0001 の判定基準により `partial` または `deferred` とする。

### `modify_config.json` の責務

`modify_config.json` の merge 内容は以下を含む:

- 既存: `banner`, `model`, `reasoning_effort`, `allowed_urls`
- 追加: ADR-0005 の翻訳結果（`allowedUrls` 拡張、必要に応じ `deniedUrls`）
- 追加: ADR-0004 の hook bind（`hooks.preToolUse`, `hooks.postToolUse`, `hooks.sessionEnd` 等）

`modify_config.json` の `merge` ロジックは現状 list を上書きする問題を `concat+uniq` で回避しているが、`hooks` 配列も同様の処理を要する → 実装フェーズで調整する。

### Skill のテンプレート化

ADR-0006 に従い、`${CLAUDE_SKILL_DIR}` を含む skill だけ `.tmpl` 化する:

| Skill | テンプレ化要 |
| --- | --- |
| `adr` | yes (`${CLAUDE_SKILL_DIR}/references/adr-template.md`) |
| `commit` | yes (`${CLAUDE_SKILL_DIR}/scripts/get-git-context.sh`, `${CLAUDE_SKILL_DIR}/references/conventional-commits-spec.md`) |
| `criticalthink` | no（変数なし） |
| `explain` | no |
| `fix` | yes (`${CLAUDE_SKILL_DIR}/references/<lang>.md`) |
| `learn` | no |
| `onboarding` | yes (`${CLAUDE_SKILL_DIR}/scripts/check-agents.sh`, `${CLAUDE_SKILL_DIR}/references/...`) |

テンプレ内変数: `{{ .chezmoi.homeDir }}/.copilot/skills/<name>` を埋め込む。

### 実行可能ファイルの命名

chezmoi の `executable_` 接頭辞慣例に従う:

- 既存 hook 5 件: 命名そのまま（`executable_check_bash.py` 等）
- skill 同梱 scripts: 既存命名 (`executable_get-git-context.sh`, `executable_check-agents.sh`) を維持

## Consequences

### 肯定的

- 既存の `modify_config.json` 構造を踏襲するため、新規ファイルが少ない
- skill / hook の配置場所が一意で、chezmoi の destination も自然
- Skill 本文のテンプレ化は変数を含むものに限定され、過剰な複雑化を避けられる

### 否定的

- `modify_config.json` の merge ロジックに `hooks` 配列処理を追加する必要があり、実装フェーズの工数が増える
- Copilot CLI の `~/.copilot/hooks/` 個別ファイル仕様が将来 stable 化した場合、ADR の見直しが必要になる
- `config.json` → `settings.json` 自動マイグレーションは Copilot 任せで、merge ロジックがどちらに対して走るかは実環境で確認が必要

## Options Considered

1. **採用**: 既存 `modify_config.json` を拡張、skill / hook は配下に配置、変数を含む skill のみ `.tmpl` 化
2. 却下: 全 skill を `.tmpl` 化
   - 却下理由: 不要な変換が入り、レビューコストが増す
3. 却下: `modify_config.json` を `modify_settings.json` にリネーム
   - 却下理由: 既存環境の `~/.copilot/config.json` パス変更による副作用が読めない

## Status の補足

本 ADR は **条件付き Accepted**: 「Hook の bind 方法」の第一候補（`modify_config.json` inline）は実装フェーズの検証完了で確定する。検証結果に応じてフォールバック手段に切り替える可能性がある（REQ-051）。

## References

- `home/dot_copilot/modify_config.json`（既存テンプレート）
- `home/dot_claude/modify_settings.json`（Claude 側のリファレンス）
- `docs/research/copilot-spec.md` §7「settings.json スキーマ」
- ADR-0004, ADR-0005, ADR-0006

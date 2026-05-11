# Tasks: 実装フェーズの作業分解

> 仕様（[`requirements.md`](./requirements.md), [`design.md`](./design.md), `adr/*.md`, [`skills.md`](./skills.md), [`hooks.md`](./hooks.md)）に基づき、`home/dot_copilot/` への実装作業を分解する。
> 本ドキュメントは **次フェーズ（実装）の入力**であり、本フェーズでは作成のみ行う。
> ID 規約: `T-<phase>-<seq>`。

## フェーズ構成

| フェーズ | 内容 | 依存 |
| --- | --- | --- |
| Phase 0 | bind 方式の検証（hook bind の inline 可否） | — |
| Phase 1 | 共通基盤 | Phase 0 |
| Phase 2 | Skill 移植（7 件） | Phase 1 |
| Phase 3 | Hook 移植（5 件） | Phase 1 |
| Phase 4 | Permission 翻訳 | Phase 1 |
| Phase 5 | 検証 / 受け入れテスト | Phase 2-4 |
| Phase 6 | ドキュメント反映・ステータス確定 | Phase 5 |

---

## Phase 0: bind 方式の検証（前提タスク）

### T-0-1: hook bind 方式を実機で確定する

- 関連: ADR-0007, REQ-051
- 目的: `~/.copilot/config.json` / `settings.json` 内に `hooks` セクションを inline 記述できるか公式に未確定なため、Copilot CLI 実機で検証
- 手順:
  1. `~/.copilot/config.json` に `{"hooks":{"preToolUse":[{"type":"command","matcher":".*","command":"echo test >&2"}]}}` を merge
  2. `copilot` を起動して任意の Bash 実行を試み、hook が呼ばれるか確認
  3. inline NG なら `~/.copilot/hooks/<event>.json` 形式を試す
  4. それも NG なら `~/.copilot/hooks/` 配下のファイル名規約を Copilot CLI changelog から再調査
- 完了条件: hook 配置先と bind スキーマが確定し、ADR-0007 を更新（必要なら Superseded by を追記）

### T-0-2: shell tool deny の永続化先を確定する

- 関連: ADR-0005, REQ-044
- 目的: Claude `Bash(...)` deny の Copilot 翻訳先（`permissions-config.json` vs settings.json inline）を確定
- 手順:
  1. `copilot --deny-tool='shell(rm:*)'` を 1 回実行
  2. `~/.copilot/permissions-config.json` の差分を観察
  3. 同ファイルを chezmoi 管理対象にできるか（自動更新タイミングと chezmoi apply の競合）を確認
- 完了条件: deny の install 経路が確定し、ADR-0005 を更新

### T-0-3: skill 引数受け渡しの動作確認

- 関連: ADR-0006, REQ-023
- 目的: `$ARGUMENTS` が Copilot CLI で置換されるか確認
- 手順:
  1. テスト用 `~/.copilot/skills/argtest/SKILL.md` を作成（本文に「引数: $ARGUMENTS」とだけ書く）
  2. `/argtest hello` で起動して出力を観察
  3. 置換されない場合、Copilot 公式の引数受け渡し構文を再調査
- 完了条件: `$ARGUMENTS` の動作 / 不動作が確定。動かない場合は SKILL-adr-003, SKILL-onboarding-005 のフォールバック誘導文を skill 本文に明記

---

## Phase 1: 共通基盤

### T-1-1: `home/dot_copilot/skills/` ディレクトリの新規作成

- 関連: ADR-0007
- 完了条件: `home/dot_copilot/skills/.keep` などで chezmoi に空ディレクトリを認識させる（必要なら）

### T-1-2: `home/dot_copilot/hooks/` ディレクトリの新規作成

- 関連: ADR-0007
- 完了条件: 同上

### T-1-3: `home/dot_copilot/modify_config.json` の merge ロジック拡張

- 関連: ADR-0007, REQ-050, REQ-052
- 目的: 既存の `allowed_urls` の concat+uniq パターンを `deniedUrls` および `hooks` 配列にも適用できるようにする
- 完了条件: chezmoi apply を 2 回連続で実行しても出力 JSON が変化しない（idempotent）

---

## Phase 2: Skill 移植（7 件）

各 skill につき以下の共通サブタスクを実施:

- (A) ディレクトリ作成（`home/dot_copilot/skills/<name>/`）
- (B) SKILL.md または SKILL.md.tmpl の作成（フロントマター + 本文）
- (C) `${CLAUDE_SKILL_DIR}` を含む場合は `.tmpl` 化して `{{ .chezmoi.homeDir }}/.copilot/skills/<name>` に静的置換（ADR-0006）
- (D) `context: fork` 持ちの場合は本文冒頭に Task ツール経由 subagent 起動指示を追記（ADR-0003）
- (E) references/, scripts/ の同梱（必要なものだけ）
- (F) chezmoi apply で展開され、`/<name>` で起動できることを確認

### T-2-1: `criticalthink` 移植

- 関連: SKILL-criticalthink-*, ADR-0002
- 特記: テンプレ化不要、Task 誘導不要（main context で実行）
- 受け入れ: SKILL-criticalthink-001, -002

### T-2-2: `explain` 移植

- 関連: SKILL-explain-*, ADR-0002, ADR-0003
- 特記: テンプレ化不要、Task 誘導必要（`explore` subagent を指定）
- 受け入れ: SKILL-explain-001, -002

### T-2-3: `learn` 移植

- 関連: SKILL-learn-*, ADR-0002, ADR-0003
- 特記: テンプレ化不要、Task 誘導必要（`general-purpose`）
- 受け入れ: SKILL-learn-001, -002, -003

### T-2-4: `commit` 移植

- 関連: SKILL-commit-*, ADR-0002, ADR-0003, ADR-0006
- 特記: テンプレ化必要、scripts/get-git-context.sh 同梱、references/conventional-commits-spec.md 同梱
- 受け入れ: SKILL-commit-001, -002, -003

### T-2-5: `fix` 移植

- 関連: SKILL-fix-*, ADR-0002, ADR-0003, ADR-0006
- 特記: テンプレ化必要、references/{cpp,go-rust,js-ts,python}.md 同梱
- 受け入れ: SKILL-fix-001, -002, -003

### T-2-6: `adr` 移植

- 関連: SKILL-adr-*, ADR-0002, ADR-0003, ADR-0006
- 特記: テンプレ化必要、references/adr-template.md 同梱、$ARGUMENTS フォールバック誘導文
- 受け入れ: SKILL-adr-001, -002, -003

### T-2-7: `onboarding` 移植

- 関連: SKILL-onboarding-*, ADR-0002, ADR-0003, ADR-0006
- 特記: テンプレ化必要、scripts/check-agents.sh + references/{agents-template,review-checklist}.md 同梱、$ARGUMENTS フォールバック誘導文
- 受け入れ: SKILL-onboarding-001〜005

---

## Phase 3: Hook 移植（5 件中 4 件 + 1 件 dropped）

各 hook につき以下の共通サブタスクを実施:

- (A) スクリプトを `home/dot_copilot/hooks/executable_<name>.{py,sh}` に配置
- (B) Claude 慣用の `exit 2 + stderr` を **`stdout JSON + exit 0`** に書き換え（ADR-0004）
- (C) 入力フィールド名 helper（snake_case / camelCase 両対応）を hook 内に持たせる
- (D) `tool_name` (Claude) 想定だった部分は `bash` / `read` / `write` / `edit` / `multiEdit` (Copilot) に対応
- (E) fail-open 化（JSON parse 失敗・例外時 exit 0）
- (F) `modify_config.json` の `hooks.preToolUse` / `hooks.postToolUse` / `hooks.sessionEnd` への bind 追記（T-0-1 で確定した方式に従う）
- (G) chezmoi apply で展開され、想定 event で発火することを確認

### T-3-1: `check_bash` 移植

- 関連: HOOK-check-bash-*, ADR-0004, ADR-0005
- 特記: 既存の Python ロジック（8 カテゴリのチェック）はそのまま流用、I/O のみ書き換え
- 受け入れ: HOOK-check-bash-001〜009

### T-3-2: `redirect-tmp` 移植 + 機能拡張

- 関連: HOOK-redirect-tmp-*, ADR-0004, ADR-0005, REQ-041
- 特記: 既存の `/tmp` 検出に **加えて** `tool_input.file_path` / `tool_input.path` の `SENSITIVE_PATH_PATTERNS` 検査を追加
- 受け入れ: HOOK-redirect-tmp-001〜004

### T-3-3: `update-adr-on-stop` 移植（partial）

- 関連: HOOK-update-adr-*, ADR-0004
- 特記: bind を `sessionEnd` に変更、`additionalContext` 注入を試みつつ stderr ログでも残す、マーカーファイル名を `copilot_adr_checked_<session_id>` に変更
- 受け入れ: HOOK-update-adr-001〜003

### T-3-4: `markdownlint` 移植（partial）

- 関連: HOOK-markdownlint-*, ADR-0004
- 特記: bind を `postToolUse` に変更、自動修正のみ実行、残存違反フィードバックは諦め stderr ログに留める
- 受け入れ: HOOK-markdownlint-001〜003

### T-3-5: `format-file` の non-installation 確認

- 関連: HOOK-format-file-001
- 特記: `home/dot_copilot/hooks/` に **配置しない** ことを確認、README に dropped と明記
- 受け入れ: HOOK-format-file-001

---

## Phase 4: Permission 翻訳

### T-4-1: URL allow / deny の反映

- 関連: REQ-043, ADR-0005
- 手順: Claude `WebFetch(domain:X)` リスト全件を `home/dot_copilot/modify_config.json` の `allowedUrls` に追加（既存の concat+uniq で merge）
- 受け入れ: chezmoi apply 後、`~/.copilot/config.json` の `allowedUrls` に Claude 側全件が含まれる

### T-4-2: shell tool deny の install

- 関連: REQ-040, REQ-044, ADR-0005
- 前提: T-0-2 完了
- 手順: T-0-2 で確定した方法で Claude `Bash(*)` deny 全件を Copilot に install
- 受け入れ: 試しに deny 対象コマンド（例 `rm -rf /tmp/foo`）を Copilot に依頼すると拒否される

### T-4-3: ask 翻訳（実装上は無アクション）

- 関連: REQ-042
- 手順: Claude `ask` リスト 9 件は **何も install しない**ことを確認し、README に明記
- 受け入れ: なし（実装上のアクションなし）

---

## Phase 5: 検証 / 受け入れテスト

### T-5-1: 全 Skill の手動 invocation 確認

- 関連: REQ-020
- 手順: `/criticalthink`, `/explain`, `/learn`, `/commit`, `/fix`, `/adr`, `/onboarding` を順に起動し、本文が表示され、誘導文（Task ツール起動指示）が出ることを確認
- 受け入れ: 7 件全てで起動成功

### T-5-2: 全 Hook の発火確認

- 関連: REQ-030, REQ-033
- 手順: 各 hook の代表的な EARS 文に対応する操作を Copilot に依頼し、期待通り deny / additionalContext 注入 / stderr ログが出ることを確認
- 受け入れ: HOOK-*-* の Event-driven 文すべて pass

### T-5-3: chezmoi apply の冪等性確認

- 関連: REQ-052
- 手順: `chezmoi apply` を 2 回連続で実行し、`~/.copilot/config.json` / `~/.copilot/skills/` / `~/.copilot/hooks/` に差分が出ないことを確認
- 受け入れ: `chezmoi diff` の出力が空

### T-5-4: 機密ファイル保護の総合テスト

- 関連: REQ-040, REQ-041
- 手順: 以下のいずれも deny されることを確認:
  - Bash: `cat ~/.ssh/id_rsa`（check_bash 経由）
  - Bash: `tar czf out.tgz ~/.ssh/`（check_bash 経由）
  - Read tool: `~/.ssh/id_rsa`（redirect-tmp 拡張経由）
  - Write tool: `./.env.production`（redirect-tmp 拡張経由）
- 受け入れ: 4 ケース全て deny

---

## Phase 6: ドキュメント反映・ステータス確定

### T-6-1: skills.md / hooks.md / README.md のステータス更新

- 関連: REQ-002b, REQ-060
- 手順: Phase 5 の結果に基づき、各資産のステータスを `migrated` / `partial` / `deferred` / `dropped` に確定
- 受け入れ: 全 12 資産のステータスが確定し、3 ファイルで一致

### T-6-2: ADR の Status 更新

- 関連: ADR-0005, ADR-0007
- 手順: T-0-1 / T-0-2 の結論に基づき、ADR-0005 / ADR-0007 を `Accepted`（確定）または `Superseded by` で更新
- 受け入れ: ADR の Status 欄が現実と一致

### T-6-3: TODO の解消・残置確認

- 関連: REQ-061
- 手順: requirements.md / 各 ADR / hooks.md / skills.md の `TODO: 要確認` をチェックし、解消できたものは消し、残るものは「実装フェーズ完了時点でも未確認」として明記
- 受け入れ: 残 TODO に対して将来対応の見通し（次に確認すべきタイミング）が書かれている

### T-6-4: home/dot_copilot/README.md の刷新

- 関連: REQ-060
- 手順: `home/dot_copilot/README.md`（実装側の README）を新構成（skills/ hooks/ の存在）に合わせて更新
- 受け入れ: skills / hooks の参照リンクが `docs/spec/` を指している

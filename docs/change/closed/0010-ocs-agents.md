# CHG-0010: ocs の中でも common.toml のエージェントとコマンドを使う

- **状態**: Done
- **更新日**: 2026-09-29
- **終了日**: 2026-09-29
- **基準**: `55f7e0d`（OpenCode `v2.0.14` / Fence `0.1.67`）

> **この文書は当時の記録。** 現在の仕様は [opencode-sandbox](../../spec/opencode-sandbox.md) の「エージェントとコマンド」。
> 採用したもの・見送ったもの・反映先・移管した未完事項は「終了結果」にまとめた。
> 「現在地」「未解決点」「次の調査・実験」は、配備の前（2026-09-29）の記録。

## 目的と非目的

`ocs`（OpenCode を Fence の境界で包むランチャー。[仕様](../../spec/opencode-sandbox.md)）の中では、
`common.toml` で定義したエージェント（`bypass`・`bypass-worker`・`commit`・`review`・`fleet-worker` など）と
コマンド（`/fleet` など）が使えない。隔離版の設定（`~/.config/opencode-sandbox/opencode.json`）に
エージェントとコマンドの定義が入っていないため。

これは、通常版の設定から隔離版の制限を緩められないようにする旧来の方針の結果だった。
[ADR-0012](../../adr/0012-ocs-boundary-for-accidents.md) で境界の目的をうっかりの防止に絞ったので、
境界の中で `bypass`（全部 allow）を使うのはむしろ自然な組み合わせになった（OS の境界が守る）。

**目的**: `common.toml` のエージェントとコマンドを、隔離版の設定にも同じ定義で出す。

**非目的**:

- 通常版の `opencode.json` から `agent` / `agents` を引き継ぐこと。単一ソースは `common.toml` のまま
- 隔離版の設定の書き出しを `chezmoi apply` 時へ寄せること（CHG-0009 から移管した段 6。この案件では扱わない）

## 実施計画

| 段 | 解決したいこと | 内容 | 状態 |
| --- | --- | --- | --- |
| 1 | `ocs` の中で `bypass` などを使いたい | `generate.py` が `rules.json` の `sandbox` 節にエージェント・コマンド（とモデルの割り当て・プロバイダの接続設定）を出し、`ocs` の `config.py` が隔離版の設定へ管理キーとして書く | 完了（本物の `ocs` で確認済み） |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り / 消滅

## 現在地

- 2026-09-29 に起票した。隔離版の設定のキーは `$schema`・`experimental`・`model`・`permissions`・
  `plugins`・`snapshots` だけで、`agent` / `agents` / `commands` が無いことを実物で確かめた
- 隔離版の `permissions` は shell を `*` で allow し、秘密や危険な操作だけを deny / ask にしている
  （確認が出るのは十数個）。`bypass-worker` への `subagent` の deny も入っている
- **段 1 を実装し、一時の設定・DB と Fence の境界の中で確かめた**（「実装・検証」）。
  `bypass` を選べ、`bypass-worker` は `bypass` からだけ起動でき、`review` などのモデルの割り当ても効いた
- 段 1 は `6bc485d` までで push 済み。この PC ではまだ `chezmoi apply` していない
  （隔離版の設定に `agent` / `agents` / `commands` がまだ無い）
- 2026-09-29 に、`c2cc535..6bc485d`（CHG-0009 の Fence 化と段 1）を別系統のモデル（`gpt-6-astra`）で
  5 ラウンドのレビューループにかけた。指摘は 13 → 11 → 10 → 5 → 3 件（R5 は BLOCKER 1・MINOR 2、NIT 1）。
  直したものは退避の間引き・不完全な退避、下位ディレクトリや配備先での起動、symlink の扱い、
  `ocs --check` の検査先、テストの git 環境の隔離など。設定の生成（本案件の段 1）は R3 で指摘なし

## 未解決点

- **本物の `ocs` での確認**（配備の後）: `bypass` を選べる、`bypass` から `bypass-worker` を起動できる、
  `/fleet` が出る
- `bypass` は permission を全部 allow にし、隔離版の `permissions` の deny も外れる。境界の外の秘密は
  OS の境界で読めない。**ワークスペースの中の秘密（`.env` など）は `bypass` から読める**
  （guide plugin の伏字化と `grep` / `glob` の結果フィルタも `bypass` では素通りになる。コードからの判断で、実機では未確認）。
  通常版の `bypass` と同じ性質で、ADR-0012 の範囲では受け入れる
- 業務 PC（Bedrock）では、`ocs` から Bedrock に届かないのでモデルの割り当てを出さず、子エージェントは
  親のモデルで動く（単体テストだけで、実機では未確認）
- 解決済み: 隔離版の `experimental.policies` は隔離版のものだけを使う。通常版の `provider.use` の policy
  （この PC のプロバイダ以外を塞ぐ）は出さない。出すと Bedrock の PC では `ocs` のモデルがすべて塞がる

## 次の調査・実験

配備（push → `chezmoi apply`）の後、本物の `ocs` で `bypass` を選び、`bypass` から `bypass-worker` を
起動し、`/fleet` が一覧に出ることを確かめる。通れば終了する。

## 評価基準

**必須**:

- 隔離版の設定に、`common.toml` と同じエージェントとコマンドが出る（通常版の設定からは引き継がない）
- `ocs` の中で `bypass` を選べ、`bypass-worker` は `bypass` からだけ起動できる
- 利用者が TUI で選んだキーなど、管理外のキーは残る
- `test/agents/` が全件通る

## 候補比較

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| `rules.json` の `sandbox` 節に出し、`config.py` が書く | 今の書き出しの仕組みのまま足せる。単一ソースは `common.toml`。一時の環境と本物の `ocs` で必須の項目を満たした | `config.py` の管理キーが増える | — | 採用 | — |
| 通常版の `opencode.json` から引き継ぐ | 実装が小さい | 通常版で手で足したエージェントまで入る。単一ソースが崩れる | — | 見送り | — |
| 隔離版の設定を `chezmoi apply` 時に生成する（段 6） | `config.py` が消える | 範囲が広い。既定モデルの選び方が変わる | — | 保留（CHG-0009 から移管、未起票） | — |

扱い: 未評価 / 検証中 / 有望 / 採用 / 保留 / 見送り

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `docs/spec/opencode-sandbox.md`「エージェントとコマンド」 | 節を新設（置くもの・差し替え方・理由・`bypass` の注意） | 段 1 | 適用済み |
| `docs/spec/agent-config-generation.md` | `ocs` でのモデルの割り当て、子エージェントが `ocs` に渡ることを反映 | 段 1 | 適用済み |

## 実装・検証

### 段 1（2026-09-29）

#### 実装

- `generate.py` の `opencode_sandbox_agents` が、`rules.json` の `sandbox` 節に `agent` / `agents` / `commands` を
  出す。通常版の `opencode.json` を作るのと同じ関数（`merge_opencode_agents`・`merge_opencode_v2_agents`・
  `merge_opencode_commands`）を、**空の既存に対して**呼ぶ（通常版で手で足した定義は入らない）
- モデルの割り当て（`merge_opencode_agent_models`）と接続設定（`merge_opencode_providers`）は、この PC の
  プロバイダが `[opencode.sandbox] providers` にあるとき（境界の内から届くとき）だけ出す
- `config.py` は `agent` / `agents` / `commands` を**丸ごと差し替える**（空なら取り除く）。通常版の
  「宣言した名前だけ差し替え、他は残す」に合わせなかった理由:
  - 隔離版の設定は境界の内から書けないので、TUI の操作で足されるエントリが無い
  - 残るのは `common.toml` から外した古い定義か、外で手書きしたものだけ。前者が全部 allow のエージェントだと、外したはずの緩和が居座る
  - 緩和に関わるキーは毎回差し替える、という既存の方針とそろう
- `providers` は宣言したプロバイダの `settings` のうち、宣言したキーだけを上書きし、未宣言のキーと他のプロバイダは
  残す（通常版の `merge_opencode_providers` と同じ。接続設定は緩和に関わらない）。宣言から外したキーも残る

#### 実機

`.tmp/opencode/chg10/` で行った。一時の XDG と、実 DB を読み取り専用で複製した DB を使い、`session.synthetic` は使っていない。

| 確認 | 結果 |
| --- | --- |
| `config.get --standalone` の正規化後 | `agents` に `bypass`（primary）・`bypass-worker`（subagent）・`commit` / `fleet-worker`（`claude-opus-5.5` の `medium`）・`review`（`gpt-6-astra`）、`commands.fleet`、`bypass-worker` への `subagent` の deny、policies、guide plugin |
| Fence の境界の中で `--agent bypass` | 隔離版で `ask` の `git config --get core.bare` が確認なしで走り、`git push origin main` は `Blocked by configuration policy` で止まった |
| `bypass` → `bypass-worker` | 起動でき、`WORKER_OK` |
| `build` → `bypass-worker` | `Permission denied: subagent` |
| guide plugin の起動元の検査 | プロジェクト設定で `task` を個別に allow して全体の deny を上書きさせても、plugin が「bypass-worker は bypass エージェントからだけ起動できます。」で止めた |
| `build` → `review` | 子セッションが `github-copilot/gpt-6-astra` で動いた（DB で確認） |

#### テスト

10 件を足し、2 件を広げた。修正前のコード（HEAD を展開した一時ディレクトリ）では 11 failed / 124 passed。
`test/` 全体で 2477 passed, 11 skipped。

### 配備後の確認（2026-09-29）

`02e6bea` まで push して `chezmoi apply` した後、利用者が本物の `ocs` で次を確かめた。すべて通った。

| 確認 | 結果 |
| --- | --- |
| Tab で `bypass` を選べる | 通った |
| `bypass` から `bypass-worker` を起動できる | 通った |
| `/` で `/fleet` が一覧に出る | 通った |
| `ocs --check` | 合格（レビューループで直した `find -H`・検査先の選択・保護対象を含む） |

## 重要な更新

- **2026-09-29**: 起票。`ocs` の中で `bypass` が使えないと利用者が気づき、`common.toml` から出すと決めた
- **2026-09-29**: 段 1 を実装し、一時の環境で必須の項目を確かめた。本物の `ocs` での確認を待つ
- **2026-09-29**: 段 1 を push した。配備の前に、Fence 化からの差分をレビューループにかける
- **2026-09-29**: レビューループを 5 ラウンドで終えた（上限）。R5 の BLOCKER（ホームが symlink のときの秘密の隠し漏れ）を直し、追加の 1 本で確認した（そこで出た symlink の秘密の取りこぼしも直した）
- **2026-09-29**: 配備し、本物の `ocs` で 4 点を確かめて終了

## 終了結果

**採用・配備済み。** `common.toml` のエージェントとコマンドを隔離版の設定にも出し、`ocs` の中で
`bypass`・`bypass-worker`・`commit`・`review`・`fleet-worker`・`/fleet` が使えるようになった。
評価基準の必須の項目は、一時の環境と本物の `ocs` の両方で満たした。

### 採用したもの

- `generate.py` が通常版と同じ関数で作った定義を `rules.json` の `sandbox` 節に出し、`ocs` の `config.py` が
  隔離版の設定へ書く。`agent` / `agents` / `commands` は丸ごと差し替え、`providers` はキー単位で上書きする
- モデルの割り当てと接続設定は、この PC のプロバイダが境界の内から届くときだけ出す
- あわせて、Fence 化（CHG-0009）からの差分を 5 ラウンドのレビューループで直した
  （退避・起動ディレクトリと配備先の拒否・symlink・`ocs --check`・テストの git の隔離）

### 撤回・見送りしたもの

| 項目 | いつ | 理由 |
| --- | --- | --- |
| 通常版の `opencode.json` から定義を引き継ぐ | 2026-09-29 | 手で足したエージェントまで入り、単一ソースが崩れる |
| 隔離版の設定でも「宣言した名前だけ差し替える」 | 2026-09-29 | 境界の内から書けないので足されるエントリが無く、外した全部 allow のエージェントが残るだけ |
| 隔離版に通常版の `provider.use` の policy を出す | 2026-09-29 | Bedrock の PC で `ocs` のモデルがすべて塞がる |
| `providers.<id>.settings` の全置換 | 2026-09-29 | 利用者が足した `baseURL` などを消す。通常版と同じキー単位の上書きにした |
| 別のプロジェクトの `write` で dotfiles を開けた場合の保護・`XDG_DATA_HOME` を置き場へ向けた場合・他の CLI の生成先での起動 | 2026-09-29 | ADR-0012 の範囲外（精査していない追加許可・利用者自身の上書き）。レビューでも見送り妥当と判定 |

### 反映先

- 仕様: [opencode-sandbox](../../spec/opencode-sandbox.md)（「エージェントとコマンド」「起動ディレクトリの制限」「制御ファイルの保護が効く範囲」「起動前の退避」）、[エージェント設定の生成](../../spec/agent-config-generation.md)、[セキュリティ](../../spec/security.md)
- 方針: [ADR-0012](../../adr/0012-ocs-boundary-for-accidents.md) の保証を条件付きにした
- 実装: `ca8b43d`・`6bc485d`（段 1）、`4b703f0`・`df17d61`・`02e6bea`（レビューループの修正）

### 移管した未完事項

| 内容 | 移管先 |
| --- | --- |
| ワークスペースの中の秘密（`.env` など）が `bypass` から読めること（コードからの判断。通常版と同じ性質で受け入れる） | 未起票 |
| 業務 PC（Bedrock）で子エージェントが親のモデルで動くこと（単体テストだけ） | 未起票 |
| 隔離版の設定を `chezmoi apply` 時に生成する（CHG-0009 の段 6） | 未起票 |

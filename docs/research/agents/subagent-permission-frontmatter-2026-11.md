# 子エージェントの権限（agent ファイルの `permission:`）の実測（2026-11-10）

観測日: 2026-11-10。対象: `pi-subagents` 0.87.0・`@gotgenes/pi-permission-system`・pi 1.5.0（Linux）。
目的: 子が作業ツリーの外を読もうとすると、確認（ask）が親の画面へ転送され、離席中は 5 分止まる。これを即座の拒否にできるか。

## 問い

agent ファイルの frontmatter の `permission:` で、`external_directory` を拒否にできるか。背景（async）の子で効くか。書式の制約は何か。

## 方法

使い捨ての project agent（`<repo>/.pi/agents/probe-deny.md`。実験後に削除）を作り、`subagent({ agent, async: true })` で起動して、作業ツリーの外・中を読ませた。
結果は子の報告だけでなく、審査ログ（`~/.pi/agent/extensions/pi-permission-system/logs/pi-permission-system-permission-review.jsonl`）の `permission_request.blocked`（`origin: project-agent`）でも確認した。

## 結果

- **入れ子の書式は無効**: `permission: { external_directory: { "*": deny } }` は、`subagent({ action: "list" })` が `Invalid agent definitions: permissions.external_directory must be allow, ask, or deny` を返した（pi-subagents の検証が、値に単一の値だけを許す）。
- **単一の値は有効**: `permission: { external_directory: deny }`。
  - 作業ツリーの外の `read`（`/etc/hostname`）・bash のパス引数（`ls /etc`・`ls /tmp`・`ls ~/.agents/skills`）は、確認ではなく即座に拒否された。メッセージ: `Denied by policy: 'external_directory_read' for tool … for agent 'probe-deny' … outside working directory`。
  - 作業ツリーの中（`README.md`・`git -C <作業ツリー> log`）は通った。
  - pi 本体の `~/.pi/agent/npm/…` の `read` は通った（pi の harness 側の読み取りの許可）。
  - **`~/.agents/skills/…`・`/tmp` の許可リスト（方針の `external_directory_read`）も拒否になる**。`deny` は許可リストより強い。
- **skill の限定**: `skills: commit` と `inheritSkills: false` で、子のシステムプロンプトには `commit` だけが載った。

## 未確認

- user 配下（`~/.pi/agent/agents/`）に配備した、組み込みと同名の写しでの動作（同名の組み込みを上書きする挙動は文書の記述）。
- bash の `ask` の挙動（pi-subagents の native 権限は bash のルールを拒否する。bash は permission-system 側）。
- 子が `skills:` の skill の本文を作業ツリーの外から読むとき（`deny` で読めない）。

## 結論

組み込みの agent を写し、`permission: { external_directory: deny }` を足す。設定（`subagents.agentOverrides`）は `permission` を扱えないので、ファイルの写しが要る。
詳細と維持費・撤去条件は [pi-subagents の設定（stock）](../../spec/agent-config-generation.md#pi-subagents-の設定stock)。

# OpenCode の bypass を「ask を allow にするだけ」に再定義する

- **ステータス**: Accepted
- **日付**: 2026-10-03
- **決定者**: applejxd

## コンテキスト

OpenCode の `bypass` エージェントは、`permission = { "*" = "allow", … }` で
**permission 層を丸ごと無効にする**逃げ道として作った
（[実測](../research/opencode/permission/bypass-agent.md)）。その結果:

- 秘密ファイルの read deny・`pip` の deny・`.ssh` の edit deny まで外れる
- 誘導（`[[opencode.shell.guide]]`）・`grep` / `glob` の結果フィルタ・shell 出力の伏字化も
  `bypass` では素通りにしていた
  （[CHG-0002](../change/0002-opencode-ask-by-default.md) の「誘導を bypass にも効かせる」は
  「誤爆したときの逃げ道が消える」ことを理由に見送った）

使い方としては「確認の ask を毎回押したくない」が主で、「deny まで外したい」場面はほぼ無い。
一方で、全 allow は**モデルが秘密を読める**状態を作る。

その後、[plugin で `ask` を `allow` に書き換える方式が成立する](../research/opencode/permission/bypass-ask-upgrade.md)
ことを実測した。`permission.evaluate` は config の静的 deny には呼ばれず、
`ask` / `allow` の呼び出しにだけ届く。plugin が緩められるのは `ask` → `allow` だけで、
deny を外すことは構造上できない。

## 決定事項

`bypass` の意味を次のとおり**再定義する**（旧: 全部 allow。新: ask だけ allow）。

1. `bypass` 系エージェント（`bypass` / `bypass-worker` / `bypass-fleet-worker`）は、
   通常のエージェントと**同じ permission** を使い、`"*" = "allow"` を持たない。
   通常で `deny` のものは `bypass` でも `deny`
2. guide-plugin の `permission.evaluate` が、**最後に**、`bypass` 扱いのエージェントの
   `ask` を `allow` に書き換える。誘導で `deny` にしたものは `deny` のまま
3. 誘導・前段停止（`execute.before` の early）・`grep` / `glob` の結果フィルタ・
   shell 出力の伏字化は `bypass` にも**同じに効かせる**（素通りをやめる）
4. `bypass` 扱いは common.toml で `bypass = true` と**明示する**。
   以前の「全 allow から始まるか」の自動判定（`_grants_everything`）はやめる
5. 子エージェントの起動制限（`bypass` からだけ `bypass-worker` /
   `bypass-fleet-worker` を起動できる）は、`bypass` の task 規則と全体の deny で
   従来どおり保つ
6. plugin が無い・`rules.json` の `bypass_agents` が読めない/壊れているときは、
   `ask` のまま（安全側。plugin を外した対照実測と同じ）
7. `.env.*` は ask から **deny へ上げる**（`.env.example` / `.env.sample` /
   `.env.template` を除く）。`bypass` が `ask` を `allow` にするため、`ask` のままだと
   秘密を含みうる `.env.local` などが通ってしまう。全 CLI の `[file]` に効く。
   例外は `[[file.deny_exceptions]]` で対の deny（`**/.env.*`）とセットで宣言し、
   その deny にだけ効かせる（`~/.ssh/.env.example` は deny のまま）

CHG-0002 の「誘導を bypass にも効かせる: 見送り」は、本 ADR で**採用に転じる**
（逃げ道が消える代わりに、`bypass` の意味を「確認を省く」だけに絞った）。

**逃げ道の変更**: 「秘密を読むために一時的に全部外す」用途は `bypass` では
できなくなった。そのときは Copilot CLI を使うか、利用者自身がコマンドを実行する。
OpenCode の中に deny を外す手段は残さない。

## 検討した選択肢

### 選択肢 1: 現状維持（全 allow の bypass）

- **利点**: 実装が単純。何でもできる逃げ道がある
- **欠点**: 秘密ファイルの read deny まで外れる。「確認を省きたいだけ」の用途に対して広すぎる

### 選択肢 2: bypass に静的 allow を足す（allow だけを列挙）

- **利点**: plugin に依存しない
- **欠点**: shell の `ask` 規則・外部ディレクトリ・`.env.*` などを列挙して allow にするのは
  通常側の規則と二重管理になり、ずれる。「通常で ask のもの」を機械的に写せない

### 選択肢 3（採用）: plugin で ask → allow に書き換える

- **利点**: 通常側の規則が単一ソースのまま。deny を外せない（構造上）。plugin が無ければ
  `ask` に戻る
- **欠点**: plugin に依存する。`bypass` 扱いの名前を plugin と生成器で揃える必要がある
  （`rules.json` の `bypass_agents` で渡す）

## 結果

### ポジティブな結果

- 秘密ファイルの read / edit deny・`pip` の deny・`.ssh` の edit deny が `bypass` でも効く
- 誘導（`cat` → `read` など）が `bypass` でも効き、モデルの癖が通常と揃う
- `bypass` の意味が「ask を省く」の 1 つに絞られ、説明が単純

### ネガティブな結果

- 誤爆した誘導を `bypass` で回避できなくなった。誤爆は誘導規則側を直す
- `.env.*` の deny 化は全 CLI に効く。Claude は deny 優先で例外を書けないので、
  **Claude では `.env.example` なども deny のまま**。OpenCode と Copilot は
  `[[file.deny_exceptions]]`（対の `**/.env.*` にだけ効く例外）でサンプルを読める。
  Bash hook 側の `.env.*`（`.env.local` 以外はサンプル扱い）の判定は変えていない
- 子エージェント（`commit` など ask 規則を持つ子）の `ask` は `bypass` の対象外のまま
  （agent 名が違うため）

## 関連 ADR

- [ADR-0006](0006-instructions-to-mechanisms.md): 指示でなく機構で止める
- [ADR-0012](0012-ocs-boundary-for-accidents.md) / [ADR-0013](0013-opencode-shell-guard-inside-ocs.md):
  ocs の中でも誘導を効かせる。ADR-0013 の「bypass エージェントは対象外」は本 ADR で改まる

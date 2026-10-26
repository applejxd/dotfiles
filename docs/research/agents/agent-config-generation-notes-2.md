# AI CLI 設定の生成に関する経緯・実測の記録（その 2）

`docs/spec/agent-config-generation.md` の「子エージェント」「コミットの確認」「並列作業（`/fleet`）」
「bypass から呼べる子エージェント」から移した記録。移設時点で再測定していない。
元の文を、書かれた時点のままここへ置く。現行の仕様は
[AI CLI 設定の生成と所有権](../../spec/agent-config-generation.md)にある。
前半の記録は [その 1](agent-config-generation-notes.md)（N1〜N8）。

- **観測日**: 各節の元の文に書かれた日付（2026-09〜2026-10）。日付が無いものは不明
- **対象**: OpenCode V2（v2.0.12〜2.0.14）
- **根拠**: 元の文にある案件・調査記録へのリンク（各節に再掲）

## 記録 N9 — 組み込みエージェントを宣言しなかったときの不具合

元: `docs/spec/opencode-config-generation.md#子エージェント`

### 問い

組み込みの `explore` / `plan` を `common.toml` で宣言して制限を並べ直すのはなぜか。

### 結果（元の文）

宣言しないと、`explore` は shell で確認を出し `.env.example` を書け、`plan` は
`.env.example` を確認なしに書けて `general` 経由で編集できた
（[調査記録](../opencode/permission/builtin-agent-override.md)、
[CHG-0017](../../change/closed/0017-builtin-agent-restrictions.md)）。

## 記録 N10 — コミットの確認で採らなかった案

元: `docs/spec/agent-config-generation.md#コミットの確認`

### 問い

コミットの承認を会話で取り、照合の仕組みや git hook を置かないのはなぜか。

### 結果（元の文）

- **承認の場を会話にする理由。** 確認画面を承認の場にすると、親が全文を示さずに先へ進めた
  （[CHG-0013](../../change/closed/0013-commit-agent-as-planner.md)）。会話で承認を求める形では、全文を示さないと
  承認を求められないので、抜けがあっても利用者の目に見える。照合の仕組みは置かない
  （[CHG-0014](../../change/closed/0014-deterministic-commit-runner.md) は部品が多く、TUI で照合が止まった）
- 子に「docs 未反映」を検出させる保険は、誤検出が多いとみて入れていない（親が飛ばすと提示の前の 1 行が欠けるので、利用者の目に見える）
- **git の pre-commit hook や plugin の `git commit` 直前のゲートには置かない。** 前者はモデルを
  動かせず利用者の手動コミットにも走る。後者は計画の承認後なので、docs を足すと提示し直しになる

## 記録 N11 — `/fleet` のコマンドの置き場

元: `docs/spec/opencode-config-generation.md#並列作業fleet`

### 問い

`/fleet` のコマンドを、コマンド用のディレクトリではなく設定の `commands` に出すのはなぜか。

### 結果（元の文）

スキルでは `~/.config/opencode/skills` が実際には走査されなかった実測があり
（[文脈の引き継ぎ](../../spec/checkpoint.md)）、同じ置き場の扱いを当てにしない。

## 記録 N12 — bypass の子の起動の実測

元: `docs/spec/opencode-config-generation.md#bypass-から呼べる子エージェント`

### 問い

`bypass` からだけ子エージェントを呼べる構成は、全体の deny でどこまで守れるか。

### 結果（元の文）

実測（全体の deny だけで build からは `Permission denied: subagent`、bypass からは
起動できる、子からの入れ子は不可。build に個別の `task = "allow"` があると全体の deny は
上書きされ、plugin の deny でも、個別の規則の最後に置いた deny でも止まる）は
[Bypass モードの調査 6 章](../opencode/permission/bypass-agent.md#6-bypass-からだけ呼べる子エージェント2026-09-28)。
`bypass` から `general` / `fleet-worker` を外した構成と `bypass-fleet-worker` の実測は
同じ調査の [7 章](../opencode/permission/bypass-agent.md#7-bypass-の子の入れ替え2026-09-30)。
全 allow を外した構成の実測は [ask→allow の調査](../opencode/permission/bypass-ask-upgrade.md)。

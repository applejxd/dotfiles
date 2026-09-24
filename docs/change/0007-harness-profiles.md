# CHG-0007: 境界をハーネス非依存にする（3 層プロファイル）

- **状態**: In progress
- **更新日**: 2026-09-24
- **基準**: `ocs` 865 行（うち汎用 758 行 / OpenCode 固有 107 行）。
  `[opencode.sandbox]` 14 キー

## 目的と非目的

**目的**: OS 境界（`ocs`）をハーネス非依存にし、**ハーネスとプロバイダを
切り離す**。新しいハーネスを境界へ入れるとき、翻訳器を書かずに済む形にする。

**非目的**:

- `common.toml` の permission 翻訳を拡張すること（[CHG-0005](0005-agents-config-naming.md)）
- Pi / oh-my-pi を境界へ入れること。あれは**利便性の軸**で進める
  （[CHG-0006](0006-pi-harness-trial.md)）。本案件は「将来入れたくなったとき」の備え
- `ocs` の既知の欠陥を直すこと（[CHG-0004](closed/0004-opencode-sandbox.md) の B2 / B3）

**発端**: 外部レビュー（Astra）の指摘。

> モデル API とハーネスを一体化しない。同じハーネスでプロバイダを切り替える
> たびに境界プロファイルが増殖する。

## 現在地

### 3 層への割り当て（`[opencode.sandbox]` 14 キーを分類した）

| 層 | 持たせるもの | 現物 |
| --- | --- | --- |
| **共有ランタイム** | 境界生成、パス検証、退避、検査、後始末 | `runtime_path` `enabled` `deny_read`、`read` のツールチェーン 5 件、`write`、`protected` のリポジトリ制御 4 件 |
| **ハーネス** | 実行ファイルと引数、専用 HOME/XDG、設定・状態の形式 | `read` の `~/.opencode` 系 3 件、`protected` の 2 件、`data_home` `db` `config_dir`、`system_prompt` `permissions` `model_preference` `policies`、`opencode.ai` ×2 |
| **プロバイダ** | API 接続先、認証方式、資格情報の参照先 | `api.githubcopilot.com` `*.githubcopilot.com` `api.anthropic.com` `api.openai.com` |

### なぜ 2 層では足りないか

当初案は「共有 + ハーネス」の 2 層で、モデル API のドメインをハーネス側に
置いていた。これだと **ハーネス × プロバイダ**で増殖する。

```text
2 層:  [opencode.sandbox] network_allow = [copilot, anthropic, openai, opencode.ai]
       [pi.sandbox]       network_allow = [copilot, anthropic, openai, pi.dev]
                                           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~ 重複
3 層:  [provider.github-copilot] / [provider.anthropic] / [provider.openai]
       [opencode.sandbox] providers = [...] + 自分のサービスだけ
```

`ocs` の実測（汎用 758 行 / OpenCode 固有 107 行 = 12%）は汎用化の見込みを
示すが、**行数比は抽象の安定性を示さない**（Astra の指摘）。2 つ目の実装を
作って初めて境界線が分かる。

## 評価基準

**必須**:

- プロバイダ層の導入で**許可ドメインの集合が変わらない**
- `test/agents/` が全件通る
- 未知の provider 名を**黙って無視しない**（fail-closed）

**望ましい**:

- ハーネスを 1 つ足すときに `generate.py` を触らずに済む

## 実施計画

| 段 | 内容 | 状態 |
| --- | --- | --- |
| **1** | プロバイダ層を切り出す（`[provider.*]`） | **完了**（2026-09-24） |
| 2 | 共有ランタイムとハーネスを節で分ける | 未着手 |
| 3 | `ocs` を汎用化し、ハーネスをプロファイルで選ぶ | 未着手 |
| 4 | 改名（`ocs` は OpenCode 由来） | **未決**。下記 |
| 5 | 2 つ目のハーネスを境界へ入れて抽象を検証する | 保留（CHG-0006 の結論待ち） |

### 段 1 の結果

```toml
[provider.github-copilot]
network_allow = ["api.githubcopilot.com", "*.githubcopilot.com"]
[provider.anthropic]
network_allow = ["api.anthropic.com"]
[provider.openai]
network_allow = ["api.openai.com"]

[opencode.sandbox]
network_allow = ["opencode.ai", "*.opencode.ai"]   # ハーネス自身のサービスだけ
providers = ["github-copilot", "anthropic", "openai"]
```

生成物への影響は **`rules.json` の 2 行の並び替えのみ**。他 4 ファイルは
完全一致。許可ドメインは 46 件のまま、集合の差分なし。

> **1 バイト不変にはできなかった。** 元の配列は `opencode.ai` が
> プロバイダ間に挟まっており、素直な連結では順序を再現できない。
> 許可リストは集合なので機能影響はないと判断した。

`provider_domains()` は未知の名前で `ValueError` を投げる。`.get(name, {})` で
空を返すと、綴り間違いが「境界内からモデルへ到達できない」という形でしか
現れず、proxy が CONNECT を 403 で落とすだけなので原因に辿り着けない。

## 段 4: 改名について（未決）

`ocs` は **o**pen**c**ode **s**andbox の略で、ハーネス非依存にするなら名前が
実態と合わなくなる。ただし**日常的に打つコマンド**なので、汎用化の前に
改名だけ先行させる意味は薄い。

| 候補 | 由来 | 備考 |
| --- | --- | --- |
| `asb` | agent sandbox | 短い。空き |
| `sbx` | sandbox | 空き。何のサンドボックスか分からない |
| `agentbox` | — | 明示的だが長い |

いずれも `command -v` で衝突なしを確認済み。

**判断**: 段 3（汎用化）と**同時に行う**。実態が変わる前に名前だけ変えると、
`ocs` のままの方が正確な期間が生まれる。移行時は `ocs` を残すか、
`.chezmoiremove` で消すかも決める必要がある。

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `[provider.*]` | （なし）→ 新設 | ハーネス × プロバイダの増殖を防ぐ | **完了** |
| `[opencode.sandbox] network_allow` | モデル API 4 件を除去 | 接続先はプロバイダで決まる | **完了** |
| `[opencode.sandbox] providers` | （なし）→ 追加 | 使うプロバイダを宣言する | **完了** |
| 共有ランタイム / ハーネスの節分け | — | 段 2 | 未着手 |
| `ocs` の汎用化と改名 | — | 段 3 / 段 4 | 未着手 |

## 重要な更新

- **2026-09-24**: 起票。3 層プロファイルの提案は外部レビューで出たあと、
  軸が利便性（CHG-0006）へ移った際に**どこにも記録されず消えかけていた**。
  記録として起こし直した
- **2026-09-24**: 段 1 完了。生成物の差分は並び順 2 行のみ

## 未解決点

- **段 3 の動機が弱まっている。** CHG-0006 で「Pi / omp を境界へ入れない」と
  決めたため、汎用化の使い道が当面ない。**再開条件は「境界へ入れたい
  ハーネスが 2 つ目になったとき」**
- **段 3 をやるなら B5（静的境界）と合流しうる。**
  [CHG-0004](closed/0004-opencode-sandbox.md) の B5 は単独では割に合わず見送ったが、
  ハーネス非依存にするなら静的な宣言の方が素直になる可能性がある。
  段 3 に着手するときは、B5 を改めて検討対象に入れる
- 段 2 は**取りかかれる**（2026-09-24 に確認）。当初「`local.toml` の追記口との
  兼ね合いが未確認」と書いたが**誤り**だった。`local.toml` は
  `common["sandbox"]` にしか触らず、段 2 の対象 `common["opencode"]["sandbox"]`
  とはキーが 1 つも重ならない（[CHG-0005](0005-agents-config-naming.md) の
  A2 の論点と取り違えていた）。このマシンに `local.toml` は存在もしない。
  **本当の難所は次の 3 つ**:
  - `protected` はワークスペース相対で、実体は「**この dotfiles リポジトリの
    制御ファイルを守る**」項目。共有層へ置くと「どのハーネスでも共有」と
    読めてしまい、性質が伝わらない
  - `enabled` の意味が「OpenCode の境界を使うか」から「境界機構そのものを
    使うか」へ変わる。ハーネスごとに切りたくなったとき**両方に必要**になりうる
  - `~/.claude/skills` は資産としてはハーネス非依存だが、**名前にハーネス名が
    入ったまま共有層へ置く**ことになる（実体パスなので変えられない）
- プロバイダ層は現在ドメインしか持たない。Astra の提案では**認証方式と
  資格情報の参照先**も持つべきだが、[CHG-0004](closed/0004-opencode-sandbox.md) の
  B2（資格情報の露出）と絡むため、そちらの結論を待つ

## 終了結果

<!-- Done にするとき記入 -->

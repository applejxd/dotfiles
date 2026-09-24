# CHG-0005: `common.toml` の命名を実態に合わせ、固有設定を分離する

- **状態**: In progress
- **更新日**: 2026-09-23
- **基準**: `common.toml.tmpl` 1242 行 / `generate.py` 1736 行。生成先は
  Claude・Copilot・OpenCode 通常版・OpenCode 境界版の 4 ハーネス

## 目的と非目的

**目的**: `common.toml` の**名前と実態のズレ**を解消し、共通でないものを
共通の器から出す。「共有設定なのに共有に見えない」状態を終わらせる。

**非目的**:

- `common.toml` の廃止。検討したが**見送った**（下記）
- 生成物の挙動を変えること。**全段で `chezmoi diff` が空**であること
- OpenCode 境界の欠陥への対処。それは
  [CHG-0004](closed/0004-opencode-sandbox.md) が扱う

**発端**: 「`common.toml` を廃止して各ハーネス専用の設定へ移行したい」という
提案。調べた結果、**問題は器ではなく命名**だった。

## 現在地

### 共有の実態（`generate.py` のどの関数がどのキーを読むかで判定）

| 節 | 共通 | 固有 | 共通率 |
| --- | ---: | ---: | ---: |
| `[bash]` | 122 | 1 | 99% |
| `[web]` | 28 | 0 | 100% |
| `[file]` | 75 | 2 | 97% |
| **`[sandbox]`** | **36** | **57** | **39%** |
| **合計** | **261** | **60** | **81%** |

**分岐は `[sandbox]` にほぼ全て集中している。** 他の 3 節は実質すべて共通。

> 測定を 2 回外した。生成物への文字列一致では**変換を追えない**（`**/.ssh/**`
> が Claude の `Read()` 構文・Copilot の絶対パス・OpenCode の glob・
> `rules.json` の正規表現へと 4 通りに化ける）。厳密一致では 19%、
> 正規化しても 55〜90% と幅が出た。**消費側のコードを読むのが唯一の正解**。

### 名前が実態とズレている

`claude_` 接頭辞が付いているのに複数ハーネスへ届くキーがある。

| キー | 件数 | 実際に届く先 |
| --- | ---: | --- |
| `file.claude_read_deny_globs` | 33 | Claude / OpenCode |
| `file.claude_write_deny_globs` | 39 | Claude / OpenCode |
| `file.claude_read_ask_globs` | 1 | Claude / OpenCode |
| `file.claude_write_ask_globs` | 2 | Claude / OpenCode |
| `sandbox.claude_network_allow` | 10 | Claude / OpenCode |

**名前が「最初の利用者」に引きずられ、2 番目以降が増えても直されていない。**
`claude_network_allow` のコメントは今も「この設定は Claude 専用」と書いているが、
CHG-0004 で OpenCode 境界を作ったときに実態が変わり、コメントだけ取り残された。

実測（`chezmoi apply` 後の生成物）:

```text
Claude   sandbox.network.allowedDomains  38 件 = [web] 28 + claude_network_allow 10
OpenCode 境界 allowedDomains             44 件 = [web] 28 + 同 10 + OpenCode 固有 6
```

### 本当に固有なもの（57 件）

`[sandbox]` の中で、キー名どおり 1 ハーネスにしか届かないもの。

| キー | 件数 | 届く先 |
| --- | ---: | --- |
| `claude_write_deny` | 20 | Claude のみ |
| `claude_read_allow` | 12 | Claude のみ |
| `claude_write_allow` | 7 | Claude のみ |
| `copilot_read_allow` | 12 | Copilot のみ |
| `copilot_write_allow` | 6 | Copilot のみ |

### 廃止を見送った理由

| 理由 | 根拠 |
| --- | --- |
| **81% が本当に共通** | 廃止すると 261 件を 4 ハーネス・3 スキーマへ書き写すことになる |
| **deny の不一致は最悪の壊れ方** | 「塞いだつもりで塞がっていない」状態を自動検出できなくなる |
| **第三者の書き込みが消える** | 生成物は `modify_` スクリプト（`modify_settings.json.py.tmpl` 等）で、**既存の中身を読んで書き換える**。静的ファイル化すると herdr が実行時に書いた `SessionStart` hook や TUI で足した設定が `apply` のたびに消える |
| **`generate.py` は縮まない** | 4 構文への変換が仕事の本体。261 件が共通である限り必要 |

3 番目は実例で確認した。`chezmoi apply` の出力が
`installed copilot integration hook to ~/.copilot/hooks/herdr-agent-state.sh`
で、この hook は `common.toml` に存在しないのに `apply` 後も残っている。

### 誤っていた見立て

- 当初 A3 として「OpenCode 固有のモデル API 6 ドメインを OpenCode 側へ移す」を
  挙げたが、**既に `[opencode.sandbox] network_allow` にある**。移す先が無いので
  **A3 は消滅**した

## 評価基準

**必須**:

- 全段で `chezmoi diff` が空。生成物が 1 バイトも変わらない
- `test/agents/` が全件通る（現在 1952 passed / 7 skipped）
- `lint_templates.py` / `lint_docs.py` / `pre-commit run --all-files` が通る
- 改名後、**`claude_` / `copilot_` 接頭辞が「固有である」ことの証明になる**。
  名前を見るだけで移動先が決まる状態

**望ましい**:

- `generate.py` から「共通でないものを共通の器に入れるための分岐」が減る
- `local.toml` の `LOCAL_SANDBOX_KEYS` が固有キーだけを列挙する形に揃う

## 実施計画

| 段 | 内容 | 規模 | 挙動 | 状態 |
| --- | --- | --- | --- | --- |
| **A1** | 改名。`claude_` を実態に合わせる | 62 箇所 / 15 ファイル | 変化なし | **完了**（2026-09-23） |
| **A2** | `claude_` / `copilot_` が残ったもの（57 件）を native へ分離 | 57 件 | 変化なし | 未着手 |
| ~~A3~~ | ~~OpenCode 固有のモデル API を移す~~ | — | — | **消滅**（既に正しい場所） |
| A4 | 廃止の是非を再評価 | — | — | 保留 |

### A1 の改名案

| 現在 | 変更後 | 理由 |
| --- | --- | --- |
| `file.claude_read_deny_globs` | `file.read_deny_globs` | Claude / OpenCode 共通 |
| `file.claude_write_deny_globs` | `file.write_deny_globs` | 同上 |
| `file.claude_read_ask_globs` | `file.read_ask_globs` | 同上 |
| `file.claude_write_ask_globs` | `file.write_ask_globs` | 同上 |
| `sandbox.claude_network_allow` | `sandbox.shell_network_allow` | 用途（shell の通信先）で命名 |

`sandbox.claude_write_deny` / `claude_read_allow` / `claude_write_allow` /
`copilot_read_allow` / `copilot_write_allow` は**そのまま**。本当に固有なので
接頭辞が正しい。

### A1 の注意点

改名対象は設定ファイルだけではない。**稼働中のコードがキー名を読む**。

```text
home/dot_claude/hooks/executable_check_file_read.py   稼働中の hook
home/dot_config/agents/command_policy.py              稼働中の判定
scripts/agents/validate_common.py                     検証スクリプト
test/agents/ 4 ファイル / docs/ 6 ファイル
```

`chezmoi apply` 後に hook の再確認が要る（`test_check_file_read.py` が押さえる）。

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `file.claude_*_globs` 4 件 | 接頭辞を外す | 97% が OpenCode へも届く | **完了**（2026-09-23） |
| `sandbox.claude_network_allow` | → `shell_network_allow` | Claude / OpenCode 共通。用途で命名 | **完了**（2026-09-23） |
| `sandbox.{claude,copilot}_*` 57 件 | `common.toml` → 各 native | 1 ハーネスにしか届かない | 未着手（A2） |
| `sandbox.claude_write_deny` | 扱いを決める | ADR-0007 規則 3 に違反 | **未解決**（A2 で判断） |
| `common.toml` の廃止 | — | 81% が共通。`modify_` の保存機能を失う | **見送り** |

## 重要な更新

- **2026-09-23**: 「廃止」の提案から出発したが、測定の結果**命名の問題**と判明し、
  改名 + 分離へ方針転換した。廃止は見送り（根拠は上記 4 点）
- **2026-09-23**: A3（OpenCode 固有ドメインの移動）は、既に正しい場所にあったため
  消滅。計画策定時の調査漏れ
- **2026-09-23**: A1 完了。**改名は ADR-0007 の原則を覆すものではなく、原則へ
  戻す作業だった**。ADR-0007 は「共有 = 無印 / CLI 固有 = CLI 名の接頭辞」を
  定めており、当時 `[file]` は Claude だけが読んでいたので接頭辞が正しかった。
  CHG-0004 で OpenCode が同じリストを読むようになり、**事実の側が変わった**のに
  名前が追随していなかった
- **2026-09-23**: 改名の過程で、テスト 3 件が**旧規約そのものを固定**していた
  ことが判明（`test_file_section_keys_are_all_claude_prefixed` など）。
  新規約を固定する形へ書き換えた

### A1 で見つかった副産物

| 発見 | 内容 |
| --- | --- |
| コメントの嘘 2 件 | `shell_network_allow` に「この設定は Claude 専用」、`write_deny_globs` に「Claude のみ反映」。どちらも OpenCode にも届いており誤り。修正した |
| 集合の配置誤り | `shell_network_allow` が `CLAUDE_SANDBOX_KEYS` に入っていた。`SHARED_SANDBOX_KEYS` へ移した（検査専用の集合なので挙動は不変） |
| **ADR-0007 規則 3 違反が 1 件残存** | `[sandbox] claude_write_deny` は「CLI 固有キーに置かれた禁止」。規則 3 が禁じている形。**A2 で扱う** |

## 重要な未解決点

`[sandbox] claude_write_deny`（20 件）は ADR-0007 の規則 3
「CLI 固有キーは『許可』の補償にだけ使う。『禁止』を置かない」に違反している。

A2 で native へ移す前に、**どちらが正しいか**を決める必要がある。

| 案 | 内容 |
| --- | --- |
| 禁止を共有へ上げる | 他の CLI でも同じ禁止を効かせる。規則 3 に適合 |
| Claude 固有のまま native へ | 規則 3 を緩める。なぜ片側だけでよいかの根拠が要る |

## 終了結果

<!-- Done にするとき記入 -->

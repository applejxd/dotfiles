# CHG-0002: OpenCode の permission を既定 ask にする

- **状態**: In progress
- **更新日**: 2026-09-22
- **基準**: OpenCode V2（`v2.0.12`）

## 目的と非目的

**目的**: OpenCode の permission から「未掲載＝無条件許可」を無くし、
既定を `ask` にする。そのうえで**秘密へのアクセス経路を機構で塞ぐ**。

**非目的**:

- Claude Code / Copilot CLI の設計変更。対象は OpenCode V2 のみ
- 確認回数の削減。**自動実行では `allow` と `ask` が等価**なので、
  自動化率には効かない（後述）
- 確認画面の情報量を増やすこと。それは
  [CHG-0003](closed/0003-ask-command-description.md) が扱う

## 発端

このリポジトリは `common.toml.tmpl` を単一ソースとして 4 つの AI CLI の
permission を生成している。OpenCode を追加した際に次が判明した。

従来の設計は allow / ask / deny の 3 リストに加えて「未掲載」を持ち、
未掲載は Claude の `auto` / Copilot の `assisted` の LLM classifier に
委ねる意図だった。**OpenCode に classifier は無い。** つまり未掲載が
「無条件許可」へ静かに退化していた。実測では `curl` / `docker run` /
`python3` / `chmod` / `dd` / `base64` が全て無条件実行だった。

ユーザはこれを受け、classifier 前提を捨てる決定をした。

## 設計の土台

**実測で確定した制約。すべての判断がここから出ている。**

| 制約 | 設計への影響 | 出典 |
| --- | --- | --- |
| **自動実行では `allow` と `ask` が等価** | 確認回数は対話時にしか効かない。自動実行で効くのは `deny` だけ | [ask と並列バッチ](../research/opencode/ask-and-parallel-batch.md) |
| permission は多層ではなく**最終一致の単一判定** | allow を足しても deny は弱まらない。順序が全て | [allow リスト監査](../research/opencode/permission/allow-list-audit.md) |
| 設定の `deny` は hook を呼ばない | 静的 deny は代替案を返せない。既定 ask のまま hook で deny へ変える | [plugin API](../research/opencode/plugin/api-probe.md) |
| plugin のロード失敗は **fail-open** | 故障時に無防備になる。静的 allow の縮小を先に済ませる | 同上 |
| plugin から `ask` を**作る** API は無い | カスタムツールは「無確認で安全」か「作らない」の二択 | [相関と承認要求](../research/opencode/plugin/correlation.md) |
| plugin は `ask` を `allow` へ引き上げ・`deny` へ引き下げできる | 機構で判定を補える | [plugin ゲート](../research/opencode/permission/shell-allow-and-plugin-gate.md) |
| `tool.execute.before` が生コマンド・`id`・`workdir` を持つ | 相関はこの hook で完結。`e.resources` は変数代入を落とすので使わない | [相関と承認要求](../research/opencode/plugin/correlation.md) |
| **静的パターンはクォート・変数・符号化で回避できる** | deny パターンは allow を残す口実にならない | [plugin ゲート](../research/opencode/permission/shell-allow-and-plugin-gate.md) |
| **scanner はリダイレクトを分割せず resource に残す** | allow に載せたコマンドは全て任意書き込みの手段になる | [allow リスト監査](../research/opencode/permission/allow-list-audit.md) |
| `grep` / `glob` が `read` の deny を迂回する | 読み取りをツールへ移すとき保護を自作する必要がある | [permission の穴](../research/opencode/permission/gaps.md) |
| `execute.after` で結果を濾せる | 確認を増やさずに出力を伏字化できる | [出力フィルタ](../research/opencode/permission/output-filter-and-subagents.md) |
| V2 対応のサードパーティ plugin は 1 件も無い | 既製品に乗れない。自作する | [生態系](../research/opencode/plugin/ecosystem.md) |

### 境界は無い

permission と plugin は**安全網であって境界ではない**。

実行前のコマンド検査はクォート・変数で、実行後の出力検査は `base64` や
`tr` ですり抜ける。**どちらも一方向にしか効かず、組み合わせても迂回の
費用を上げるだけ**（いずれも実測）。

境界を作るには OS レベルの隔離が要る。`opencode` のプロセスごと
bubblewrap で隔離すれば可能だが、**採用しないと判断した**（下記）。

### sandbox を採用しない理由

成立は実測で確かめたうえで見送った
（[sandbox の調査](../research/opencode/permission/sandbox.md)）。

| 期待 | 実際 |
| --- | --- |
| 自動化率が上がる | **上がらない**（自動実行では `ask` が素通り） |
| 確認回数が減る | **減らない**（既定 `ask` を維持するため） |
| 敵対的なリポジトリから守れる | **守れない**（プロジェクト設定で外せる） |
| このリポジトリが安全になる | **ならない**（`chezmoi` が snap 版で bwrap 内から動かない） |

残る利点は「`chezmoi` を使わないプロジェクトで難読化された持ち出しを
止められる」ことだけ。ラッパーの自作と維持、macOS 未実装、常駐サービス
経由の脱出対策という費用に見合わない。

### 設定で入れる保護は設定で外せる

`<project>/.opencode/opencode.json` の permission は**グローバルの deny に
勝つ**（[permission の穴](../research/opencode/permission/gaps.md)）。

| 影響 | 対処 |
| --- | --- |
| 外部リポジトリを開くだけで保護が外れる | **塞げない** |
| エージェントが自分で書いて権限を広げられる | `**/.opencode/opencode.json` を write deny（適用済み） |

## 現在地

### 動いているもの

| 項目 | 状態 |
| --- | --- |
| 既定 `ask`（`{shell, *, ask}` を先頭に配置） | 配備済み |
| `[opencode.shell] allow` 5 件 | 配備済み |
| write deny（`.git/config` / `.opencode/opencode.json` 等） | 配備済み |
| `bypass` エージェント（全ツール許可の逃げ道） | 配備済み |
| 誘導 plugin の基盤（`guide-plugin`） | 配備済み。規則は `cd` 1 件のみ |

### 残っていること

段階 2 の本体（`read` への誘導、`grep` / `glob` の結果フィルタ、
shell 出力の伏字化）。設計は確定し、前提も実測で裏づけ済み。

### まだ分からないこと

- Claude / Copilot も既定 ask にするか。Copilot は hook の `ask` が
  自動承認されるバグ（github/copilot-cli#3590）があり効果が限定的

## 評価基準

**必須:**

1. Claude / Copilot / Codex / Gemini の生成物に diff が出ないこと
   （テストで固定）
2. **自動実行のまま**、保護対象のファイルを `cat` / `grep` / `head` で
   読んだ内容がモデルへ渡らないこと。素直な形で実測して判定する
3. 任意コード実行を含むコマンドが allow に 1 件も無いこと
4. plugin がロードに失敗しても、危険側（無条件許可）に倒れないこと

**基準 2 に「難読化した形でも遮断」は求めない。** 符号化されるとすり抜ける
ため達成不能。伏字化は事故と素朴なプロンプトインジェクションへの
安全網であって、意図的な持ち出しへの境界ではない。

## 実施計画

| 段階 | 内容 | 状態 |
| --- | --- | --- |
| 0 | 穴と plugin API の実測、計測基盤の確立 | 完了 |
| 1 | `[opencode.shell]` 新設 + 既定 ask | **完了**（2026-09-21） |
| 2 | plugin 基盤 + 読み取り経路の保護 | **着手中**（基盤と `cd` 規則が完了） |
| 3 | `verify` ツール | 未着手 |
| 4 | 残り約 280 件への手当 | 判断保留 |

### 段階 1（完了）

`[bash]` に触らず `[opencode.shell] allow` を新設し、permissions の先頭へ
`{shell, *, ask}` を置いた。`[bash]` は 3 CLI 共通なので、そこを削ると
効果の切り分けができなくなるため。

allow の基準は副作用なし・冪等・**任意コード実行を含まない**こと。

```toml
[opencode.shell]
allow = ["git log", "wc", "grep -n", "uv pip list", "docker ps"]
```

当初あった `git diff` / `git status` は監査で**任意コード実行の経路を
持つ**と判明し外した（`.git/config` の `diff.<name>.command` と
`core.fsmonitor`）。あわせて `.git/config` / `.git/hooks/**` /
`~/.gitconfig` を write deny に追加した。

`find` に「`-exec` の付いた形だけ静的 deny」は採らない。
`find . -exe""c …` が deny を素通りして `find *` の allow に一致し、
**無確認で任意コード実行**になるため。

結果は 224 → 218 rules、他 CLI の生成物はバイト単位で無差分。
配備後に実環境で `pip --version` の deny を確認した（その後の write deny
追加で現在は 225 rules）。詳細は
[allow リスト監査](../research/opencode/permission/allow-list-audit.md)と
[費用対効果の調査](../research/opencode/permission/shell-allow-and-plugin-gate.md)。

配備の過程で Orca overlay の問題（`OPENCODE_CONFIG_DIR` が global config を
置き換える）を踏み、`shellenv.sh` に条件付き `OPENCODE_CONFIG` を入れて
解決した（[試験環境の隔離方法](../research/opencode/test-isolation.md)）。

### 段階 2（着手中）

**sandbox を採用しない以上、ここが唯一の防御層になる。**

`--auto` では `ask` が自動承認されるため、効くのは `deny` だけ。
静的 deny にはしない（hook を呼ばず代替案を返せないため）。既定 ask の
まま hook が deny へ変える構成にすると、**故障時は ask に縮退**して
安全側に倒れる。

#### 方針: 保護される層へ寄せ、残りに安全網を敷く

穴はどれも permission の `read` / `edit` を **shell 経由で迂回**すること
に起因する。

| 経路 | `read` / `edit` の deny |
| --- | --- |
| shell の `cat` / `grep` / リダイレクト | **効かない** |
| `read` ツール | **効く**（実測 P3-1） |
| `grep` / `glob` ツール | 効かない。hook で自作が要る（実測 P3-2） |

2 段構えにする。

1. **誘導** — shell の `cat` / `head` / `tail` を `deny` し `read` ツールへ
   寄せる。**deny が効かない経路から効く経路へ移す**のが目的
2. **伏字化** — それでも shell を通るものに `execute.after` で
   出力フィルタをかける

**誘導は確認削減の施策ではなく保護の一部。** ここが振り直し後の中心。

#### 塞ぐ対象

| 穴 | 例 | 手段 | 効き目 |
| --- | --- | --- | --- |
| 秘密の読み出し | `cat ~/.ssh/id_ed25519` | 誘導 → `read` ツール | **deny が効く** |
| 誘導を抜けたもの | `sed -n 1p ~/.aws/credentials` | `execute.after` で伏字化 | 安全網 |
| 検索での読み出し | `grep -r . ~/.aws` | `grep` へ誘導 + 結果を濾す | **濾せる** |
| 保護パスへの書き込み | `echo x > ~/.config/opencode/opencode.json` | 文字列検査で `deny` | 限界あり |

`grep` / `glob` の保護は `result.content[].text` に埋まった絶対パスを
`read` の deny glob で判定して落とす。**件数ヘッダと `metadata` も
書き換える**こと。放置すると「`Found 1 matches`」だけ残って存在が漏れ、
結果とも矛盾する（実測）。

書き込み側は**完全には塞げない**。`printf` / `tee` / `python3 -c` と
経路が無数にあるため、明らかな形だけ deny する。

#### 誘導の対象

確認回数は目的ではないが、**過剰ブロックの判断材料**として測ってある
（466 呼び出しの実履歴）。

| 対象 | 代替案 | 保護上の意味 | 確認の削減 |
| --- | --- | --- | ---: |
| `cat` / `head` / `tail` / `sed -n` | `read` ツール | **deny が効く経路へ移る** | 13 (2.8%) |
| `grep` / `rg` / `find` | `grep` / `glob` ツール | 保護は hook で自作 | 11 (2.4%) |
| `cd X && ...` | `shell` の `workdir` | 無し（作法） | 15 (3.2%) |
| 区切り用途の `echo "==="` | 不要 | 無し | **0 (0%)** |

- **区切り `echo` は採用しない。** 保護上の意味が無く確認も減らないのに、
  deny は 1 往復を捨てさせる。作法の話は `AGENTS.md` で足りる
- `cd` は採用済みだが**保護目的ではない**
- `ls` は誘導しない。`read` deny の対象ではなく、移しても保護が増えない

#### 過剰ブロックへの歯止め

誘導は `deny` なので、外すと作業が止まる。

- `read` で代替できない用途（`head -c`、パイプの途中、`cat` の結合）は
  **誘導しない**。リダイレクト・パイプを含む形は対象外にする
- 誘導は必ず**代替案を本文に書く**（`cd` → `workdir` の乗り換えが
  1 ターンで起きることを実機で確認済み）
- 規則を足すたびに実履歴 466 件へ当てて誤爆を数える

#### plugin 全体に効く 2 つの規約

**規約 1: すでに `allow` と判定されたものには触らない。**

```js
if (e.effect === "allow") return
```

`allow` でも `permission.evaluate` は発火する。これが無いと
[bypass エージェント](../research/opencode/permission/bypass-agent.md)が
誘導 hook に引っかかって機能しない。bypass は全 action が `allow` に
なるので、この 1 行がエージェント識別の代わりになる（実測）。

**規約 2: リダイレクトを含むコマンドは `allow` へ引き上げない。**

```js
if (/[<>]/.test(cmd)) return   // ask のまま
```

引き上げると `find . -name x > path` が無確認で通る。`deny` 側には
当てない（止める方向は常に安全）。

#### 配置と生成

plugin は `~/.config/opencode/guide-plugin/` に置く。**登録先は 2 つに
分かれる**（[ロード経路](../research/opencode/plugin/loading.md)）。

| 登録先 | 読まれるもの |
| --- | --- |
| `opencode.json` の `plugins` | `index.js`（サーバ側） |
| `cli.json` の `plugins` | `tui.ts`（TUI 側） |

判定表は `common.toml` の `[[opencode.shell.guide]]` から `rules.json` と
して生成し、`index.js` は読むだけにする。

制約が 3 つある。

- 明示指定は**絶対パスのディレクトリ**でないと解決されない。単一ファイルも
  `~` も**黙って無視される**
- 自動探索は `OPENCODE_CONFIG_DIR` 基準なので Orca セッションでは
  `~/.config/opencode/plugins/` が読まれない
- ディレクトリ名に `plugin` / `plugins` を使わない（二重ロードになる）

**サーバ側 plugin を更新したら `opencode service restart` が要る**
（常駐サービス内で動くため）。

#### `find` の選別器

段階 1 で allow から外した分をここで回収する。丸ごと deny にはしない
（逃げ場が `python3 -c "os.walk(…)"` や `ls -R` になり悪化するため）。

| 条件 | 判定 |
| --- | --- |
| 危険フラグ（`-exec` / `-execdir` / `-ok` / `-okdir` / `-delete` / `-fprint*`） | `deny` + `glob` への誘導 |
| `$` / バッククォートを含む | 触らない（`ask`） |
| リダイレクトを含む（規約 2） | 触らない（`ask`） |
| それ以外の列挙形 | `allow` |

**`ask` へ落とす分岐は対話でしか安全弁にならない。** `--auto` では
自動承認される。自動実行で確実に止めたいものは `deny` に倒す。

実装上の制約が 2 つ。

- **`e.resources` ではなく生コマンドを読む。** scanner が `;` 分割時に
  変数代入を落とす（`Z=--zap; echo hi $Z x` → `echo hi $Z x`）
- **`shlex` 相当の正規化を通す。** `-exe""c` が素通りするため。既存の
  `bashrules` へ橋渡しするなら `-exec sh -c` と `-fprint*` の追加が要る

### 段階 3: `verify` ツール

`AGENTS.md` の検証コマンド表を
`verify(target: "all" | "agents" | "templates" | "docs" | "shell")` の
ツール 1 個に畳む（5 個作るのとコンテキストコストが 3 倍違う）。
`codemode` は既定のままにして固定費を 0 にできる
（[ツールのコンテキストコスト](../research/opencode/tool-context-cost.md)）。

**自動承認はしない。** `verify(target:"all")` は
`.pre-commit-config.yaml` の local hook を起動するため、設定を書き換えれば
任意コマンドが動く。ファイルを書ける権限と、それをホスト権限で実行できる
権限は別。ゲートは `tool.execute.before` で自作する。

### 段階 4: 残り約 280 件

**第一候補は「何もしない」。** 目的は確認回数の削減だが、自動実行では
`allow` と `ask` が等価なので効くのは対話時だけ。

#### 既定を `allow` に戻さない理由

| 理由 | 内容 |
| --- | --- |
| 得るものが無い | 自動実行では既に素通りしている |
| 故障時に危険側へ倒れる | 設定が読まれない事故は実在した（Orca overlay）。基準 4 に反する |
| 元の状態への回帰 | 既定を変えても shell deny 85 件は残る。実態は「その 85 件以外は無条件」＝この案件が最初に否定した状態 |

## 候補比較

段階 4 の候補と、検討して見送った手段。

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| **LLM classifier（`ask` → `allow`）** | 機構は実証済み。専用の安価モデルなら 1 回 $0.0006 / 1.1 秒で、**当初の「トークンが嵩む」という反対理由は弱まった** | **自動実行では `allow` と `ask` が等価**なので自動化率は上がらない。誤許可は**誰も見ないまま危険な操作が走る** | 偽許可率。インジェクション耐性（1 例のみ） | **見送り** | — |
| **LLM classifier（`ask` → `deny`）** | **deny だけが自動実行で意味を持つ**。静的パターンが破られる穴を意味で補える。誤検知は安全側 | 遅延が全コマンドに乗る。入力は攻撃者に操作されうる | 偽許可率・偽拒否率。「不安定」の中身 | **未評価** | 実履歴 466 件にラベル付けして偽許可率を測る。**1 件でも出たら却下** |
| sandbox（プロセスごと隔離） | 唯一の境界。難読化した持ち出しを止められる | 上の「採用しない理由」 | macOS | **見送り** | — |
| saved approval の蓄積 | 対話の「常に許可」が project 単位で永続化される | 学習された安全性ではなく恒久的な権限付与 | — | **未評価** | 段階 2〜3 の結果を見てから |
| session スコープの事前宣言 | セッション内で完結し永続化しない | **`ctx.permission.rules` が存在しない**（公式ドキュメントには記載あり） | API の追加待ち | **保留** | 実装されたら再評価 |
| `check_bash.py` への bridge | 既存の判定資産（4,913 行・1,782 テスト）を再利用できる | 承認エンジンにはせず、既知の危険の拒否・誘導のみに使う | 統合方法 | **未評価** | 同上 |

## 次の調査・実験

| # | 減らしたい不確実性 | 方法 |
| --- | --- | --- |
| （なし） | 調査は決着。段階 2 の実装待ち | — |

決着済み: P0-1 / P0-2（[plugin の相関](../research/opencode/plugin/correlation.md)）、
P1-3（[plugin ゲート](../research/opencode/permission/shell-allow-and-plugin-gate.md)）、
P1-4（[ask と並列バッチ](../research/opencode/ask-and-parallel-batch.md)）、
P2-1〜P2-4 / P3-1〜P3-3（[出力フィルタ](../research/opencode/permission/output-filter-and-subagents.md)、
[permission の穴](../research/opencode/permission/gaps.md)）。

P3-4（macOS の `sandbox-exec`）は sandbox 不採用のため**打ち切り**。

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `common.toml.tmpl` | `[bash] allow` を共用 → `[opencode.shell] allow` を新設 | `[bash]` は 3 CLI 共通で切り分けできない | **適用済み** |
| `generate.py` | allow を `[bash]` から取得 → `[opencode.shell]` から取得 + 先頭に `{shell, *, ask}` | 既定を ask にする本体 | **適用済み** |
| `claude_write_deny_globs` | `.git/config` / `.opencode/opencode.json` 等を追加 | どちらも書けると防御を外せる（実測） | **適用済み** |
| `guide-plugin` | （なし）→ 誘導 hook の基盤 | 静的 deny は代替案を返せない | **適用済み**（規則は `cd` 1 件） |
| `guide-plugin` | `cd` のみ → `read` 誘導・`grep` フィルタ・伏字化 | 段階 2 の本体 | 未着手 |
| AGENTS.md の検証コマンド表 | 5 コマンドの手打ち → `verify` ツール 1 個 | コンテキストコストが 3 倍違う | 未着手 |

## 重要な更新

**2026-09-22 — sandbox を検討し、採用しないと決めた。**
成立は実測したが利点がほぼ否定された（上記）。これにより
**境界を持たない前提**に統一し、評価基準から「難読化耐性」を外した。
あわせて**プロジェクト設定がグローバルの deny に勝つ**ことが判明し、
`**/.opencode/opencode.json` を write deny に追加した。

**2026-09-22 — 誘導の位置づけを保護へ戻した。**
前日に「確認削減の効果が小さい」として格下げしたが、`cat` を `read`
ツールへ寄せることは**deny の効かない経路から効く経路へ移す**保護その
ものだと分かった（P3-1 で実測）。確認回数は副次効果に過ぎない。

**2026-09-21 — 確認回数の測定単位が誤っていた。**
計画はセグメント数で数えていたが、permission は**呼び出し 1 回につき
1 判定**。区切り `echo` のように他の作業と同居するものは、やめても確認が
1 件も減らない。正しく測り直すと誘導全体でも 8%（39 件 / 466 呼び出し）で、
当初の評価基準「6 割削減」は達成不能だった。目的を確認削減から
**自動実行で効く穴塞ぎ**へ振り直した。

**2026-09-21 — allow の選定基準を既存リスト自身が満たしていなかった。**
「任意コード実行を含まない」を基準にしながら、残した `git diff` /
`git status` が**どちらも任意コード実行の経路を持っていた**。
外部レビュー（Astra）と実測で判明し、両方を allow から外した。
同時に「allow を増やすと deny が弱まる」という記述が誤りだと分かった
（permission は最終一致の単一判定）。

## 終了結果

<!-- Done / Abandoned にするとき記入 -->

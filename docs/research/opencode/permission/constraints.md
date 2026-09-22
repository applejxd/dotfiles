# OpenCode の permission 設計を縛る制約（実測の総覧）

> **調査日: 2026-09-20 〜 2026-09-22 / 対象: `opencode v2.0.10` 〜 `v2.0.12`**
>
> [CHG-0002](../../../change/0002-opencode-ask-by-default.md) の判断は
> すべてここから出ている。案件側は計画だけを書き、根拠はこの文書と
> 各調査記録が持つ。

## 1. 制約の一覧

| 制約 | 設計への影響 | 出典 |
| --- | --- | --- |
| **自動実行では `allow` と `ask` が等価** | 確認回数は対話時にしか効かない。自動実行で効くのは `deny` だけ | [ask と並列バッチ](../ask-and-parallel-batch.md) |
| permission は多層ではなく**最終一致の単一判定** | allow を足しても deny は弱まらない。順序が全て | [allow リスト監査](allow-list-audit.md) |
| 設定の `deny` は hook を呼ばない | 静的 deny は代替案を返せない。既定 ask のまま hook で deny へ変える | [plugin API](../plugin/api-probe.md) |
| plugin のロード失敗は **fail-open** | 故障時に無防備になる。静的 allow の縮小を先に済ませる | 同上 |
| plugin から `ask` を**作る** API は無い | カスタムツールは「無確認で安全」か「作らない」の二択 | [相関と承認要求](../plugin/correlation.md) |
| plugin は `ask` を `allow` へ引き上げ・`deny` へ引き下げできる | 機構で判定を補える | [plugin ゲート](shell-allow-and-plugin-gate.md) |
| `tool.execute.before` が生コマンド・`id`・`workdir` を持つ | 相関はこの hook で完結。`e.resources` は変数代入を落とすので使わない | [相関と承認要求](../plugin/correlation.md) |
| **静的パターンはクォート・変数・符号化で回避できる** | deny パターンは allow を残す口実にならない | [plugin ゲート](shell-allow-and-plugin-gate.md) |
| **scanner はリダイレクトを分割せず resource に残す** | allow に載せたコマンドは全て任意書き込みの手段になる | [allow リスト監査](allow-list-audit.md) |
| `grep` / `glob` が `read` の deny を迂回する | 読み取りをツールへ移すとき保護を自作する必要がある | [permission の穴](gaps.md) |
| `execute.after` で結果を濾せる | 確認を増やさずに出力を伏字化できる | [出力フィルタ](output-filter-and-subagents.md) |
| `permission.evaluate` に `agent` が載る | bypass をエージェント名で見分けられる | [hook の呼ばれ方](hook-order.md) |
| V2 対応のサードパーティ plugin は 1 件も無い | 既製品に乗れない。自作する | [生態系](../plugin/ecosystem.md) |

## 2. 境界は無い

permission と plugin は**安全網であって境界ではない**。

実行前のコマンド検査はクォート・変数で、実行後の出力検査は `base64` や
`tr` ですり抜ける。**どちらも一方向にしか効かず、組み合わせても迂回の
費用を上げるだけ**（いずれも実測）。

境界を作るには OS レベルの隔離が要る。`opencode` のプロセスごと
bubblewrap で隔離すれば成立することは確かめたが、**採用しない**。

| 期待 | 実際 |
| --- | --- |
| 自動化率が上がる | **上がらない**（自動実行では `ask` が素通り） |
| 確認回数が減る | **減らない**（既定 `ask` を維持するため） |
| 敵対的なリポジトリから守れる | **守れない**（プロジェクト設定で外せる） |
| このリポジトリが安全になる | **ならない**（`chezmoi` が snap 版で bwrap 内から動かない） |

残る利点は「`chezmoi` を使わないプロジェクトで難読化された持ち出しを
止められる」ことだけで、ラッパーの自作と維持・macOS 未実装・常駐サービス
経由の脱出対策という費用に見合わない
（[sandbox の調査](sandbox.md)）。

## 3. 設定で入れる保護は設定で外せる

`<project>/.opencode/opencode.json` の permission は**グローバルの deny に
勝つ**（[permission の穴](gaps.md)）。

| 影響 | 対処 |
| --- | --- |
| 外部リポジトリを開くだけで保護が外れる | **塞げない** |
| エージェントが自分で書いて権限を広げられる | `**/.opencode/opencode.json` を write deny（適用済み） |

## 4. 誘導の対象を選んだときの計測

段階 2 で何を誘導するか決めるために、実履歴 466 呼び出しへ当てた。
**確認回数は目的ではないが、過剰ブロックの判断材料**として測ってある。

| 対象 | 代替案 | 保護上の意味 | 確認の削減 |
| --- | --- | --- | ---: |
| `cat` / `head` / `tail` / `sed -n` | `read` ツール | **deny が効く経路へ移る** | 13 (2.8%) |
| `grep` / `rg` / `find` | `grep` / `glob` ツール | 保護は hook で自作 | 11 (2.4%) |
| `cd X && ...` | `shell` の `workdir` | 無し（作法） | 15 (3.2%) |
| 区切り用途の `echo "==="` | 不要 | 無し | **0 (0%)** |

- **区切り `echo` は採用しない。** 保護上の意味が無く確認も減らないのに、
  deny は 1 往復を捨てさせる。作法の話は `AGENTS.md` で足りる
- `ls` は誘導しない。`read` deny の対象ではなく、移しても保護が増えない

### 過剰ブロックへの歯止め

誘導は `deny` なので、外すと作業が止まる。次を守る。

- `read` で代替できない用途（`head -c`、パイプの途中、`cat` の結合）は
  **誘導しない**。リダイレクト・パイプを含む形は対象外にする
- 誘導は必ず**代替案を本文に書く**（`cd` → `workdir` の乗り換えが
  1 ターンで起きることを実機で確認済み）
- 規則を足すたびに実履歴へ当てて誤爆を数える

## 5. 段階 1 で allow から外したもの

`git diff` / `git status` は「任意コード実行を含まない」という基準を
立てた当人が**基準を満たしていなかった**。`.git/config` の
`diff.<name>.command` と `core.fsmonitor` が経路になる。外部レビュー
（Astra）と実測で判明し、両方を外して `.git/config` / `.git/hooks/**` /
`~/.gitconfig` を write deny に追加した。

`find` に「`-exec` の付いた形だけ静的 deny」は採らない。
`find . -exe""c …` が deny を素通りして `find *` の allow に一致し、
**無確認で任意コード実行**になる（[allow リスト監査](allow-list-audit.md)）。

## 6. 実装の置き場と再起動

plugin は `~/.config/opencode/guide-plugin/`。**登録先が 2 つに分かれる**
（[ロード経路](../plugin/loading.md)）。

| 登録先 | 読まれるもの |
| --- | --- |
| `opencode.json` の `plugins` | `index.js`（サーバ側） |
| `cli.json` の `plugins` | `tui.ts`（TUI 側） |

- 明示指定は**絶対パスのディレクトリ**でないと解決されない。単一ファイルも
  `~` も**黙って無視される**
- ディレクトリ名に `plugin` / `plugins` を使わない（二重ロードになる）
- **サーバ側 plugin を更新したら `opencode service restart` が要る**

現行の仕様は[エージェントの権限設定](../../../spec/agent-permissions.md)が正本。

## 再確認すべき情報源

- OpenCode の scanner が複合コマンドをどう分割するか（**未確認**）
- `ctx.permission.rules`（公式ドキュメントに記載があるが**存在しない**）

[調査記録一覧へ戻る](../../index.md)

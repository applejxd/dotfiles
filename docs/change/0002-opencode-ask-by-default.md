# CHG-0002: OpenCode の permission を既定 ask にし、自動化率を機構で回復する

- **状態**: Planned
- **更新日**: 2026-09-21
- **基準**: OpenCode V2

## 目的と非目的

**目的**: AI CLI の permission 設計から「LLM classifier への委譲」を廃止し、
OpenCode の既定を `ask` にする。そのうえで確認回数を機構（hook / 構造化ツール）
で減らし、実用的な自動化率を保つ。

**非目的**: Claude Code / Copilot CLI の設計変更。今回は OpenCode V2 のみを
対象にする。

## 現在地

このリポジトリは `home/dot_config/agents/common.toml.tmpl` を単一ソースとして、
Claude Code / Copilot CLI / Codex CLI / Gemini CLI の permission・hook・
sandbox・MCP を生成している。判定ロジックは Python
（`home/dot_claude/hooks/lib/bashrules/` で約 4,913 行、pytest 1,782 件）。

直前の作業で 4 つ目の生成先として OpenCode V2（`~/.config/opencode/opencode.json`）
を追加した。その過程で以下が判明した。

1. 従来の設計には allow / ask / deny の 3 リストに加えて「未掲載」という
   4 つ目の選択肢があり、未掲載のコマンドは Claude の `auto` モード /
   Copilot の `assisted` モードの LLM classifier に委ねる意図的な設計だった
2. **OpenCode に classifier は無い**。`allow` は「プロンプトなしで継続」の
   意味でしかない。つまり「未掲載」戦略が OpenCode では「無条件許可」へ
   静かに退化していた
3. 実測では `curl` / `wget` / `docker run` / `gh api` / `python3` /
   `chmod` / `dd` / `base64` / `git add` / `echo` / `history` などが
   全て未掲載＝無条件実行だった

ユーザはこれを受けて「LLM 判定は不安定でトークンも嵩む」として classifier
前提を捨てる決定をした。

**決定済みの方針:**

1. permission の既定を `ask` にする
2. 確認回数の回復は指示（AGENTS.md）ではなく機構（hook）で行う。これは
   このリポジトリの ADR-0006「エージェントへの指示を減らし、強制は機構へ
   寄せる」の適用である
3. ハーネスごとに設定を作り込む方向へ移行する。OpenCode を tier 1 とし、
   `common.toml` の `[bash]` は Claude / Copilot 用として当面そのまま残す

**分かったこと:**

関連する調査記録は次の 3 本。

- [opencode-plugins.md](../research/opencode-plugins.md) —
  プラグイン生態系の棚卸し
- [opencode-plugin-api-probe.md](../research/opencode-plugin-api-probe.md) —
  plugin API の実測
- [opencode-permission-gaps.md](../research/opencode-permission-gaps.md) —
  permission 適用範囲の穴

実セッション 184 件のシェル呼び出し（`&&` `;` `|` で分割して 755 セグメント）
を、OpenCode の照合規則（後勝ち・`*` は `/` を跨ぐ・末尾の `*`（先頭の
半角空白込み）は引数無しにも一致）で再生した。

数字は 2 種類あり、**一致しない**ので区別する。

| 用語 | 意味 |
| --- | --- |
| セグメント数 | シェル呼び出しを `&&` `;` パイプで分割した断片の数 |
| 確認減少数 | そのうち既定 ask で確認になるものの数。移行して実際に消える確認の数 |

ずれるのは、一部のコマンドが静的 allow に載っていて既に無確認で通っている
ため。既に通っているものを移しても確認は減らない。

測定時点は 2026-09-21、1,005 セグメント。既定 ask での確認総数は
959 件（現行 allow 14 件を適用）。

| 移行対象 | セグメント数 | 確認減少数 | 備考 |
| --- | ---: | ---: | --- |
| `cd X && ...` → `workdir` | 163 | 163 | 一致 |
| 区切り用途の `echo` | 105 | 105 | 一致 |
| `cat`/`sed -n`/`head`/`tail`/`ls` → `read` | 213 | 205 | `wc` が allow にある分ずれる |
| `grep`/`rg`/`find` → `grep`/`glob` | 70 | 39 | `grep -n` と `find` が allow にあるため |
| `uv run` などの検証系 → `verify` | 57 | 57 | 一致 |
| 上記以外 | 397 | 390 | その場限りのコマンド |

5 つの対策で 959 → 390 件まで減る計算になる。効果の順位は
読み取り移行（−205）が最大で、`cd` 廃止（−163）、`echo` 廃止（−105）、
`grep` 移行（−39）、`verify`（−57）と続く。この順位は当初の想定
（ツール化が主役）を否定するもので、**読み取り移行が最優先**という結論に
なった。

残り 390 件は `python3 -c` / `opencode api` / `export` / `sed 's` /
`curl -fsSL` など、その場限りのコマンドで列挙では潰せない。

測定元の `~/.local/share/opencode/opencode.db` は作業のたびに増えるため、
**件数は測定時点でしか意味を持たない**。またサンプルは調査セッション由来で
`python3 -c` による分析が多い偏りがある。比率の傾向を見る用途に限ること。

生成済み `opencode.json` の shell allow は 14 件だが、うち 7 件
（`find` / `gcc` / `g++` / `cmake -S` / `cmake --build` / `uv sync` /
`mise run`）が任意コード実行を含む。`common.toml` のコメントは
「読み取り専用・冪等なものだけ」と書いてあり実態と乖離している。

OpenCode V2 plugin API の実測結果は次のとおり。

- `.opencode/plugins/*.js` は自動ロードされる。`@opencode/plugin` の
  import すら不要で、`id` と `setup` を持つ default export だけでよい
- 発火順は `tool.execute.before` → `shell.create.before` →
  `permission.evaluate`
- `tool.execute.before` は生コマンド（分割前）と `id` を持つ。
  `permission.evaluate` の `source.id` と一致するので相関できる
- `shell.create.before` は `cwd` を持つが `id` を持たない。ただし
  **P0-1 の決着により、この hook は使わない**。`tool.execute.before` の
  `input.workdir` が cwd を持ち `id` 付きなので、そちらで完結する
- `permission.evaluate` で `effect="deny"` にすると実際にブロックでき、
  `message` がエージェントへ届く
- hook 内の例外は fail-closed（実行が止まる）。プラグインのロード失敗は
  fail-open（無防備に実行される。ただし WARN ログには出る）
- 設定の `deny` は hook を呼ばない（公式記載を実証）。つまり静的 deny を
  置くと代替案メッセージを返せない
- 非対話実行（`opencode run`）は `ask` を自動拒否する

permission の穴として次を実測した（重要）。

- `grep` の permission resource は検索正規表現のみで、検索先パスが
  入らない。`read` で deny したファイルの中身が `grep` の結果から逐語的に
  返った（カナリア実験で確認）。ファイルごとの `read` 判定も走らない
- `glob` も `read` deny 対象のパスを列挙する
- `editor.add` で登録したカスタムツールには `permission.evaluate` が
  発火しない。`--auto` なしでも無確認で実行される

ただし保護は自作できることを実測で確認した。

- `grep` / `glob` の `tool.execute.before` は `path` / `include` を持つ。
  `source.id` で相関して判断できる
- `permission.hook("evaluate")` から `grep` を deny できる
  （理由メッセージも届く）
- `tool.hook("execute.after")` で `grep` の結果を書き換えられる
  （秘密を含む行の伏字化に成功）。検索は通しつつ出力だけ濾せるので
  確認回数が増えない
- カスタムツールは `tool.hook("execute.before")` で例外を投げれば実行を
  止められる。`e.input` の書き換えも効く（引数の正規化・制約が可能）

`session.hook("context")` でモデルへ送られる直前のツール一覧を観測した。
ベースラインは 13 ツール・12,596 bytes、システムプロンプト 30,015 bytes。

- `codemode: true`（既定）で登録したツールは常時提示の一覧に**載らない**
  （固定費 0 bytes）。`search()` 経由の遅延提示になる
- `codemode: false` で登録すると載る（単純なツール 1 個で 111 bytes）

したがってツール化によるコンテキスト逼迫は、既定のまま登録すれば問題に
ならない。

npm の人気順 20 件を依存から判定した結果、**V2 対応のサードパーティ製
プラグインは 1 件も見つからなかった**。oh-my-opencode（OmO）も最新 beta
（2026-09-20 公開）を含めて V1（`@opencode-ai/plugin`）のまま。Claude Code
hook 互換を謳うプラグイン 3 件も全て V1。したがって既製品に乗る道は現時点で
無く、自作するしかない。

なおこの環境では Orca の `orca-opencode-status.js` が V1 形式のため V2 で
ロードに失敗している（副次的な発見）。

**まだ分からないこと:**

- Claude / Copilot も既定 ask にするか。Copilot は hook の `ask` が
  自動承認されるバグ（github/copilot-cli#3590）があるため効果が限定的

## 評価基準

**必須:**

1. 段階 1 の完了時点で、Claude / Copilot / Codex / Gemini の生成物に diff
   が出ないこと（テストで固定）
2. 段階 2 の完了時点で、実セッションのリプレイによる確認減少数が
   測定時点の総数の 6 割以上になること（2026-09-21 時点なら 959 → 390 件）。
   件数は測定時点でしか意味を持たないため、絶対値ではなく比率で判定する
3. 任意コード実行を含むコマンドが OpenCode の allow に 1 件も無いこと
4. プラグインがロードに失敗しても、危険側（無条件許可）に倒れないこと

## 候補比較

段階 4（残り約 280 件への手当）の手段候補。段階 1〜3 の実績を見てから
判断する。「耐えられる頻度」なら何もしない選択もある。

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| saved approval の蓄積 | 対話で「常に許可」した内容が project 単位で永続化される | 学習された安全性ではなく人間が恒久的に権限を与えた状態になる | — | **未評価** | 段階 1〜3 の結果を見てから |
| session スコープの事前宣言（`ctx.permission.rules()`） | セッション内で完結し永続化しない | **2.0.10 に `ctx.permission.rules` が存在しない**（公式ドキュメントには記載あり） | API の追加待ち | **保留** | 実装されたら再評価 |
| `check_bash.py` への bridge | 既存の判定資産（4,913 行・1,782 テスト）を再利用できる | 承認エンジンにはせず、既知の危険の拒否・誘導のみに使う方針 | 統合方法 | **未評価** | 同上 |

## 次の調査・実験

| # | 減らしたい不確実性 | 方法 |
| --- | --- | --- |
| P1-3 | allow に残すコマンドの選定 | ユーザと相談しながら段階 1 の allow リストを確定する |

決着済み: P0-1 / P0-2（[plugin の相関と承認要求の可否](../research/opencode-plugin-correlation.md)）。

| # | 結果 |
| --- | --- |
| P0-1 | **解決。** `shell.create.before` は不要。`tool.execute.before` の `input.workdir` が cwd を持ち `id` 付きなので相関に迷いがない。`workdir` 省略時はセッションのディレクトリで確定する |
| P0-2 | **不可能。** plugin から承認要求を作る API が存在しない。`ctx.permission` は `hook` / `list` / `get` / `reply` のみで、新規作成の口が無い |

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `common.toml.tmpl` | `[bash] allow` を共用 → `[opencode.shell] allow` を新設 | `[bash]` は 3 CLI 共通のため、ここを削ると効果の切り分けができない | 未着手 |
| `generate.py` | OpenCode の shell allow を `[bash]` から取得 → `[opencode.shell]` から取得 + 先頭に `{action:"shell", resource:"*", effect:"ask"}` を追加 | 既定を ask にする本体変更 | 未着手 |
| `test_generate_opencode.py` | （なし）→ 任意コード実行を含むコマンドが allow に無いことと、他 CLI の生成物に diff が出ないことを固定するテスト | 段階 1 の受入条件を機械的に担保する | 未着手 |
| `.opencode/plugins/` | （なし）→ 誘導 hook（deny + 代替案メッセージ） | 静的 deny は hook を呼ばず代替案を返せないため、既定 ask のままプラグインが deny へ変える構成にする | 未着手 |
| AGENTS.md の検証コマンド表 | 5 コマンドの手打ち → `verify(target: "all" \| "agents" \| "templates" \| "docs" \| "shell")` ツール 1 個 | enum 引数 1 個に畳むとコンテキストコストが 3 倍違う | 未着手 |

## 実装・検証

### 実施計画

| 段階 | 内容 | 状態 |
| --- | --- | --- |
| 0 | `grep`/`glob` の穴と plugin API の実測、計測基盤の確立 | 完了 |
| 1 | `[opencode.shell]` 新設 + 既定 ask | 未着手 |
| 2 | プラグイン基盤 + 誘導 hook | 未着手 |
| 3 | `verify` ツール | 未着手 |
| 4 | 残り約 280 件への手当 | 判断保留 |

### 段階 1 の詳細

`common.toml.tmpl` に `[opencode.shell] allow` を新設する。`[bash]` には
触らない。理由は、`[bash] allow` が 3 CLI 共通のため、ここを削ると
Claude / Copilot にも影響して効果の切り分けができなくなるため。これは
以前合意した「ハーネスごとに作り込む」方針の最初の適用でもある。

変更対象は次の 3 つ。

- `home/dot_config/agents/common.toml.tmpl` に `[opencode.shell] allow`
  を新設
- `scripts/agents/generate.py` の `build_opencode_permissions()` で
  allow の取得元を切り替え、先頭に
  `{action:"shell", resource:"*", effect:"ask"}` を置く
- `test/agents/test_generate_opencode.py` に「任意コード実行を含む
  コマンドが allow に無いこと」「Claude / Copilot の生成物に diff が
  出ないこと」を固定するテストを追加

allow の選定基準は、副作用なし・冪等・任意コード実行を含まないこと。
`find` は `-delete` / `-exec` があるので入れない。ビルド系（`gcc` /
`cmake` / `uv sync` / `mise run`）はプロジェクトのコードを実行するので
入れない。残す候補は `git diff` / `git status` / `git log` / `wc` /
`uv pip list` / `docker ps` 程度。

撤退方法は `[opencode.shell]` を削除するだけ。`[bash]` に触らないので
他 CLI へ影響しない。

### 段階 2 の詳細

プラグインの hook で次を deny + 代替案メッセージにより誘導する。静的
deny にしてはいけない（deny は hook を呼ばないため代替案を返せない）。
既定 ask のままにして hook が deny へ変える構成にする。これならプラグイン
故障時は ask に縮退して安全側に倒れる。

| 誘導対象 | 代替案 | 確認減少数 |
| --- | --- | ---: |
| `cd X && ...` | `shell` ツールの `workdir` を使う | 163 |
| 区切り用途の `echo "==="` | 不要 | 105 |
| `cat` / `sed -n` / `head` / `tail` / `ls` | `read` ツール | 205 |
| `grep` / `rg` / `find` | `grep` / `glob` ツール（保護は hook で自作） | 39（段階 1 後は 70） |

`grep` 行だけ 2 通りあるのは、現行 allow の `grep -n` と `find` が
効いているため。段階 1 でこれらを落とすと ask に変わるので、
移行で減る確認は 39 件から 70 件へ増える。

判定は前方一致で足りるので `check_bash.py` の意味解析は要らない。
パターンと代替案メッセージの表を `[opencode.shell]` に書いて生成するのが、
単一ソースを保ちつつ最小の実装になる。

`grep` / `glob` へ誘導する場合は、`tool.execute.before` で `path` /
`include` を退避し、`execute.after` で結果を濾す保護を同時に入れる。

### 段階 3 の詳細

`AGENTS.md` の検証コマンド表を
`verify(target: "all" | "agents" | "templates" | "docs" | "shell")` という
enum 引数 1 個のツールにする。ツールを 5 個作るのではなく 1 個に畳む
（コンテキストコストが 3 倍違うため）。`codemode` は既定（true）のまま
にして固定費を 0 にする。

ただし自動承認はしない。`verify(target:"all")` は `.pre-commit-config.yaml`
の local hook を起動するため、設定ファイルを書き換えれば任意コマンドが
動く。「エージェントは既にそのファイルを編集できるのだから権限は増えない」
という議論は成立しない（ファイルを書ける権限と、それをホストユーザー権限で
実行できる権限は別）。ゲートは `tool.execute.before` で自作する。

### 段階 4 の詳細

残り約 280 件はその場限りのコマンドで列挙では潰せない。手段の候補は
上の「候補比較」を参照。

## 重要な更新

（なし）

## 終了結果

（未終了）

# エージェント CLI のランタイム設定を秘密として扱う

- **ステータス**: Accepted
- **日付**: 2026-09-03
- **決定者**: applejxd

## コンテキスト

このリポジトリは AI CLI の permission と hook を
`home/dot_config/agents/common.toml` に単一ソース化し、
`scripts/agents/generate.py` から各 CLI の設定へ展開している。
秘密ファイルの読み書きは 2 つの層で止めている。

| 層 | 実体 | 効く対象 |
| --- | --- | --- |
| permission | `[file] read_deny_globs` / `write_deny_globs` → `Read()` / `Edit()` | Claude のファイルツール |
| hook | `home/dot_claude/hooks/executable_check_bash.py` | 両 CLI の bash コマンド |

`~/.claude.json` が GitHub PAT を平文で持つのではないか、という問いから
実際の内容と両層の挙動を確認した。

- 現時点の `~/.claude.json` に**秘密は入っていない**。
  `mcpServers` は deepwiki の HTTP URL のみで、トークン様の文字列は 0 件。
  ただし `oauthAccount`（メールアドレス・組織 UUID）と
  `projects` 配下の全プロジェクトパスは平文で、パーミッションは `0644`
- **秘密が入る経路は実在する**。`claude mcp add --env GITHUB_PAT=...` や
  `--header "Authorization: Bearer ..."` を使うと、この JSON に平文で書かれる。
  ファイルは CLI 自身が随時書き換えるため、chezmoi の管理下にない
- 実測で `cat ~/.claude.json` は hook を**素通り**した
- `~/.copilot/config.json` は `read_deny_globs` に載っているが、
  hook 側の一覧には無く `cat` で読めた。**層ごとに対象がずれていた**

問題は 2 つある。第一に、秘密を持つファイルの判定が
「いま秘密が入っているか」を暗黙の前提にしていたこと。設定ファイルの中身は
CLI の操作で変わるので、入った瞬間を検知する手段がない。
第二に、permission と hook で対象一覧が独立しており、
片方だけに追加された項目がそのまま穴になっていたこと。

## 検討した選択肢

### 選択肢 1: 現状維持

現時点で秘密が入っていない以上、対処しない。

- **利点**: 変更コストがゼロ。エージェントが MCP 設定を自分で調査できる
- **欠点**: `claude mcp add --env` を一度でも使えば、その後に走る
  すべてのエージェントが PAT を読める状態になる。
  設定を変えた本人が deny リストの更新を思い出す保証がない

### 選択肢 2: 秘密が実際に書き込まれた時点で塞ぐ

内容を検査し、トークン様の文字列を含むファイルだけを deny する。

- **利点**: 誤って正当なファイルを塞ぐことがない
- **欠点**: hook は 1 コマンドあたり数 ms で判定する必要があり、
  対象ファイルを開いて走査する設計にはできない。
  仮にできても「秘密が書かれてから最初の検査まで」の窓が残る

### 選択肢 3: ファイルのパーミッションを `0600` にする

- **利点**: 他ユーザーからの読み取りは防げる
- **欠点**: エージェントは**ユーザー自身の権限で動く**ので、
  この問題に対しては効果がない。多層防御としては有効だが代替にならない

### 選択肢 4: 秘密が「入りうる」時点で予防的に deny し、両層へ同時に登録する

chezmoi 管理外の CLI ランタイム設定を、内容にかかわらず秘密として扱う。

- **利点**: 設定変更の順序に依存しない。層の不整合も同時に解消できる
- **欠点**: 秘密が入っていないファイルまで読めなくなる。
  エージェントが MCP 設定の不具合を自分で調べられなくなる

## 決定事項

**選択肢 4 を採用する。**

理由: 設定ファイルの中身は CLI の操作で変わり、秘密が入った瞬間を
検知する手段がない。選択肢 2 は検知の窓とコストの両方で成立せず、
選択肢 1 は「deny リストの更新を人が思い出す」ことに依存する。
選択肢 3 は攻撃モデルが違う（エージェントはユーザー権限で動く）。

適用した規則は次のとおり。

1. **判定は「秘密が入っているか」ではなく「秘密が入りうるか」で行う。**
   MCP サーバ定義の `headers` / `env` を持てる設定ファイルは、
   現時点の内容にかかわらず秘密扱いにする

2. **chezmoi 管理外のランタイム設定を秘密扱いにする。**
   `~/.claude.json` と `~/.copilot/config.json` は `chezmoi managed` に
   現れない。CLI が自分で書き換えるだけで、内容がリポジトリ側に存在しない。
   一方 `~/.claude/settings.json` や `~/.copilot/hooks/from-claude.json` は
   `common.toml` から生成しており、知りたい内容はリポジトリを読めば分かる
   ので通す。読めなくなって困る／困らないの線がここで一致する

3. **deny は permission 層と hook 層の両方に置く。**
   片方だけに載せると、もう片方が穴になる。
   `~/.copilot/config.json` が `Read()` では拒否されるのに `cat` で読めていた
   のがその実例

4. **一致方法は名前の一意性で選ぶ。**
   `.claude.json` はこの名前自体が一意なので basename 完全一致
   (`_SENSITIVE_BASENAMES`)。`config.json` は一般的すぎるので
   ディレクトリ込みの suffix 一致 (`_CREDENTIAL_PATHS`) にする。
   ADR-0004 の「確実な証拠と語彙ヒューリスティックを分ける」に従い、
   `*claude*` のような部分一致は使わない

5. **deny は最後の防波堤であって、秘密の置き場所の代替ではない。**
   MCP へトークンを渡すときは設定ファイルへ直書きせず、
   環境変数や `gh auth token` のような外部の資格情報ストアを経由させる

## 完了条件

- [x] `common.toml` の `read_deny_globs` / `write_deny_globs` に
      `~/.claude.json` を追加し、`~/.copilot/*` の write 側の欠落も揃える
- [x] `check_bash.py` の `_SENSITIVE_BASENAMES` に `.claude.json` を、
      `_CREDENTIAL_PATHS` に `/.copilot/config.json` を追加する
- [x] 生成物 (`~/.claude/settings.json`、`~/.copilot/hooks/from-claude.json`、
      `home/dot_copilot/hooks/from-claude.json.tmpl`) を巻き込まないことを確認する
- [x] `test/agents/test_check_bash_decision.py` に deny 4 件・許可 3 件の
      回帰テストを追加する
- [x] `uv run --with pytest --no-project pytest test/agents/ -q` が通過（1224 件）
- [x] `uv run pre-commit run --all-files` が全通過
- [x] `docs/agents-permissions.md` に判定の根拠と一致方法の使い分けを記載

## 結果

### ポジティブな結果

- `claude mcp add --env` で PAT を書き込んでしまった後でも、
  エージェントがそれを読み出せない。設定変更と deny リスト更新の
  順序に依存しなくなった
- permission 層と hook 層の対象一覧のずれが 1 件解消した。
  「両層に置く」という規則が残ったので、次の追加でも同じ穴を作らない
- 新しく秘密扱いにするかどうかの線が「chezmoi 管理下にあるか」で
  説明できるようになり、今後の追加に基準ができた

### ネガティブな結果

- エージェントが `~/.claude.json` を直接読めなくなり、MCP 設定の不具合を
  自分で調査できない。`claude mcp list` のようなコマンド経由に限られる
- 秘密が入っていないファイルも一律に塞ぐため、deny の範囲が
  実際のリスクより広い。これは選択肢 4 が意図的に受け入れた代償

### 中立的な結果

- `~/.gemini/settings.json` と `~/.codex/config.toml` も MCP 定義を持てるが、
  どちらも chezmoi が生成する側なので規則 2 に従って対象外とした。
  これらに `gemini mcp add` などで直接トークンを書くと保護されない。
  規則 5（直書きしない）が実質的な担保になっている
- `~/.copilot/settings.json` は `chezmoi managed` に含まれる（`modify_` で
  一部のキーだけを管理し、`trustedFolders` などは CLI が書く）が、
  以前から `read_deny_globs` に載っている。規則 2 の線とは一致しないものの、
  今回は判断を変える材料がないのでそのまま踏襲し、write 側の欠落だけを揃えた

## 関連 ADR

- [ADR-0004](0004-hook-check-semantic-axis.md): 「確実な証拠と語彙ヒューリスティックを
  分ける」という判定軸。本 ADR の規則 4 はその適用であり、判定軸自体は変えていない
- [ADR-0001](0001-external-tool-config-coexistence.md): AI CLI の設定ファイルを
  「chezmoi の専有領域」「外部と共有する領域」「管理外」に切り分けた決定。
  本 ADR の規則 2 はその切り分けを、読み取りの可否にも使う

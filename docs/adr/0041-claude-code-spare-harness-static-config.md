# Claude Code を予備のハーネスとして、静的な標準設定だけを chezmoi で管理する

- **ステータス**: Accepted
- **日付**: 2026-11-18
- **決定者**: applejxd（2026-11-18 に、次を承認した: Claude Code を予備のハーネスにする。設定の共通化は全くしない。標準の設定記載だけを chezmoi で配る。pi の設定から反映できるものだけを反映する。既存の `permissions` は pi 由来の一覧で置き換える。リポジトリ直下の `CLAUDE.md` は置かない。claude が PATH にある機だけに配る。同日の追加の指示: スキルは `commit`・`sdd-docs` 相当だけを写す。`CLAUDE.md` は最低限に絞る。claude は試験の対象外にする。claude は会社用の前提にして、MCP も配る（方式は chezmoi の modify、MCP ツールは `permissions.allow` に足す））
- **関係**: [ADR-0037](0037-retire-custom-profile-and-other-harnesses.md) の「pi 以外のハーネス」のうち、Claude Code の**設定の管理**だけを部分的に置き換える。導入の自動化・設定の生成・単一ソース・hook は、ADR-0037 のまま持たない。[ADR-0031](0031-evaluate-existing-extensions-first.md)（既存の評価が先）に従う。

## コンテキスト

- ADR-0037 は、Claude Code の導入・設定の生成・hook を撤去し、すでに入っている `~/.claude` は触らない（以後は更新されない）と決めた。
- 利用者は、pi が使えないときの予備として Claude Code を使いたい。設定の共通化（5 つの CLI の単一ソースから生成する形）には戻さない。
- 今の `~/.claude/` は、撤去した生成器の残り（`CLAUDE.md`・`commands/`・`hooks/`・`skills/herdr`）と `settings.json` がある。`settings.json` には、Orca が入れる hook（13 イベント）・`enabledPlugins`・`env`・`sandbox`、
  `permissions`（allow 46・ask 22・deny 209。うち 21 は廃止した kcage などの残り）・`defaultMode: auto` が入っている（2026-11-18 の実測）。
- 公式 docs（2026-11-18 取得）で確かめたこと:
  - [Settings](https://code.claude.com/docs/en/settings): ユーザーの設定は `~/.claude/settings.json`。規則のリスト（`permissions.allow` など）はスコープをまたいで結合される。ファイルは厳密な JSON で、書き換えは実行中に読み直される。`~/.claude.json` は本体が自分で書く状態ファイルで、編集する必要はない（MCP の設定・認証の状態・プロジェクトごとの信頼を持つ。user スコープの MCP の置き場でもある）。
  - [Permissions](https://code.claude.com/docs/en/permissions): 規則は deny → ask → allow の順で、最初に当たったものが決まる（allow で ask・deny の例外は作れない）。Bash の規則は `nohup` などの wrapper を剥がしてから照合し、`git -C . push` のような別の形は止めない（境界ではない）。`Read` の deny は同じパスの Edit・Write も止める。パスは gitignore の書式（`//` が絶対パス、`~/` がホーム）。
  - [Skills](https://code.claude.com/docs/en/skills): 個人のスキルは `~/.claude/skills/<名前>/SKILL.md`。`~/.agents/skills` は読まない。カスタムコマンド（`~/.claude/commands/`）はスキルに統合された。
- 実機（Claude Code 2.1.270）の `claude doctor` は、`CLAUDE_CONFIG_DIR` に一時の場所を指せば、認証なしで設定の文法の誤りを「Invalid settings」として出す（終了コードは 0 のまま）。

## 検討した選択肢

| 案 | 内容 | 判定 |
| --- | --- | --- |
| **A（採用）** | 静的ファイルと、chezmoi の標準機能 `chezmoi:modify-template`（`settings.json` の `permissions.deny` / `permissions.ask` だけを置き換える） | Python もスクリプトも要らない。実験で、他のキー・hook・冪等・新規作成・`claude doctor` を確認した |
| B | 何も管理しない（必要な日に手で書く） | 予備が要る日に方針が無い。利用者の依頼に合わない |
| C | `settings.json` を丸ごとテンプレートで配る | Orca の hook や `/config` が書く内容と衝突する |
| D | `/etc/claude-code/managed-settings.json` | root が要る。利用者の設定を上書きできない側になる |
| E | 生成器・単一ソース（旧 `common.toml`） | ADR-0037 で撤去した。共通化しない方針に反する |
| F | 小さな Python の modify スクリプト（pi の `compaction.json` と同じ型） | 動くが、テンプレートで足りるので、維持するコードを増やさない |
| G（MCP の配備） | A: `~/.claude.json` への modify（**採用**）／B: `claude mcp add-json` を run スクリプトで／C: pi の TOML から導出 | B は本体の CLI が書くので競合が無いが、sh と ps1 の 2 本が要り、宣言的でない（消されても戻らない）。C は共有になる（決定 2 に反する）。A は、そろっていれば書き換えないので競合の窓を最小にできる |

## 決定

1. **管理するのは 6 つだけ**: `~/.claude/CLAUDE.md`（全体。最低限の指示だけ）、`~/.claude/settings.json` の `permissions.deny` と `permissions.ask` だけ（会社 PC は `permissions.allow` への MCP の 2 件の追加も）、`~/.claude/commands/stepback.md`、スキル `~/.claude/skills/commit/` と `~/.claude/skills/sdd-docs/`、`~/.claude.json` の `mcpServers`（会社 PC だけ）。ほかのキー（hook・`enabledPlugins`・`env`・`sandbox`・`permissions.allow`・`defaultMode`）は触らない。
2. **pi とは共有しない。** pi の指示・権限の方針・プロンプト・スキルから、反映できるものを**手で写した静的なスナップショット**で、pi 側を直しても追随しない（必要なら手で足す）。
3. **権限は、pi の bash の deny・ask の規則を `Bash(...)` に写す**（`*` の意味は同じだが、末尾の `*` の省略の条件が違うので、* が複数の規則には、末尾の `*` と直前の空白を除いた形を足す）。`path` の deny は `Read(...)`、`path_write` の deny は `Edit(...)` に写す。Claude に対応物が無いものは写さない。pi が使う `cc-safety-net`（破壊的なコマンドを止める層）の対応物として、git の破壊的な形とディスク・デバイスの破壊だけを glob で足す（[仕様](../spec/claude-code.md#pi-から写したもの写さなかったもの)）。
4. **配る範囲は、claude が PATH にある機だけ**（`.chezmoiignore.tmpl` の `lookPath`）。MCP（`~/.claude.json`）は、そのうえで会社 PC（`is-work`）だけ。導入は自動化しない（ADR-0037 のまま）。
5. **スキルは、`commit` と `sdd-docs` の写しだけ**（pi の版を、Claude Code 向けに直した独立の複製。委譲・pi 固有の記述を除き、置き場を `~/.claude/skills` に読み替える。symlink による共有はしない）。**持ち込まないもの**: ほかのスキル・子の定義・会社 PC の 2 件以外の MCP・hook・`sandbox`・リポジトリ直下の `CLAUDE.md`。`.chezmoiremove` の `.claude/skills/commit`・`.claude/skills/sdd-docs`（旧い置き場の掃除）は外す。
6. **既存の deny（209）・ask（22）は、置き換えで消える。** 個人用の追加は、`.claude/settings.local.json` に書く（リストは結合される）。
7. **Claude Code の設定は、試験の対象外**（利用者の決定）。維持するコードを減らす（ADR-0037 の教訓）。変えるときの手での確認は、[仕様](../spec/claude-code.md#試験の対象外)。
8. **Claude は会社用の前提。** 家の機だけの指示（Tailscale）は置かない（`CLAUDE.md` は静的なファイル）。**MCP は会社 PC（`is-work`）だけに配る**: pi の宣言（`pi-mcp-servers.toml`）のうち、会社 PC の 2 件（`agentcore-websearch`・`webfetch`）の**手で写した静的な写し**（共有しない）。会社 PC は Bedrock 経由で、内蔵の検索が使えないため。配備は `~/.claude.json`（user スコープの置き場）への `chezmoi:modify-template`（宣言した名前の定義だけを置く。そろっていれば入力をそのまま返し、書き換えない。認証の状態を持つので `private_` で 0600 を保つ。`private_` が無いと、chezmoi が既存の 0600 を 0644 に広げることを実測した）。MCP ツールは `permissions.allow` に足す（利用者が承認。pi の方針と同じ）。詳細は [仕様](../spec/claude-code.md#mcp会社-pc-だけ)。

### 自作の記録（ADR-0031 の 3）

| 項目 | 内容 |
| --- | --- |
| (a) 既存で満たせない理由 | Claude Code に、dotfiles 向けの宣言的な取り込みは無い（`settings.json` は本体・Orca・`/config` が書く）。chezmoi の標準機能（`chezmoi:modify-template`）と静的ファイルで足りるので、コードは書かない |
| (b) 維持費 | テンプレート約 20 行・権限のデータ（deny 129・ask 133）・指示約 8 行・スキルの写し 2 本（`commit`・`sdd-docs`。検査のスクリプト 3 本を含み、pi の版から追随しない）・MCP の写し 2 件と modify 約 30 行。試験は置かない。上流で追従が要るのは、規則の文法と、Bash の照合（wrapper の剥がし）の 2 点。pi 側の変更は追随しない |
| (c) 撤去の条件 | Claude Code を予備として使わなくなったとき（`home/dot_claude`・`home/modify_private_dot_claude.json`・二つのデータ（`claude-permissions.json`・`claude-mcp-servers.json`）とこの ADR を撤回する。配った MCP は `claude mcp remove --scope user <名前>` で消す）。上流が `~/.agents/skills` や `AGENTS.md` を読むようになったときは、スキルと指示の扱いを見直す |
| (d) 承認 | 利用者が、方式（静的ファイルと `modify-template`）・範囲・置き換え（既存の deny・ask）を承認し、同日に、スキル 2 本の写し・`CLAUDE.md` の最低限化・試験の対象外・会社用の前提での MCP の配備（方式は modify、`allow` に足す）を追加で指示・承認した（2026-11-18） |

## 結果

**得るもの**:

- pi が使えないときに、同じ作業の約束（応答・検証・書式・拒否への対処）と、害の大きい操作の deny・ask を持った Claude Code に切り替えられる。
- 設定の源が増えない（pi の源とは別の、独立した静的な写しだけ。生成器も共有の源も無い）。

**失うもの・限界**（詳細は [仕様](../spec/claude-code.md#限界)）:

- 試験を置かないので、写し（スキル・権限のデータ・MCP の宣言）が pi の版から食い違っても、壊れても、検査では気づけない。MCP の写しは、pi の版・引数を変えたら手で直す。
- `~/.claude.json` は、本体が頻繁に書く状態ファイル。書くのは宣言と違うときだけだが、Claude Code を終了してから apply する。会社の管理者の方針によっては、user スコープの MCP は読み込まれない（排他的な `managed-mcp.json`、または許可リストにないサーバ。迂回しない）。MCP のサーバが Claude Code の `sandbox` の対象かは未確認で、`private_` の 0600 は Unix 系の話（Windows は未確認）。
- Bash の deny・ask は、**境界ではない**（別の形・別の呼び出しは止まらない）。実際の囲いは、既存の `sandbox`。`cc-safety-net` 本体は入っていない（公式の `npx -y cc-safety-net@latest install --claude-code` で、プラグインとして Claude Code にも入れられる。入れるかは利用者が決める）。
- `allow` で ask・deny の例外は作れないので、pi の例外（`*.env.example` の読み取り、`git worktree remove` の `.tmp/worktrees/` 配下、`git config --get`）は写せない。`git config` は読み取りも deny になる。
- 規則が実際の対話で意図どおり当たるかは、Claude Code を動かさないと確かめられない（文法は `claude doctor` で確認した）。Windows は未検証。
- 既存の手書きの deny・ask は消える。キーの並びは辞書順に整う（見た目だけ）。

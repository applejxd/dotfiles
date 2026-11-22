# リポジトリのモジュール性: 配布と利用時の境界はどこで結合しているか

**全面分割は不要。** 肥大化は主に独立したスキルの量で、直す価値が高いのは配布の例外とエージェントの検索ツール名の結合。最優先は **Windows での個人用検索コードの意図しない配布を止めること**。次に、WSL 判定と各スキル固有の除外を、標準のテンプレート・ignore に局所化できる。

- **観測日**: 2026-11-22。**対象**: `develop` の `c38fbd398b7854ddb5c20bcd2b0af7efc44b5c08`。
- **環境**: Linux 上の chezmoi 2.72.1・Python 3.13.6。別の OS はテンプレートの入力を合成した。`chezmoi apply`、管理者スクリプト、MCP サーバへの接続は実行していない。
- **一次情報**: [対象コミットのソース](https://github.com/applejxd/dotfiles/tree/c38fbd398b7854ddb5c20bcd2b0af7efc44b5c08)、[chezmoi の適用順](https://www.chezmoi.io/reference/application-order/)、[ignore の規則](https://www.chezmoi.io/reference/special-files/chezmoiignore/)、[既存ファイルの一部を管理する標準機能](https://www.chezmoi.io/user-guide/manage-different-types-of-file/#manage-part-but-not-all-of-a-file)（公式文書の確認日 2026-11-22）。
- **範囲**: どこが一緒に変わるか、どの境界なら依存を減らせるか。今回は診断と隔離した試作であり、採用の決定や配備仕様の変更ではない。

## 大きさと実際の結合

| 観測 | 結果 | 読み方 |
| --- | --- | --- |
| source state `home/` の追跡パス | 635（サブモジュールの参照 1 を含む） | ディレクトリを別リポジトリにするだけでは配備時の依存は消えない |
| 共通スキル `home/dot_agents/skills/` | 22 本、313 パス。上位 3 本の `powerpoint-studio` 96、`conference-video` 62、`readme-writer` 45 で 203 パス | ここには個々のスキルの文書・試験・lock・vendor も含む。サイズを pi 本体の複雑さとみなさない |
| pi と予備の Claude Code | `home/dot_pi/` 30、`home/dot_claude/` 21、`scripts/agents/` 3 | pi の実行系は複数の場所にある。`dot_pi/` の数だけで全体の規模は測れない |
| 自動導入スクリプト | 41 本（Windows 20、Linux 8、macOS 7、Unix 共通 6） | Windows が多い。ただし 20 本が Unix に依存するわけではない |
| 共有テンプレートの静的参照 | 31 呼び出し元から 21 テンプレートへ 46 組。最多は `sudo-keepalive.sh.tmpl` 10、`is-work` 6 | 実行回数ではなく、呼び出し元と呼び出し先の組。共有で重複が消えている場合もある |
| 配布の調整点 | `.chezmoiignore.tmpl` 254 行、`.chezmoiremove` 171 行 | 前者に OS・用途・実行時成果物の除外が混在。後者は既に配ったものの移行履歴で、現在の配布とは別の契約 |

直近の非マージ 250 コミット（`a60ebf0f` から `295fd841`）を `git log --no-merges` で数えた。`.chezmoiignore.tmpl` を変えた **24 件のうち 21 件**は pi 関連も変更し、**3 件**は導入スクリプトも変更した（重複可）。pi 関連の **85 件**のうち 84 件は検証関連、7 件は共通スキル、7 件は Claude の配布設定、5 件は導入スクリプトも変更した。変更例は `295fd841`（pi の起動入口と配布）、`53471fc2`（個人機だけのスキルと指示）、`b0d702b5`（予備の Claude と配布）。この期間はエージェント基盤の変更が多い。これは**変更の波及の手がかり**で、構造上の依存・頻度の定常値ではない。試験の同時変更は境界の保護でもある。

集計方法: `git ls-files` のプレフィックスで数え、`SKILL.md` は `skills/<名前>/SKILL.md` だけを数えた。静的参照は `home/` の `.tmpl`・`modify_`・`.chezmoitemplates/` のうち、Go テンプレートのコメントを除き、リテラルの `template` / `includeTemplate` が実ファイルを指す組を重複排除した。`source`・`exec`・環境変数・外部パッケージ・動的に決まる名前はこの数に含まれない。履歴では pi 関連を `dot_pi`・`dot_config/{agents,pi-sandbox}`・`pib` / `pib-shell` / `pi-sandbox-runner` / `pi-t3`・共有の `pi-*` / `modify_pi*` / `modify_json*`・`scripts/agents` とし、検証関連は `test/`・`scripts/verify.py`・`scripts/lint_templates.py` とした。Claude は `dot_claude`・`modify_private_dot_claude.json`・共有の `claude-*`、導入は `.chezmoiscripts/` とした。

```sh
git ls-files home | wc -l
git ls-files home/dot_agents/skills | cut -d/ -f4 | sort | uniq -c | sort -nr | head -3
git ls-files home/.chezmoiscripts | cut -d/ -f3 | sort | uniq -c
git log c38fbd39 -250 --no-merges --format='%x1e%H' --name-only
```

## 依存の地図と所有権

| 境界 | 実際の依存 | 残す契約・分けられる責務 |
| --- | --- | --- |
| 判定 → 選択 → 適用 | `is-raspi`・`is-work`・`no-sudo` は apply 時の共有判定。`.chezmoiignore.tmpl` が配布を選び、`.chezmoiscripts/` の 5 区画と `before` / `after` とターゲット名の辞書順が実行順を担う。`lint_templates.py` もディレクトリ規則を読む | 判定を `init` 時の `[data]` に焼き付けない。選択は配布対象、適用は順序・権限・再実行の責務を持つ。OS 別の入口は残す |
| OS → agent の導入 | Unix は `005_python` が `modify_` 用 Python の入口を準備し、`125/225_mise` の後、`126/226_agent_cli` が同じ Unix テンプレートを呼ぶ。Windows はランチャー `py -3` と `309` の昇格処理、`313` / `314` の別経路 | Unix の共有は既にある。Windows の UAC・文字コード・パッケージ検出を Unix の抽象 API に押し込んでも依存が増える |
| agent の宣言 → 利用者設定 | MCP は宣言 TOML → `modify_json.py.tmpl` → Python 選択・一時 TOML → `generate.py`。`settings.json` は 241 行の `modify_pi_stock_settings.py.tmpl` に packages・子のモデル・prompt・検索・圧縮・shellPath・移行を収める | 出力の JSON を直接管理しない。ファイル単位で上書きすると利用者のキー・MCP の `enabled` / `exposure` を失う。変換は「repo が所有する値を渡す」「既存 JSON との合成」を分けられる |
| 検索 → 呼び出し元 | MCP の宣言、`settings` の子への `mcp:<server>`、子 2 役の prompt、plan mode の完全名、permission-system の設定、配布先と、予備の Claude の独立した写し | これらは実際に別の読み手を持つ。検索・取得の能力とサーバ名の対応を明示できるが、宣言にある全サーバを子や plan mode に渡してはいけない |
| コマンドの囲い → agent の設定 | 非 Linux の配布除外、Linux の `shellPath` と package 選択、`pib` / `pib-shell` / runner、`/sandbox` の切り替えが連鎖。ファイルツール自体は囲いの外なので permission-system も必要 | 「Linux で配る能力」と「いま囲いが有効か」を分ける。囲いとファイルツールの拒否集合は `test/test_pi_sandbox_runner.py` の照合が既にある。権限層を一方に寄せない |
| 共通スキルと予備ハーネス | `dot_agents/skills` は個々の CLI・資産を持てる。検索の核は `dot_config/agents/websearch` にあり、pi の MCP とスキル側の両方が利用。Claude は `lookPath "claude"` つきで設定を配り、MCP と 2 スキルは独立した写し | 検索の核とハーネスへの接続は既に別。Claude の予備系は単独で撤去できるようにし、汎用ハーネス生成器を復活させない |
| リポジトリの検証・移行 | `scripts/verify.py` が変更パスから試験・lint を選ぶ。`.chezmoiremove` と `clean_stale_source.py` が旧ターゲットと source 側の残骸の衝突に対応 | 依存の削減は、検証の除外や配布済み資産の無条件削除では測らない。移行・掃除には別の寿命と撤去条件がある |

`is-work` と「指定したユーザー名だけ」は同じではない。個人ユーザー名のまま `work=true` を渡すと、検索スキル `imozuru` は除外されるが、ユーザー名で制御する `.vscode-server/` の除外は出ない。この境界をまとめると `work` の上書きが他の手続きや個人専用ファイルの条件に波及する。

## 試作 1: 適用内容を動かさず、配布と判定を局所化する

隔離した source に、Git の `home/` の追跡ファイル名を空のファイルで再現し、ignore と共有テンプレートは実物を使用した。外部取得・削除定義・設定を読み込まないよう除き、キャッシュ・宛先・設定も一時ディレクトリに隔離。`claude` の有無は PATH にダミー実行ファイルを置くかで制御し、起動はしていない。`BW_SESSION` は空。これでパターン文字列の有無だけでなく、chezmoi が選んだ**ターゲット一覧**を比較した。

1. `git grep -l -F 'contains "microsoft"' -- home` で得た 5 ファイルの式を共有テンプレート `is-wsl` へ移す。`is-wsl` は `.chezmoi.os` が `linux` かつ kernel release を小文字にして `microsoft` を含むときだけ `true` を返す。元の条件式そのものを `eq (includeTemplate "is-wsl" .) "true"` に置き換えた。
2. ルートの ignore から `powerpoint-studio` と `conference-video` の成果物パターンを、対応する `dot_agents/skills/<名前>/.chezmoiignore` に相対パターンで移す。`.tmp` や `.venv` は source では `dot_` 属性を付けて合成し、残すファイルも一緒に置いた。
3. Ubuntu / WSL / Raspberry Pi / macOS / Windows の各入力で、個人用と制約のある機、sudo なしの指定の有無、`claude` の有無を組み合わせる。`execute-template` と `managed` を使い、現行と試作の標準出力をバイト単位で比較した。

```console
WSL: 5 files, 84 byte-identical render pairs
managed synthetic checks: first case includes 559 entries
Selection: 40 identical managed manifests; 28 patterns relocated
```

描画 84 組の内訳は、Linux 専用スクリプト 2 本を Linux 3 種 × 用途 2 種 × sudo 指定 2 種、残り 3 本を 5 種 × 2 × 2。manifest 40 組は 5 × 2 × 2 × 2。再現時は `chezmoi -c <空の設定.toml> -S <試作用source> -D <空の宛先> --cache <隔離先> --persistent-state <隔離先> --refresh-externals=never --skip-secrets --override-data '<合成したJSON>' managed --include=files,dirs,scripts,symlinks` を使う。描画は同じ設定で `managed` を `execute-template` に替え、対象テンプレートを標準入力へ渡す。

**意図と食い違った現行挙動**:

- **Windows かつ `is-work=true` でも**、`.config/agents/websearch/` と `core.py`、`mcp_server.py` が配布される。ルートの Windows 例外 `!.config/agents/websearch/` と `!…/**` が、後の除外に優先するため。[公式の規則](https://www.chezmoi.io/reference/special-files/chezmoiignore/)は “All excludes take priority over all includes.” と記載している。pi の MCP 登録とは別の層であり、試験で通信・登録・秘密の露出を観測したわけではない。
- 2 つの `!` 例外を `is-work` が偽の機だけに絞る別試作では、**40 ケース中 4 ケース（Windows + `is-work=true`）だけ**で、上記 3 パスが外れた。`agentcore_websearch_mcp.py` と個人用 Windows の配布には差がなかった。ignore は既に配ったものを削除しないので、既存機の扱いは別に決める。
- macOS でも未使用の `wslenv.sh` が配布される。`shellenv.sh.tmpl` の読込は WSL のみ。影響が小さく、判定の共通化とは分ける。

## 試作 2: agent の結合を、宣言・出力・反例で切り分ける

`home/.chezmoitemplates/` のコピーと架空の HOME・入力 JSON を使用。`chezmoi execute-template` で現行の `modify_mcp`・`modify_settings`・`modify_pi-plan-mode` を描画し、`python3 <描画したスクリプト>` の標準入出力を検査した。MCP は起動せず、宣言と生成 JSON の名前だけを比較した。

| 実験 | 確認した結果 |
| --- | --- |
| 現行の MCP 変換、個人用・制約のある機の 2 ケース | 子の既定のサーバは順に `websearch` と `agentcore-websearch` / `webfetch`。利用者のサーバ、宣言済みサーバの上書き、JSON の未知の値（日本語・大きな整数）を保持。2 回目の出力は同一 |
| 標準の `fromToml` と、`fromJson` → `setValueAtPath` で置換できるか | 宣言の TOML は読め、正常な JSON の大きな整数も保持。だが壊れた JSON は終了 1、配列 `[1,2]` はオブジェクトへ置換。現行 Python はどちらも変更せず終了 0。**Claude と同じ単純なテンプレートへの置換は同値でない** |
| 予備の Claude の写し | 2 件の stdio 定義は、描画した pi の `command` と `args` に一致。管理するキー・上書きの契約は異なる |
| 隔離した宣言だけで `id = "webfetch"` を改名 | pi の新規 MCP JSON には新しい ID が入り、子 2 役の `tools` と prompt、plan mode の列挙、Claude の写しには旧名が残った。宣言の妥当性検査だけではこの波及を捕まえられない |

標準機能の反例は、隔離した設定下で次の式を `chezmoi execute-template` に渡して再現できる。

```gotemplate
{{ `[1,2]` | fromJson | setValueAtPath "mcpServers.synthetic" (dict "command" "dummy") | toJson }}
```

出力: `{"mcpServers":{"synthetic":{"command":"dummy"}}}`。入力を `{"custom":` にすると `fromJson: unexpected EOF` で失敗する。標準機能そのものに欠陥があるのではなく、pi と Claude の契約をそろえようとすると挙動が変わるという反例。より複雑なテンプレートで再実装する価値は示せなかった。

## 候補の比較と着手順

| 優先度 | 候補 | 減らせる依存・費用 | 採用前の条件／見送り理由 |
| --- | --- | --- | --- |
| 1 | **Windows の例外を用途判定の下に置く** | ルール順の誤解をなくし、OS の例外が用途制約を覆わないようにする。変更範囲は試作で確定 | `managed` の個人・制約あり双方の回帰テストと Windows 実機。既存配備の削除は別判断 |
| 2 | **WSL 判定を共有し、成果物の ignore をスキルへ移す** | WSL 式の編集点 5 → 1。無関係なスキルの実行時パス 28 規則を中央から外す。ランタイムや依存ツールの追加なし | `is-wsl` を通る分岐を lint / 試験の入力に足す。スキル側への移動は `managed` だけでなく `chezmoi add` の拒否と検証ルールも確かめる。配布横断の規則はルートに残す |
| 3 | **MCP の名前の契約をテストで守り、照合対象だけを共通化** | まず両用途の宣言・子の参照・plan mode の対象名が食い違うと検出する。必要なら検索・取得の役割と ID の小さな表を渡し、`settings` に OS／用途を重ねない | 既定の名前だけを照合する。利用者の上書きは保つ。plan mode の完全名を一般化したり、MCP 全体を自動許可したりしない。Claude の写しを結合する設計は [ADR-0041](../adr/0041-claude-code-spare-harness-static-config.md) と別の判断が要る |
| 4 | **pi の MCP 変換を 1 用途の入出力に絞る** | `generate.py` の `TARGETS` は 1 件、共通 wrapper の呼び出し元も 1 件。先に汎用 dispatch をなくし、宣言のスキーマ検証と既存 JSON との合成は Python の小さな純粋関数として残せる | 暫定 Python の選び直し・UTF-8 と CRLF・壊れた JSON・エラー時に部分出力なしを同値にできるまで、子プロセスや一時ファイルは消さない。`.chezmoi.toml` の掃除 hook や別の `modify_` も Python を使うので、この変更だけで Python 前提は消えない |
| 5 | **settings の宣言を値にして、合成処理から分ける** | サブエージェントの既定モデルや圧縮は値であり、ユーザー値の尊重・旧値だけの移行とは責務が異なる。MCP 名の契約を先に整理すれば、引数を減らせる | 単に Python を複数ファイルへ移す案は見送り。移行コードは cp932 の変換が全 Windows 機で済んだときに削れる。共通マージ・DSL の追加より削除を優先 |
| 条件付き | Linux の囲いを「配布する能力」として束ねる | `shellPath`・package・配布の入口の整合が見通しやすくなる。囲いそのものは runner として既に分離 | 現在は単純な Linux 条件なので、汎用 capability registry は作らない。対応 OS や配備対象が増えるなら小さい契約の試験を先に追加。runtime・権限・`pib` の検査は別のまま |
| 見送り | 全 OS を 1 つのインストーラへ統合、Ansible 化、repo を分割、すべての ignore を include 化 | 見かけ上の行数は減っても、別ランタイム、実行順、データの転送、共通リリースの管理が増える | [既存の Ansible 試作](chezmoi/ansible-trial-121.md) は行数が減らず、初回の `--check` に前提不足。Win/Unix の差は本質的。責務ごとに標準機能で局所化する方が撤回しやすい |

順序の提案は、**不正な組み合わせを先に止め、分割の前後を比較できるようにしてから、依存の少ない境界を移す**こと。Windows の制約ありの設定と macOS/WSL の実行は実機では未確認。カーネル、UAC、`py -3`、run-once の成功履歴、移行済みファイル、認証状態、外部取得を含む初回導入の結果はこの検証からは分からない。

## この記録の検証

- agent・Windows 資産・chezmoi 描画・WSL・Raspberry Pi・検証の入口に絞った pytest は **1,188 件成功、1 件スキップ**。
- `mise run verify` は変更した文書 2 件の Markdown lint・秘密検出・索引整合に成功。`check_refs.py --baseline` の新規参照切れは **0 件**。
- `uv run pre-commit run --all-files` は変更していない `readme-writer` 評価素材の 4 件で失敗した（YAML の `truthy` 3 件、Ruff `RUF100` 1 件）。対象 4 ファイルと hook 設定に基準コミットからの差分はない。診断のために評価素材は変えていない。

設計上の制約は [プロジェクト構造](../spec/structure.md)、[設定の所有権](../spec/agent-config-generation.md)、[自作より既存機能を先に評価する方針](../adr/0031-evaluate-existing-extensions-first.md)、[旧カスタム基盤の撤去](../adr/0037-retire-custom-profile-and-other-harnesses.md) を参照。

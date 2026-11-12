# imozuru（調べものスキル）

知らない分野を、用語・人・場から引用と著者を芋づる式にたどり、**原文を要約せずに保存**して、要る主張ごとに原文の行番号を付けるスキル。
上流は [MaryCache/imozuru](https://github.com/MaryCache/imozuru)（MIT）で、`home/dot_agents/skills/imozuru/` に vendor して調整した。
検索は、使える検索ツールで行う（pi は自作の MCP `websearch` の `web_search` / `search_papers` / `fetch_page`。[Web 検索](web-search.md)）。スキル `web-search`（`websearch.py`）は 2026-11-09 に廃止した。検索役のサブエージェントは使わない。
入口を skill + CLI にした理由は 入口の選び方、拡張でなくスキルで足りる判断は [ADR-0031](../adr/0031-evaluate-existing-extensions-first.md)（旧 ADR-0016 を置き換え）。

- 取り込んだ版: 上流 `ecb82c71b611872a0f49e783eda3bec987c80d91`。取得物の sha256 と原本のハッシュは、スキル内の `references/upstream.md`
- 調査の日付・確認の範囲（コードは読んだだけで、実際の通信・実機の囲い（`pib`）では未確認）は [記録](../research/agents/imozuru-spec-notes.md)

## 配る範囲

**個人用（`is-work` でない機、つまり applejxd）だけ**に配る。個人用の検索の核・MCP と同じ理由（制約のある環境の機の検索語を AWS の外へ出さない）に、依存関係（秘匿チェックは核を借りる）を足した。

| 対象 | 条件 | 実装 |
| --- | --- | --- |
| スキル本体（`.agents/skills/imozuru/`） | `is-work` でない機 | `home/.chezmoiignore.tmpl` が `is-work` のとき除く |
| `fetch_youtube.py`（YouTube の字幕） | **ユーザー名が applejxd** | `home/.chezmoiignore.tmpl` の「個人 PC のみで導入」の節が、それ以外のユーザーには配らない |
| `yt-dlp` 本体 | ユーザー名が applejxd | `home/dot_config/mise/config.toml.tmpl`（以前から） |

検査は `test/test_chezmoi_templates.py`（Bedrock と `fetch_youtube.py` の除外）。既に配られたファイルは、除外しても自動では消えない（chezmoi の除外は「管理しない」で、削除ではない）。

## 構成

| 場所 | 役割 |
| --- | --- |
| `SKILL.md` | 流れ（0 周目で map.md を作り、周ごとにたどり、証拠で止める）、置き場、検索ツールの使い方、道具 |
| `scripts/chain.py` | OpenAlex で引用・被引用・著者をたどる（`find` / `refs` / `cites` / `author`）。上流のまま（+ 秘匿チェックだけ） |
| `scripts/fetch.py` | 原文の取得と保存（PDF は `pdftotext`、HTML は markdown、必要なら OCR）。YouTube は通さない |
| `scripts/fetch_youtube.py` | YouTube の字幕（`yt-dlp`）。**個人の PC だけ**に配る別スクリプト |
| `scripts/report.py` | 抜き書きを原文と機械で照合し、`report.html` を作る |
| `scripts/watch.py` | RSS / Atom の新着の見張り（`add` / `list` / `check`） |
| `scripts/imozuru_root.py`・`imozuru_net.py` | **この dotfiles 側の追加**（下の 3 節） |
| `test/test_imozuru.py` | 追加分の試験（通信なし） |

置き場は、作業ツリーの **`.tmp/research/<話題>/`**（上流の既定の `~/research/` から変えた。サンドボックスの外へ書けないため、`away-shift` の `.tmp/away-shift/` と同じ流儀）。

## 検索役を使わない理由

上流の「検索役」は、Web 検索できる軽いモデルのサブエージェントを 2 本並べる設計。このリポジトリでは使わない。検索と原文の読み取りは、使える検索ツール（MCP の `web_search` / `search_papers` / `fetch_page`）を使う。スクリプトは確認なしに実行できる（下の「許可規則」）。子エージェント（`pi-subagents` の `researcher`）が MCP の検索ツールを使えるかは環境次第（[子への検索 MCP の渡し方](mcp-servers.md#子のエージェントへの検索-mcp-の渡し方)）。保存の `fetch.py` は、結果を置き場へ書くので、子には任せず親が行う。既定は親が検索ツールを順に呼ぶ形で、広く浅い検索を子に任せるのは任意（SKILL.md の「検索役」の節）。検索語の秘匿チェックは検索の核（MCP が呼ぶ）が掛ける。

採らなかった案（専用の検索役 `searcher`）の理由は [記録](../research/agents/imozuru-spec-notes.md)。

## 書き込み先の制限

スクリプトを確認なしの許可に載せても、引数のパスで作業ツリーの別の場所へ書かれないようにするため、`imozuru_root.confine()` を足した（`fetch.py`・`report.py`・`watch.py` の最初に通す）。

- 根は、いまのディレクトリの `.tmp/research/`。**環境変数では変えられない**（上流の `IMOZURU_ROOT` 案は、根を固定できないので採らなかった）
- `.tmp` と `.tmp/research` が**シンボリックリンクなら拒否**する（リポジトリが外を指すリンクを持ち込める）
- 渡したパスを解決した先が根の外なら拒否する（`..`・リンクでの脱出）
- 渡したディレクトリの**中**に、シンボリックリンクが 1 つでもあれば拒否する（`watch/`・一時ファイル・`watch.tsv` が外を指していると、書き込みがリンク先へ届く）
- 通常ファイルの**ハードリンク**（リンク数 2 以上）も拒否する（追記・上書きが、置き場の外の同じ実体へ届く）
- 中のファイルが 20,000 件を超えるのは異常として拒否する

**残る限界**: 検査してから書くまでの間にリンクを差し替える競合（TOCTOU）は防げない。非敵対の同時実行しか想定しない。

## 接続の固定

上流の `fetch.py` / `watch.py` は、名前を引いて宛先を検査したあと、`urllib` がもう一度名前を引いて接続する（上流の docstring も限界として認めている）。引き先を変えられる名前（DNS rebinding）だと、内側の宛先へ届く。

`imozuru_net.py` が、**接続の直前に名前を 1 回だけ引き、全部が公開アドレスならその IP にだけ接続する**（TLS の SNI・証明書の検証・`Host` は元の名前。検索の核の `fetch_page` と同じ方式）。`fetch.py` と `watch.py` の `_OPENER` に差し込んだ。

- **プロキシ宛ての要求（HTTP のプロキシ・HTTPS の CONNECT）は固定しない**: プロキシが名前を引くので、stdlib の接続のまま。`no_proxy` などで**直接つなぐ宛先は、環境変数の有無に関わらず固定する**（要求ごとに `req.has_proxy()` / `_tunnel_host` で判定）
- 上流の宛先の検査（`url_problem`）は残る。VPN などで外の名前まで内側に引ける環境は、`IMOZURU_ALLOW_PRIVATE=1` で外せる（上流の仕様）
- **残る限界**: プロキシ経由の通信では、プロキシが後で別の IP に解決するのを、こちらでは固定できない。囲いの内側のプロキシが内側の宛先を拒むかは**未確認**。この限界は、下の「許可規則」にも関わる

## 外へ送る文字列の秘匿チェック

`imozuru_root.refuse_secrets()` が、`fetch.py` の URL、`watch.py add` の URL、`chain.py` の検索語を、外へ送る前に検査する（終了コード 2）。

- 検査は検索の核 `~/.config/agents/websearch/core.py` の `check_query`（秘密鍵・AWS のキー・GitHub のトークン・API キー・JWT・`password=…`・内部アドレス・長いトークン）を**そのまま借りる**（パターンを二重に持たない）。核が読めない機械のために、同じ内容の代替を内蔵する
- `watch.py` は、`add` で保存した URL（外部のページが示したもの）も、`check` で**送る直前に、名前を引く前に**検査する（ホスト名に秘密があると、DNS 問い合わせに載るため）
- **限界**: 未知の形式の秘密・個人データは防げない。機密を含む調べものは、そもそも使わない（SKILL.md の境界）。検索ツールの秘匿チェックと同じ水準

## YouTube

`yt-dlp` は**自分で通信し、宛先をこちらで確かめられない**（接続の固定が効かない）。制約のある環境の機で動画を取ることも避けたいので、次の 2 段にした。

1. `fetch.py` は YouTube の URL を**常に拒否**する（`yt-dlp` を起動せずに FAIL。メッセージで `fetch_youtube.py` を案内する）
2. `fetch_youtube.py`（`fetch.py` を YouTube 許可つきで呼ぶだけの別スクリプト）は、**個人の PC（applejxd）にだけ chezmoi が配る**。`yt-dlp` が自分で通信する

環境変数や印のファイルで切り替える案は採らなかった（環境変数は親プロセスから継承されると確認を迂回できる。印のファイルは実行時の検査が増える）。切り替えは**配布（`.chezmoiignore.tmpl`）だけ**で行う。そのほか、`yt-dlp` には `--ignore-config` を付け、外部コマンドの標準入力を遮断した（上流への追加）。

## 許可規則

撤去した `pis` では、スクリプトごとに許可（allow / ask）を決めていた（`[pi.skill_scripts.allow]`）。今の pi では、スクリプトごとの規則は無い。
`python3 ~/.agents/skills/imozuru/scripts/<名前>.py <引数>` は、permission-system が `python3` を読み取りと宣言しているため、**確認なしで通る**
（[permission-system の設定](agent-config-generation.md#permission-system-の設定)。環境変数の前置・リダイレクトは別の規則で扱う）。

- 通信を伴うもの（`fetch.py`・`watch.py add` / `check`・`fetch_youtube.py`・`chain.py`）も、確認なしで実行される。任意の URL へ通信し、結果を置き場へ保存する。
  守りは、スクリプト自身の検査（書き込み先の制限・接続の固定・秘匿チェック）と、囲い（`pib`）の許可リスト型の読み書きにある。
- `pib` の通信は開いている（ドメインの許可リストは無い）。通信を使わない作業は `pib --offline`（[pi-sandbox-runner](sandbox/pi-sandbox-runner.md)）。

## レビューの経緯

取り込む前に `review` の子（別系統のモデル）へ 3 回レビューさせた。各回の指摘と対応は [記録](../research/agents/imozuru-spec-notes.md)。
現行の契約（上の「書き込み先の制限」「接続の固定」「外へ送る文字列の秘匿チェック」「YouTube」「許可規則」）は、その対応を反映している。

## 上流との差分

上流への変更は最小にした（`chain.py` +6 行、`fetch.py` +21、`report.py` +6、`watch.py` +17 の見積もり。2026-11-12 に、`pis` 専用のプロキシ越しの取得の差分を外したので、実際の行数は上流の原本との差分で確かめる）。置換は `scripts/vendor/imozuru_patch.py` で、上流の原本に何度でも当て直せる（置換元が 1 つでなければ止まる）。編集ツールの後処理の整形が差分を膨らますので、置換は編集ツールでなくこのスクリプトで行う。**`fetch.py` / `watch.py` を編集ツールで直接直すと、整形が走って差分が 300 行規模になり、上流の文字列を壊す**（失敗談は [記録](../research/agents/imozuru-spec-notes.md)）。このファイルを直すときは、編集ツールを通さない置換スクリプトを `python3` で実行する。`pyproject.toml` の `extend-exclude` に、上流の 4 本を載せてある（整形・lint の対象外）。

**上流を更新する手順**: 新しい版を取得して原本と比べ（`references/upstream.md` の sha256）、差分を取り込んでから `imozuru_patch.py` を当て直し、`test/test_imozuru.py` と `review` で確かめる。

## 未確認・未決

- 実際の通信（実機の `fetch.py` / `watch.py` / `chain.py`）、TLS・プロキシ越しの動作
- 実機で、`python3 ~/.agents/skills/imozuru/scripts/*.py` が確認なしで通ること（上の「許可規則」）
- 実際のモデルが、SKILL.md の流れ（周・飽和・止めどき）を守るか。上流の主張（「通常の頼み方より良い」）は未検証
- Windows の素の `pi`（スキルは配るが、スクリプトは `uv run --no-project` に読み替える）
- 専用の検索役 `searcher`（[検索役を使わない理由](#検索役を使わない理由)）

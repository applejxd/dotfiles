# imozuru（調べものスキル）

知らない分野を、用語・人・場から引用と著者を芋づる式にたどり、**原文を要約せずに保存**して、要る主張ごとに原文の行番号を付けるスキル。
上流は [MaryCache/imozuru](https://github.com/MaryCache/imozuru)（MIT）で、`home/dot_claude/skills/imozuru/` に vendor して調整した。
検索は、すでにある [web-search](web-search.md) スキルの `websearch.py` を使う（検索役のサブエージェントは使わない）。
入口を skill + CLI にした理由は [入口の選び方](guard/pi-guard.md#入口の選び方)、拡張でなくスキルで足りる判断は [ADR-0016](../adr/0016-pi-extensions-own-first.md)。

- 取り込んだ版: 上流 `ecb82c71b611872a0f49e783eda3bec987c80d91`（2026-10-21）。取得物の sha256 と原本のハッシュは、スキル内の `references/upstream.md`
- 調査の日付: 2026-10-22。**コードは実行せずに読んだ**（上流の README・SKILL.md・スクリプト・試験名）。実際の通信・実機の `pis` では未確認

## 配る範囲

**個人用（`llm-provider` が `github-copilot`、つまり applejxd）だけ**に配る。`web-search` と同じ理由（制約のある環境の機の検索語を AWS の外へ出さない）に、依存関係を足した。

| 対象 | 条件 | 実装 |
| --- | --- | --- |
| スキル本体（`.claude/skills/imozuru/`） | `llm-provider` が `github-copilot` | `home/.chezmoiignore.tmpl` が Bedrock のとき除く |
| `fetch_youtube.py`（YouTube の字幕） | **ユーザー名が applejxd** | `home/.chezmoiignore.tmpl` の「個人 PC のみで導入」の節が、それ以外のユーザーには配らない |
| `yt-dlp` 本体 | ユーザー名が applejxd | `home/dot_config/mise/config.toml.tmpl`（以前から） |
| 許可規則（`[pi.skill_scripts.allow]`） | `llm-provider` が `github-copilot` | `common.toml.tmpl` |

検査は `test/test_chezmoi_templates.py`（Bedrock と `fetch_youtube.py` の除外）。既に配られたファイルは、除外しても自動では消えない（chezmoi の除外は「管理しない」で、削除ではない）。

## 構成

| 場所 | 役割 |
| --- | --- |
| `SKILL.md` | 流れ（0 周目で map.md を作り、周ごとにたどり、証拠で止める）、置き場、`websearch.py` の使い方、道具 |
| `scripts/chain.py` | OpenAlex で引用・被引用・著者をたどる（`find` / `refs` / `cites` / `author`）。上流のまま（+ 秘匿チェックだけ） |
| `scripts/fetch.py` | 原文の取得と保存（PDF は `pdftotext`、HTML は markdown、必要なら OCR）。YouTube は通さない |
| `scripts/fetch_youtube.py` | YouTube の字幕（`yt-dlp`）。**個人の PC だけ**に配る別スクリプト |
| `scripts/report.py` | 抜き書きを原文と機械で照合し、`report.html` を作る |
| `scripts/watch.py` | RSS / Atom の新着の見張り（`add` / `list` / `check`） |
| `scripts/imozuru_root.py`・`imozuru_net.py` | **この dotfiles 側の追加**（下の 3 節） |
| `test/test_imozuru.py` | 追加分の試験（通信なし） |

置き場は、作業ツリーの **`.tmp/research/<話題>/`**（上流の既定の `~/research/` から変えた。サンドボックスの外へ書けないため、`away-shift` の `.tmp/away-shift/` と同じ流儀）。

## 検索役を使わない理由

上流の「検索役」は、Web 検索できる軽いモデルのサブエージェントを 2 本並べる設計。このリポジトリの `guarded_task` の子（`explore` / `review`）は**読み取り専用だが、`websearch.py` の `search`・`papers`・`fetch` と `chain.py` は確認なしに実行できる**（2026-10-24 に `explore` の子で `websearch.py search` を実行して確かめた。許可は `[pi.skill_scripts.allow]` にあり、役割を問わず効く）。保存の `fetch.py` だけは確認が要るので、子には任せず親が行う。既定は親が `websearch.py` を順に呼ぶ形で、広く浅い検索を子に任せるのは任意（SKILL.md の「検索役」の節）。検索語の秘匿チェックは `websearch.py` が掛ける。

なお、`explore` / `review`（`explorer` 役）の子は、スキルのスクリプトの許可が全役割に効くため、`websearch.py` の `search` / `papers` を**確認なしで呼べる**（2026-10-21 の実測。使い捨ての試験）。専用の検索役 `searcher`（`bash` だけ・`search` / `papers` だけ・軽い階層）を足す案は、imozuru の試用のあとに判断する。

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

`imozuru_net.py` が、**接続の直前に名前を 1 回だけ引き、全部が公開アドレスならその IP にだけ接続する**（TLS の SNI・証明書の検証・`Host` は元の名前。`websearch.py` の `fetch` と同じ方式）。`fetch.py` と `watch.py` の `_OPENER` に差し込んだ。

- **プロキシ宛ての要求（HTTP のプロキシ・HTTPS の CONNECT）は固定しない**: プロキシが名前を引くので、stdlib の接続のまま。`no_proxy` などで**直接つなぐ宛先は、環境変数の有無に関わらず固定する**（要求ごとに `req.has_proxy()` / `_tunnel_host` で判定）
- 上流の宛先の検査（`url_problem`）は残る。VPN などで外の名前まで内側に引ける環境は、`IMOZURU_ALLOW_PRIVATE=1` で外せる（上流の仕様）
- **残る限界**: プロキシ経由の通信では、プロキシが後で別の IP に解決するのを、こちらでは固定できない。`pis` のサンドボックス（Fence）のプロキシが内側の宛先を拒むかは**未確認**。この限界のために、`fetch.py` と `watch.py` の `add` / `check` は確認なしの許可に載せていない（下の許可規則）
- **`pis` の内側のプロキシ越しの取得**（2026-10-25）: 内側は DNS が引けないので、`url_problem` の事前の名前解決で全 URL が失敗していた。`PIS_FETCH_VIA_PROXY=1`（`pis` が付ける）とループバックの
  `HTTPS_PROXY` が揃い、`no_proxy` に当たらない https の URL だけ、`url_problem` が名前を引かずにホスト名の形だけ見る（`imozuru_net.py` の
  `via_fetch_proxy` / `proxy_url_problem`。`websearch.py` と同じ規則で、正規表現の一致は `test_imozuru.py` が固定する）。仕組みと理由は
  [web-search、pis の内側のプロキシ越しの取得](web-search.md#pis-の内側のプロキシ越しの取得)。
  `urllib` が実際に使うプロキシと `no_proxy` を同じ関数で見るので、検査だけ省いて直接つなぐ食い違いは出ない。
  Fence のプロキシは、許可ドメインの外を 403 で拒む（`curl` で実測）。ただし「内側の宛先を拒む」こと自体は、許可リストに内部名が無いことに依存する
   実測（2026-10-25、`pis -p` の内側）: `fetch.py` は arxiv の abs を `OK`（終了コード 0）で保存でき、許可外のドメインは
   `FAIL … URLError: <urlopen error Tunnel connection failed: 403 Forbidden>`（終了コード 1）で止まった
- **残る限界**: プロキシ経由の通信では、プロキシが後で別の IP に解決するのを、こちらでは固定できない。この限界のために、`fetch.py` と `watch.py` の `add` / `check` は確認なしの許可に載せていない（下の許可規則）

## 外へ送る文字列の秘匿チェック

`imozuru_root.refuse_secrets()` が、`fetch.py` の URL、`watch.py add` の URL、`chain.py` の検索語を、外へ送る前に検査する（終了コード 2）。

- 検査は `web-search` の `check_query`（秘密鍵・AWS のキー・GitHub のトークン・API キー・JWT・`password=…`・内部アドレス・長いトークン）を**そのまま借りる**（パターンを二重に持たない）。`web-search` が読めない機械のために、同じ内容の代替を内蔵する
- `watch.py` は、`add` で保存した URL（外部のページが示したもの）も、`check` で**送る直前に、名前を引く前に**検査する（ホスト名に秘密があると、DNS 問い合わせに載るため）
- **限界**: 未知の形式の秘密・個人データは防げない。機密を含む調べものは、そもそも使わない（SKILL.md の境界）。`websearch.py` の `search` / `papers` の確認なしの許可と同じ水準

## YouTube

`yt-dlp` は**自分で通信し、宛先をこちらで確かめられない**（接続の固定が効かない）。制約のある環境の機で動画を取ることも避けたいので、次の 2 段にした。

1. `fetch.py` は YouTube の URL を**常に拒否**する（`yt-dlp` を起動せずに FAIL。メッセージで `fetch_youtube.py` を案内する）
2. `fetch_youtube.py`（`fetch.py` を YouTube 許可つきで呼ぶだけの別スクリプト）は、**個人の PC（applejxd）にだけ chezmoi が配る**。許可規則には載せないので、呼ぶたびに確認が出る

環境変数や印のファイルで切り替える案は採らなかった（環境変数は親プロセスから継承されると確認を迂回できる。印のファイルは実行時の検査が増える）。切り替えは**配布（`.chezmoiignore.tmpl`）だけ**で行う。そのほか、`yt-dlp` には `--ignore-config` を付け、外部コマンドの標準入力を遮断した（上流への追加）。

## `pis` の許可規則

`[pi.skill_scripts]`（`common.toml.tmpl`）に載せた（`llm-provider` が `github-copilot` のときだけ）。**`python3 ~/.claude/skills/imozuru/scripts/<名前>.py <引数>` の形だけ**が確認なしで通る。

| 形 | 判定 | 理由 |
| --- | --- | --- |
| `chain.py find` / `refs` / `cites` / `author` | allow | 公開 API（OpenAlex）へ検索語を送るだけ。書き込みなし。検索語は秘匿チェックを通す |
| `report.py <topic>`（`--check` も） | allow | 置き場の中を読み、`report.html` を置き場の中へ書くだけ。通信なし |
| `watch.py list` | allow | 置き場の中の `watch.tsv` を読むだけ |
| `fetch.py` | **ask** | 任意の URL へ通信し、結果を保存する。プロキシ経由では接続を固定できない（上の限界） |
| `watch.py add` / `check` | **ask** | 同じ（任意の feed の取得・保存を行う） |
| `fetch_youtube.py` | **ask** | `yt-dlp` が自分で通信する |
| 環境変数の前置・リダイレクト・別のスクリプト（`imozuru_root.py` など） | ask / deny | 既存の `[pi.skill_scripts]` の仕組み（[スキルのスクリプト](agent-config-generation.md#スキルのスクリプト)） |

検査は `test/agents/test_decide.py::test_imozuru_scripts_allow_only_the_confined_or_read_only_forms`。

**`fetch.py` を確認なしにする条件**（満たしたら載せる）: `pis` のサンドボックス（Fence）のプロキシが内側の宛先を拒むことを確かめる。または、プロキシ宛ての接続でも固定できる実装にする。それまでは、確認を毎回出す。
なお、`pis` の既定のサンドボックスは**ドメイン単位の許可リスト**（`allowedDomains`）で通信を絞るので、任意のドメインの原文を取るには、許可リストを足すか `pis --no-sandbox` が要る（[pi のガード](guard/pi-guard.md#サンドボックス)）。この点は実機で未確認。

## レビューの経緯

`review` の子（別系統のモデル。読み取りと `git` の読み取りだけ）に、取り込む前に 3 回レビューさせた（2026-10-22。1 回約 0.2〜0.4 ドル）。最初の 1 回は展開前の取得物しか無く、読めなかった。

| 回 | 見つかったこと | 対応 |
| --- | --- | --- |
| 2 | **BLOCKER**: `confine()` が渡したディレクトリしか見ず、中の子パスのシンボリックリンク経由で外へ書ける / DNS の検査後に再接続するので DNS rebinding が効く。**MAJOR**: 送る URL・題名・著者名に秘匿チェックが無い / `yt-dlp` の設定・標準入力 | リンク走査・根の固定・`imozuru_net.py`・`refuse_secrets()`・`--ignore-config` と標準入力の遮断 |
| 3 | **BLOCKER**: プロキシ環境変数があるだけで直接接続も固定を失う / ハードリンクが `confine()` を通る。**MAJOR**: YouTube（`yt-dlp`）は固定を通らない / 代替の秘匿検査が弱く、feed URL は送る直前に検査されない | 要求ごとのプロキシ判定・ハードリンクの拒否・YouTube の分離・代替の補強・feed URL の検査 |
| 4 | **BLOCKER**: プロキシ経路は固定できない。**MAJOR**: YouTube の環境変数は継承で迂回できる / feed URL は名前を引いたあとに秘匿検査している | 環境変数をやめて `fetch_youtube.py` に分離・秘匿検査を先に移した。プロキシ経路は**許可に載せないことで対応**（修正は未着手） |

- レビューは、3 回とも私の暫定の結論に反対した（「`confine()` を足せば全部を許可に載せてよい」など）。依頼文は、`pi-guard.md` の「[review への依頼の書き方](guard/pi-guard.md#review-への依頼の書き方)」の型で書いた
- レビューの子は**コードも試験も実行できない**（判定で拒否される）。「53 件が通った」などの実行結果は、親が実行した値で、子は再検証していない
- 問題なしとされた点: `fetch.py` の `<name>`（単一のファイル名）の検査、`report.py` の引用元の検査、外部コマンドを引数リストで起動していること

## 上流との差分

上流への変更は最小にした（`chain.py` +6 行、`fetch.py` +21、`report.py` +6、`watch.py` +17。`fetch.py` と `watch.py` の +4 行はプロキシ越しの取得）。置換は `scripts/vendor/imozuru_patch.py` で、上流の原本に何度でも当て直せる（置換元が 1 つでなければ止まる）。編集ツールの後処理の整形が差分を膨らますので、置換は編集ツールでなくこのスクリプトで行う。**`fetch.py` / `watch.py` を編集ツールで直接直すと、整形が走って差分が 300 行規模になり、上流の文字列を壊す**（2026-10-25 に実際に起きた）。このファイルを直すときは、編集ツールを通さない置換スクリプトを `python3` で実行する。`pyproject.toml` の `extend-exclude` に、上流の 4 本を載せてある（整形・lint の対象外）。

**上流を更新する手順**: 新しい版を取得して原本と比べ（`references/upstream.md` の sha256）、差分を取り込んでから `imozuru_patch.py` を当て直し、`test/test_imozuru.py` と `review` で確かめる。

## 未確認・未決

- 実際の通信（実機の `fetch.py` / `watch.py` / `chain.py`）、TLS・プロキシ越しの動作
- `pis` のサンドボックスの通信先の許可リストと、プロキシが内側の宛先を拒むか
- 実機の `pis` で、許可規則（allow / ask）が上の表のとおりに働くか（判定器の試験までは済み）
- 実際のモデルが、SKILL.md の流れ（周・飽和・止めどき）を守るか。上流の主張（「通常の頼み方より良い」）は未検証
- Windows の素の `pi`（スキルは配るが、`websearch.py` は `uv run --no-project` に読み替える）
- 専用の検索役 `searcher`（[検索役を使わない理由](#検索役を使わない理由)）

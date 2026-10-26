# Web 検索（`web-search` skill）

pi など、内蔵の検索ツールが無い AI CLI のための Web 検索・ページ取得・論文検索。**skill + CLI** の形で、標準ライブラリだけの Python
（`home/dot_claude/skills/web-search/scripts/websearch.py`）を、`python3`（Windows は `uv run --no-project`）で呼ぶ。
入口を skill + CLI にした理由と、MCP・拡張との比較は [入口の選び方](guard/pi-extensions.md#入口の選び方)、方針は
[ADR-0016](../adr/0016-pi-extensions-own-first.md)。

## 配る範囲

**個人用（`is-work` でない機、つまり `applejxd`）だけに配る。**（切り替えの経緯は [記録](../research/agents/web-search-spec-notes.md)） 制約のある環境用（Bedrock）は、検索を
[AgentCore Web Search の MCP](mcp-servers.md#mcp-サーバ)に一本化する（制約のある環境の機のクエリを AWS の外の検索へ出さず、手段が 2 つになってモデルが迷うのを避ける）。

- skill の配布: `home/.chezmoiignore.tmpl` が、`is-work` のとき `.claude/skills/web-search/` を除く
- `pis` の許可（`[pi.skill_scripts]`）: `common.toml.tmpl` が、`github-copilot` のときだけ出す
- 鍵ファイルの作成（441 / 349）: `applejxd` の機械だけ
- 判定は `is-work`（[会社 PC の判定](agent-model-assignment.md#会社-pc-の判定)が正本）。検査は `test/test_chezmoi_templates.py` と、OpenCode 向けの規則を見る `test/agents/test_opencode_external_read.py`（OpenCode 専用。撤去予定。CHG-0020 段 6 は保留中）
- 既に配られたファイルは、除外しても自動では消えない（chezmoi の除外は「管理しない」で、削除ではない）

## 構成

| 場所 | 役割 |
| --- | --- |
| `home/dot_claude/skills/web-search/SKILL.md` | 名前と説明だけが常駐し、本文は必要時に読まれる。pi は `[pi.settings] skills = ["~/.claude/skills"]` で拾う |
| `home/dot_claude/skills/web-search/scripts/websearch.py` | CLI の本体。`search` / `fetch` / `papers` / `status` |
| `test/test_websearch.py` | 通信なしの試験（偽の HTTP・偽の名前解決） |

```bash
python3 ~/.claude/skills/web-search/scripts/websearch.py search "クエリ" [-n 8] [--json] [--no-cache]
… fetch "https://…" [--max-chars 20000]
… papers "クエリ" [-n 8] [--from-year 2024]
… status
```

## 検索の鎖

`Brave → Exa → Tavily → DuckDuckGo`。上から順に試し、最初に結果を返したものを使う。

| プロバイダ | 呼び方 | 鍵 | 備考 |
| --- | --- | --- | --- |
| Brave | `GET /res/v1/web/search`（`X-Subscription-Token`） | 要 | 文字列（版・エラー文・設定名）を手がかりにした検索向き |
| Exa | `POST /search`（`x-api-key`、`contents.highlights`） | 要 | 意味検索 |
| Tavily | `POST /search`（`Authorization: Bearer`、`search_depth: basic`） | 要 | |
| DuckDuckGo | HTML 版の検索フォームへ `POST` | 不要 | 最後の砦。`GET` は bot の確認（HTTP 202）になりやすいので `POST` を使う（実測は [記録](../research/agents/web-search-spec-notes.md)）。ブラウザの UA は偽装しない |
| OpenAlex | `GET /works`（`search=`、`api_key` は任意） | 任意 | **鎖に入れない。** `papers` の専用。論文のメタデータで、一般の Web 検索の代替にならない |

順位の根拠と各社の無料枠は[記録](../research/agents/web-search-spec-notes.md)にある。**品質・鮮度の優劣は未実測**なので、固定順で始め、実際のクエリで比べて入れ替える。

### 次へ回す条件

| 状況 | 動作 |
| --- | --- |
| 鍵が無い | 呼ばずに次へ（`no-key`） |
| 429 | `Retry-After` が 2 秒以内なら 1 回だけ待って再試行。それ以外は次へ |
| 5xx・タイムアウト・通信エラー | 次へ |
| 401 / 403 | 次へ。そのプロバイダを 1 時間休止 |
| 402（容量切れ） | 次へ。そのプロバイダを 24 時間休止（`state.json`。毎回試さない） |
| 結果が 0 件 | 一度だけ次へ回す。2 つ目も空なら、空のまま返す |
| その他の 4xx（入力エラー） | **次へ回さず**、止める（同じ不正なクエリを全社へ流さない） |
| 全て失敗 | 終了コード 3。`[経過]` に各プロバイダの結果を出す |

## 鍵

環境変数（`BRAVE_API_KEY` / `EXA_API_KEY` / `TAVILY_API_KEY` / `OPENALEX_API_KEY`）→ `~/.config/agents/websearch-keys.json` →
`bw get password websearch-<名前>`（`BW_SESSION` があるときだけ）→ 無ければそのプロバイダを飛ばす。

- Bitwarden の項目は **Login 種別**、項目名は `websearch-brave` / `websearch-exa` / `websearch-tavily` / `websearch-openalex`、鍵は **Password 欄**
- 鍵は出力・例外・ログに出さない（`status` は有無だけ、`--json` にも入れない。試験で確かめている）
- **鍵ファイルの作成**: `chezmoi apply` が、`applejxd` の機械で、`BW_SESSION` があるときだけ `websearch.py sync-keys` を呼ぶ
  （`400_unix/run_after_441_websearch_keys.sh.tmpl`、`300_windows/run_after_349_websearch_keys.ps1.tmpl`）。Bitwarden の各項目を `bw get password` で引き、
  `~/.config/agents/websearch-keys.json` に書く（POSIX は mode 600、Windows はプロファイルの ACL）。
  - **既にある値は残す**。取れた名前だけ足す（項目が無い名前は飛ばす。無ければファイルも作らない）。取り直すときは `DOTFILES_RESYNC_WEBSEARCH_KEYS=1`（`--force`）
  - `BW_SESSION`・`bw`・`uv` が無いときは何もせず 0 で終わる（`apply` を止めない・入力待ちにしない）。`chezmoi` のテンプレート関数 `bitwarden` は使わない
    （項目が無いと apply が止まり、`.chezmoiignore` の「一度だけ展開」の仕組みが Windows の `agents` 配下では使いにくいため）
  - `bw` は解決したパスで呼ぶ（Windows の npm 版は `bw.cmd`）。出力は ASCII の 1 行（鍵は出さない）
  - 実測は [記録](../research/agents/web-search-spec-notes.md)

### 鍵の取り直し（対話で使う）

鍵を変えたとき（Bitwarden の値を直したとき）は、1 つのコマンドで取り直せる。**`BW_SESSION` が無ければ `bw unlock` のマスターパスワードを求め、
取りに行く前に `bw sync` も行う**（Vault が未同期だと、追加・変更した項目が見えないため）。

```bash
mise run websearch:keys      # このリポジトリで。= sync-keys --force --unlock
python3 ~/.claude/skills/web-search/scripts/websearch.py sync-keys --force --unlock   # どこからでも (Windows は uv run --no-project)
```

- `--unlock` は対話で使う。`chezmoi apply` の呼び出し（441 / 349）は付けない（`BW_SESSION` が無ければ飛ばし、入力待ちにしない）。Windows では端末の判定が当てにならない
  （`NUL` を端末と見なす）ので、自動判定ではなく明示のフラグにした
- 鍵が全部ある（`--force` なし）ときは、`bw` を呼ばず、同期もしない
- PowerShell では `変数=値 コマンド` の書き方ができない（`$env:変数 = '値'; コマンド`）。`DOTFILES_RESYNC_WEBSEARCH_KEYS=1 chezmoi apply` を使うなら、この書き方にする。上のコマンドなら環境変数は要らない
- 鍵の確認: `search "クエリ" --provider exa`（鎖を使わず、そのプロバイダだけで検索する。キャッシュしない。`brave` / `exa` / `tavily` / `duckduckgo`）

## 安全策

| 対象 | 内容 |
| --- | --- |
| クエリ | 秘密鍵・AWS のキー・GitHub のトークン・API キー・JWT・`password = …` の代入・内部アドレス（`10.*`、`192.168.*`、`*.internal` など）・長いトークンらしき文字列（40 文字以上の英数字の列。**URL の中でだけ**、`/` で区切った各パスの区切りが「語を `-` `_` でつないだだけ」なら、長さの数えから除く。「語」は英字だけ（20 文字まで、大文字も可）、数字（8 桁まで）、短い英小文字と数字の混在（`z3`、末尾の `2ea0` など 6 文字まで、最大 2 つ）。区切りが 4 部分以上なら英字だけの語が 3 つ以上、あるいは 3 部分以下なら混在なし・30 文字以下。大文字・小文字・数字が混ざるトークン・`=` を含む値・16 進の群をつないだ値・URL の外の語をつないだパスフレーズには当たらない（引き続き止める）。**限界**: URL の中の、語をつないだ長いパスフレーズは通る。[CHG-0032](../change/0032-guard-url-false-positive.md)）を含むと、**外部へ送らず**止める（終了コード 2）。フォールバックで同じクエリを送る相手が増えるため |
| 結果 | 先頭に「信頼できない外部の内容」の注意を付ける。スニペットは 300 文字、取得本文は 20,000 文字（`--max-chars`）で打ち切る |
| `fetch` | `http` / `https` の 80・443 だけ。名前を解決した**全ての IP**が公開アドレスでなければ止める（`127.0.0.1`、`10.*`、`169.254.169.254`、`::1`、IPv4 マップの IPv6 など）。認証情報つき URL・`file:` は止める。リダイレクトは 5 回まで、**毎回**検証する。接続は検証した IP に固定し、`Host` と SNI は元の名前（DNS の再解決で差し替えられない）。本文は 2 MB、`text/*` と JSON・XML だけ（PDF などは止める） |
| キャッシュ | `~/.cache/websearch/`（Windows は `%LOCALAPPDATA%\websearch`）に、クエリ単位で 1 時間。休止の状態は `state.json`。結果だけを置き、鍵は置かない |
| 重複 | URL を正規化（`utm_*`・`gclid` などのトラッキング・フラグメント・末尾の `/` を除く）して重複を除く |

## 実測（2026-10-12、Windows 11、鍵なしで実行）

実測（鍵なし・実際の鍵での確認、Vault 未同期の症状）は [記録](../research/agents/web-search-spec-notes.md)に移した。
試験は `uv run --with pytest --no-project pytest test/test_websearch.py`。`sync-keys` は取りに行く前に `bw sync` する。

## `pis` の許可規則

`[pi.skill_scripts]`（`common.toml.tmpl`）に `websearch.py` を、サブコマンド `search` / `fetch` / `papers` / `status` に絞って載せた。
**`python3 ~/.claude/skills/web-search/scripts/websearch.py <サブコマンド> …` の形だけ**が確認なしで通る。判定器（`decide.py`）で確かめた結果:

| 形 | 判定 |
| --- | --- |
| `… search "クエリ"` / `fetch` / `papers` / `status` | allow |
| `… sync-keys`（`bw` を呼ぶ） | ask（載せない） |
| 引数に `$(…)`・バッククォート、`;` でつないだ別コマンド、`>` のリダイレクト、変数に入れた呼び方、別のスクリプト | ask |
| `… search x \| sh` | deny（パイプで実行する形） |

- 既存の `[pi.skill_scripts]` の仕組みを使う（runner は `python3`。`uv run --no-project` は、作業ツリーの `.python-version` の実行ファイルを起動するので runner に足さない）。
  そのため skill の呼び方は `python3 …`（Windows の素の pi は判定器が無く、`uv run --no-project` に替える）
- 外へ出るのはクエリだけで、秘匿チェックが止める。`fetch` の取得先は SSRF 対策で公開アドレスに限る
- 検査は `test/agents/test_decide.py::test_web_search_script_allows_only_its_read_only_subcommands`

## `pis` の内側のプロキシ越しの取得

**症状**: `pis` の内側で `fetch` が `取得を止めた: 名前を解決できない`（終了コード 2）になる。imozuru の `fetch.py` も
`ホストを引けない（Temporary failure in name resolution）` で全 URL が失敗する。

**実測**（`pis -p` の内側）は [記録](../research/agents/web-search-spec-notes.md)。内側は DNS を引けず、`HTTPS_PROXY=http://127.0.0.1:3128`（Fence のプロキシ）経由なら許可ドメインに届く。
**ドメインの許可はプロキシが強制している**。

**原因**: `fetch` は接続の前に自分で名前を引き、全ての IP が公開アドレスかを検査して、その IP に接続を固定する。
内側では名前を引けないので、プロキシに届く前に検査で落ちる。

**対処（プロキシモード）**: 次の**両方**が揃うときだけ、事前の名前解決を省いて、プロキシへ `CONNECT` して取る。

1. `PIS_FETCH_VIA_PROXY=1`（`pis` の `inner_env` だけが付ける。ホストの同名の値は落とす）
2. `HTTPS_PROXY`（または `https_proxy`）が `http://127.0.0.1:<port>` の形（ループバックだけ。認証情報つき・`socks5h` などは使わない）

境界の外（普通のシェル、`--no-sandbox`）では、フラグが無いので従来どおり（名前を引いて公開 IP に固定する）。
環境変数は境界の証明にならない（`PI_HARNESS_BOUNDARY` と同じく「期待」にすぎない）ので、既存のプロキシ設定だけでは有効にしない。

プロキシモードの規則:

| 項目 | 内容 |
| --- | --- |
| 対象 | **https の URL だけ**。http（と、リダイレクトで http に落ちた先）は従来の経路。中継は平文の HTTP を 403 にするため |
| ホスト名 | 小文字の ASCII で、ドットで区切った名前だけ。最後の部分は英字で始める（10進・16進・省略形の IPv4 を名前として通さない）。IP の直指定、`localhost`、`*.local` / `*.internal` / `*.lan` / `*.home.arpa` / `*.localhost` / `*.intranet` / `*.corp`、末尾のドット、`@`・`%`、非 ASCII は止める |
| 接続 | プロキシへ `CONNECT <ホスト>:443`。TLS は元のホスト名で証明書を検証する。検査・CONNECT・SNI に同じホスト名を使う |
| 残す検査 | 認証情報つき URL、ポート 443 のみ、リダイレクトは 5 回まで**毎回**同じ検査、本文 2 MB、`text/*` と JSON・XML のみ |
| 失敗の分類 | CONNECT が拒否されたら `取得を止めた: プロキシが接続を拒否した …`（終了コード 2。許可ドメインの外の可能性）。ページが 403 なら `HTTP 403`（終了コード 3） |

**防御の位置が移る**: 内部アドレスに解決される名前の防御は、ツール内の IP 検査から、プロキシの許可ドメインへ移る。
許可リストに内部名を足さない限り、内部の宛先へは届かない。

**未対応**: imozuru（`fetch.py` / `imozuru_net.py` / `watch.py`）は、同じ事前の名前解決で止まるので、未対応のまま。

**修正後の実測**（2026-10-25）は [記録](../research/agents/web-search-spec-notes.md)。許可外のドメインは `取得を止めた: プロキシが接続を拒否した …`（終了コード 2）。

検査は `test/test_websearch.py`（`fetch_proxy`、ホストの検査、名前を引かないこと、http の経路、リダイレクト、CONNECT の拒否）と
`test/agents/test_pi_boundary.py`（フラグを `inner_env` が付けること）。

## 未実装・未決

- プロバイダの順位の実測比較（Brave と Exa）
- 入力トークン・キャッシュヒットの実測（skill の説明だけが常駐するので小さい見込み）

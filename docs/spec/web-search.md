# Web 検索（`web-search` skill）

pi など、内蔵の検索ツールが無い AI CLI のための Web 検索・ページ取得・論文検索。**skill + CLI** の形で、標準ライブラリだけの Python
（`home/dot_claude/skills/web-search/scripts/websearch.py`）を、`python3`（Windows は `uv run --no-project`）で呼ぶ。
入口を skill + CLI にした理由と、MCP・拡張との比較は [入口の選び方](pi-guard.md#入口の選び方)、方針は
[ADR-0016](../adr/0016-pi-extensions-own-first.md)。

## 配る範囲

**私用（`llm-provider` が `github-copilot`、つまり `applejxd`）だけに配る。** 業務用（Bedrock）は、検索を
[AgentCore Web Search の MCP](agent-config-generation.md#mcp-サーバ)に一本化する（業務機のクエリを AWS の外の検索へ出さず、手段が 2 つになってモデルが迷うのを避ける）。

- skill の配布: `home/.chezmoiignore.tmpl` が、Bedrock のとき `.claude/skills/web-search/` を除く
- `pis` の許可（`[pi.skill_scripts]`）: `common.toml.tmpl` が、`github-copilot` のときだけ出す
- 鍵ファイルの作成（441 / 349）: `applejxd` の機械だけ
- 判定は `llm-provider`（`chezmoi.toml` の `[data] llm_provider` があればそれを優先）。検査は `test/test_chezmoi_templates.py` と `test/agents/test_opencode_external_read.py`
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
| DuckDuckGo | HTML 版の検索フォームへ `POST` | 不要 | 最後の砦。`GET` は bot の確認（HTTP 202）になりやすかった（2026-10-12 実測）。ブラウザの UA は偽装しない |
| OpenAlex | `GET /works`（`search=`、`api_key` は任意） | 任意 | **鎖に入れない。** `papers` の専用。論文のメタデータで、一般の Web 検索の代替にならない |

順位の根拠と、各社の無料枠（2026-10-11 に各社のページで確認）は、設計の相談の記録による: Brave は月 $5 の無料クレジット（約 1,000 件）、Exa は月 $10
（約 2,500 件）、Tavily は月 1,000 クレジット。**品質・鮮度の優劣は未実測**なので、固定順で始め、実際のクエリで比べて入れ替える。

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
  - 実測: Windows で、偽の `bw.cmd` で追加・維持・取り直しを確認し、実際の Bitwarden でも 4 件が取れた（2026-10-12）

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
| クエリ | 秘密鍵・AWS のキー・GitHub のトークン・API キー・JWT・`password = …` の代入・内部アドレス（`10.*`、`192.168.*`、`*.internal` など）・長いトークンらしき文字列を含むと、**外部へ送らず**止める（終了コード 2）。フォールバックで同じクエリを送る相手が増えるため |
| 結果 | 先頭に「信頼できない外部の内容」の注意を付ける。スニペットは 300 文字、取得本文は 20,000 文字（`--max-chars`）で打ち切る |
| `fetch` | `http` / `https` の 80・443 だけ。名前を解決した**全ての IP**が公開アドレスでなければ止める（`127.0.0.1`、`10.*`、`169.254.169.254`、`::1`、IPv4 マップの IPv6 など）。認証情報つき URL・`file:` は止める。リダイレクトは 5 回まで、**毎回**検証する。接続は検証した IP に固定し、`Host` と SNI は元の名前（DNS の再解決で差し替えられない）。本文は 2 MB、`text/*` と JSON・XML だけ（PDF などは止める） |
| キャッシュ | `~/.cache/websearch/`（Windows は `%LOCALAPPDATA%\websearch`）に、クエリ単位で 1 時間。休止の状態は `state.json`。結果だけを置き、鍵は置かない |
| 重複 | URL を正規化（`utm_*`・`gclid` などのトラッキング・フラグメント・末尾の `/` を除く）して重複を除く |

## 実測（2026-10-12、Windows 11、鍵なしで実行）

- `fetch https://example.com` は成功（固定した IP への TLS 接続）。`http://localhost/`・`http://169.254.169.254/` は実際の名前解決で止まった（終了コード 2）
- `search`: 鍵がないので Brave・Exa・Tavily は飛ばされ、DuckDuckGo が答えた（関連する Microsoft Learn のページが出た）。同じクエリの 2 回目はキャッシュ（`(cache)`）
- `papers`: 鍵なしで OpenAlex が答えた
- 試験は 49 件（`uv run --with pytest --no-project pytest test/test_websearch.py`）
- **実際の鍵での確認（2026-10-12）**: `apply` が Bitwarden の 4 項目から鍵ファイルを作り（`added=['brave','exa','tavily','openalex']`）、
  **Brave・Exa・Tavily・DuckDuckGo・OpenAlex の全てが実際の API で結果を返した**（鎖の先頭は Brave）。最初は Exa が HTTP 401（`INVALID_API_KEY`）で、
  Bitwarden の項目の値（25 文字）が違っていた。値を直して取り直したら通った（36 文字）。401 は「auth」として次へ回り、そのプロバイダは 1 時間休止する
- `fetch` は実際の文書サイト（`https://pi.dev/docs/latest/codemode` など）で動き、`search` の結果から公式の URL の形を見つけられた
- **`added=none missing=[…]` になるときは、Vault が未同期**（実機で、アンロック済みでも項目が見えず、`bw sync` のあとに取れた）。`sync-keys` は取りに行く前に `bw sync` する

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

## 未実装・未決

- プロバイダの順位の実測比較（Brave と Exa）
- 入力トークン・キャッシュヒットの実測（skill の説明だけが常駐するので小さい見込み）

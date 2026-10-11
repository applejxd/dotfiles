# Web 検索（`web-search` skill）

pi など、内蔵の検索ツールが無い AI CLI のための Web 検索・ページ取得・論文検索。**skill + CLI** の形で、標準ライブラリだけの Python
（`home/dot_claude/skills/web-search/scripts/websearch.py`）を、`uv run --no-project` で呼ぶ。
入口を skill + CLI にした理由と、MCP・拡張との比較は [入口の選び方](pi-harness.md#入口の選び方)、方針は
[ADR-0016](../adr/0016-pi-extensions-own-first.md)。

## 構成

| 場所 | 役割 |
| --- | --- |
| `home/dot_claude/skills/web-search/SKILL.md` | 名前と説明だけが常駐し、本文は必要時に読まれる。pi は `[pi.settings] skills = ["~/.claude/skills"]` で拾う |
| `home/dot_claude/skills/web-search/scripts/websearch.py` | CLI の本体。`search` / `fetch` / `papers` / `status` |
| `test/test_websearch.py` | 通信なしの試験（偽の HTTP・偽の名前解決） |

```bash
uv run --no-project ~/.claude/skills/web-search/scripts/websearch.py search "クエリ" [-n 8] [--json] [--no-cache]
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
  - 実測: Windows で、偽の `bw.cmd` を使い、1 回目に 2 件追加、2 回目は取れていない 2 件だけを引き、`--force` で 4 件すべてを引き直すことを確認した。実際の Bitwarden は未確認

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
- **有料プロバイダ（Brave・Exa・Tavily）は、鍵が無く実機では未確認**。API の形は各社の公式ドキュメントで確認した（`curl` で取得）。応答の解析は、試験用の応答で確かめている

## 未実装・未決

- `pis` の許可規則（`uv run --no-project …/websearch.py` を、サブコマンドを絞って許可する）。それまでは確認になる
- プロバイダの順位の実測比較（Brave と Exa）
- 入力トークン・キャッシュヒットの実測（skill の説明だけが常駐するので小さい見込み）

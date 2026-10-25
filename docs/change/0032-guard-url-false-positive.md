# CHG-0032: 判定器と検索・取得の検査が URL を誤検出して調査を止める

- **状態**: In progress
- **更新日**: 2026-10-24
- **基準**: 判定器（`home/dot_config/pi/harness/judge/` と `home/dot_claude/hooks/lib/bashrules/`）、`imozuru` と `web-search` のスクリプト。コミット `0573900` 時点（実装は未デプロイ。`chezmoi apply` と `pis` の再起動後に実機で確かめる）

## 目的と非目的

**目的**: コマンドの引数に入る **URL を、ローカルのファイルのパスと誤認して拒否しない**。同じく、`imozuru` の `fetch.py` と `web-search` の `websearch.py` が、**単語をハイフンでつないだ長い URL（記事の題名をそのまま使ったもの）を、「トークンらしき文字列」と誤認して拒否しない**。調査（[CHG-0033](0033-sandbox-build-value-assessment.md)）で、必要な資料が取れなくなったため。

**非目的**:

- 本物のセンシティブなパス（`~/.ssh`・`.env` など）の検出を弱めない
- 外へ送る値に実際の秘密（API キー、JWT など）が入っていないかの検査を弱めない
- bypass の経路や、判定の結果（allow / ask / deny の区別）の仕組みを変えない

## 実施計画

| 段 | 解決したいこと | 内容 | 状態 |
| --- | --- | --- | --- |
| 段 1 | どの入力が、なぜ誤検出されるか分からない | 誤検出の入力を集めて再現し、判定器のどの規則が当たっているかを特定する | 完了（Python 版で再現。TS 版は正解データの一致で確認） |
| 段 2 | 直し方の候補が複数ある | 候補を評価し、`review` に見せて方式を決める | 完了（`review` 2 回） |
| 段 3 | 判定器の実装 | 選んだ方式を TS 版と Python 版の両方に入れ、正解データ 3 種を再生成し、試験を足す | 完了（全件検証の最終確認は「実装・検証」） |
| 段 4 | 取得・検索のスクリプトの検査 | `web-search` の `check_query` と、`imozuru` の内蔵の代替の「トークンらしき文字列」の検査を、URL の中のスラッグを許す形に直す | 完了 |
| 段 5 | 仕様に反映する | `docs/spec/guard/agent-command-policy.md` と `web-search.md` に、URL の扱いを書く | 完了 |
| 段 6 | 実機で確かめる | `chezmoi apply` の後、`pis` で、取れなかった記事（[記録 O1](../research/agents/openshell-comparison.md) の「届かなかったもの」）が取れることを確かめる | 未着手（CHG-0033 の段 P1 で行う） |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り / 消滅

## 現在地

**確かめたこと**（2026-10-23。再現は `.tmp/url_probe.py`、Python 版で実行）:

- 拒否した規則は `sensitive.py` の `sensitive_path_in_command`（`home/dot_claude/hooks/lib/bashrules/sensitive.py`。TS 版は `judge/sensitive.ts`）。引数の**末尾の名前**に `credential`・`secret` などの語（`_SENSITIVE_WORD_RE`）が含まれるかで判定する。URL の末尾の名前が、ファイルの名前として評価されていた
- 再現した入力（修正前）: `python3 fetch.py https://…/egress-proxy-api-credentials-ai-agent-sandboxes out.md` と `curl -sL https://…/secrets-management-guide` が、語のヒューリスティックで当たる。`python3 -c "print('https://…/secrets-management-guide')"` は、コード片を空白で分けた断片の末尾（`…guide')`）が当たり、インラインコードの規則（`rules_exec.py` の `check_interpreter_inline_code`）が拒否する。`curl https://example.com/.env` は、確実な証拠の側（`.env`）で当たる（リモートの URL なので誤検出）
- 本物のパス（`cat ~/.ssh/id_rsa`、`python3 -c "open('/home/u/.ssh/id_rsa')"`、`curl -T ~/.ssh/id_rsa https://…`、`curl file:///home/u/.ssh/id_rsa`）は、修正前から拒否されていた（`curl` は読み取り系の規則の対象外のため、`file://` は判定の関数では当たるが、フック全体では deny にならない。修正前後で同じ）
- `fetch.py` 側の拒否は、`websearch.py` の `LONG_TOKEN`（40 文字以上の英数字・`-`・`_`・`/`・`=`・`+` の列で、数字と英字を両方含むもの）が、`2026-09-10-learning-formal-methods-agent-policy` のような長いスラッグに当たるため

**直した内容**（未デプロイ）:

- 判定器: 各引数から、`http(s)://` で始まる部分（直前が `[\w/.~-]` でないもの。IPv6 `[::1]` を許し、空白・引用符・`)` `>` `,` `[` `]` の手前まで）を除いてから検査する。`./https://host/.ssh/id_rsa`、`~/https://host/.env`、`file://…`、`https://a,~/.ssh/id_rsa` は除かない。仕様は [agent-command-policy](../spec/guard/agent-command-policy.md) の「引数の URL はパスとして判定しない」
- 検査: 長いトークンの数えから、**URL の中の**、英小文字の語（20 文字まで）と数字（8 桁まで）だけを `-` `_` `/` でつないだ 4 部分以上の区切り（スラッグ）を除く。URL の外では従来どおり。仕様は [web-search](../spec/web-search.md)

## 未解決点

1. **既知の限界**: `--url=https://…` のように `=` の直後の URL も除くので、`=https:` という名前のディレクトリを作って保護対象を読む形は見逃す。事故防止の水準（[ADR-0012](../adr/0012-ocs-boundary-for-accidents.md)）では、そのディレクトリを作る必要があり、実質の穴ではないとして許容した（`review` の MINOR）
2. **既知の限界**: URL の中の、語をつないだ長い小文字のパスフレーズ（`correct-horse-battery-staple-…`）は、検査を通る。URL の外では止まる。許容の判断は、実際に URL へ秘密を埋める事故が起きにくいこと（`review` の MAJOR に対し、URL の中に限定する形で対処）
3. 実機（`chezmoi apply` 後の `pis`）で、取れなかった記事が取れるか。**再開条件**: 実機で確かめる（CHG-0033 の段 P1 の再調査は「完了（取れた範囲）」で、この条件から外した。残りは CHG-0033 の未解決点）
4. TS 版は、Python 版と同じ正規表現を `pyRegex` で写した。Unicode の `\w` の境界での食い違いは、正解データには無く、直接は試験していない

## 次の調査・実験

- 実機で、段 6（上の実施計画）を行う
- `.tmp/url_probe.py`（使い捨て）の入力のうち、価値のあるものがあれば、`test/agents/` に取り込む（現状は、同じ入力を `test_check_bash_sensitive.py` と正解データに入れた）

## 評価基準

**必須**:

1. 本物のセンシティブなパスの拒否が、現状と同じ（既存の正解データの拒否のケースがすべて同じ結果）
2. 上の誤検出の入力が通る（URL の末尾に `credential`・`secret` を含む記事、長い英単語のスラッグ）
3. TS 版と Python 版が、同じ入力に同じ結果を返す（正解データ 3 種で固定）
4. 実際のトークンの形（`sk-…`、`ghp_…`、JWT、AWS のキー、大文字混じり、`=` 付き、16 進）は、引き続き拒否される
5. `review` を経る（判定器に触るため）

**望ましい**: 誤検出の頻度を測る（ログがあれば）。

## 候補比較

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| A: `http(s)://` の部分を、パスの判定から除く（`file://` は除かない）。除く位置は、直前が `[\w/.~-]` でないものに限る | 実装が小さい。URL はローカルのパスではない。`review`（設計・実装の 2 回）の指摘で、ローカルのパスに混ざる URL 風の文字列は除かない形に絞った | `=` の直後の URL は除く（許容） | Unicode の境界の食い違い | **採用** | 実機 |
| B: URL の末尾の名前にだけ、語のヒューリスティックを適用しない（パスの glob 照合は URL にも適用） | 保護対象のディレクトリの名前が URL に含まれる場合は引き続き止まる | `curl https://example.com/.env` のような、確実な証拠の側の誤検出が残る | — | 見送り（A で足りる） | — |
| C: 取得専用のスクリプト（`fetch.py`・`websearch.py`）の引数だけ、除外する | 変更の範囲が狭い | `curl`・`wget` など、ほかの取得コマンドで同じ誤検出が出る | — | 見送り | — |
| D: URL を短縮して避ける | 判定器を変えない | 調査の質が下がる。短縮サービスへ送る内容が増える | — | 見送り | — |
| E（取得・検索の検査）: URL の中の、英小文字・数字だけのスラッグを、長さの数えから除く | スラッグを通し、実際のトークンの形は止まる。URL の中に限定し、各部分の長さに上限を付けた（`review` の MAJOR への対処） | URL の中の、語をつないだ小文字のパスフレーズは通る | — | **採用** | 実機 |
| E'（取得・検索の検査）: URL の内外を問わずスラッグを除く | 実装が小さい | 語をつないだパスフレーズが通る（`review` の MAJOR） | — | 見送り | — |

扱い: 未評価 / 検証中 / 有望 / 採用 / 保留 / 見送り

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `docs/spec/guard/agent-command-policy.md` の「センシティブパスの判定を 2 段に分ける」 | URL の扱いを書いていない → 「引数の URL はパスとして判定しない」の節を足した | 現在地の誤検出 | 適用済み |
| `docs/spec/web-search.md` の秘匿チェック | 長いトークンらしき文字列 → URL の中のスラッグを数えから除く、と書いた | 現在地 | 適用済み |

## 実装・検証

- 実装: `sensitive.py`（`_URL_RE`）、`sensitive.ts`（`URL_RE`）、`websearch.py`（`is_slug`・`check_query`）、`imozuru_root.py`（内蔵の代替 `_is_slug`・`secret_reason`）
- 試験: `test/agents/test_check_bash_sensitive.py`（URL の節）、`test/test_websearch.py`、`test/test_imozuru.py`。正解データ 3 種を再生成した（追加のみ。checks +160、decide +55、policy +89 行。既存の行の変更なし）
- `review` 2 回: 設計（`./https://…` を消す MAJOR を取り入れ）と実装（スラッグの緩和が語をつないだパスフレーズを通す MAJOR を、URL の中に限定して取り入れ、`=https://` の MINOR は許容）
- **途中で見つけた試験の弱点**: `test_review_child_may_read_a_revision_with_git` は、`git diff` の出力に「どの規則にも当たらない」が入ると失敗する（正解データの差分に、この文言が入るため）。出力全体ではなく、拒否の形（`tool error: guarded_bash: …`）だけを見る形に直した
- **不安定だった試験**: `test_pi_commit_confirm.py` の TUI の試験が、並列実行の負荷時に固定の `sleep` で落ちた（単体では通る。この案件の変更とは無関係）。画面を見ながら待つ形に直した

## 重要な更新

- **2026-10-23**: 起票。`imozuru` の調査（[記録 O1](../research/agents/openshell-comparison.md)）で、URL に `credential`・`secret` を含む記事と、長い英単語のスラッグの URL が取れなかった。利用者の指示で、判定器の誤検出の除去と再調査を、コンパクト化の後に再開する。
- **2026-10-23**: 段 1〜5 を実装。方式は「A（URL の部分を除く）と E（スラッグを長さの数えから除く）」。`review` の MAJOR 2 件（ローカルのパスに混ざる URL 風の文字列を消す、語をつないだパスフレーズを通す）を取り入れ、除く条件を絞った。
- **2026-10-24（追加の修正）**: 再調査で、dev.to の記事の URL（末尾の短い ID、`z3` のような短い英数字）と GitHub のパスの URL（`NVIDIA/product-security/tree/main/2026/5872`、gist の 32 桁のハッシュ）が、「長いトークン」の検査に当たった。`is_slug` を、`/` で区切った各パスの区切りに、語（英字 20 文字まで、大文字も可）・数字（8 桁まで）・短い英小文字と数字の混在（6 文字まで、最大 2 つ）を許す形に一般化した。URL の中に限る、4 部分以上は英字の語が 3 つ以上、という制約は維持した。試験に、実際の URL と、16 進の群をつないだ値の拒否を足した。確認の範囲: デプロイ済みの修正（1 回目）で、日付つきの長いスラッグの記事が取れた。一般化した修正は未デプロイで、リポジトリ内のスクリプトを直接実行して、dev.to の 2 本・gist・GitHub のパスの URL が取れることを確かめた（公式の Supported Agents のページは、取得時に HTTP 404 で、URL の検査とは無関係）。

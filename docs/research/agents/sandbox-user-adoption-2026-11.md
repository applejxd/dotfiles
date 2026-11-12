# AI コーディングエージェントの利用者は、どれくらい隔離して使っているか（声と指標。定性的）

- **日付**: 2026-11-06
- **目的**: ADR-0028 の判断材料。ハーネス（ツール側）の機能ではなく、**利用者の選択**の多さを、公開リポジトリの設定と、少数のスレッドから見る。
- **注意**: 検索結果・外部ページは信頼できない外部の内容。数は粗い目安で、母集団の代表ではない。

## 1. GitHub の公開リポジトリのコード検索（ファイル数。利用者個人の設定は見えない）

取得: `gh api -X GET search/code -f q=... --jq .total_count`（2026-11-06）。件数は概数で、ファイル数（利用者数ではない）。

| 検索 | 件数 | 読み方 |
| --- | ---: | --- |
| `filename:settings.json path:.claude` | 83,584 | Claude Code のプロジェクト設定（分母） |
| 上のうち `sandbox` と `enabled` を含む | 1,134 | 約 1.4%。語の一致なので上限の目安。個人設定（ホーム）は見えないので、実際の有効化は、これより多い |
| `filename:devcontainer.json claude-code` | 6,752 | devcontainer（Docker）で Claude Code を使う設定 |
| `filename:config.toml path:.codex` | 11,200 | Codex のプロジェクト設定（分母） |
| 上のうち `sandbox_mode` を明示 | 2,535（約 23%） | 残りの約 77% は既定（Codex は既定で workspace-write のサンドボックス有効） |
| `sandbox_mode` が `workspace-write` | 1,652 | 明示した中の約 65% |
| `sandbox_mode` が `danger-full-access` | 466 | 明示した中の約 18%（全体の約 4%） |
| `sandbox_mode` が `read-only` | 417 | 明示した中の約 16% |
| `dangerously-skip-permissions`（全ファイル） | 214,016 | 文書・スクリプト・alias の言及。使用者数ではなく、広く知られている目安 |

## 2. 声（Ask HN・Reddit・個人の発言）

- **Ask HN: How are you sandboxing coding agents?**（2025-12-27、46 点、コメント 32）<https://news.ycombinator.com/item?id=46400129>。コメントの語の出現（重複あり）: docker・container 10、YOLO・dangerously 7、VM 3、OS のサンドボックス（bubblewrap・seatbelt・landlock・firejail）3、別の機械・ユーザー 2、「サンドボックスしない・git で足りる」5。
- **「早期 2026 年に皆どう隔離しているか」の調査スレッド**（2026-02-27、コメント 20）<https://news.ycombinator.com/item?id=47185250>。docker・container 7、OS のサンドボックス 6、VM 4。投稿者の観察: 「最も多い答えは (a) コンテナ (b) YOLO」。
- **Simon Willison**（Pragmatic Summit, 2026-03。孫引き）: 「Mac 上で、ほぼ `--dangerously-skip-permissions` で動かしている。なぜそうすべきでないかの第一人者なのに。とても良いので」。2026-02 に X で「`--yolo` や `--dangerously-skip-permissions` で動かしているか」と利用者に尋ねた（結果の数は未確認）。<https://x.com/simonw/status/2022323970276786460>
- **Reddit**（スニペットのみ。本文と票数は取得できず）: r/ClaudeCode「How often do you use --dangerously-skip-permissions」に「YOLO mode は docker の中だけ」「`dc`＝dangerous claude の alias」。r/ChatGPTCoding「Do you use yolo mode...」に「ほぼ全部 VS Code の Dev Container か VM の中」。r/ClaudeAI「How are you sandboxing your coding agents?」に「built-in では `~/.ssh` が読めるので sandbox とは言えない」。
- **利用者を対象にした数値つきの調査**: 見つからなかった。Stack Overflow 2026 は AI の信頼と検証の方法の設問で、サンドボックスの設問は（検索の範囲では）確認できなかった。

## 2b. GPU を使う割合（コンテナ設定の目安。後から追記）

GitHub の公開リポジトリのコード検索（2026-11-06。ファイル数。概数）。

| 検索 | 件数 | 割合 |
| --- | ---: | ---: |
| `devcontainer.json`（分母） | 252,672 | |
| うち `"--gpus"` を含む | 3,724 | 約 1.5% |
| うち `nvidia` を含む | 3,100 | 約 1.2% |
| `docker-compose.yml`（分母） | 2,310,144 | |
| うち `driver: nvidia` を含む | 25,088 | 約 1.1% |

HN の Docker Sandboxes の公開スレッド（コメント 392 件）で、GPU に触れたのは 3 件。サンドボックス製品の GPU 対応は、Modal・Daytona・Northflank が対応、E2B・Vercel Sandbox・Cloudflare は非対応、Docker Sandboxes は専有 GPU の実験機能（販売元・比較記事の記述）。**GPU を使うコンテナ設定は、1〜3% 程度の少数派**。間に合わせの解が少ない理由になりうる（推測）。

## 3. 読み取り

- 利用者の選択は、大きく **(a) ホストでそのまま（YOLO）**、**(b) Docker・devcontainer**、が多数派。OS のサンドボックス・VM・別の機械は少数。
- Claude Code の内蔵サンドボックスは、プロジェクト設定で有効にしている例が少ない（上限でも 1〜2%）。Codex は既定でサンドボックス有効なので、既定のまま使う人が大半。明示して全開放（`danger-full-access`）にする人は明示した人の約 18%。
- 経験者でも、ホストで権限確認を外す例が公に語られている（YOLO の常用）。
- 専用の WSL ディストロを隔離に使う例は、今回の調査では測っていない（未調査）。

## 4. 限界

- 公開リポジトリのファイル数で、個人設定（`~/.claude`・`~/.codex`）と非公開のリポジトリは見えない。
- コード検索の件数は概数。語の一致で、実際の設定値とは限らない。
- スレッドは 20〜32 コメントの小さな標本で、投稿する人に偏る（隔離に関心のある人が多い）。
- ベンダー・ブログ（ハーネス側の主張）は、この集計に含めていない。

## 再現

- GitHub: 上の `gh api` を実行（認証が要る。1 分 10 回までの制限）。
- HN: Algolia の API（`https://hn.algolia.com/api/v1/items/<id>`）でコメントを取り、語の出現を数えた（簡単な正規表現。スクリプトは非公開メモ）。

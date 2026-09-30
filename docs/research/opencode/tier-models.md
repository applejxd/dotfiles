# OpenCode の階層（routine / worker）に当てるモデルと effort の計測

<!-- 現在の総合判断は docs/change/ の候補比較表が正本。
     ここは「いつ何を観測したか」を積む場所 -->

> **現行の仕様**: [階層](../../spec/agent-config-generation.md#階層)
>
> この記録の「記録 E3〜E6」は [commit / review エージェントの実機確認](commit-review-agents.md) の節を指す。

## 結論

- **worker（`fleet-worker`）**: 基本の課題 5 種類では、`claude-opus-5.5` と `claude-sonnet-5.5` の
  low / medium / high は 6 組とも 10/10 で合格した。難しめの課題 2 種類も 4/4 で合格し、
  **合格率に差は無かった**。所要時間は sonnet の low / medium がいちばん短く（中央値は基本の課題で
  19〜21 s、難しめの課題で 44〜48 s）、opus#medium（今の Copilot の既定）は 33 s / 72 s だった。
  `claude-haiku-4.5#high`（今の Bedrock の worker の近似）は、難しめの課題で 0/4、
  担当外の編集が 2 回あった。3〜4 倍遅く、Bedrock の単価で試算した費用も sonnet 5.5 より高い
- **routine（`commit`）**: `claude-sonnet-5.5` の low / medium / high は、3 組ともコミット 10/10
  （medium は対照の 5/5）、書式は 16 件すべてそろった（medium は 8 件）。所要時間の中央値は
  16 / 16 / 19 s で、**差は無い**
- 推奨（回数が少ないことを踏まえた目安）:

  | プロバイダ | routine | worker |
  | --- | --- | --- |
  | Copilot（予算無制限） | `claude-sonnet-5.5#medium`（今のまま。low でも差は無い） | `claude-sonnet-5.5#medium`（今は `claude-opus-5.5#medium`） |
  | Bedrock（有限） | `global.anthropic.claude-sonnet-5-5`（今のまま） | `global.anthropic.claude-sonnet-5-5`（今は `claude-haiku-4-5`） |

- deep（旧 heavy）は計測しなかった（[理由](#deep-を計測しなかった理由)）
- この結果で、worker を両プロバイダとも Sonnet 5.5 に切り替え、routine は変えなかった
  （[階層](../../spec/agent-config-generation.md#階層)）

## 記録 E1 — 2026-09-30

- **対象バージョン**: opencode v2.0.14
- **環境**: WSL2 Ubuntu / 基準コミット `0cdf263`。計測を始めた時点では、その変更は index にあった
  （別作業で分けてコミット中）。index を書き出して設定を生成し、計測中に `0cdf263` までコミット
  された。`common.toml`・`generate.py`・guide plugin・commit スキルは `0cdf263` と同じ内容

### 問い

階層の名前を用途に改める（`routine` / `worker` / `deep` / `second_opinion` / `default`）のに合わせ、
次を決める。

- worker（`/fleet` の作業役 `fleet-worker`）に、どのモデルと effort を当てるか。
  Copilot は予算無制限なので質と速さで、Bedrock は有限なので費用も見て決める
- routine（`commit`）の `claude-sonnet-5.5` の effort は、medium（記録 E6）から変える価値があるか

### 事前の予想

- worker: opus の方が合格率は高く、effort を上げるほど合格率は上がるが遅くなる。haiku は合格率が落ちる
- routine: effort を上げても書式とコミットは変わらず、遅くなるだけ

### 方法・条件

**共通**（[commit / review エージェントの実機確認](commit-review-agents.md)の記録 E4〜E6 の仕組みを流用。
置き場は `.tmp/opencode/tiers/`）

- 本体の index を `git ls-files -s` と `git cat-file` で `idx/` に書き出し、その `common.toml` から
  通常版の `opencode.json` を生成した（`gen.py`）。plugin は計装した guide plugin の複製だけにし、
  `ask_description` は外した。組ごとに、対象のエージェントの `model` だけを差し替えた
- 隔離: `env -u OPENCODE_CONFIG -u OPENCODE_CONFIG_CONTENT`、実行ごとの一時の `XDG_*` と `TMPDIR`、
  実 DB を読み取り専用で複製して資格情報だけ残した `OPENCODE_DB`、組ごとの `OPENCODE_CONFIG_DIR`、
  `opencode run --standalone --auto --format json`。`session.synthetic` は使っていない
- 計装: 記録 E3 の probe（`permission.evaluate` の前後と、ツールの実行の前後を記録する）。shell の
  `ask` は利用者が承認した扱いにし、危ない形（`rm` / `mv` / `git reset` など）は拒否した扱いにする。
  shell 以外の `ask` は、2 回目の実行から承認した扱いにした（下記の「止まった 3 回」を参照）
- 並行は 5 本。組と課題の順は乱数で混ぜ、組ごとの混み具合の差を減らした
- 費用: 「OpenCode」は複製した DB の `session_v2.cost`（OpenCode が単価表から出す参考値。Copilot の
  実際の課金とは別で、キャッシュの書き込みは 0 円の扱い）。「Bedrock の試算」は、同じトークン数に
  models.dev の Bedrock（`global.*`）の単価（USD / 100 万トークン。opus 4 / 20、sonnet 2 / 10、
  haiku 1 / 5、キャッシュの読み込み 0.2 / 0.2 / 0.1、書き込み 5 / 2.5 / 1.25。2026-09-30 取得）を掛けた
  もの。**Bedrock 上では試していない**。キャッシュの効き方が Copilot と同じだと仮定した推測値

worker の条件:

- 依頼の形: 親（`build`、`claude-opus-5.5`）に「次の作業を `fleet-worker` に 1 件だけ任せる。依頼文を
  一字も変えずに渡し、自分では読まない・編集しない・実行しない。報告をそのまま返す」と頼み、
  その下に依頼文を付けた。依頼文は `/fleet` の手順 4 が求める項目（目的・担当ファイル・触っては
  いけないファイル・完了条件・確認方法）をそろえた。`fleet-worker` の `system` と権限は
  `common.toml` の `[opencode.agents.fleet-worker]` のまま
  - `opencode run --agent fleet-worker` で直接起動する形は採らなかった。`/fleet` と同じく、親の
    `subagent` 呼び出しを通したかった
  - 親は 98 回すべてで `subagent` を 1 回呼んだだけだった。依頼文との差は、98 回中 4 回（すべて `ini`）で
    `"\n"` の引用符が `\"` にエスケープされたことだけだった（内容は同じ）
- 使い捨てのリポジトリ: Python のパッケージ `tk`（9 モジュール・既存テスト 9 件）。
  `.venv` は共有の venv（pytest 9.1.1）へのシンボリックリンク
- 課題（依頼文は `briefs/`、隠しテストは `hidden/`。どちらも作業役には見せない場所に置いた）:

  | 課題 | 種類 | 担当ファイル | 隠しテスト |
  | --- | --- | --- | --- |
  | `feature` | 小さな機能追加（`parse_duration`） | 2 | 30 件（正常・異常・型・往復） |
  | `bugfix` | 症状の報告から 3 関数のバグを直す | 2 | 16 件 |
  | `refactor` | 重複を helper 2 つへまとめる（出力は不変） | 1 | 52 件（元の実装との出力の一致・helper の契約・公開関数が helper を呼ぶか・公開関数に `ljust` が残っていないか） |
  | `tests` | 実装済みの `money.py` にテストを足す | 1（新規） | 変異 9 個をすべて落とせるか（元の実装では通ること） |
  | `multi` | 設定・クライアント・CLI・README にまたがる `timeout` の追加 | 6 | 18 件 |
  | `semver`（難しめ） | SemVer の解析・比較・範囲判定（prerelease の規則を含む） | 2（新規） | 78 件 |
  | `ini`（難しめ） | INI の読み込み（継続行・行内コメント・補間・行番号付きのエラー） | 2（新規） | 26 件 |

  - 隠しテストは、模範解答で全件が通り、元のリポジトリでは落ちることを確かめてから使った
  - `bugfix` には罠を置いた。`cli.py`（担当外）は `paginate()` の誤りを `page - 1` で打ち消している
    ので、直すと `tk list --page 2` がずれる。作業役がこれに気付いて報告するかも見た
- 合格の判定（`grade.py`）: 隠しテストが全件通る、かつ既存と追加のテストが全件通る、かつ
  担当外のファイルに変更が無い（`git status --porcelain --untracked-files=all` で、`.gitignore`
  の `__pycache__` などは除く）
- 組: `claude-opus-5.5` の low / medium / high、`claude-sonnet-5.5` の low / medium / high、
  `claude-haiku-4.5#high`。基本の課題 5 種類 × 2 回と、難しめの課題 2 種類 × 2 回。計 98 回
- 所要時間は、親の `subagent` 呼び出しの開始から終了まで。トークンと費用は `fleet-worker` の
  セッションの値。手数は `fleet-worker` の応答（assistant メッセージ）の数

routine の条件:

- 記録 E6 と同じ作業用リポジトリ 5 種類（`multi` / `new` / `delete` / `long` / `newdir`）と同じ依頼文。
  commit スキルは index の版（記録 E6 の版と同じ内容であることを `diff -r` で確かめた）
- 組: `claude-sonnet-5.5#low` と `#high` を 5 種類 × 2 回。対照として `#medium` を 5 種類 × 1 回
  （E6 から index までの設定の変化で結果が変わっていないかを見る）
- 数え方は記録 E4〜E6 と同じ（`analyze_commit.py`・`fmt.py`・`cost.py`）

```console
uv run -q --no-project --with pytest --with pyyaml python gen.py ws-medium fleet-worker github-copilot/claude-sonnet-5.5#medium
xargs -P 5 -L 1 bash job.sh < jobs.txt      # 95 本（worker 70・commit 25）。09:36〜10:23
xargs -P 5 -L 1 bash job.sh < jobs2.txt     # 31 本（難しめ 28・止まった 3 回のやり直し）。10:26〜10:39
python3 analyze_worker.py
python3 analyze_commit.py runs/r-rs-low-* ; python3 fmt.py runs/r-rs-low-* ; python3 cost.py runs/r-rs-low-*
```

### 結果

**worker**（1 組 14 回。所要時間は中央値、それ以外は 1 回あたりの平均。確認・誘導は 14 回の合計。
確認は shell の `ask`・shell 以外の `ask`・拒否した扱いの合計。静的な `deny` は全組 0 回）:

| 組 | 基本 5 種の合格 | 難しめ 2 種の合格 | 担当外の編集 | 所要時間（基本 / 難しめ） | 出力 + 推論トークン | キャッシュ読み込み | キャッシュ書き込み | 費用（OpenCode） | Bedrock の試算 | 確認 | 誘導 | 手数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| opus low | 10/10 | 4/4 | 0 | 27 s / 46 s | 3190 | 67729 | 16421 | $0.077 | $0.159 | 21 | 10 | 4.7 |
| opus medium | 10/10 | 4/4 | 0 | 33 s / 72 s | 4154 | 72352 | 17344 | $0.098 | $0.184 | 23 | 7 | 4.9 |
| opus high | 10/10 | 4/4 | 0 | 40 s / 112 s | 5650 | 105499 | 19165 | $0.134 | $0.230 | 29 | 12 | 6.4 |
| sonnet low | 10/10 | 4/4 | 0 | 19 s / 44 s | 3652 | 62349 | 16858 | $0.049 | $0.091 | 21 | 15 | 4.4 |
| sonnet medium | 10/10 | 4/4 | 0 | 21 s / 48 s | 4167 | 65537 | 17745 | $0.055 | $0.099 | 19 | 14 | 4.5 |
| sonnet high | 10/10 | 4/4 | 0 | 23 s / 84 s | 5859 | 72730 | 19083 | $0.073 | $0.121 | 19 | 9 | 4.6 |
| haiku 4.5 high | 9/10 | 0/4 | 2 | 75 s / 207 s | 10333 | 319660 | 27739 | $0.084 | $0.118 | 35 | 16 | 15.3 |

課題ごとの所要時間（s。1 回目 / 2 回目）:

| 組 | feature | bugfix | refactor | tests | multi | semver | ini |
| --- | --- | --- | --- | --- | --- | --- | --- |
| opus low | 24 / 28 | 26 / 19 | 27 / 29 | 14 / 15 | 32 / 35 | 68 / 49 | 37 / 43 |
| opus medium | 34 / 33 | 33 / 26 | 33 / 33 | 16 / 16 | 36 / 37 | 76 / 75 | 63 / 69 |
| opus high | 46 / 38 | 31 / 29 | 45 / 42 | 15 / 22 | 55 / 43 | 116 / 106 | 109 / 121 |
| sonnet low | 20 / 23 | 16 / 16 | 20 / 25 | 12 / 12 | 18 / 25 | 48 / 49 | 41 / 39 |
| sonnet medium | 28 / 21 | 19 / 21 | 26 / 21 | 14 / 14 | 19 / 23 | 62 / 52 | 44 / 43 |
| sonnet high | 34 / 29 | 19 / 20 | 24 / 22 | 14 / 16 | 33 / 24 | 95 / 92 | 74 / 75 |
| haiku 4.5 high | 82 / 72 | 78 / 84 | 53 / 49 | 51 / 47 | 86 / 96 | 144 / 182 | 232 / 261 |

- haiku の不合格 6 回の内訳:
  - `feature` 1 回: 隠しテストは全件通ったが、確かめ用の `verify_parse_duration.py` をリポジトリの
    直下に残した（担当外の編集）
  - `semver` 2 回: どちらも `">=1.2.3 ||"`（空の組）を ValueError にしなかった。うち 1 回は
    確かめ用の `test_verify.py` を直下に残した。これを消そうとした `rm` は、計装が拒否した扱いにした
  - `ini` 2 回: どちらも行内コメントの規則（`c = #c` → 空文字列、タブの後ろの `#`）を外した
- opus / sonnet の 84 回で、担当外の編集は 0 回だった。git で履歴やステージを変える操作
  （add / commit など）は全組 0 回（使ったのは `git status --short` と `git show` だけ）
- `bugfix` の罠（`cli.py` の打ち消し）に触れた報告は **14 回中 0 回**だった。`cli.py` を読んだり
  `paginate` の呼び出し元を grep したりした実行も 0 回だった
- 確認（shell の `ask`）165 回のうち 120 回は、依頼文の確認方法の `.venv/bin/python -m pytest -q` だった
  （パイプや連結を付けた形が 89 回、単独が 31 回）。`pytest` は allow に無いので、形によらず確認が出る。
  残り 45 回は `ls; ls src/tk tests; cat pyproject.toml` のような連結した読み取りなど。
  誘導 83 回は `cat` / `head` / `tail` が 53 回、`cd` が 21 回、その他 9 回で、どの組も同じ程度だった
- **止まった 3 回**: 1 回目の実行で、opus high の `refactor` 2 回と opus medium の `refactor` 1 回が、
  比較用の一時ファイルを作業ツリーの外（`$TMPDIR/opencode/`）へ `write` しようとした。これは
  `edit` の `ask` になる（`TMPDIR` が `~/.local/share/chezmoi` の下で、そこの `edit` は `ask`）。
  計装は shell の `ask` しか承認しないので、`--auto` の下で答える人がいないまま 1800 s の時間切れまで
  止まった（作業ツリーの変更は済んでいて、採点は 3 回とも合格）。計装を直してやり直すと、opus high の
  2 回はまた外へ `write` して確認が出た（承認した扱いで完了）。表は、やり直した回の値
- 作業ツリーの外への書き込みは、opus の `refactor` だけに出た。やり直した回と 2 回目を合わせた 4 回
  （medium 2・high 2）すべてで、元の `report.py` を `git show HEAD:src/tk/report.py > ../tmp/opencode/…`
  で外へ書き出して新旧の出力を比べた（shell の `ask`）。high の 2 回は、比較用のスクリプトも `write`
  ツールで外へ書いた（`external_directory` は allow、`edit` は `ask`）。sonnet と haiku では 0 回だった

**routine**:

| 組 | コミットまで進んだ実行 | コミット | Conventional Commits の件名 | 件名 72 文字以内 | `- Motivation:` / `- Change:` / `- Impact:` の 3 行 | `git commit` 以外の確認・誘導 | 所要時間の中央値 | 出力トークンの平均 | キャッシュ読み込みの平均 | 費用の平均（OpenCode） | Bedrock の試算 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| E6（medium、再掲） | 10/10 | 16 | 16 | 16 | 15 | 0 | 16 s | 962 | 121315 | $0.034 | — |
| low | 10/10 | 16 | 16 | 16 | 16 | 0 | 16 s | 853 | 109536 | $0.031 | $0.069 |
| medium（対照） | 5/5 | 8 | 8 | 8 | 8 | 0 | 16 s | 886 | 114887 | $0.032 | $0.072 |
| high | 10/10 | 16 | 16 | 16 | 16 | 0 | 19 s | 1176 | 126132 | $0.038 | $0.077 |

- `new` の個人メモは、どの組でもコミットに入らなかった（5 回とも未追跡のまま）
- `long` は 5 回とも、版上げ（`chore(release):`）と振る舞いの変更（`feat(core)!:` / `feat(calc)!:`）の
  2 つに分けた
- 言語は、low が英語 14 件・日本語 2 件、medium が英語 8 件、high が英語 9 件・日本語 7 件
- 推論トークンの平均は low 12・medium 29・high 80 で、どれも小さい

### 考察

- **worker の合格率は、opus と sonnet 5.5 の 6 組で差が無かった**（基本の課題は 60 回すべて、
  難しめの課題は 24 回すべて合格）。課題が 6 組にとって易しすぎ、上限に張り付いている可能性がある。
  「sonnet は opus と同じ質」とまでは言えず、「この程度の課題では差が出ない」にとどまる
- 速さは sonnet の low / medium が最も速く、opus#medium の約 2/3。effort を high にすると、
  opus / sonnet とも難しめの課題で 1.5〜2 倍遅くなり、合格率は上がらなかった
- opus の medium / high は、リファクタリングで元の実装と出力を突き合わせるために、作業ツリーの外へ
  ファイルを書く。確かめ方としては丁寧だが、実際の `/fleet` ではそのたびに利用者への確認になる
  （推測。TUI では確かめていない）。`write` ツールの確認は `--auto` でも答える人がいないと止まる
- haiku 4.5 は、易しい課題では通るが、仕様の細部（空の組・行内コメント）を落とし、確かめ用のファイルを
  担当外に残す。手数が 3 倍あり、キャッシュの読み込みが 5 倍になるので、単価が安くても
  Bedrock の試算は sonnet 5.5 の low / medium より高い（$0.118 と $0.091 / $0.099）。
  Bedrock の worker を haiku から sonnet 5.5 へ上げても、費用はむしろ下がる見込み（推測。
  キャッシュの効き方が Bedrock でも同じだと仮定している）
- 担当外への影響（`cli.py` の打ち消し）は、どの組も気付かなかった。worker の effort では補えず、
  親（取りまとめ役）の最後の差分の確認と検証（`/fleet` の手順 6）に頼ることになる
- routine は low / medium / high で、コミット・書式・確認のどれにも差が無かった。所要時間と費用は
  high がわずかに多い（19 s と 16 s、Bedrock の試算で $0.077 と $0.069）。記録 E6 の medium からは
  変えなくてよい。対照の medium は E6 と同じ結果で、E6 から index までの設定の変化の影響は見えなかった

### deep を計測しなかった理由

deep（旧 heavy）は「難しい判断」に当てる階層で、良し悪しを機械的に判定できる課題を作れない。
設計の判断や原因の切り分けは正解が 1 つに決まらず、隠しテストのような採点ができない。
worker の難しめの課題でも opus と sonnet の差が出なかったので、差を見るにはさらに難しい課題と
人手の評価が要る。今回は計測せず、今の割り当て（opus の上位の effort）を変える根拠も無い。

### 次の問い

- worker の課題を難しくすると（大きなコードベースでの変更・曖昧な仕様・長い手順）、opus と sonnet の
  差は出るか。未確認
- Bedrock の `global.anthropic.claude-sonnet-5-5` で同じ傾向か、キャッシュの効き方が同じか。未確認
  （この PC から Bedrock は使えない）。Bedrock の Sonnet 5.5 に `#medium` などの variant が
  付けられるかも未確認
- `fleet-worker` の `system` に「確かめ用のファイルは作業ツリーに残さない・外に書かない」
  「担当外の呼び出し元への影響を確かめて報告する」を足すと、haiku の担当外の編集、opus の外への
  書き込み、`cli.py` の見落としは減るか。未確認
- `pytest` の確認（worker の確認のほとんど）を減らすには、検証コマンドを allow に載せるか
  （任意コード実行になるので載せていない）。判断は未了

### 参照

- models.dev の単価（Bedrock の `global.anthropic.claude-*`、Copilot の `claude-*`）。2026-09-30 取得

出典: <https://models.dev/api.json>

## 追記 — 2026-09-30: 公開のベンチマークと割り当ての判断

上の計測では effort による差が出なかった。課題が易しく、どの組も上限に張り付いたためと考え、
公開の数字で effort とモデルの差の大きさを確かめた。どれも自己申告か集計サイトの転載で、
条件（ハーネス・試行回数）はそろっていない。

| 出典 | 内容 |
| --- | --- |
| Anthropic「Optimizing for cost and intelligence」 | Opus 5.5 は SWE-bench Pro の部分集合で medium（既定）92.8%、low 87.4%。調査・知識作業では medium と high の差は測れず、low でも 1〜3 ポイント減るだけ。検証できる出力なら low で回して失敗だけ high でやり直すと、合格率を保って費用が約半分 |
| Artificial Analysis（集計） | Fable 5.1 の SWE-bench は low 75.2% / medium 77.1% / high 79.1% / xhigh 80.7% / max 81.6%。Opus 5 は medium 74.3% / high 76.5% / xhigh 77% / max 78% |
| Anthropic の Sonnet 5.5 の発表（The New Stack 経由） | Terminal-Bench 4.0 で Sonnet 5.5 70.6%、Opus 5.5 66.4%。CursorBench で Opus 5.5 との差は約 2 ポイント。FrontierCode は Sonnet 5.5（2 番目に高い effort）52.1%、Opus 5.5 54.4%。「決まった答えの無い、長く判断を続ける仕事では Opus 5.5 のほうが明らかに強い」 |
| 論文（THOUGHTTERMINATOR・THINK-Bench・ACL 2026 Findings・NeurIPS 2025） | 易しい問題では考えすぎても精度が上がらず、予算を増やすほど効き目が小さくなる。考えすぎで正解が不正解に変わることもある |

### 判断

- effort の差は、難しいコーディングの課題で 1 段あたり 1〜3 ポイント、low から max で 6 ポイント前後。
  上の計測で差が出なかったのは、課題がその差を測れる難しさに届いていなかったため
- 割り当て（2026-09-30 に決定）: Copilot（使い放題）は `routine` / `worker` とも
  `claude-sonnet-5.5#medium`。Bedrock（予算が有限）は `routine` を `#low`、`worker` を `#medium`。
  Bedrock の Sonnet 5.5 に effort を付けられることは、利用者が確かめた（この PC からは未確認）

### 再考の候補: Bedrock の主エージェントを Opus 5.5 の low にする

公式の資料は「品質が足りなければ、上の段のモデルを low で試す」と勧め、上位モデルを低い effort で
使うほうが、仕事 1 件あたりの費用が安くなる例を挙げている（Opus 5.5 low は SWE-bench Pro の部分集合で
87.4%、正解 1 件あたり $0.12）。Bedrock の主エージェント（`default`）は費用の大半を使うので、効けば
影響が大きい。

採らなかった理由（2026-09-30）: Sonnet 5.5 と同じ条件で比べた数字が無い。主エージェントの
`default` に effort を付けられるかも確かめていない。利用者の判断で Sonnet 5.5 のままにし、
候補として残す。再考するなら、Bedrock の PC で実際の作業を Sonnet 5.5（既定）と
Opus 5.5 low で比べ、1 件あたりの費用と手戻りを数える

出典:

- <https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence>
- <https://platform.claude.com/docs/en/build-with-claude/effort>
- <https://renovateqr.com/tools/compare>（Artificial Analysis のデータ）
- <https://thenewstack.io/claude-sonnet-55-launch/>
- <https://arxiv.org/abs/2504.13367>、<https://arxiv.org/abs/2505.22113>、
  <https://aclanthology.org/2026.findings-acl.1199/>、
  <https://proceedings.neurips.cc/paper_files/paper/2025/hash/fc067ac218430c409d6f65403328f740-Abstract.html>

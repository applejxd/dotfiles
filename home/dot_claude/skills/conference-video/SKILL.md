---
name: conference-video
description: "研究のリポジトリ・論文から、3〜5 分の学会発表動画風の日本語解説動画を作る。動機と理論背景は Manim の動く映像で、結果は録画済みの実動作動画を貼り込み、VOICEVOX のナレーションと字幕を付けて video.mp4 に仕上げる。「学会動画を作って」「論文解説動画を作って」「発表動画を manim と音声合成で」「この研究の紹介動画」で使う。数学の定理・証明だけの解説、スライド資料(pptx)の作成、論文の全文翻訳、動画の公開・投稿、英語ナレーションには使わない。"
---

# conference-video

研究のリポジトリや論文から、学会発表動画風の解説動画を作る。
流れは 取材 → 台本 → 音声 → 描画 → 仕上げ → 確認。
土台は `vendor/manim-skill`(MIT、`vendor/UPSTREAM.md`)で、
音声は VOICEVOX に差し替えてある。

## 契約

- 成果物: `video.mp4`、`narration.txt`、`timestamps.json`、`script.py`、
  `subtitles.ass`、`description.txt`(クレジット入り)
- 保存先は作業ディレクトリの外のセッションフォルダ
  `${CONF_VIDEO_HOME:-$HOME/.conference-video}/<slug>/`(`<slug>` は
  kebab-case の短い題名)。利用者のリポジトリは読むだけで、書き込まない
- 既存の成果物を上書き・削除しない(`finish.py` は `--force` が無いと止まる)
- 結果の数値・動画は、論文・公式の動画・利用者が渡したものだけを使う。
  数値を作らない。各主張に出典(論文の節、ファイルと行)を付けて台本に
  メモする
- 利用者の承認を 2 回取る: 構成案(台本の前)と台本(音声合成・描画の前)。
  承認前に先へ進まない。取材では利用者への質問を多くしてよいが、
  読めば分かることは聞かない
- 確認・承認・修正は**確認サーバ**(`scripts/review_server.py`)の画面で取る。
  台本・読み・素材・動画を 1 画面で見て、その場で直して承認できる。承認は
  `approvals.json` に内容のハッシュつきで残るので、利用者が不在でも画面に残して
  待てる。質問ツール(`ask`)は短い選択式の質問だけに使い、承認には使わない
  (長く不在だと無視される)
- 公開用には VOICEVOX のクレジット(`VOICEVOX:<キャラクター名>`)を入れる。
  キャラクターごとの利用規約は利用者が確認する
- 外部から取得した画像・動画は、出典・ライセンス・状態を素材台帳
  (`assets.json`。`assets_ledger.py` の `add` / `set` / `rm`)に記録し、**画面の隣に出典を出す**(論文の図・公式動画は「引用」)。規則は
  `references/attribution.md`。公開用には「仮」の素材を使わない
- 利用者に確認を頼むファイル(`narration.txt`、`review.csv` など)は、
  **絶対パスで伝える**(「セッションフォルダ」とだけ言わない)。読み辞書(`yomi.json`)は手で編集せず、
  確認画面の「読み」タブか `yomi.py set` で直す(ADR-0003)
- `SKILL_DIR` はこの `SKILL.md` のあるフォルダ。以下のパスはそこからの相対

## 手順

### 0. 事前確認

```bash
python3 SKILL_DIR/scripts/preflight.py
```

NG があれば表示どおりに直す。VOICEVOX ENGINE は
`docker run --rm -d --name vv -p 127.0.0.1:50021:50021 voicevox/voicevox_engine:cpu-latest`。
Manim 用の環境は `uv sync`(`UV_PROJECT_ENVIRONMENT` で置き場所を指定。
`SKILL_DIR/pyproject.toml`)。以降の `manim` は
`uv run --project SKILL_DIR manim` で呼ぶ。

### 1. 取材(利用者への質問)と構成

`references/storyline.md` を読む。**取材では、利用者への質問を多くしてよい。**
まずリポジトリの README・docs、論文、渡された動画を読み、読めば分かることは
聞かずに、既定値を示して確認だけ取る。分からないこと・判断が要ることは、
推測で埋めずに聞く。

- 質問は質問ツール(あれば)で、1 回に最大 4 問まとめ、選択肢つきで尋ねる。
  推奨を先頭に置く。質問ツールが無ければ、番号つきで地の文で尋ねる
- 聞く項目は `references/storyline.md` の質問表(目的と聴衆、主張、素材と許可、
  表現、読み・用語、公開)。答えが次の質問を決めるときは、続けて尋ねる
- 回答と判断は `assets/brief.template.md` を写した `brief.md` に記録する
- 子エージェントは質問できない。質問が要るときは、質問の一覧を親に返して
  止まる(推測で進めない)

素材から次の構成の素材を集める。

0. 冒頭: タイトルと**全体の概要図**(手法の全体像を 15〜25 秒で見せる)
1. 動機(なぜ必要か) 2. 課題 3. 提案と理論背景 4. 結果 5. まとめ

- **冒頭の概要図**: 論文の全体図(パイプライン図、アーキテクチャ図)を使う。
  使えるかは取材で許可を聞く。許可が無い・合わないときは、論文の構成要素を
  なぞって Manim で簡略図を自作する。理論部では同じ図を使い回し、該当する
  ブロックを強調して「いま全体のどこか」を示す
- **動機・課題は具体的な素材**(応用の写真や短い動画)で見せる。抜象的な
  アイコンで済ませない。集め方は「1.5 素材の収集」

動画は 3〜5 分、台本は 1 行 1 クリップ。尺の配分と、どの部を Manim の
アニメーションにし、どの部を実動画・実写にするかを決める。

**確認 1(構成案)**: 台本に進む前に、構成案(部ごとの尺、各部の要点 1 行、
使う図・動画・写真、**冒頭の概要図の案**、出典)を `brief.md` に書き、確認サーバの
「構成案」タブで承認してもらう(「確認サーバの使い方」)。

### 1.5 素材の収集(動機・課題の具体素材と概要図)

確認 1 の後、台本の前に素材を集める(素材に合わせて台本を書くため)。

1. **候補を探す**: 動機・課題の場面ごとに、代表的な応用の写真・短い動画を探す
   (例: AR グラスを使う場面、ロボットが室内を走行する場面)。検索は
   web-search スキル(`websearch.py search` / `fetch`)を使う
2. **出典ポリシーに従う**(`references/attribution.md`)。素材は 3 区分:
   確認済み(CC0 / CC BY / Pexels など許諾あり、または著者本人が許可)、
   出典表示(許諾は未確認だが、出典を出して使う。短い・改変しない・説明の従)、
   仮(私的な検証だけ)。確認済みを優先する。素材はすべて「画面の隣に出典を
   出す」「説明文に出典を入れる」「台帳に記録する」。使わない素材
   (透かし、肖像が主題、ロゴが主題、他者の発表動画の転載など)もここにある
3. **利用者に見せて選んでもらう**: 候補の一覧(URL、ライセンス、使う場面)を
   見せ、承認されたものだけ取得する
4. **取得と記録**: 画像は `curl`、動画は `uvx yt-dlp`(mise の yt-dlp は古いと失敗すること
   がある)でセッションの `assets/` に取得し、台帳を作って記録する:

   ```bash
   python3 SKILL_DIR/scripts/assets_ledger.py init assets.json
   python3 SKILL_DIR/scripts/assets_ledger.py check assets.json
   ```

   公開用は `check --public` を通す(仮は止まる)。取得日・作者を必ず記録する。
   取得後は確認サーバの「素材」タブで、サムネ・動画と出典を見て状態を確定して
   もらう(不採用はメモに書いてもらい、台帳から外す)
5. **取れないとき**: 作らずに利用者に素材の提供を求める。生成した画像を実写と
   して見せない
6. 取得した素材を使う場面を、台本の段階で決める(「この行で AR の写真」)

### 2. 台本と音声

1. `narration.txt` に話し言葉で書く(形式は下)。数式は読み上げる言い方に
   する(`Q_3D = Q_T ∪ Q_S` ではなく「キュー三次元は、時間と空間の和集合」)。
   各行の出典(論文の節、表、ファイル)は `brief.md` か別メモに残す。
   冒頭の行は概要図を見せながら全体の流れを 1〜2 行で言う。動機の行は
   収集した具体素材(「この行で AR の写真」)に合わせて書く
2. 読み辞書(`yomi.json`)を作る。層は 既定(`assets/yomi.default.json`)<
   ユーザー共通(`$CONF_VIDEO_HOME/yomi.json`)< 動画ごと(セッションの
   `yomi.json`)。取材で聞いた用語は先に入れる(`yomi.py set 表記 読み`)。
   台本を書いたら、辞書に無い英字を
   `yomi.py candidates` で候補にする(ENGINE の現在の読みが下書きで入り、状態は
   「候補」)。形式と読みの書き方は `references/yomi.md`
3. 検査(`narration_check.py`)と読みの確認(`readings.py`)を行う。
   状態が「候補」の語が残っていると検査が止まる(確認済みにするまで)
4. **確認 2(台本と読み)**: 音声合成・描画の前に、台本と、候補・変更した読みの一覧を
   利用者に見せて承認を得る(下)。利用者は確認画面の「読み」タブで直してよい。
   承認前に先へ進まない
5. 承認後に合成する。`--speaker`、`--speed` は任意(話者 ID は ENGINE の
   `/speakers` で確認)。合成で `voiceover.wav` と `timestamps.json` ができる。
   候補のままの語は辞書に使われない
6. 実測の総時間を利用者に報告する。目標を外れたら、台本を直して 3 から
   やり直す(直した行は再度確認を取る)。
   **`timestamps.json` の `duration_s` が各行の時間予算になる**
7. 合成後は利用者に「聞いて確かめて」と伝える(エージェントは音を聞けない)。
   語ごとに確かめたいときは `yomi.py audition` の試聴音声を渡す。
   指摘は画面の「読み」タブか `yomi.py set` で直して合成をやり直す(直した語を含む行だけ再合成される)

**確認 2(台本)の出し方**:

- 確認サーバを起動し(下)、URL を利用者に伝える。「台本」「読み」タブで全文と
  読みを見て、本文・読みをその場で直し、タブごとに承認してもらう
- 数値・固有名詞・主張の言い回しは特に確認を求める(誤りは動画では
  直しにくい)。各部の行数、推定の総時間(`narration_check.py` の出力)、数値を含む行の
  出典は、会話でも添える
- 承認は `approvals.json` に、内容のハッシュつきで記録される(`brief.md` への手書きは
  不要)。承認後に内容を変えると「古い」になり、再度の承認が要る
- 承認を待つ間は先へ進まない。次に利用者が戻ったら `review_server.py --summary` で
  状態を読む。「要修正」はコメントを読んで直し、直した項目の再確認を頼む
- 画面で台本を直した行は、再合成が要る(`tts_generate.py`)

### 確認サーバの使い方

```bash
python3 SKILL_DIR/scripts/review_server.py --workdir .             # bg_run で起動
python3 SKILL_DIR/scripts/review_server.py --workdir . --summary   # 状態だけ読む
```

- 起動したら、表示される `REVIEW_READY <URL>` を**そのまま**利用者に伝える。
  あわせて「作業フォルダ」の絶対パスも伝える。URL は作業フォルダのパスから決まるので、
  同じフォルダなら再起動しても同じ(ブックマークしてよい)。127.0.0.1 のみで待ち受ける
- 利用者が不在から戻ったときは、`--summary` の「確認画面:」行で確かめる(動いていれば URL、
  止まっていれば「停止中」と起動コマンド)。**停止中なら再起動する**(URL は変わらない)
- 同じフォルダですでに動いているときは、起動コマンドは新しいサーバを立てず、動いている
  サーバの `REVIEW_READY <URL>` を出して終わる(何度呼んでもよい)
- ポートが使用中(別の作業フォルダのサーバ、他のプログラム)なら、`--port <別の番号>` で起動し直す
  (自動では繰り上げない。`--port 0` は空いているポート)
- 画面の操作は、作業フォルダの既存ファイルに保存される: 台本の本文は
  `narration.txt`(直前の内容は `.bak`)、読みは `yomi.json`、素材の状態は
  `assets.json`、指摘は `notes.json`、承認は `approvals.json`。サーバは窓で、
  正本はファイル
- `yomi.json` は窓口(`state_store`)だけが書く。画面と `yomi.py` が同時に書いても更新は
  消えない。画面で見た後にその語が別で変わっていたときは、保存が 409 になり、
  再読み込みを求める(他の語の変更では止めない)。手で壊されているときは書かずに止める
- `assets.json` も同じ窓口を通る(CLI と画面が競合しても更新は消えない。Excel 用は
  `assets_ledger.py export` で書き出す。書き出し専用で、取り込みはしない)
- 利用者が別のマシンのブラウザで見る場合は、ポート転送が要る(未検証)

### 承認ゲート(先へ進む条件)

先へ進む前に、次のコマンドの**終了コード**で判定する(0 = 通過、1 = 停止、2 = 引数の誤り)。
`approvals.json` の `status` だけを見て進めてはいけない(「古い」承認を見落とす)。

```bash
python3 SKILL_DIR/scripts/review_server.py --workdir . --summary --require plan,script,yomi
```

| 先へ進む操作 | `--require` |
| --- | --- |
| 台本を書く・素材を集める | `plan` |
| 音声合成・描画 | `plan,script,yomi` |
| 素材を使う描画・仕上げ(`assets.json` がある) | `plan,script,yomi,assets` |
| 完成の報告 | 上に `video` を加える |

停止の理由と対応:

- `未承認`: 画面で承認を依頼して待つ
- `古い`: 承認後に内容が変わった。再承認を依頼して待つ
- `要修正`: コメントを読んで直し、再確認を依頼する
- `読めない`: 承認済みでも正本(台本・辞書・台帳)が壊れている。ファイルを直す
- `approvals.json` が壊れている: 内容を確認して直すか、別名に退避する(黙って作り直さない)
- 承認を代行しない。`ask` や会話の「いいよ」で代用せず、`approvals.json` を直接書かない
- ゲートを通した後でも、利用者が画面で直したら「古い」に戻る。次の操作の前にも判定する

```bash
python3 SKILL_DIR/scripts/yomi.py candidates narration.txt --out yomi.json
python3 SKILL_DIR/scripts/narration_check.py narration.txt --target-sec 240
python3 SKILL_DIR/scripts/readings.py --narration narration.txt
python3 SKILL_DIR/scripts/tts_generate.py --narration narration.txt
python3 SKILL_DIR/scripts/yomi.py audition --out audition   # 任意
```

`--yomi` を省くと、上の 3 層を合成して使う(セッションのフォルダで実行する)。

`narration.txt` の形式:

```text
subtitles:
- 最初の一行です。
- 二行目です。
```

### 3. 描画

`references/scene-patterns.md` を読む。`script.py` に 1 部 1 クラスで書く。

- 各行を `self.add_subcaption(text, duration=duration_s)` にし、
  `play()` に `run_time=` を明示、行の最後に `self.wait(max(0, dur - used))`
- 字幕は動画に焼かない(`finish.py` が行う)。Manim 内の文字は図の説明だけ
- 日本語は `Text(..., font="Noto Sans CJK JP")`、数式は `MathTex`
- 結果部は `VideoMobject` で実動画を貼る(`references/scene-patterns.md`)
- 動機・課題の写真・動画素材(1.5 で取得)は `ImageMobject` / `VideoMobject` で貼り、
  出典(作者・ライセンス)を画面の隨に小さく出す
- 冒頭の概要図を理論部で使い回し、説明中のブロックを強調する

### 4. 検査と描画

```bash
python3 SKILL_DIR/vendor/manim-skill/tools/lint-subtitles.py script.py
uv run --project SKILL_DIR manim -ql script.py Scene1 Scene2 ...   # 確認用
```

リンタが通ってから描画する(終了コード 1 = 時間の不整合、2 = 模擬が不完全)。
**描画が 1 つでも失敗したら、結合・仕上げに進まない**(古いシーン動画が残っていて、
一見成功したように見える。`Rendered シーン名` が全シーン分出たことを確かめる)。
描画したシーンを順に `concat.txt` に書き、
`ffmpeg -y -f concat -safe 0 -i concat.txt -c copy video_silent.mp4`。

**画質の切り替え**: スクリプト内の `config` は CLI の `-ql` / `-qh` より
後に効く。`scene-patterns.md` のとおり環境変数
`CONF_VIDEO_QUALITY=high` で切り替える。最終はこれを付けて再描画し、
出力フォルダ(`1080p30` など)に合わせて `concat.txt` を直す。
完成後は `ffprobe` で解像度と fps を確認する。

### 5. 仕上げ

```bash
python3 SKILL_DIR/scripts/finish.py --credit "VOICEVOX:四国めたん" \
  --title "題名" --assets assets.json
```

字幕の焼き込み、BGM のダッキング(`--bgm`)、-16 LUFS への調整、結合を行う。

- 出力(`video.mp4`、`subtitles.ass`、`description.txt`)のどれかが
  既にあると終了コード 2 で止まる。作り直すときだけ `--force`
- `video.mp4` は一時ファイルで作ってから置き換える。失敗しても
  中途半端なファイルは残らない
- `--credit` は字幕を無効にして(`--no-subs`)も末尾に焼く
- `--assets assets.json` は、素材台帳の出典(作者・ライセンス・URL、仮は (仮))を
  `description.txt` に入れる。公開用は、先に `assets_ledger.py check --public`

### 6. 確認

- `ffprobe` で長さ・音声の有無を確認する
- 拍ごとの静止画を見て、字幕の重なり・はみ出し・図の読みやすさを確認する
  (`ffmpeg -ss <秒> -i video.mp4 -frames:v 1 f.png`)
- 音声と映像の同期は、台本の各行の先頭の秒で静止画を見て確かめる
- 利用者に動画の場所と、確認できたこと・できていないことを伝える。
  利用者の確認は、確認サーバの「動画」タブ(再生、行へのジャンプ、指摘)で受ける。
  vendor の動画ビューア(時刻付きメモ)も使える:

  ```bash
  python3 SKILL_DIR/vendor/manim-skill/tools/video_viewer.py \
    video.mp4 --order concat.txt --script script.py
  ```

### 7. 聴き取りと修正

1. 利用者に確認サーバの「動画」「台本」タブで、`video.mp4` を見て聴いてもらい、
   気になった行の「指摘」に書いてもらう(語単位なら `yomi.py audition` の
   `all.wav` も)。指摘は `notes.json` に保存される(台本が変わると「古い」と示す)。
   `review_sheet.py` で Excel 用のシート(`review.csv`。書き出し専用)を作って見てもよい
   (会話で「0:45 のところ、…」と伝えてもよい)。シートに直接書いても取り込まない。
2. `review_sheet.py --notes` で指摘のある行だけを読み、種類で直す場所を分ける
3. 直したら、`tts_generate.py` が表示する「時間が変わった行」を見て、
   再描画の要否を決める(「時間の変更なし」なら描画は不要)

| 指摘 | 直す場所 | やり直し |
| --- | --- | --- |
| 読み・アクセント | 「読み」タブか `yomi.py set` | `tts_generate.py`(該当行だけ再合成) |
| 言い回し・数値 | `narration.txt` | 確認 2 をやり直す → 合成 |
| 間・同期・映像 | `script.py` | リンタ → 該当シーンを描画 |

どの直しも、最後はシーンを `concat.txt` で結合して `finish.py --force`。
音声だけの修正で時間が変わらないときは、描画をスキップして
`finish.py --force` だけでよい。

## エラー・中断

- ENGINE に接続できない: `tts_generate.py` は終了コード 2 で止まる。
  起動方法を示し、他の TTS に黙って切り替えない
- 結果の動画・数値が無い: 作らずに利用者に求める。台本の結果部は
  「ここに実動画」と明示した仮置きで止めてよい
- 利用者に質問できない文脈(子エージェント、非対話)で承認が要る: 質問と
  台本を返して止まる。「承認されたことにして」進めない
- 拒否された操作(ネットワーク、権限)を迂回しない

## 検証手順

- 決定的な検査: `mise run test:conference-video`(偽 VOICEVOX と実 ffmpeg、確認サーバの API と起動)
- 確認サーバの画面を変えたときは、実ブラウザの検証を手元で実行する
  (`tests/e2e/ui_e2e.py`。Playwright と ffmpeg が要る。実行方法はファイル冒頭)
- 実エンジンでの結合・描画・同期の体感は手動の確認(未自動化)
- 評価ケースは `evals/`。実モデルでの試験は依頼があるときだけ行い、
  結果は `experiments/conference-video/` に残す

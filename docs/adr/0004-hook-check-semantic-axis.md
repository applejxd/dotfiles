# hook の判定軸を表層構文から副作用の性質へ移す

- **ステータス**: Accepted
- **日付**: 2026-09-01
- **決定者**: applejxd

## コンテキスト

`home/dot_claude/hooks/executable_check_bash.py` は、両 CLI 共通の PreToolUse hook として
bash コマンドを検査し `deny` / `ask` / 未掲載を返す。詳細は
[`docs/agents-permissions.md`](../agents-permissions.md)。

「開発をできるだけ阻害せず、deny すべきところは確実に deny する」という観点で
全チェックを棚卸しした。実測の出発点は次のとおり。

- ごく普通の開発コマンド 30 件のうち **15 件が `deny`**（承認の余地なし）だった。
  `set -e`、`cat data.json | python3 -c '...'`、`cat src/secrets.py`、
  `gh api -H "Authorization: bearer $GITHUB_TOKEN"`、`cp ~/.bashrc ./backup/`、
  `git -C sub show HEAD -- config/app.yml` など
- 一方で、危険なコマンド 15 件のうち **9 件が素通り**した。
  `eval "$(curl ...)"`、`bash <(curl ...)`、`sh -c "$(curl ...)"`、
  `curl -o a && sh a`、`echo $GH_PAT` など

この 2 つは無関係な不具合ではなく、**同じ原因の裏表**だった。
各チェックが「危険にしている性質」ではなく「表層の構文」に反応していた。

| チェック | 反応していた表層 | 本来の危険の性質 |
| --- | --- | --- |
| `check_pipe_to_shell` | リテラルの `\|` | 取得した内容をコードとして実行すること |
| `check_secret_env_echo` | `$VAR` の展開すべて | 値が出力・外部へ流れること |
| `check_file_read` | basename の語彙 | 秘密そのものを読むこと |
| `check_shell_startup_write` | 引数に現れるパス | 書き込み先であること |
| `check_privilege_escalation` | `/etc/...` の文字列 | 書き換えること (shadow/sudoers は読み取りも) |
| `check_git_c_dangerous` | `-C` と `config` の部分一致 | (normalize 済みで既に不要) |

表層に反応すると、無関係な形で誤爆し（開発阻害）、等価だが表層の違う形は
すり抜ける（防御の穴）。`check_pipe_to_shell` は
`cat data.json | python3 -c` を deny しながら `eval "$(curl ...)"` を通しており、
両方の症状を同時に示していた。

加えて 2 つの制約がある。

1. Copilot CLI は hook の `ask` を数十 ms で自動承認する既知バグを抱える
   （github/copilot-cli#3590）。**`ask` は防御として数えられない**
2. hook は全 bash コマンドの前に走る。当初は 1 コマンドあたり
   `normalize()` が 28 回、`common.toml` の tomllib パースが 4 回走っていた

## 検討した選択肢

### 選択肢 1: 現状維持

- **利点**: 変更のリスクがない
- **欠点**: 15/30 の阻害は承認疲れを生み、通し方が雑になる。穴は塞がらない

### 選択肢 2: 誤検知するチェックを deny から ask へ降格する

- **利点**: 実装が単純。deny の範囲を「確実なものだけ」に絞れる
- **欠点**: Copilot では ask が自動承認されるため、**降格は事実上の廃止**。
  誤検知は消えるが防御も消える

### 選択肢 3: 各チェックを副作用の性質で判定し直し、敵対的レビューで収束させる

判定軸を書き換え、判定不能なら fail-closed。
そのうえで「通したいコマンド」と「止めたいコマンド」の両方を実測し、
外部レビューで bypass を探して収束するまで反復する。

- **利点**: 誤検知と穴を同時に減らせる。判定根拠が説明可能になり、
  例外を足すときの基準ができる
- **欠点**: 判定ロジックが複雑になる。緩和のたびに新しい bypass を
  作りうるので、レビューと回帰テストが必須になる

### 選択肢 4: 個別チェックを廃し、CLI の auto / assisted 判定に委ねる

- **利点**: 保守コストがゼロになる
- **欠点**: Copilot の cloud agent や無人実行で防御が無くなる。
  `curl | sh` のような明確な禁止も表現できなくなる

## 決定事項

**選択肢 3 を採用する。**

理由: 誤検知と穴が同じ原因から出ている以上、片方だけを直しても再発する。
選択肢 2 は Copilot の制約下では防御の廃止と等価であり、
「deny はしっかり」という目的と両立しない。

適用した規則は次のとおり。

1. **チェックは副作用の性質を判定軸にする。**
   「取得内容の実行」「値が出力先へ流れること」「書き込み先であること」の
   ように、危険を成立させている性質でチェックを定義する。
   同じ性質を持つ形は表層が違っても捕捉し、性質を持たない形は通す

2. **確実な証拠と語彙ヒューリスティックを分ける。**
   `.env` / `id_rsa` / `.ssh/` のような完全一致は deny。
   basename の語彙一致は、ソースコード拡張子と列挙コマンド
   （`ls` / `tree` / `find` / `fd`）では適用しない

3. **判定できない形は緩和の対象にしない (fail-closed)。**
   `_is_local_url()` も `_reads_stdin_as_code()` も、静的に確定できなければ
   従来どおりの厳しい既定に倒す

4. **正規化はラッパーまで剥がしてから head を見る。**
   `env` / `timeout 5` / `nice -n 10` / `xargs -I X` のように値を取る
   オプションを持つラッパーは、値を取り違えると実行対象を見失う。
   `env -S` の値はコマンドラインそのものなので展開して解析を続ける

5. **緩和は必ず bypass 探索とセットで行う。**
   緩めた直後に「等価だが表層の違う形」を列挙して実測する。
   本作業では 3 回の敵対的レビューで 18 件の指摘を受け、
   **うち 6 件は緩和自体が作った regression** だった。
   レビュー無しでは緩和は入れない

6. **`normalize()` とポリシー読み込みはプロセス内でキャッシュする。**
   hook は 1 プロセスにつき 1 コマンドしか検査しないので安全。
   キャッシュ対象は不変値 (tuple) にして、呼び出し側が変更しないようにする

## 完了条件

- [x] 表層一致だった 6 チェックを副作用の性質で判定し直す
- [x] `check_git_c_dangerous` を削除する (normalize + `check_policy_deny` で代替)
- [x] `_write_targets()` を導入し、読み取りと書き込みを分離する
- [x] `_normalize` / `_segments` / `_deny_patterns` / `_ask_patterns` をキャッシュし、
      `check_http_dangerous_output` の共有リスト変更バグを直す
- [x] 3 回の敵対的レビュー (`code-review`) で指摘された 18 件をすべて修正する
- [x] 回帰テストを追加し `uvx pytest test/agents/` が 1169 件通過
- [x] `uv run pre-commit run --all-files` が全通過
- [x] `docs/agents-permissions.md` に判定軸と例外の根拠を記載

## 結果

### ポジティブな結果

- 開発コマンドの阻害が 15/30 から 0 になった。ask リストの発火も
  `rm` / `git commit` など意図したものだけになった
- `eval "$(curl ...)"`、`bash <(curl ...)`、`curl -o a && sh a`、
  `env -S bash`、`xargs -I{} sh -c`、`sh -c 'echo $TOKEN'`、
  `python3 -c "print(os.environ['GITHUB_TOKEN'])"` など、
  以前は素通りしていた形が deny になった
- 1 コマンドあたりの `normalize()` 呼び出しが 28 回から 5 回になり、
  典型的なコマンドの検査時間が 52ms から 6.4ms になった
  (プロセス起動を含む実測は 111ms → 110ms でほぼ変わらない。
  支配的なのは Python の起動時間)
- 判定軸が明文化されたので、次に例外を足すときの基準ができた

### ネガティブな結果

- 判定ロジックが増え、`_strip_exec_wrappers` のようにラッパーごとの
  オプション表を持つ必要が出た。新しいラッパーには追随が要る
- 緩和はレビューとセットでしか安全に入れられない。
  本作業で 6 件の regression を作った事実がその裏付けになる
- `_SECRET_SINK_COMMANDS` に `sed` / `awk` / `jq` のようなフィルタを
  含めたため、これらのコマンドで秘密の変数名を扱うと deny になる

### 中立的な結果

- チェックの粒度が「コマンド名」から「意味論」へ寄ったぶん、
  ユニットテストの件数が増えた (1090 → 1169)
- `ask` を防御として数えない前提が、ADR-0002 に続いて再び決定の
  分かれ目になった。Copilot 側のバグが直れば設計の自由度は戻る

## 関連 ADR

- [ADR-0002](0002-loopback-http-approval-scope.md): ループバック宛の緩和を
  ask 層に閉じた決定。本 ADR はその「deny は副作用の性質で見る」という
  考え方を全チェックへ一般化したもの
- [ADR-0001](0001-external-tool-config-coexistence.md): 同じ hook / permission
  生成系を扱うが、対象は外部ツールとの設定領域の共存であり独立している

# CHG-0028: 全件の検証を速くし、調査・実装・レビューを子エージェントへ任せる運用を整える

> この文書は当時の記録。現在の仕様は [検証の方針と選択実行](../../spec/development.md#検証の方針と選択実行)、[pi のガード](../../spec/guard/pi-guard.md)、[判定器](../../spec/guard/pi-decide.md)。
> 残った作業の引き継ぎ先は「終了結果」の「移管した未完事項」。

- **状態**: Done
- **更新日**: 2026-10-22
- **基準**: 全件の検証が直列で 643.67 秒（4198 件。2026-10-22 の実測）。作業の多くを親が自分で行い、親の文脈が長くなる

## 目的と非目的

- **目的**: (A) 日常の検証を数分以内にする。(B) 確認の要らない範囲の調査・読み取り・レビュー・実装を、子エージェントへ任せる。
  親は利用者との聞き取り・ToDo の管理・結果の判断・承認が要る操作に絞る。
- **非目的**: 試験を減らす・間引くこと（判定器の正解データは安全の根拠）。検証コマンドを確認なしの許可に直接載せること。
  親が何にも触れない厳格な運用（文脈を渡す費用・子の承認不可・通知の不安定さが勝つ）。

## 実施計画

段ラベルは `A*`（検証の速度）と `B-*`（委譲と土台）。状態は 2026-10-22 時点。

| 段 | 解決したいこと | 内容 | 状態 |
| --- | --- | --- | --- |
| A4 | どの試験が遅いか分からない | 直列の全件を `--durations=60` で測る | 完了 |
| A1 | 全件が直列で約 11 分かかる | `pytest-xdist` で並列化し、`--dist` の方式を比べる | 完了（`worksteal` を採用。`verify.py` に反映済み） |
| A2 | 小さな変更でも全件を回したくなる | 変更パスから走らせる試験・検査を選ぶ入口 `scripts/verify.py` | 完了 |
| A3 | 全件をいつ・どこで回すかが無い | 日常は選択実行、全件はコミット前に 1 回。`mise run verify` / `verify:all`。CI は測定後に判断 | 文書と `mise` は完了、CI は未着手 |
| B-1 | 委譲の原則が指示に無い | 共通の指示に「子エージェントへの委譲」の節を足す | 完了（試験で確認済み） |
| B-2 | 子の結果の形がばらつき、長いと通知で切れる | 結果の標準形（結論 / 根拠 / 未確認 / 次の候補）を役割の指示に入れる。**長さの上限と使えるコマンドの案内は未反映** | 一部完了 |
| B-3 | 完了通知の遅延・順序入れ替わり・消失を疑う | 通知の経路を調べる | 調査完了、対応は未着手 |
| B-4 | 検証を子に任せられない（確認が子で止まる） | 任せ方の設計を比べる | 調査と `review` 完了。方針を決定（下の「判断」）。(iv) の実験は未着手 |
| B-5 | `explorer` 役が `git diff -- <パス>` を使えない | 判定器の `--` の扱いを直す | 設計完了、実装は未着手 |
| B-6〜B-8 | ToDo が待ち状態を表せない・子と結び付けていない・階層が無い | `blocked` 状態、`todo` 引数での結び付け、階層化（後回し） | B-6・B-7 完了、B-8 は未着手（B-6: `blocked` 状態、B-7: `todo` 引数での結び付けの指示） |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り

## 現在地

（以下は 2026-10-22 時点の観測と見立て。結果は「終了結果」にまとめた。）

- **A4（実測）**: 全件 643.67 秒。最長の単体でも 15.6 秒（`test_decide` のコーパス比較）。上位 60 件（1.8 秒以上）の合計は約 3 分で、残りの約 7 分は、数千件の小さい試験（`test_check_bash_*` など、1 件 0.1〜0.2 秒）。
  `test_pi_harness.py` は約 128 件 × 約 1.8 秒（pi の起動）で、約 4 分。
- **A1（完了）**: 直列 643.67 秒 → `-n auto` 122.30 秒（約 5.3 倍）→ `--dist loadfile` 242.21 秒 → **`--dist worksteal` 96.25 秒（約 6.7 倍）**。どの方式でも並列による新規の失敗なし（失敗は既存の `test_mcp_servers` の 1 件のみ）。
  `loadfile` は予想どおり `test_pi_harness.py`（約 4 分）が下限。`verify.py` は、全件と、選択が 3 ファイル以上のときだけ `-n auto --dist worksteal` を付ける（少数では起動の方が高い）。
- **A2**: `review` が最初の版に取りこぼし 8 件と、削除・リネームの見逃しを指摘した。`worker` が直し、さらに**試験ソースの参照パスから取りこぼしを機械で検査する**仕組みを足した（`test/test_verify.py`、50 件）。
- **B-3（読みによる）**: 遅延と順序入れ替わりは設計どおりに説明がつく（親の作業中は `followUp` がターンの終わりまで待ち、1 件ずつ取り出される）。
  結果を失いうる箇所は、`sendMessage` の例外を握りつぶす 2 か所（`index.ts` の `catch {}`）と、`session_shutdown` / `bypass` 切り替え時の `closeAll()`。
  「完了通知のあとに `status` が存在しないと返す」順序は、設計では説明できない（起動時の `jobId` の取り違えなどが候補）。完了した job の結果を保持する仕組みは無い。
- **B-4（読みによる。`review` で確認済み）**: 守りの本体は許可リストではなくサンドボックスにある。サンドボックスの内側に限って検証だけを許す `verifier` 役が有望だが、現在の Fence は workspace 全体と共有 `.git`、`~/.cache` を書込可にし、通信も共通の許可ドメインを使う。「被害が `.tmp/` に収まる」は現状の保護としては成立しない（実験の目標としてのみ）。
  - **判断（2026-10-22、利用者）**: 通常は (i) 親が実行する。(ii) は「利用者が bypass を ON にした後の新しい `worker`」に限る明示的な例外運用。`explore` / `review`（`explorer` 役）は既定が deny で、bypass でも検証は通らない。(ii) の代償は、その `worker` の他の確認も通ること。(iv) は隔離の実測を先に行う。別案: 利用者の端末や CI が検証を実行し、親は終了コードとログを読む。
  入口に自己検査を持たせて改ざんを防ぐ案は、穴が多くて割に合わない（`conftest.py`・未追跡ファイル・`.gitignore` 対象・`PYTHONPATH`・依存の連鎖・承認ハッシュの置き場）。
- **B-5（読みによる）**: 判定器の `--` の後ろを別コマンドとして拾う処理（`normalize.ts` と Python 版 `command_policy.py` の対応箇所）が原因。
  **許可リスト方式（ラッパーの先頭語だけ拾う）は deny の検出を弱める**（`kubectl exec p -- git push` など）。**拒否リスト方式（まず `git` だけ除く）**が最小。正規化後の先頭語が `git` のときだけ、`--` の後ろを別コマンドとして抽出しない（パス引数として扱う）。これは**埋め込みコマンドの抽出を抑えるだけ**で、共通 deny・役割 deny・ask・allow の判定は従来どおりコマンド全体に掛かる（`git push -- origin main` は deny のまま）。TS と Python の両実装と正解データの再生成が要る。
- **B-9（実測。B-5 とは独立の既存の穴）**: allow に当たる git コマンドが、前置設定やオプションで任意のプログラムを起動できた。`git -c core.pager=id log -- file.txt`、`git --paginate log`、`git -c diff.external=id diff --ext-diff`、`git -c core.fsmonitor=id status`、`git --exec-path=/tmp log` が explorer と implementer で `allow` / source `rule`（`--` を外しても同じ）。正規化が前置オプションを落として `git log` に揃えるため。直し方は、元のセグメントの `git` のグローバル領域（`git` とサブコマンドの間）の `-c` `--config-env` `--exec-path` `--paginate` `-p` と、サブコマンド以降の `--ext-diff` `--textconv` `--exec` `--upload-pack` `--receive-pack` を allow にしない（`--output` と同じ層。deny / ask は足さない。`git log -p` 等は従来どおり）。両実装に入れ、試験と正解データの再生成は未実行。
- **B-10（実測。B-9 と同じ層の既存の穴）**: コマンドの前の環境変数の代入を正規化が落とすため、代入の有無で allow 判定が変わらなかった。`GIT_PAGER='sh -c id' git log`（explorer と implementer で allow / rule）、`GIT_EXTERNAL_DIFF=id git diff`・`GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.fsmonitor GIT_CONFIG_VALUE_0=id git status`（explorer で allow）、`GIT_DIR=` `LD_PRELOAD=` `PATH=` `FOO=1` `env GIT_PAGER=id` を前置した `git log` も allow（対照: `FOO=1 ls` は explorer で deny / default）。直し方は、B-9 と同じ層（`allSegmentsAllowed` / `_all_segments_allowed` の入口）で、位置を追わず、元のコマンド全体の `NAME=value` 形のトークン（先頭の `(` `{` `;` `!` は除く）を見て、名前が `LANG` `LC_*` `TZ` `NO_COLOR` `COLUMNS` `LINES` `TERM` `CI` `FORCE_COLOR` `CLICOLOR` `PYTHONDONTWRITEBYTECODE` 以外なら allow にしない（`-` 始まりの引数を持つ `env` も同様。deny / ask は足さない）。最初に入れた先頭の位置を追う方式は、`( GIT_PAGER=id git log )` `{ GIT_PAGER=id git log; }` `if git status; then GIT_PAGER=id git log; fi` `xargs env GIT_PAGER=id git log` で抜けた（親の実測。正規化が剥がす構文との集合の食い違い）ため作り直した。両実装に入れ、試験と正解データの再生成は未実行。
  - **既知の限界**: リポジトリ自身の設定（`.git/config` の fsmonitor や外部 diff など）から起動する経路は、この除外の対象外。`cd <別のリポジトリ> && git log` や `git -C <dir> log` は allow のままで、移動先のリポジトリ自身の設定から実行される経路も対象外。
  - **追記**: レビューで、`env LANG=C${IFS}GIT_PAGER=id git log` のように、変数展開の語分割で代入を後から作る形が指摘された。`$` を含む形も allow にしないことにした（`$(` だけだった除外を `$` に広げた）。
- **コミット状況**: btw・imozuru・検証の入口（A1〜A3・B-1・B-2）はコミット済み（`ba78b5e` `1424b3e` `51c226d`）。B-3・B-5・B-6・B-7・B-9・B-10 もコミット済み（`65d49b0` `32b085c`）。

## 未解決点

- A1: `test_pi_harness.py` が `HOME` を隔離していない（pi が実 `~` に書くかは未確認）。`worksteal` の複数回の再実行での安定性。
- A3: Linux の CI の追加（リポジトリは public で Actions は無料。素の runner で通るかは未確認）。**再開条件**: A1 の方式が決まったあと。
- B-2: 返答の長さの上限（通知が約 6,600 文字で切れた）と、`explorer` が使えるコマンドの案内を足すか。
- B-3: 症状の原因の確定（`closeAll()` の発火ログ、`jobId` の取り違えの有無）。
- B-4: `verifier` 役の実験（書き込みが `.tmp/` に限られるか、通信が閉じるか、`uv` / `mise` のキャッシュの扱い）。**再開条件**: B-5 の後。
- B-5: 実装の前に `review` を挟む（判定器は境界の変更にあたる）。

## 次の調査・実験

- A1: `HOME` の隔離を試す（`test_pi_harness.py` の `env` fixture）。`worksteal` を数回再実行して安定性を見る。
- B-3: `catch {}` を見える化し、完了した job の結果を `status` で引けるよう保持する小さな変更（`children.ts` と `index.ts`）。
- B-5: `normalize.ts` と `command_policy.py` の同じ形の変更、正解データの再生成、`test_pi_harness.py` の `DOUBLE_DASH`（xfail）を外す、`kubectl exec p -- git push` などの回帰試験。
- B-6: 完了（`blocked` を足し、リマインド対象外にした。`todo` の試験 23 件通過）。実機でのリマインドの確認は未実施。

## 評価基準

- A: 全件が約 2 分以内。並列による新規の失敗がない。選択実行が、本来走らせる試験を落とさない（機械検査で守る）。
- B: 子の結果の採用が、根拠（パスと行・実行結果）で確かめられる。確認なしの範囲が広がらない。

## 候補比較

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| A1: `-n auto`（試験単位） | 122.30 秒。新規の失敗なし | `module` スコープの fixture を共有する試験が散る | 時間に敏感な試験の安定性（1 回は通った） | 見送り（worksteal が速い） | — |
| A1: `--dist loadfile` | fixture をファイル内に保てる | `test_pi_harness.py`（約 4 分）が下限。242.21 秒 | — | 見送り | — |
| A1: `--dist worksteal` | **96.25 秒**。新規の失敗なし。試験単位で偏りに強い | — | 再実行での安定性 | 採用 | 数回の再実行 |
| B-4 (i) 親が実行 | 追加設計なし。承認は利用者 | 子に任せられない | — | 採用（今） | — |
| B-4 (ii) `bypass` の区間 | 実装済み | 守りが弱まる。`explorer` は deny が既定で `pytest` は通らない | — | 採用（`worker` に限る例外運用） | — |
| B-4 (iii) 入口を許可に載せる | 一致判定の形が既にある | 改ざん検出の穴が多い | — | 見送り（単独では） | — |
| B-4 (iv) `verifier` 役 | サンドボックス内に限れば被害を抑えられる見込み（現状の Fence では `.tmp/` には収まらない） | 書き込み範囲・通信・キャッシュが未確認。`default = "deny"`・`inherit_bypass = false`・専用の `shell_allow` が必要 | 実験が要る | 保留（隔離の実測が先） | 使い捨ての作業ツリーで実測 |
| B-5 許可リスト方式 | — | deny の検出が弱まる | — | 見送り | — |
| B-5 拒否リスト方式（`git` だけ除く） | 最小。抽出を抑えるだけで判定は従来どおり | 両実装と正解データの変更 | 正解データの差分の件数 | 有望 | `review` → 実装 |

扱い: 未評価 / 検証中 / 有望 / 採用 / 保留 / 見送り

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `AGENTS.md`・`docs/spec/development.md`・`testing.md` | 検証の入口に `mise run verify` / `verify:all`、方針（日常は選択実行、コミット前に全件 1 回）を足す | A2・A3 | 適用済み |
| 共通の指示（`agent-instructions.md`）・`common.toml.tmpl` | 「子エージェントへの委譲」の節、子の結果の標準形 | B-1・B-2 | 適用済み（試験 156 件通過） |
| 判定器（TS と Python）・正解データ | 正規化後の先頭語が `git` のときだけ、`--` の後ろを別コマンドとして抽出しない（抽出を抑えるだけで、判定は従来どおり） | B-5 | 実装済み（正解データ 3 種を再生成し、`test/agents/` 3874 passed。失敗は既存の `test_mcp_servers` のみ） |
| `todo` 拡張 | `blocked` 状態 | B-6 | 適用済み（未コミット） |

## 実装・検証

- 実測 2026-10-22（16 コア。`uv run --with pytest --with pyyaml --no-project pytest test/ -q`）:
  - 直列: 643.67 秒、4198 passed / 1 failed（既存の `test_mcp_servers`）/ 11 skipped / 4 xfailed。
  - `--with pytest-xdist` で `-n auto`: 122.30 秒、`-n auto --dist loadfile`: 242.21 秒、`-n auto --dist worksteal`: **96.25 秒**。いずれも 4248 passed / 1 failed（同上）/ 11 skipped / 4 xfailed。
- `test/test_verify.py` 50 件通過。選択の例: docs のみ → pytest なし、`common.toml.tmpl`・削除されたファイル → 全件、`web-search` → 2 ファイル。
- 子の使い方の実績（2026-10-22）: `explore` 並列 3 本（約 24〜100 秒、各 0.1〜0.4 ドル）、`worker`（実行できないので親が試験を回して差し戻す周回）、`review`（取りこぼし・設計の弱点を独立に指摘）。
  **子の返答が約 6,600 文字を超えると、通知の末尾が切れた**（A2 の調査結果で表の後半が欠けた）。

## 重要な更新

- **2026-10-22**: 案件を起こした。A4 の実測で、遅さが少数の重い試験ではなく数千件の小さい試験に由来すると分かり、並列化（A1）の効果が大きいと見込んだ。
  `-n auto` で 643.67 秒 → 122.30 秒。**A1 を完了**: 3 方式を測り、`--dist worksteal`（96.25 秒）を採用して `verify.py` に反映した（`test_verify.py` 52 件通過）。`review` が A2 の最初の版の取りこぼしを指摘し、機械検査を足して直した（過程は「実装・検証」）。
- **2026-10-22（終了）**: 判定器の穴（B-5・B-9・B-10）を、`review` 4 回の指摘を受けて直した。通知の追跡（B-3）を足し、`todo` の `blocked` 状態を足し、子と ToDo の結び付けを必須にした。この案件を終了し、残りを ToDo・CHG-0025・CHG-0029 へ移した。

## 終了結果

**採用（一部は確認待ちを移管）。** 全件の検証を直列 643.67 秒から並列 96.25 秒にし、変更に応じた選択実行と Linux の CI を用意した。
子エージェントへの委譲は「調査・レビューは子へ、実装は担当を分けて子へ、実行と判断は親」を基本に整えた。
実行を子に任せる案は、隔離の実測が先として CHG-0029 へ移した。途中で見つかった判定器の既存の穴 3 種を直した。

### 採用したもの

| 段 | 採用した内容 | 証拠 |
| --- | --- | --- |
| A1 | `pytest-xdist` の `--dist worksteal` | 直列 643.67 秒 → 96.25 秒。3 回再実行で安定（93〜95 秒、結果も同じ） |
| A2 | 変更パスから試験・検査を選ぶ入口 `scripts/verify.py`。試験ソースの参照から取りこぼしを検出する検査 | `test/test_verify.py` 52 件 |
| A3 | `mise run verify` / `verify:all`、方針（日常は選択実行、コミット前に全件 1 回）、Linux の CI（`.github/workflows/linux.yml`） | CI は `actionlint` と近似環境で確認。**本物の runner での初回の結果は未確認** |
| B-1 | 共通の指示の「子エージェントへの委譲」の節 | 試験 156 件 |
| B-2 | 子の結果の標準形（結論 / 根拠 / 未確認 / 次の候補）、`worker` の system への道具の使い方 | 試験 |
| B-3 | 完了通知の追跡（警告・結果の保持・通番と時刻・`.tmp/subagents` への保存） | `review` の MAJOR 5 件を直して、関連試験 160 件 |
| B-4 | 方針: 通常は親が実行。bypass を ON にした後の新しい `worker` に限る例外。`verifier` 役は隔離の実測の後 | `review` と利用者の判断（2026-10-22） |
| B-5・B-9・B-10 | 判定器: `--` の後ろを `git` のときだけ抜き出さない。`git` の前置設定とオプション、環境変数の前置と変数展開を含む形を、allow にしない | `review` 4 回、`test/agents/` 3874 passed。実測で、元の攻撃形が deny/default になることを確認 |
| B-6・B-7 | `todo` の `blocked` 状態、子と ToDo の結び付け（`explore` / `review` / `worker` の単独の新規依頼で必須。`todo` ツールが有効のときだけ） | `test/agents/` 3886 passed |
| 派生 | `reader` を子の役割から外して親専用と明記。`ask` の推奨の事前チェック。試験のうち、実行する機械に依存する 3 件の修正 | 全件 4406 passed（失敗 0） |

### 撤回・見送りしたもの

| 項目 | いつ | 理由 |
| --- | --- | --- |
| A1: `-n auto`（試験単位）、`--dist loadfile` | 2026-10-22 | `worksteal`（96.25 秒）が最速。`loadfile` は `test_pi_harness.py`（約 4 分）が下限で 242.21 秒 |
| B-4 (iii): 検証の入口を許可に載せる | 2026-10-22 | 改ざん検出の穴が多い（`conftest.py`・未追跡・`.gitignore`・`PYTHONPATH`・依存の連鎖）。単独では見送り |
| B-5: 許可リスト方式 | 2026-10-22 | 拒否していた入れ子実行（`kubectl exec p -- git push` など）の検出が弱まる |
| `pre-push` hook に全件を入れる | 2026-10-22 | 待ち時間が `--no-verify` を誘う |
| 子ごとの編集範囲（`paths`）の強制と、期待値ファイルの編集禁止 | 2026-10-22 | 並列の衝突は worktree で分離する前提で、強制の必要性が下がる。「期待値の分離」だけが残る（CHG-0029 の W3） |

### 反映先

- 仕様: [検証の方針と選択実行](../../spec/development.md#検証の方針と選択実行)、[テストの仕組み（Linux の GitHub Actions）](../../spec/testing.md#linux-の-github-actions)、
  [pi のガード](../../spec/guard/pi-guard.md)（子の操作・結果の保持・`todo` の必須化・`blocked`）、[判定器](../../spec/guard/pi-decide.md)（allow の除外）
- 実装: `scripts/verify.py`、`test/test_verify.py`、`mise.toml`、`.github/workflows/linux.yml`、`home/dot_config/pi/harness/`、
  `home/dot_claude/hooks/lib/decide.py`、`home/dot_config/agents/command_policy.py`、`home/dot_pi/agent/extensions/{todo,ask}/`、共通の指示
- 観測: [公開拡張の調査と worktree の先行例（記録 P6）](../../research/agents/pi-public-extensions-survey.md)
- コミット: `51c226d` `65d49b0` `32b085c` `1573f55` `fe58617` `77d8980` `1484767` `171cf25`（この終了と同時にコミットする `todo` 必須化を除く）

### 移管した未完事項

| 内容 | 移管先 |
| --- | --- |
| A3: `linux.yml` の初回の実行結果の確認（利用者が push 済み。Actions のログを貼ってもらう） | ToDo（利用者待ち） |
| A1: `test_pi_harness.py` が `HOME` を隔離していない（実 `~` への書き込みの有無の確認） | ToDo（小さい作業） |
| B-2: 子の返答の長さの上限（通知が約 6,600 文字で切れる）と、結果の形式の検証 | ToDo（優先 4: 子の結果の形式検証と、主張とログの突き合わせ） |
| B-3: 「does not exist の後に通知が届く」症状の原因（未解明。警告・保持・保存で手がかりを得られるようにした） | ToDo（再発時に調査） |
| B-3: `pruneSaved` と `close` 競合の試験、型検査、警告の実機確認 | ToDo（実機確認の項目と、小さい作業） |
| B-4 (iv) と検証の隔離（`verifier` 役、完了時の自動検証） | [CHG-0029](../0029-worktree-isolation.md) の W0（実測）と W2 |
| B-5 のあとの「期待値を決める人と実装する人の分離」と、`worker` の git 制限の見直し | [CHG-0029](../0029-worktree-isolation.md) の W3 |
| B-8: `todo` の階層化 | [CHG-0025](../0025-goal-autonomous-loop.md)（`/goal` の自律ループと一緒に判断する。該当する節はこの案件を終えるときに足す） |
| 実機での確認（`blocked` のリマインド、`ask` の推奨チェック、`todo` 必須化、警告の出方） | ToDo（利用者待ち。`/reload` が要る） |
| 判定器の既知の限界（リポジトリ自身の設定から起動する経路、`cd <別のリポジトリ> && git log`） | [判定器の仕様](../../spec/guard/pi-decide.md)（限界として記載済み）。新しい案件は起こさない |

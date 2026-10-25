# CHG-0038: ガードを「防ぐ害」で分類し直し、外部への送信・公開の穴を塞ぐ（`confirm` の新設）

- **状態**: Exploring
- **更新日**: 2026-10-24
- **基準**: コミット `6b61aa8`（`pis` は、サンドボックスでの起動で bypass が既定オン。内側の認証情報は偽物のみ）。判定器は TS 版が本番（[pi-decide.md](../spec/guard/pi-decide.md)）、Python 版は照合用（[CHG-0035](0035-retire-python-judge-oracle.md)）

## 目的と非目的

**目的**: 本格運用に入るにあたり、ガードを「防ぐ害」で分類し、起動パターンごとの on/off を決める。内側の認証情報が偽物のみになったので、残る主なリスクは**private リポジトリの公開と、意図しない外部への送信（git push、issue・PR の作成、リポジトリの公開設定の変更、パッケージの publish など）**。この穴を、標準の `pis`（サンドボックス＋bypass）で確実に塞ぐ。

**非目的**:

- 外部の責務（PAT のスコープ、IAM、ブランチ保護）をガードで代替する（[CHG-0033](0033-sandbox-build-value-assessment.md) の「責務の棚卸し」）。ガードは「うっかり防止」で、境界ではない。強い保証は、PAT のスコープ・ブローカー・ネットワークの側で担う
- 全規則への分類タグ付けと、起動パターンごとに区分を on/off する仕組み（`[pi.modes]` など）。**当面は作らない**（下の「分類は整理であり、切り替えの仕組みではない」）
- サンドボックスでのホスト側の認証情報の保護（C1）の縮小（内側に残るものの棚卸しの後。段 G6）

## 分類

**「防ぐ害」の軸**（1 つの検査が複数に属しうる。排他的な 1 つの `class` にしない）:

| 区分 | 内容 | 例 |
| --- | --- | --- |
| U | UX の誘導 | `bg_run` への誘導、read・write ツールへの誘導、todo、nudge |
| C1 | ホストの認証情報の保護 | `~/.ssh`・`~/.aws`・環境変数の echo・履歴・秘密ストアの deny |
| C2 | 作業ツリー内の秘密の保護 | `.env`・`*secret*`・`*credential*` の読み取り拒否、伏字化 |
| E | 外部への送信・公開の防止 | `git push`、`gh` の書き込み、publish、`curl` の POST、`ssh` |
| D | 破壊の防止 | `rm` の保護、`git reset --hard`、`sudo` |
| S | 構造の保護 | ガード自身の改竄防止、役割のツール制限、カナリア |

**分類は整理であり、切り替えの仕組みではない**（利用者との検討、2026-10-24）:

- 起動パターンごとの on/off を検討したが、**すべての起動パターンで、すべての区分がオン**になる（C1 の縮小は、棚卸しの後に判断するため保留）。切り替える対象が、いまは無い
- 起動パターンによる差は、**既存の仕組み**（サンドボックスの既定緩和＝`boundary`、`bypass`）だけで足りる。`pis`・`pis --no-bypass`・`pis --no-sandbox` のいずれも、U・E・D・S・C1・C2 がオン
- 切り替えの利益は、サンドボックスでの C1 の誤検出・煩わしさの低減だが、**そうした実績はまだ無く**、保守の費用も減らない（C1 の規則は `--no-sandbox` のために残る）
- 必要なのは、分類ではなく **E の穴埋め**（`confirm` と公開系の deny）。分類は、棚卸しと判断のための整理・文書として残す。**必要が出たとき（サンドボックスで C1 の誤検出が実際に煩わしい、など）に、実績を見て、タグ付けと on/off を検討する**
- 注記: **read への誘導（`cat`・`head`・`tail`・`sed -n` を `read` ツールへ寄せる規則）は、U と C2 の両方の性質を持つ**。目的は保護（シェル経由では `read` の deny が効かない）で、C1・C2 のどちらを指すかはコマンドから静的に分からないため、**常時オン**。1 検査が複数の区分に属しうる

**C1 と C2 を分けても、当面の運用は変わらない**（どちらも常時オン）。区分は、将来 C1 をサンドボックスで縮小するかを判断するための、設計上の整理。

## 決定（利用者、2026-10-24）

1. **gh の日常の投稿**（issue・PR の作成・コメント・レビュー・編集）は、標準の `pis`（bypass オン）でも、**内容つきで必ず確認を出す**（`confirm`＝bypass 不可の ask）。**無反応のまま時間が過ぎたら deny**。UI が無い実行（print・子）は deny。
2. **公開・配布系**（リポジトリの公開設定の変更、publish など）は **deny**。
3. **C1 の縮小**は、内側に残るものの棚卸し（`*_API_KEY` の環境変数、`--no-broker`、検索 API の鍵）の後に判断する。それまでは何も外さない。
4. **実装の順**: 先に E の穴埋め（pi 専用の小さな表と `confirm`）。全面の分類リファクタと区分の on/off の仕組みは作らない（上の「分類は整理であり、切り替えの仕組みではない」）。CHG-0035（Python 版の撤去）は独立して進める。
5. **E の穴埋め（段 G1〔G5）は必須**（利用者の指示、最優先）。採用・見送りの判断対象ではなく、本格運用の前提条件として完遂する

## 現状の穴（`explore` の調査。コードの読みが中心）

- 評価順は、共通 deny → 役割 → 誘導 → 役割の shell_deny → ask 規則 → allow 規則 → 既定 → **サンドボックスの内側なら、既定の ask（規則に載っていない bash）を allow** → **bypass は ask をすべて allow**。bypass でも deny・誘導・秘密の保護は変わらない
- したがって、標準の `pis` では、**規則に載っていない外部書き込みが、確認なしで通る**: `gh repo edit --visibility public`、`gh repo create --public`、`gh pr edit/review/comment/close`、`gh issue edit`、`gh workflow run`、`npm publish`、`uv publish`、`twine upload`、`cargo publish` など。載っている ask（`gh pr create`、`gh issue create/comment/close`、`curl` の POST、`gh api` の書き込み、`docker push`、MCP、`git commit` の確認）も、bypass で確認なしで通る
- deny に載っているもの: `git push`、`git remote add/set-url`、`ssh`/`scp`/`rsync`/`sftp`、`gh release create/upload`、`gh gist create`、`gh secret set/list`、`gh pr merge`、`gh repo delete`、クラウドへの転送
- 判定器の on/off の軸は、実質 `boundary`・`bypass`・役割の 3 つ。`PI_HARNESS_NO_SANDBOX` は表示専用（安全の根拠にしない）

## `confirm` の仕様案（レビュー済みの要点）

- **意味**: bypass で allow にならない ask。確認は、**内容つき**（宛先・本文・オプション）で出す。**無反応で時間が過ぎたら deny**（既存のハーネスは、`ctx.ui.confirm(title, body, { signal, timeout })` を使っており、同じ仕組みで実現できる）。UI が無いとき（print・子・RPC）は deny
- **評価順**: 共通 deny・役割の制限・誘導・役割の shell_deny の**後**、一般の allow・サンドボックスの既定緩和・bypass の**前**。**未掲載のコマンドを検出する規則は、既定の緩和より先に置く**（さもないと緩和で allow になる）
- **実装の形**: 新しい decision 値を増やすより、`ask` に「bypass 不可」の属性を付け、緩和と bypass の条件を属性で制限する（変更範囲が小さい）。`tool_call` の承認と `execute` 時の入力の一致を保つ
- **表示**: `/bypass` の説明を「bypass 可能な ask だけを通す」に、フッターも合わせる。素の `pi` の `commit-confirm` は、`pis` では外れるので、代行しない
- **逃げ道**: 操作・宛先を限定した `deny / confirm / allow` の明示設定（E 全体を `/bypass` で外す逃げ道は、目的と矛盾するので作らない）
- **位置づけ**: 語で拾う規則は「うっかり防止の改善」で、境界ではない（別の CLI・スクリプト・MCP・`gh api` の別の書き方が残る）。強い保証は、PAT のスコープ・ブローカー・ネットワークで担う

## E の権限表（案。段 G1 で確定）

| 操作 | 案 |
| --- | --- |
| `gh repo edit --visibility`、`gh repo create --public`、`npm/uv/twine/cargo publish`、`gem push`、`gh release *`、`docker push`、`gh gist create` | **deny** |
| `gh pr create/edit/review/comment/close/reopen`、`gh issue create/edit/comment/close/reopen/lock`、`gh repo fork/rename/archive`、`gh workflow run`、`gh api` の書き込み | **confirm**（内容つき） |
| `curl`/`wget` の POST、MCP の書き込み | 要判断（頻度と影響を見て決める。現状は bypass 可能な ask） |
| `git push`・`git remote add/set-url`・`ssh`/`scp` | 現状の deny を維持 |
| 規則に載っていない外部書き込み | 語（`gh repo`・`publish`・`upload`・`release`・`visibility` など）で deny/confirm へ倒す。許可リスト方式（外部へ書くサブコマンドを明示した許可だけ通す）は、費用が高いので、効果を見てから |

## 実施計画

| 段 | 解決したいこと | 内容 | 状態 |
| --- | --- | --- | --- |
| 段 G0 | 分類と方針が決まっていない | 棚卸し（`explore`）、設計の `review`、利用者の決定 | 完了（上の「決定」） |
| 段 G1 | E の権限表が未確定 | 上の表を、操作別に確定する（`curl` の POST と MCP の扱いを含む） | 完了（2026-10-25） |
| 段 G2 | `confirm` の実装設計が粗い | 評価順・属性・UI 無しと子の扱い・`/bypass` の表示・TS と Python（照合用）の両実装・正解データの形を、設計にして `review` へ | 完了（2026-10-25） |
| 段 G3 | 実装 | deny の追加（`[bash]`）、pi 専用の確認の表（`[pi]` 下）、`generate.py`、TS の判定器、ハーネスの確認の処理、Python 版・正解データ | 完了（2026-10-25） |
| 段 G4 | 試験 | 標準の `pis`（bypass オン）・`--no-bypass`・UI 無し・子・無反応の時間切れ、の期待結果を固定 | 完了（2026-10-25） |
| 段 G5 | 実機 | `pis` で、公開・投稿の操作が止まる・確認が出ることを確かめる | 進行中（利用者の `pis` で、確認が実際に出ることを確かめる） |
| 段 G6 | C1 を縮小してよいか分からない | 内側に残るものの棚卸し（環境変数・読めるパス・`--no-broker`・検索 API の鍵）の可視性表を、実機で作る | 未着手 |
| 段 G7 | 全規則への分類タグ付けと、区分の on/off の要否 | **見送り**。必要が出たとき（C1 の誤検出が実際に煩わしい、など）に、実績を見て判断する | 見送り |
| 段 G8 | 誤導規則（bash から read・write へ寄せる deny）が多発し、作業を止めている | 実績の計測と原因の分析（下の「重要な更新」）。**ツール定義の側を先に作り込む**（`AGENTS.md` より先）: ① `guarded_bash`・`guarded_read`・`guarded_write`・`guarded_edit` の description と `promptGuidelines` を、ハーネスの登録時に上書きし、使い分けと具体的な言い換えを書く。② `guarded_read` に `tail`（末尾から N 行）、`guarded_write` に `append`（追記）を足して、代替の同等性の欠けを埋める。③ 複合コマンドは拒否せず注記にする（または拒否のメッセージに該当の断片を示す）。④ サンドボックスでは、UX 目的の誘導を deny から注記へ下げる。設計し、`review` へ | 未着手 |
| 段 G9 | E の「境界」を、GitHub ブローカー（Envoy）の経路ポリシーで決定的に塞ぐか | 候補: REST のパス・メソッドの deny（コンテンツ API・ref の作成更新・リポジトリの公開設定・削除）と、GraphQL のミューテーション名の拒否（Lua）。**保留**（利用者の判断）: issue への返信などができなくなり、コピペの手間が増える。まずはガード（段 G1〔G5）で対処し、実績を見て判断する | 保留 |
| 段 G10 | deny を権限側へ寄せる: 個人機は絞った fine-grained PAT、制約のある環境の機は classic PAT（`repo` のみ）と Admin でないロール。サーバ側の 403 の確認。縮小は Admin 級の REST の列挙まで | 手順は下の記録。利用者の実機の確認が先 | 手順書のみ（2026-10-25） |
| 段 G11 | 投稿・コミットの流れの固定: 宣言的アクション表 `[[pi.actions]]` と `guarded_action` 1 本。承認 1 回、argv をハーネスが組み立てて実行、bash の同じ操作は deny + 呼び出し例つきの案内 | 設計を記録（下の記録）。レビュー、実装の順 | 段階 1・2 は実装済み（2026-10-25）。実機の TUI の確認と段階 3 は未 |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り / 消滅

## 現在地

- 分類と方針は決定済み（上の「決定」）。**段 G1〔G4 は完了**（2026-10-25。実装はコミット `9e37e04`、仕様は [pi-decide.md](../spec/guard/pi-decide.md#confirm) と [pi-guard.md](../spec/guard/pi-guard.md#confirm-の確認)）。**段 G5 は利用者の `pis` で、確認画面が実際に出ることを確かめる**。段 G6（C1 の棚卸し）・段 G8（誘導の縮小の次の項目）は、再計測の後。段 G9 は保留
- 関連: [CHG-0033](0033-sandbox-build-value-assessment.md)（責務の棚卸し）、[CHG-0035](0035-retire-python-judge-oracle.md)、[CHG-0037](0037-pis-usability-and-telemetry.md)

## 未解決点

1. `curl`/`wget` の POST と MCP の書き込みを、confirm にするか（頻度が高いと、確認が煩わしい）
2. `gh api` の GET のクエリ文字列での持ち出し、スクリプト経由（`requests.post` など）の送信は、語では塞げない
3. （2026-10-25 に隔離済み。CHG-0037 の記録）検索 API の鍵（`websearch-keys.json`）が内側から読める件（[CHG-0033](0033-sandbox-build-value-assessment.md) の「責務の棚卸し」）。C1 の縮小の判断に含める
4. 子エージェントの確認の扱い（UI が無いので deny。`inherit_bypass` との関係。**実装と統合試験で確かめた**）
5. 実際の TUI での確認画面の表示（残り秒数、長い本文のスクロール）。試験は RPC と print だけ
6. `gh api` の暗黙の POST（`-f`/`-F`/`--input`）、`-X` の別形、前置フラグへの対応の試験の追加（調査で、OSS も欠く穴と分かった）
7. **サンドボックスで検索のプロバイダーに届かない**（実測。許可の一覧に無い。[CHG-0037](0037-pis-usability-and-telemetry.md) の通信の方針とあわせて決める）
8. 確認の誤入力の防止（表示直後の確定キーの無視）と、判定の監査ログ（JSONL）（調査で参考になった。実績を見て判断）

## 評価基準

- 標準の `pis`（bypass オン）で、公開・投稿の操作が、deny か内容つきの確認になる
- 無反応で時間が過ぎたら deny、UI が無ければ deny
- 既存の deny・ask の挙動と、正解データが、意図した差分だけで変わる

## 実装・検証

段 G1〔G4 は実装済み（`9e37e04`）。段 G5（実機）は利用者の確認待ち。検証: 全件検証 exit 0。

## 重要な更新

- **2026-10-24（起票。のちに「切り替えの仕組みは作らない」と検討）**: 利用者の分類案（1. UX の誘導、2. 認証情報の対策、3. 漏洩の防止）を、`explore` の棚卸しと `review` で検討した。区分は「防ぐ害」の軸（U・C1・C2・E・D・S）で、複数に属しうる。**「サンドボックスでは認証情報の対策が要らない」は成立しない**（作業ツリー内の `.env`、`*_API_KEY`、`--no-broker`、検索 API の鍵が残る）。**最大の穴**は、標準の `pis` で、規則に載っていない外部書き込みと、載っている ask が、確認なしで通ること。利用者が、confirm（bypass 不可、内容つき、無反応は deny）、公開・配布は deny、C1 の縮小は棚卸しの後、E の穴埋めを先、と決定した。
- **2026-10-24（誘導規則の多発の計測。段 G8）**: 利用者の違和感（bash から read・write へ誘導される deny が多発する）を、実績で確かめた。**計測**（ホストの pi のセッション 77 件。親が、セッションの記録から、誘導の deny の本文を数えた）: bash の呼び出し 2,818 回に対し、誘導の deny は約 130 回（約 4.6%）。内訳は、書き込み系 約 80（`python3 - <<EOF` などのインラインスクリプト 20、新規ファイル `cat > f <<EOF` 13、追記 `cat >> f <<EOF` 6、その他のヒアドキュメント 8 など）、読み取り系 約 35、`sleep` 約 8、`&` 約 12。同じセッションで 3 回以上くり返したものが、書き込みで 5 セッション、読み取りで 3 セッション。**読み取り系の約 7 割（35 件中 24）は、複合コマンド**（`cd X; sed -n …; git diff …` のように、複数の操作を 1 回にまとめた中の 1 つ）で、**1 つの断片のために、呼び出し全体が拒否される**。**原因の仮説**（実績からの推測）: ① **誘導が示す代替が、同等でない**: `read` ツールには `tail`（末尾から）が無く（offset が要るので `wc -l` が先に要る）、`write` は上書きで**追記ができず**（`edit` は固有のアンカーが要る）、インラインスクリプトの代替は「ファイルを書いて、実行する」の 2 手になる。モデルが、効率のよい手を選んでいるだけ。② **複合コマンドを丸ごと拒否する精度**: 有用な他の断片も一緒に止まり、メッセージは、どの断片が原因かを示さない。③ **拒否が、コマンドを組み立てた後に来る**（1 ターンの無駄）。④ **保護の根拠が、サンドボックスでは薄い**: 読み取りの誘導の「保護」は、ホスト側（Fence が担う）と作業ツリー内（検査 `check_file_read` が、リテラルの機密パスを deny する）で、すでに重複する。書き込みの誘導の「保護」（`edit` の deny を迂回する書き込み）は、サンドボックスでは Fence の書き込み拒否が担う。つまり、**多くの誘導は、サンドボックスでは UX だけの目的**で、deny でなく**注記（allow ＋ 1 行の示唆）**で足りる。**モデルが read の利点を理解できていない、というのは、主因ではなさそう**（deny の後は、従って read を使っている。くり返しは、代替のコストが高いことの表れ）。**候補（未設計）**: 複合コマンドは拒否せず注記にする、`tail` を対象から外す、追記とインラインスクリプトは許す（またはサンドボックスで許す）、拒否のメッセージに、該当の断片と具体的な言い換えを入れる、システムプロンプトの方針（ツール名は `guarded_read` などなので、`read` と書かれた方針と、ずれている可能性がある）を整える。この候補は、サンドボックスでの on/off を要する可能性があり、段 G7 の「見送り」を、段 G8 の結果で見直す。**確認すること**: 見直し後の誘導の deny の割合（目標は 1% 未満）を、同じ方法で再計測する。
- **2026-10-24（今回の発見の記録。ガードは「境界」ではない。E の決定的な下限は GitHub ブローカーにある）**: 利用者の指摘（原理上、Python 経由なら read も write も自由にできる）を受けて整理した。① **シェルの誘導・deny は、Python などで迂回できる**。ガードは、モデルが普通に使う経路の事故を減らす「うっかり防止」で、境界ではない。迂回できないのは、OS（Fence の読み書き・ネットワーク）、認証情報の隔離（ブローカー）、PAT のスコープ。② **`git push` の deny は、API で迂回できる**: 内側の GitHub の認証は、ブローカーのソケットだけ。書き込み権限の PAT があれば、コンテンツ API（`PUT /repos/*/contents/*`）や Git データ API（`POST /repos/*/git/refs`）で、push なしに書き込める（**いまも通る状態**）。③ **GitHub への書き込みは、すべて Envoy を通る**ので、取り返しのつかない操作（公開設定・削除・作成、ref の作成更新、コンテンツの書き込み、リリース）を、**決定的に deny できる**。ただし、`gh issue create`・`gh pr create` などは GraphQL（1 つのパスに、ミューテーションが本文で入る）なので、パスだけでは分けられず、本文の検査（Lua）が要る。④ **利用者の判断: 当面はブローカーでは塞がず、ガード（段 G1〜G5）で対処する**。理由: issue への返信などができなくなり、コピペの手間が増える。段 G9 は保留とし、実績（ガードで足りるか）を見て判断する。⑤ **「auto mode」（分類器が操作ごとに可否を判断する方式）は、いまは不要**: 遅延・費用・揺れ・判定器自身へのインジェクション、決定的な下限が無い。まず決定的な下限（ブローカー）と、人の確認（他人に見える投稿だけ）を整える。将来、確認の振り分けとして足す選択肢。
- **2026-10-24（誘導が効きにくい理由。モデル別の実績と、ツール定義の改善。段 G8）**: 実績（ホストのセッション 77 件）の大半は `claude-sonnet-5.5`（bash 2,805 回、誘導の deny 94 回＝**3.4%**。`read` は 564 回）。つまり、**sonnet でも誘導を受ける頻度は、くり返し一定**で、「わかっていない」より「同等の代替が無い・コストが高い」の側。**誘導が効きにくい理由（仮説）**: ① **ツール定義の側の誘導が弱い**: ハーネスは、pi の組み込みの定義を `...def` で展開して `guarded_*` として登録するだけで、description は組み込みのまま（`guarded_bash` は「Execute bash commands (ls, grep, find, etc.)」と、ファイル操作の `ls`・`grep`・`find` を勧めてさえいる）。システムプロンプトの方針（「`read` を使え」など）は、ツール名（`guarded_read`）とずれ、決定の場面から遠い。② **代替が同等でない**: `read` に `tail` が無い、`write` に追記が無い、インラインスクリプトの代替が 2 手。③ **拒否が事後**で、複合コマンドは丸ごと拒否され、どの断片かも示さない。④ 長いセッションでは、方針が薄まる（くり返しが一定）。**改善（`AGENTS.md` ではなく、ツール定義の側を先に。段 G8 の ①〜④）**: description と `promptGuidelines` の上書き、`guarded_read` の `tail` と `guarded_write` の `append` の追加（同等性の欠けを埋める）、複合コマンドは注記に、サンドボックスでは UX 目的の誘導を注記に下げる。**目標**: 誘導の deny の割合 1% 未満（同じ方法で再計測）。
- **2026-10-24（他ハーネスの調査と、設計の修正。段 G8）**: 利用者の依頼で、他のエージェントの実装を満遍なく調べた（[記録](../research/agents/tool-design-survey.md)）。**要点**: ① `tail`・一括読み・追記・stdin の専用引数は、どの製品にも無い（Gemini の一括読みは非推奨）。**一括読みは、並列の呼び出しで足りる**が実績のある流儀 → 一括読みの案（B の配列）は**やらない**。② **cat の bash 読みを拒否する製品は無く、bash の説明文での誘導が主流**（Claude Code は単一ファイルの `cat` を読みとして扱う）。自作の deny は他社より厳しい。③ **Claude 系の先験**: Anthropic の bash ツールの例がヒアドキュメントで書いている → 書き込みの誘導が効きにくい説明になる。④ 安い改善: 不正な offset でファイルの長さを返す（Copilot）、似た名前の提案（Crush）、トークン効率の記述（Gemini・Amp）。**設計の修正（`review` の指摘と合わせて）**: 先行 = **A（説明・snippet・guidelines の上書き。Claude Code・Crush・Amp の型で、`cat`・`sed`・`echo >` ごとの具体的な言い換えと、並列の `guarded_read` の案内）＋ G（拒否メッセージに該当の断片と具体的な言い換え）＋ `guarded_read` の `tail`（単一パス）と `guarded_write` の `append`（同じ書き込みの queue 内で追記）＋ 読みの失敗のヒント（offset が長さを超えたら長さを返す、似た名前の提案）**。次 = **複合コマンドは拒否せず注記に**（保護の検査 `check_file_read` は全断片に掛けたまま）、**サンドボックスでの書き込み系の誘導（ヒアドキュメント）を注記に下げる**（保護の根拠は Fence の書き込み拒否で、境界チェックで「保護対象へ書けない」を実測済み。読み取り系は、リテラルのパスの `check_file_read` で足りる範囲を個別に確かめてから）。後段・見送り = **E（`stdin` の引数。pi の bash は `command` と `timeout` しか受けず、専用の実行経路・判定・確認表示の契約が要る）**、**F（透過実行）**、`executable`、`replace_all`・行番号指定の編集。**測り方**: 誘導の deny の割合に加え、同じ目的の再試行、1 タスク当たりのツール呼び出し数、read に対する bash の比率、ask 件数を、セッションの記録から数える。
- **2026-10-24（段 G8 の先行分の実装と実測）**: 他ハーネスの調査を踏まえた設計（`review` 済み）で、先行分を実装した: ① `guarded_*` の説明・snippet・guidelines の上書き（`tools-ext.ts`。仕様は [pi-guard.md](../spec/guard/pi-guard.md#ツールの拡張guarded_read--guarded_write--guarded_bash-の使いやすさ)）、② `guarded_read` の `tail`、③ `guarded_write` の `append`、④ 読みの失敗のヒント（有効な範囲、似た名前）、⑤ 誘導の deny への具体的な言い換え。あわせて、グローバルの指示（`agent-instructions.md`）から、ツール側が持つ説明（ToDo の `blocked`、`guarded_task` の `todo`、`review`・子への依頼の書き方の詳細）を削った。**試験**: 新規 62 件（`test_pi_tools_ext.py`、node の単体と faux プロバイダーの通し）が通過、既存のハーネスの試験（254 件）も通過。**実機（`pis`、境界あり）**: `guarded_read` の `tail=2` が末尾 2 行を返し、`guarded_write` の `append` が追記し、`sed -n 1,2p notes.txt` の deny に「`guarded_read {path: "notes.txt", offset: 1, limit: 2}`」の言い換えが付いた。**軽微な既知の点**: 改行で終わるファイルの `tail` の結果に、組み込みの read の「続きは offset=…」の注記が付く（空の末尾行を数えるため）。**次**: 実績の再計測（誘導の deny の割合、同じ目的の再試行、1 タスク当たりのツール呼び出し数）を、普段使いの後に行う。段 G8 の次の項目（複合コマンドを注記に、サンドボックスでの書き込み系の誘導を注記に）は、再計測の後に判断する。**未実施**: 段 G1〜G5（E の穴埋め。必須）。
- **2026-10-25（段 G1〜G5 の設計の `review` と、実装の中断。サンドボックスではガードのソースが読み取り専用）**: **`review` の指摘と反映**: ① `gh api` の書き込みを一律 confirm にすると、公開設定・release・ref の更新（push 相当）も、確認後に通る → **公開・配布に当たる `gh api` の操作は deny**（新しい deny 検査 `check_gh_api_publish`。REST: `repos/{o}/{r}` の PATCH・DELETE、コンテンツ・ref・release・pages・hooks・collaborators・dispatches・secrets など。GraphQL: `createRepository`・`updateRepository`・`deleteRepository`・`archiveRepository`・`transferRepository`・`createRef`・`updateRef`・`deleteRef`・`createCommitOnBranch`・`mergePullRequest`）。② 「内容つき」は、コマンド全文では成立しない（`--body-file`、標準入力、コマンド置換）→ **標準入力・コマンド置換の形は deny**、`--body-file <path>` は、ハーネスがファイルを読んで確認画面に出し、読めない・本文が 8,000 字超なら確認を出さず拒否、承認後に差し替えられないよう、実行時に再読み。③ `gh repo create` は `--public` を区別できないので、**`gh repo create` も `gh repo edit` も全部 deny**。④ 検査の名前は `check_gh_api_mutation`（`check_policy_ask` が先に当たる順序は保つ）。⑤ 正規表現（`publish|upload|deploy`）は複合コマンドと引用文で不安定 → **採用せず**、既知のコマンドの前方一致だけ（未掲載の CLI はすり抜けうる）。⑥ 確認の結果（時間切れ・拒否・取消・UI 無し）を区別し、時間切れは「再試行せず、利用者の新しい指示を待つ」。⑦ 正解データは、標本を除かず、比較で `mustConfirm` と、(TS: ask＋mustConfirm / Python: allow＋bypassed または ask) の組を一致とみなす。**確かめた事実**: 確認の `timeout` は TUI でも守られる（画面を出した時点から数え、残り秒数が出て、期限で false。pi 1.3.0 のソース）。RPC でも `hasUI` は true（子は、親が UI 要求を自動で取り消す）。同梱の `permission-gate.ts` は、パターンに合うものだけを確認し、bypass の概念もタイムアウトも無い（自作の方が強い）。**実装は中断**: 2 つの worker（判定器側・ハーネス側）が、ガードのソース（`home/dot_config/pi/harness/`、`home/dot_config/agents/`、`scripts/agents/`、`home/dot_claude/hooks/lib/bashrules/`）が**読み取り専用**で、変更ゼロで戻った。`pis`（サンドボックス）では、エージェントが自分のガードを書き換えられない**設計どおりの保護**。**`pis --no-sandbox` で開き直して続行する**。指示書は `.tmp/handoff-g1g5/`（`worker-a.md`・`worker-b.md`・`README.md`・`research-queries.md`）。**もう 1 つの実測（段 U2 の未検証の穴）**: `pis` の内側から、検索のプロバイダー（`api.search.brave.com`・`api.exa.ai`・`api.tavily.com`・DuckDuckGo・OpenAlex）へ届かない（`curl` が 000、`websearch.py` が「名前を解決できない」。`explore` の子も同様）。許可は `[sandbox] shell_network_allow`（パッケージのレジストリなど 10 件）と `[web] allow_domains` で、検索のプロバイダーが無い。**サンドボックスでは、ネット調査ができない**。足すか、拒否リスト型の通信方針（CHG-0037）で対処する。
- **2026-10-25（段 G1〜G5 の実装と検証。サンドボックスの外で実施）**: `pis --no-sandbox` で開き直し、設計どおり実装した（worker A: 判定器・設定・生成器・Python 版・照合、worker B: ハーネスの確認 UI・タイムアウト・文言）。**仕様**: [pi-decide.md の confirm](../spec/guard/pi-decide.md#confirm)、[pi-guard.md の confirm の確認](../spec/guard/pi-guard.md#confirm-の確認)。**内容**: `mustConfirm`（bypass でもサンドボックスの緩和でも allow にならない ask）、確認表 `[pi.confirm] bash`（`gh pr/issue` の投稿、`gh repo fork/rename/archive`、`gh workflow`、`gh variable`、`gh gist edit/delete`）と、確認に格上げする検査 `check_gh_api_mutation`、本文を確認できない形（標準入力・コマンド置換）は deny、公開・配布の deny（`gh repo edit/create`、`gh release delete/edit`、`npm/yarn/pnpm/uv publish`、`twine upload`、`cargo publish`、`gem push`、`docker push`）、`gh api` の公開・配布に当たる操作の deny（新しい検査 `check_gh_api_publish`。TS と Python の両方。**GitHub API 経由の push 相当を塞ぐ**）。ハーネスは、確認の本文（コマンド全文、制御文字の可視化、`gh` の参考表示、`--body-file` の読み込み。再読みで差し替えを検出）、`timeout_seconds`（既定 300。TUI でも有限。時間切れは「再試行せず」）、UI 無し・子は deny、`/bypass` の文言とフッター。**検証で見つけて直した穴**: (a) `git commit -m x && gh api -X POST …` のように、先に別の ask（`check_policy_ask`）が当たると、`mustConfirm` が付かず bypass で通る → **確認に格上げする検査を、他の ask より先に引く**よう修正（試験で固定）。(b) worker B の統合試験が、規則の形（guide 形式のオブジェクト）を誤っていて 8 件が失敗 → 実際の形（前方一致の文字列）に直した。**試験**: 新規の判定器・生成器・ハーネスの試験が通過、正解データを再生成（`mustConfirm` を比較から外し、TS: ask＋mustConfirm／Python: ask か allow＋bypassed を一致とみなす。標本は除かない）。**調査**（[記録](../research/agents/permission-bypass-survey.md)）: Claude Code が最も近い設計、外部送信を既定で止める製品は無い、`gh api` の暗黙の POST（`-f`/`-F`/`--input`）や `-X` の別形への手当てを、OSS も欠く。**未確認・次**: 実際の TUI での確認画面の表示（残り秒数、長い本文）と、`gh pr create` などの確認が実際に出ること（利用者の `pis` で）。`gh api` の暗黙の POST・`-X` の別形・前置フラグの試験の追加。確認の誤入力の防止（確定キーの 0.5 秒無視）と判定の監査ログ（JSONL）は、実績を見て判断。段 G9（ブローカーでの決定的な deny）は保留のまま。
- **2026-10-25（方針の転換: deny は権限側で縛る。段 G10。制約のある環境では classic PAT のみの場合があるため、個人機と制約のある環境の機で分ける）**: 網羅調査（[記録](../research/agents/guard-design-alternatives.md)）の結果、**一次の防御を、サーバ側の権限にする**。`confirm`（ask 強制）は残し、判定器の deny は「サーバ側で塞げない物」だけに縮小する。**制約のある環境では、fine-grained PAT が使えず classic PAT だけの場合がある**ため、権限の絞り方が違う（リポジトリのロールが Admin でない場合を想定する）。classic のスコープの内訳は記憶に基づく（公式 docs の本文は未確認）。実機で確かめるまで、判定器の撤去はしない。
  - **個人機（fine-grained PAT）**: Metadata: Read（自動）、Issues: **Write**、Pull requests: **Write**、Contents: **Read**、Actions / Checks / Commit statuses: Read。**Administration・Workflows・Actions Write・Secrets・Webhooks は付けない**。対象リポジトリは必要な物だけ、期限は 30〜90 日。`~/.config/pis/github-token`（0600）に置いて `github_token_file` を設定し、`github_token_command = ["gh","auth","token"]`（広い OAuth）は外す。push は境界の外で行い、agent は push 済みのブランチへ `gh pr create` を使う。これなら公開化・削除・refs/contents の書き込み・release・マージが、サーバ側で拒否される（GraphQL も同じ権限の対象のはず。**要確認**）
  - **制約のある環境の機（classic PAT）**: `repo` スコープ 1 つで issue・PR・contents・release が全部入り、**投稿だけ許して push を許さない形は作れない**。外せるスコープは `delete_repo`・`workflow`・`write:packages`・`delete:packages`・`admin:*`・`gist` など。そのため、最小のスコープは `repo`（と、必要なら `read:org`）だけにし、**ロールが Admin でないこと**で Admin 級（公開化・設定変更・Webhook・collaborator・Pages・secrets・削除）をサーバ側で拒否させる。保護ブランチへの直接の push・マージは、ブランチ保護・ruleset（Admin でないと変更できない）で止まる。**残る**のは、非保護ブランチへの refs・contents・release の書き込み、GraphQL の `createRef`/`mergePullRequest` など → **判定器の deny は残す**。縮小できるのは、**Admin 級の REST の列挙**（`repos/{o}/{r}` の PATCH/DELETE、hooks・collaborators・pages・actions secrets など）だけで、ロールの実効を確かめてから
  - **確認手順**（個人機・制約のある環境の機とも。使い捨てのテスト用リポジトリで、サーバ側の応答を見る。判定器が先に deny する形は避け、Python で直接 HTTP を呼ぶ、または境界の外の別の `gh` で行う）: ① `gh api repos/<o>/<r> --jq .permissions`（admin/push の真偽）。② 日常の操作が通る: `gh issue list`、`gh issue create`、`gh issue comment`（`confirm`）、`gh pr create`（push 済みのブランチ。`--reviewer` やラベル付きも）、`gh pr checks`、`gh run view`。**fine-grained PAT は Web でしか作れず（作成 API は無い。公式の明記は未確認）、gh は GraphQL で追加の情報を読むため、権限不足で失敗する報告がある（cli/cli の issue 12798・9166・7978）。通らないコマンドが多ければ、個人機の絞り込みは取りやめる**（[調査](../research/agents/guard-design-alternatives.md)）。③ 403 になるか: 公開化（`PATCH repos/o/r -f private=false`）、`POST repos/o/r/git/refs`、`PUT repos/o/r/contents/x`、GraphQL の `createRef`、PR のマージ、リポジトリの削除。**個人機（fine-grained）は全部 403 になる見込み、制約のある環境の機（Admin でないロール）は Admin 級だけ 403 で、refs・contents・マージは通る見込み**（実機で確かめる）。④ 個人アカウントの fine-grained PAT で `gh repo create` が通るか、`gh` が追加で要求する権限の有無
  - **撤去の範囲**: 個人機の確認後は、**個人機では** `check_gh_api_publish` が冗長になるが、**判定器は機を問わず同じ設定を使う**ので、制約のある環境の機のために残す。縮小するなら、Admin 級の REST（制約のある環境の機でも Admin でないロールなら 403 になると確かめたものだけ）に限る。`[bash] deny` の `gh repo edit/create`・`gh release delete/edit` は「うっかり防止」の 1 行として残す。配布系 CLI の deny も残す（トークンが境界の中に無いかは、段 G6 の可視性表で確かめる）
  - **戻し方**: 403 でない操作があれば、その権限を外すか、縮小を取りやめる。**CHG-0035（Python 版の撤去）は、この件と独立**に進められる（規模の削減は、むしろこちらが大きい）
  - **状態**: 手順書のみ。コードは変えていない。**次**: 利用者が個人機の PAT と、制約のある環境の機での `.permissions` の確認結果を貼る
- **2026-10-25（段 G11 の設計: 宣言的アクション表と `guarded_action`。レビュー前）**: **問題**: `gh issue comment`・`git commit` などは、通常の ask（コマンドを見せて判断）と流れが違う。実際は、エージェントがチャットで内容を見せて承認を取り、コマンドを作り、確認画面で再度承認を求める（承認が 2 回）。承認した内容と実行されるコマンドの整合は、`--body-file` の再読みなど、コマンドの解析で守っている。**設計**: ツールを **`guarded_action` の 1 本**に固定し、操作は設定の表 `[[pi.actions]]`（`common.toml`）で増やす（ツールは増やさない）。
  - **表の項目**: `id`、`label`、`argv`（`{field}` の置換点を持つ配列。シェルを通さない）、`fields`（名前 → 型。`repo`（`owner/name` の正規表現）・`int`・`text`（複数行。`content=true` は確認画面に全文）・`enum`・`bool`（フラグ）・`list`（繰り返しのフラグ））、`preview`（読み取り専用の固定コマンド。commit は `git diff --cached --stat` とブランチ、PR は `git log base..head --oneline`）、`replaces`（この操作に当たる bash のコマンド・`gh api` の経路の一覧）、`bash`（`deny` か、表に無い形のための `confirm`）。
  - **実行**: ツールが `action` と `params` を受け、ハーネスが検証して argv を組み立て、`execFile`（シェル無し）で実行する。本文は、ハーネスが 0600 の一時ファイル（作業ツリーの外）へ書いて `--body-file` に渡す。**表示する argv と実行する argv は同一の配列**。値が `-` で始まる位置引数は拒否。
  - **確認**: 1 回だけ。承認／編集して承認／理由つき拒否。`content` を全文表示し、実行する argv も併記する。bypass でも省略不可、無反応は deny、UI 無し（子・print）は deny。承認は 1 回の呼び出しに限り、使い回せない。編集した場合は、実際に実行した最終の内容を戻り値に入れる。
  - **正しい経路へ寄せる設計（誤って bash や `ask` へ行かせない）**: ① `replaces` に当たる bash は **deny**（ask にしない。承認の抜け道を作らない）。評価の位置は、`[bash] allow`・`skill_scripts`・`[bash] ask` より前（confirm 表と同じ。bypass でも外れない）。複合コマンド・`git -C x commit`・`bash -c '…'` の形も、既存の意味解析で当てる。**解析できない形でも、`gh … comment` のような語が含まれるなら fail-closed で deny**。② **deny の理由に、`guarded_action` の呼び出し例（`action` と、コマンドから解析できた `params`）をそのまま入れる**（既存の「誘導 deny の具体的な言い換え」と同じ仕組み。モデルはそのまま再発行できる。解析できなければ、一般の案内）。③ `gh api` の同じ操作（`POST repos/o/r/issues/N/comments` など）と `curl`/Python 経由の同等の投稿も、`replaces` の経路として当てて、同じ案内にする（別の道へ流れるのを防ぐ）。④ ツールの説明・スニペット・ガイドラインに、「投稿・コミットはこのツール。承認はこのツールが取る。**事前にチャットや `ask` で承認を取らない**」と書き、操作の ID と引数を 1 行ずつ自動で載せる。`ask` ツールの説明にも「投稿・コミットの承認には使わない」と入れる。⑤ 未知の `action`・足りない引数は、使える ID・必須の引数を返すエラーにして、モデルが自己修正できるようにする。⑥ このツールを持たない役割（読み取り役・探索役）と子エージェントには、bash の deny の理由を「この役割では実行できない。下書きを親へ返す」に切り替える。⑦ 計測: 誘導 deny と同様に、`replaces` による deny の件数と、その後に `guarded_action` が呼ばれた割合をセッションのログから集計する（目標: 誤った経路の割合 1% 未満。導入前の `git commit`・`gh … comment` の bash の呼び出し数を、先に集計して基準にする）。
  - **最初の表**: `gh_issue_comment`・`gh_issue_create`・`gh_pr_create`・`gh_pr_comment`・`git_commit`。表に無い形（`gh pr edit` など）と `gh api` の書き込みは、今の `[pi.confirm]` のまま。新しい操作は表に 1 項目足すだけ（ツールの追加なし）。
  - **段取り**: ① 設計の `review` ② 表のスキーマと生成器（検証 → `rules.json`、TS・Python の判定器と正解データ） ③ ハーネス（ツール・確認画面・実行器・試験） ④ 判定器（`replaces` の deny と案内） ⑤ 最初の表 ⑥ 実機確認と docs。
  - **懸念（`review` に確認）**: モデルが `params` の入れ子を正しく作れるか、引数の注入（`-` 始まり・改行・`--` の扱い）、一時ファイルの権限と掃除、`replaces` が正当なコマンドを塞ぐ範囲、解析の fail-closed の誤検出、子エージェントの扱い、`git commit` の hook（pre-commit）の出力と失敗時の再試行、`gh` の既存の `[pi.confirm]` との併存。
- **2026-10-25（段 G11 のレビュー結果と、見直した段取り）**: 独立 `review` の指摘（BLOCKER 1・MAJOR 3・MINOR 1）を受けて設計を直した。**①「誘導」と「強制」を分ける**: 誤った経路へ行かせない仕組み（`replaces` の deny と案内、ツールの説明）は、通常のモデル操作を寄せる**うっかり防止**で、経路の強制ではない（Python・curl・`git commit-tree`・alias は迂回できる）。強制が要る GitHub 操作は、段 G10（権限・ブローカー）で行う。**② commit の同一性**: プレビュー時に、リポジトリ・HEAD・ブランチ・index のツリーハッシュ（`git write-tree`）を固定し、**実行直前に照合**して、不一致なら再承認にする。プレビューのコマンドは、設定からは指定できず、**コードの許可リスト**（読み取り専用の固定の argv）に限る。hook による実行中の変更までは保証しない（明記）。本文ファイルは、排他的作成・0600・終了時に掃除し、承認後に再読みしない（引数の値は `-` 始まり・改行・`@file` 形式を、フィールドごとに検証）。**③ 事前承認の指示との衝突**: 今のグローバル指示と `commit` スキルが、コミット承認を `ask` で取るよう要求しており、**二重承認の主因**になっている。`pis` では確認画面が承認の場になるよう、適用範囲つきで指示を直し、`ask` ツールの説明にも書く。**④ 退路**: `replaces` に当たる bash は**常に deny**（`bash=confirm` の併用はしない。直接 bash へ戻る誘因になる）。対応外のフラグは、表に足すか、利用者に手動実行を依頼する。**⑤ 呼び出し例**: 解析した値は「候補」と表示し、曖昧なら ID のみ案内する。**語だけの fail-closed はやめ**、既存と同じ正規化したセグメント単位で照合する（誤検出は正解データで固定）。**見直した段取り**: 段階 1（軽い）= 指示の整理（グローバル指示・`commit` スキル・`ask` の説明）と確認画面の表示の見直し、導入前の基準の集計（`git commit`・`gh … comment` の bash の呼び出し数、直前の `ask` の有無）。段階 2 = `guarded_action` の最小実装（`git_commit` と `gh_issue_comment` の 2 操作。型つきの表。同一性の照合、一時ファイル、承認 1 回、bash の同じ操作は deny + 案内）。段階 3 = 実測の後で、表を一般化（新しい操作は表に足すだけ）。利用者の判断（2026-10-25）: 段階 1 → 段階 2 を続けて進める。全 tool の構成の整合を `review` で確かめ、整っていれば実装を始める。
- **2026-10-25（段 G11 段階 2 の実装と検証）**: 設計は 2 回の独立 `review`（設計、ツール全体の構成）を経た。**条件**（段階 1 で承認の指示を先に有効化しない、判定器と役割制限を通る設計を明示する、親の実装役のみに登録する、文言を揃える）を反映した。**実装**: 表 `[[pi.actions]]`（`gh_issue_comment`・`git_commit`）と生成器の検証、判定器（TS・Python。`action` は役割の許可だけで allow、`replaces` に当たる bash は `action` を持つ役割だけ deny＋呼び出し例）、ハーネスのツール `guarded_action`（確認 1 回、承認後の HEAD・index の照合、本文ファイル、`execFile`）、文言（`guarded_bash`・`ask`、グローバル指示、`commit` スキル）。仕様は [pi のガード](../spec/guard/pi-guard.md#guarded_action承認つきの外部操作)。**導入前の基準**（`scripts/agents/measure_routing.py`、71 セッション）: 投稿・コミットの bash の直接実行 275 回、うち直前に `ask` で承認を取ったもの 60 回（約 22%）。**検証で直した**: implementer に `action` を足したので、implementer の `git commit` と `gh issue comment` は deny になる。従来の `git commit` の確認画面・preflight の試験は、`action` を持たない役割・別の ask の例で確かめる形に直した。全件検証 exit 0。**未確認・次**: 実際の TUI での確認画面（3 択、長い本文、editor）、サンドボックス内の `gh` の実機、`git commit` の hook が失敗したときの運用、導入後の再計測（bash の直接実行の割合）。段階 3（表の一般化、`gh pr create`・`gh issue create`・`gh pr comment` などの追加）は、実測の後。

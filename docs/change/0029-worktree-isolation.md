# CHG-0029: 子エージェントの実装作業を git worktree で分離し、検証を子の隔離環境で回せるようにする

- **状態**: In progress
- **更新日**: 2026-10-23
- **基準**: コミット 171cf25、pi 1.3.0。`worker` は親と同じ作業ツリーを共有し、git の状態を変える操作を禁じている

## 目的と非目的

- **目的**:
  1. 並列の `worker` が、互いの編集と親の未コミットの作業を壊さないようにする
  2. `worker` の編集結果を、親が差分として確かめてから取り込む
  3. 子の中で検証（`pytest` など）を回しても、被害が子の作業ツリーに限られる形にする。完了時の自動検証と、将来の検証専用の子の土台になる
- **非目的**: `explore` / `review` / `commit` の隔離（読むだけで、親の未コミットの状態を見る必要がある）。人が並列に使う pi セッションの worktree。
  取り込みの自動化（`merge` は親または利用者の操作）。Windows の素の pi（フルガードが無い）。公開拡張の導入（[ADR-0016](../adr/0016-pi-extensions-own-first.md)）

## 実施計画

段ラベルは `W0a` / `W0b` / `W1` / `W2` / `W3`。状態は 2026-10-22 時点。

| 段 | 解決したいこと | 内容 | 状態 |
| --- | --- | --- | --- |
| W0a | 隔離の前提のうち、Fence なしで確かめられるものが実装の前に分からない | 使い捨てのリポジトリで、スナップショット（一時 index・未追跡・ignored・サブモジュール・容量と秘密の選別）、差分と取り込み（E3）、並列作成と掃除（E5）、ref と `git gc` の保持関係を確かめる | 完了（2026-10-22。結果は「現在地」の W0a の実測。秘密の選別の方式と、容量の上限は W1 の前に決める） |
| W0b | **子の書き込み境界がどこにあるか、設計の前提が逆だった**（`review`） | `pis` の実機（Fence）で、子の cwd を別の場所に移したときの実効の書込可を調べ、境界の方式を選ぶ（E1・E2・E4）。成果物と記録の保管場所を子から書けるかも確かめる | E1・E2・E4 は完了（「現在地」の W0b の実測）。入れ子は、`fence` は不可、Landlock は可（「現在地」の入れ子の実測）。残りは、実際の `pis` の Fence での確認 |
| W1（最小段。**W0b の後でなければ始めない**） | `worker` 同士・親の作業が混ざる | 事前選別 → 作成 → 停止後の確実な回収 → 起動時の警告と手動復旧。**取り込みは作らず、利用者が差分（patch）を確認して手動で `git apply` する** | 実装は完了（S0〜S4。2026-10-23）。S5（利用者の実機 `pis` での通し確認）待ち |
| W2 | 完了結果の正しさを、子の言葉でなく事実で確かめたい。取り込みを安全に自動化したい | 取り込み（`integrate`。受入条件は「W1 の前に決める仕様案」の取り込みの節）。完了時にハーネスが検証を worktree の中で実行して通知に付ける。取り込み前に、安全に直結するファイルの変更を検出する。`.worktreeinclude` 相当（ignored のファイルを選んでコピー・リンクする仕組み）、読み取り専用のリンク、書込可の追加の承認（詳細は「大きなデータと外部フォルダ」） | 未着手（W1 の後） |
| W3 | 作業ツリーの共有が理由だった git 制限と、期待値を決める人の分離が残る | `worker` のコミット許可を見直す。期待値のファイルの扱いを決める | 未着手（W1・W2 の後） |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り

## 現在地

- **先行例**（[記録 P6](../research/agents/pi-public-extensions-survey.md#記録-p6--2026-10-22-worktree-隔離の先行例と-p1p5-の訂正)。Claude Code・Codex・Cursor は、[記録 P7](../research/agents/pi-public-extensions-survey.md#記録-p7--2026-10-22-worktree-隔離の先行例の比較-claude-codecodexcursor)）:
  `@gotgenes/pi-subagents-worktrees` 0.3.3 と `@tintinweb/pi-subagents` 0.22.0 の配布物を、ハッシュを照合して読んだ。
  - 共通: 一時の作業ツリーを HEAD から `--detach` で作り、完了時に変更があれば `git add -A` → コミット → ブランチ `pi-agent-<id>` に残して作業ツリーを消す
  - `@gotgenes` の工夫: 作成に失敗したら**子の実行を失敗にする**（黙って共有ツリーで動かさない）。後片付けが未確定なら**消さずに残し**、起動時に警告する。削除は利用者のスラッシュコマンドだけで、モデルには渡さない。統合は対象外（利用者の仕事）
  - `@tintinweb` の弱点: 作成に失敗すると黙って共有ツリーで動く。後片付けの失敗で強制削除する（作業を失いうる）。コミットは常に `--no-verify`
  - 両者とも、**コミットの hook を飛ばす**（`--no-verify`）。このリポジトリは `--no-verify` を禁じている
- **このリポジトリの条件**:
  - `worker` の git 制限の理由は「作業ツリーを共有するため」（`common.toml.tmpl` の `[pi.profiles.worker]`）。worktree で分ければ緩められる見込みだが、共有の `.git`（`refs` と `objects`）は子から書ける
  - Fence は、**親の起動時の cwd**（`boundary.py` が `allowWrite` に入れる）と共有 `.git`、`~/.cache` を書込可にする。**`~/worktrees` は読み取り（`work_read`）だけで、書込可ではない**（`common.toml.tmpl`）。子はこの Fence と環境を継ぐ。`/tmp` は hook が `.tmp/` へ誘導する
  - linked worktree では `.git` がファイルになる（`checkpoint.py` と `docs/spec/checkpoint.md` に既存の注意）
  - HEAD から作る worktree には追跡されたファイルだけが入る。しかしこの案の**スナップショットは `git add -A` を使うので、未追跡で ignored でない秘密（`.env` など）が共有 `.git/objects` に入りうる**
  - 作業中の変更はコミット承認の制のもとで**常に未コミット**。HEAD から作ると、親や他の `worker` の変更が子に見えない
- **W0a の実測（2026-10-22、git 2.43.0、使い捨てのリポジトリ。`.tmp/w0a.py` と `.tmp/w0a2.py`。本物のリポジトリには書いていない。`clone` だけ参考に作った）**:
  - **スナップショット**（一時 index で `read-tree HEAD` → `add -A` → `write-tree` → `commit-tree -p HEAD`）: 追跡ファイルの変更、**未追跡で ignored でないファイル（`.env` を含む）**、シンボリックリンクが入り、ignored は入らない。実 index と refs は変わらず、**hook は走らない**（`pre-commit` のマーカーで確認）
  - **worktree**（`git worktree add --detach <スナップショット>`）: 親の未コミットの状態を再現して clean。`.git` はファイル。**このリポジトリ（927 ファイル、14.6 MB）で、作成 0.21 秒、並列 4 つで合計 0.23 秒、削除 4 つで 0.13 秒**
  - **回収と取り込み**: 結果を `refs/pi-agent/<id>` に残し、`git diff --binary --full-index --no-renames <起点> <結果>` の patch を `git apply`（`--index` 無し。実 index は触らない）。追跡ファイルの変更（親の別の未コミットの変更を保つ）、親で未追跡だったファイルの編集、削除、新規、実行ビット、バイナリ、CRLF、リネーム（追加と削除として）が、すべて往復できた。**patch は、`subprocess` のテキストモードを通すと CRLF が壊れる**（最初の実験の誤りの原因）。バイナリで扱う
  - **衝突**: 親が同じ行を編集、子の新規ファイルと同名を作る、子が削除したファイルを編集、のとき `git apply --check` が拒否し、**親は何も変わらない**（事前に存在する衝突での拒否まで。並行編集と適用途中のエラーは未実測）。長いファイルの中央の変更は、親が先頭に 1 行足し、別の行を編集していても、行のずれを許容して適用できた。ただし、**5 行ほどの短いファイルで、hunk が端に接していると、端に固定されて拒否される**
  - **gc**: `refs/pi-agent` の結果と、その親のスナップショットは `gc --prune=now` でも残る。ref を消して `gc --prune=now` すると、使い捨てのリポジトリでは、スナップショットの `.env` を含むオブジェクトも消えた（実リポジトリの共有 `.git` で同じになる保証は無い）
  - **共有 `.git`**: worktree の中から、本体の refs を書ける（`update-ref`・`branch` が効く）。`git worktree list` で他の worktree が見える（E2 の一部。実機の Fence での確認は W0b）
  - **サブモジュール**: **このリポジトリには 2 つある**（`.gitmodules`。Windows のアプリデータ用）。スナップショットは gitlink（160000）として記録し、worktree ではサブモジュールのディレクトリは空。親のサブモジュールの中の未コミットの変更は、起点に入らない（pi の作業への影響は小さい）
- **W0b の実測（2026-10-22、WSL、利用者の `pis` の実機。`scripts/agents/w0b_probe.sh probe` と E4 の 3 操作）**: `~/worktrees/w0b/wt1`（使い捨ての `main` の linked worktree）を cwd にして `pis` を起動した。
  - **E1（通る）**: `git status`、ファイルの編集、`git add`（`.git/worktrees/<id>/index`）、一時 index での `read-tree` と `add -A`、`write-tree`（共有 `objects`）、`commit-tree`、`update-ref refs/pi-agent/*`。本体の `.git` の `worktrees/`・`objects`・`refs` への書き込みが、Fence で許されている
  - **E2（拒否）**: 兄弟の worktree、本体の作業ツリー、本体の `.git/hooks`、本体の `.git/config`、ホーム直下（いずれも Read-only file system か Permission denied）。**コード実行につながる `hooks` と `config` は書けない**
  - **E2（通った。期待と違う）**: `update-ref refs/heads/<新しい名前>`。子は、ブランチの作成・削除・付け替えができる。対策は、判定器で、子の `git update-ref`・`branch`・`tag`・`symbolic-ref`・`worktree` を拒否すること（W1 の前に決める）
  - **E4（期待どおり）**: `wt1` の中への `write` は通り、`../main/x.txt` への `write` は拒否され（サンドボックスの外）、`wt1/.env` の `write` と `read` は `**/.env` で拒否された
  - **結論**: Fence は linked worktree を扱える。子の書込境界を worktree に移せば、「子の被害が、自分の worktree と共有の `objects`・`refs` に限られる」を、`refs/heads` 以外について満たす。**独立 clone は、この点では不要**
  - **この実測で未確認**: `wt1` で `pis` を起動した場合の結果であり、運用で必要な「親の `pis`（cwd = 本体）が、子の `pi` を、worktree を cwd にした新しい Fence の下で起動する」ことは確かめていない（下の「入れ子の調査」）
- **入れ子の調査（2026-10-22、`explore`。コードを読んだ推測で、実行はしていない）**: 子は今、同じ Fence の中で素の `pi` として起動される（`children.ts:207`、`spawn(..., { cwd: ctx.cwd })`。`pi-guard.md` の「同じ Fence の中で動く」）。Fence の実体は外部バイナリ `fence`（bubblewrap・Landlock・seccomp）で、`pis` が `fence --settings <json> -- <cmd>` を起動する。内側から `pis` を再起動する経路は、次の点で通らない見込みが強い: `ocs` の状態領域（`~/.local/state/opencode-sandbox`）が内側から見えない、agent 置き場（`~/.local/share/pi-sandbox`）を内側から作れない、`~/.local/share/ocs` の読み取りが未確認、カナリアが親の環境変数に依存する。`fence` 自体の入れ子（user namespace、`no_new_privs`、seccomp）は未確認で、リポジトリの docs に記述が無い。確かめる実験の案は 2 つ: (1) Fence の外の端末で `fence --settings <最小の設定> -- fence --settings <最小の設定> -- true`、(2) 実機の `pis` の中から `pis --check`
- **入れ子の実測（2026-10-22、WSL、親の Fence の外の私の環境で実行。`fence` 0.1.67、Landlock ABI 7）**:
  - **`fence` の入れ子は不可**: `fence -- sh -c 'fence -- sh -c ...'` は内側で `bwrap: setting up uid map: Permission denied` で失敗する。子の `pi` を、新しい `fence` の下で起動する案は成立しない
  - **Landlock の入れ子は可**: `fence --settings <最小の設定（.tmp だけ書込可）> -- python3 <使い捨てのスクリプト>` の中で、ctypes から `landlock_create_ruleset`・`add_rule`・`restrict_self` を呼び、書込可を 1 つのディレクトリ（`a`）に狭めた。外側の Fence が書込可にしている兄弟のディレクトリ（`b`）への書き込みは `Permission denied` になり、`a` への書き込み・読み取り・実行は通った（Fence なしでも同じ結果）
  - **意味**: 子ごとの書込境界を、親の Fence の内側で、さらに狭められる。ただし、**狭められるだけで広げられない**ので、子が書く領域（worktree、共有 `.git` の `worktrees/<id>`・`objects`・`refs/pi-agent`、`~/.cache`）は、親の Fence がすでに書込可にしている場所でなければならない。親の cwd（本体のリポジトリ）の下の `.tmp/` に worktree を置く案が自然で、`~/worktrees` は読み取りだけなので使えない。W0b の結果と合わせると、`refs/heads` は Landlock の許可から外せるので、**子が `refs/heads` を書ける穴も、判定器に頼らずにふさげる**（推測。未実測）
  - **実装の形（案。未実測）**: 子の起動を、小さなラッパー（標準ライブラリだけの Python。ctypes で上の 3 つを呼ぶ）で包む: `python3 landlock_exec.py --write <worktree> --write <.git の必要な場所> ... -- pi ...`。カーネルの ABI 版に応じて、扱うアクセスの種類（`REFER`・`TRUNCATE` など）を変える必要がある。使い捨てのスクリプトは `.tmp/landlock_try.py`（コミットしていない。ABI 1 の種類だけを扱う）
  - **未確認**: 親の実際の `pis` の Fence の中での実行（今回の確認は、最小の設定の Fence）。`uv`・`pytest` が、狭めた許可で動くか。Landlock が使えないカーネル（ABI なし）での振る舞い（拒否して起動しない、が案）
- **Landlock ラッパーの試作の実測（2026-10-22、WSL。`scripts/agents/w0b_landlock.py` と `w0b_probe.sh nest`）**: 書込可を、worktree、共有 `.git` の `worktrees/<id>`・`objects`・`refs/pi-agent`、`~/.cache`、tmp、`/dev/null` に絞って子のコマンドを包んだ。
  - **通った**: `git status`、編集、`git add`、`update-ref refs/pi-agent/*`、`python3`、`uv run`、`uv run pytest`
  - **拒否された**: `update-ref refs/heads/*`、`git tag`（`refs/tags`）、兄弟 worktree・本体の作業ツリー・本体 `.git/hooks` への書き込み
  - **条件**: (1) Fence なし、(2) 親を模した Fence（wt1・共有 `.git` の `worktrees`・`objects`・`refs` 全体・`~/.cache`・`/tmp` が書込可。`refs` 全体が書込可でも、Landlock が `refs/heads` と `refs/tags` を拒否した）の 2 通りで、同じ結果だった
  - **試作で見つけた不具合**: `git` は `/dev/null` を読み書きで開くので、書込可に含める必要がある。Landlock はファイルに対して、ディレクトリ用の権限（`MAKE_*` など）を指定できないので、ファイルは別の権限の集合にする（`w0b_landlock.py`）
  - **未確認**: 利用者の実際の `pis` の Fence の中での実行（`wt1` で `pis` を起動し、`!sh scripts/agents/w0b_probe.sh nest`）。ネットワークが要る `uv` の操作。`REFER`（ディレクトリをまたぐ名前変更）が要る操作
- **実際の `pis` の境界での実測（2026-10-22、私の環境で。LLM は使わない）**: `ocs` のモジュール（`boundary.build_boundary`）が、`wt1` を cwd にして組み立てる Fence の設定を取り出し、その下で `w0b_probe.sh nest` を実行した（`.tmp/real_fence_nest.py`。未コミットの使い捨て）。設定の中身は、書込可が wt1・`~/.cache`・境界用の agent 置き場・本体の `.git` 全体、書込不可が `wt1/.opencode`・本体の `.git/hooks`・`.git/config`。結果は、親を模した Fence の実測と同じ: `git status`・編集・`git add`・`update-ref refs/pi-agent/*`・`python3`・`uv run`・`uv run pytest` が通り、`refs/heads`・`refs/tags`・兄弟・本体の作業ツリー・`hooks` が拒否された。**本体の `.git` 全体が書込可でも、Landlock が `refs/heads` と `refs/tags` を拒否した**。この実測で未確認なのは、`pis` の起動全体（中継、事前検査、内側の環境変数、実際の `pi` が子を起動する経路）と、利用者の端末での実行
- **S0 の実測（2026-10-23、WSL。`ocs` が組み立てる実際の境界（親の cwd = リポジトリ根）の内側で、Landlock のラッパー（`scripts/agents/w0b_landlock.py`）越しに、`pis` と同じ内側のコマンド（`inner_command`）で子の `pi`（偽モデル）を起動。LLM は使わない。`.tmp/s0_probe.py`。未コミットの使い捨て）**:
  - **子の `pi` は、ラッパー越しに、実際の境界の下で 1 往復を終えられる**（`python3` も Fence の下で起動できる）
  - **往復だけに必要な書込可は `agent_dir`（`PI_CODING_AGENT_DIR`。認証・設定のロックファイルを作る）だけ**。外すと `EACCES: mkdir '.../auth.json.lock'` で失敗する。`wt`・`.git/worktrees/<id>`・`objects`・`refs/pi-agent`・`~/.cache`・`/tmp`・`/dev/null`・`/dev/tty` は、往復だけなら要らない
  - **作業の最小**（ファイルの書き込み、`git status`、`git diff`、`ls` を子のツールで実行）: `wt`、`/dev/null`（`git` が開く）、`agent_dir`。`uv run`・`uv run pytest`・`/tmp` と `~/.cache` への書き込みには、`~/.cache` と `/tmp` が要る。**`git add` には、`wt` の `gitdir`（`.git/worktrees/<id>`）と共有の `objects` の両方が要る**（`gitdir` だけでは失敗）。**`/dev/tty` は要らない。`refs/pi-agent` は、子には要らない**（回収はハーネスが子の外で行う）
  - **拒否の確認**（書込可 = `wt`・`/dev/null`・`agent_dir`・`~/.cache`・`/tmp`・`gitdir`・`objects`）: 親の作業ツリーへの書き込み、`update-ref refs/heads/*`、`git tag`、本体 `.git` の `hooks` への書き込み、`.git/config` の変更、`refs/pi-agent` への書き込み、ホーム直下への書き込みは、すべて拒否された
  - **計画への反映**: 子の Landlock の書込可は、`wt`、`wt` の `gitdir`、共有 `objects`（`git add` を許すとき）、`agent_dir`、`~/.cache`、`/tmp`、`/dev/null`、存在するデバイス（許可リストのもの）にする。**`refs/pi-agent` と `/dev/tty` は含めない**。`objects` を外せば、子は共有の `objects` に書けなくなるが、子の `git add` が失敗する（子が `git add` を要するかは未確認）
  - **この実測で未確認**: 印刷モード（`-p`）での偽モデルの 1 往復であり、`rpc` モード（実際の子の起動）、実際の MCP とキャッシュ、実際のモデルは、S5 の実機で確かめる。`agent_dir` は親と共有で、凍結したパス（`settings.json` など）は Fence が書込不可にしているが、ラッパー越しの子から書けないことは、明示的には確かめていない
- **`review`（2026-10-22）の指摘**:
  - **BLOCKER**: Fence の書込可は親の起動時の cwd で、子はそれを継ぐ。子の cwd を `~/worktrees` に移しても、子の編集は拒否される見込みで、親の cwd への書込可も残る。「親を書き換えられない」という必須の条件を、コマンドの deny だけでは証明できない
  - **MAJOR**: スナップショットが秘密を Git オブジェクトへ永続化しうる（伺字化はツールの返答に掛ける処理で、ファイルや patch を書く前の秘匿処理ではない）。共有 `.git` の書込可と、`hooks` / `config` の拒否は子向けに境界を生成した場合の設定で、親の cwd から継いだ境界で効くかは未確認。子のコマンドの deny（`update-ref`・`worktree`・`branch`）は誤操作の抑止で、隔離の保証ではない
  - **MAJOR**: `git apply --check` は、この起点からの往復を保証しない（スナップショットで初めて追加した未追跡ファイルの編集・削除、親が後から同名を作る・同じ行を編集する、`--check` と適用の間の編集）
  - **MAJOR**: job の寿命（`keep` の追加依頼、失敗・中断）と成果物の寿命が違う。各往復で回収するか、job を閉じてからか、ハーネスが落ちたときの未回収の発見をどうするか。起点・worktree・結果 ref・patch の対応を永続記録し、再起動時は削除せず一覧・警告から復旧する。TTL による自動破棄は勧めない
  - **判断（利用者、2026-10-22）**: 設計の方向（起点＝スナップショット、回収＝プラミングで `refs/pi-agent`、場所＝`~/worktrees`）を踏まえて、実測の前に `review` へ。場所は境界の方式を選ぶまで保留
- **`review`（2026-10-22、仕様案への 2 回目）の指摘**: 仕様案を直した（「W1 の前に決める仕様案」）。BLOCKER は 1 件で、秘密の検査が `git add` の後にあり、オブジェクトを共有 `.git` へ書いた後では遅い。MAJOR は、パス規則の限界、未取り込み成果物の期限掃除、`integrate` の原子性が未証明、復旧記録の競合と改ざん、`gc --prune=now` の組み込み。MINOR は、子の終了確認と中断後の状態の不足
- **未確認**: `@gotgenes` と `@tintinweb` の実機での挙動。Claude Code の公式 docs（記録 P7 で読んだ。一次。取り入れた点は「W1 の前に決める仕様案」）。Orca の worktree 運用。このリポジトリで、普段 `read_deny_globs` に当たる未追跡ファイルがあるか（git が実行できず未確認）

## 未解決点

W0a と W0b の実測の対象（E1・E2・E4 は 2026-10-22 の W0b で、E3・E5 は W0a で実測済み。結果は「現在地」）。実測前の記述は時点を残している。

- **E1**（W0b で実測済み: 通る。「現在地」参照）: Fence の下の子が、linked worktree で `git status` とファイルの編集、`uv run pytest` を実行できるか（`.git/worktrees/<id>/` への書き込みが要る）
- **E2**（W0b で実測済み: 兄弟・本体の作業ツリー・`.git/hooks`・`config` は拒否。`update-ref` は通った。「現在地」参照）: 子が、兄弟の worktree・本体の `.git` の `hooks` と `config`・親の作業ツリーに書けるか（書けるなら、隔離の効果が限られる）
- **E3**（W0a で実測済み。「現在地」参照）: スナップショットの往復。親が未コミットでも、子の差分を `git apply` で取り込めるか。バイナリ・実行ビット・改行の扱い
- **E4**（W0b で実測済み: 期待どおり。「現在地」参照）: `~/worktrees` 配下の子の cwd が、判定器の「作業ツリーの中」の判定と、`protected` の相対パスで正しく扱われるか
- **E5**（W0a で実測済み）: このリポジトリで、作成と削除に何秒かかるか（並列 4 つのとき）
- **判定器の追加**: 子が共有 `.git` に対して、`git branch -D`・`update-ref`・`worktree remove` などで本体を壊せるか。deny に足す必要があるか
- **境界の方式**（W0b。最優先）: 子の書込境界を、worktree に移す方法。候補は、子ごとに境界を作り直す（worktree を起動 cwd にした Fence）、独立 clone。親の Fence を継いだまま cwd だけ移す案は、境界が移らないので成り立たない
- **スナップショットの対象と秘密**（W1 の前に決める。仕様案の最初の節）: `git add` の前に、候補のパスを検査し、容量を測る。当たったら起動を止める。結果の ref・patch の保存権限
- **取り込みの規則**（W2 の受入条件。仕様案の取り込みの節）: 排他、適用直前の再確認、途中失敗からの復旧、複数の pi プロセスと dirty な親、bypass 中の確認
- **job の寿命と成果物**（W1 の前に仕様にする）: 回収の契機、永続する対応記録（起点・worktree・結果 ref・patch）、再起動時の復旧、手動の破棄の操作

## 次の調査・実験

- E1〜E5 のうち、E1・E2・E4 は W0b として `pis` の実機（Fence）で行う（利用者の端末が要る）。E3・E5 は W0a で済み
- Claude Code と Orca の worktree 運用を、公式の資料で確認する（Claude Code は記録 P7 で読んだ。Orca は未読）

## W0b の手順

利用者の端末（`pis` を使える環境）で行う。所要は数分。使い捨てのリポジトリだけを触り、本物のリポジトリには書かない。

1. **作成**（Fence の外のシェルで 1 回）: `sh scripts/agents/w0b_probe.sh setup`。`~/worktrees/w0b` に使い捨ての `main` と、linked worktree の `wt1`・`wt2` ができる。
2. **E1・E2（書込境界）**: `cd ~/worktrees/w0b/wt1` して `pis` を起動し、その中で（`pis` のシェル経由で）`sh <このリポジトリのパス>/scripts/agents/w0b_probe.sh probe` を実行して、出力の表を貼る。
   - 表の上半分（E1）は「通る」が期待。ここが拒否されると、worktree を起動 cwd にした境界では、`git add` などの通常の作業ができない。
   - 下半分（E2）は「拒否」が期待。通ると、その経路は隔離の効果を持たない（兄弟・本体の作業ツリー・本体の `hooks` と `config`・`refs/heads` へ書ける）。
   - 基準として、Fence なしの環境では全項目が「通った」（2026-10-22、WSL）。
3. **E4（判定器の「作業ツリーの中」の判定）**: 同じ `pis` の中で、次の 3 つをエージェントに頼む。(a) `wt1` の中のファイルを `write` で作る（通るはず）。(b) `../main/x.txt` を `write` で作る（拒否されるはず）。(c) `wt1` の中に `.env` を作り、読む（保護対象として拒否されるはず）。結果を貼る。
4. **後片付け**（Fence の外のシェルで）: `sh scripts/agents/w0b_probe.sh clean`。

結果で、境界の方式（子ごとに、worktree を起動 cwd にした境界を作る／独立 clone）を選ぶ。W1 は、この結果の後でなければ始めない。

## 評価基準

- **必須**:
  - 親の未コミットの作業が、失われず、子に書き換えられない
  - 子の被害が、自分の作業ツリーと、専用の ref（`refs/pi-agent/`）、共有 `objects` への不要なオブジェクトに限られる（W0b と Landlock の実測で、`refs/heads` と `refs/tags` は拒否できると分かった。「専用の ref だけ」とは言わない）
  - 作成に失敗したとき、黙って共有ツリーで動かさない
  - コミットの hook を飛ばす操作（`--no-verify`）を使わない
  - 親への反映は、利用者の明示的な操作で行う（W1 は利用者の手動の `git apply`。W2 以降の `integrate` は、衝突したら何も変えないことを受入条件にする）
  - 秘密のパスを、共有 `.git` へオブジェクトを書く前に検査する（内容中の秘密は保証しない）
- **望ましい**: 作成が数秒以内。残った作業ツリーが取り残されない（起動時に警告）。ディスクと件数の上限

## 候補比較

| 論点 | 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- | --- |
| 起点 | HEAD から作る（先行例） | 単純 | 未コミットの変更が子に見えない。この運用は常に未コミット | — | 見送り | — |
| 起点 | 親の作業ツリーのスナップショットから作る | 未追跡（ignored を除く）を含めて子に渡せる。hook の走らない git のプラミングで作れる（一時の index で `add -A` → `write-tree` → `commit-tree`） | 実装が増える。バイナリ・実行ビットの扱い | 実測済み（W0a） | 採用（推奨。秘密の事前検査が前提） | — |
| 起点 | 親に事前コミットを要求する | 仕組みが要らない | コミット承認の制と衝突する | — | 見送り | — |
| 回収 | ブランチにコミット（先行例） | 利用者が `git merge` できる | hook が失敗したとき `--no-verify` が要る（方針と衝突） | — | 見送り | — |
| 回収 | プラミングで `refs/pi-agent/<job id>` に残し、差分を `.tmp/subagents/<通番>-<job id>.patch` にも書く | hook が走らない。`--no-verify` が要らない。ブランチ一覧を汚さない | 利用者が慣れた `git merge` が使えない（`git diff` と `git apply` を使う） | 実測済み（W0a） | 採用（推奨） | — |
| 取り込み | `git merge`（先行例の想定） | 標準の道具 | 親の作業ツリーが未コミットだと、重なるファイルがあれば拒否される | — | 見送り | — |
| 取り込み | W1: 利用者が patch を確認して手動で `git apply` | 親へ書く操作をハーネスが持たないので、排他・途中失敗・bypass の問題が起きない | 利用者の手間が残る | — | 採用（W1） | — |
| 取り込み | W2 以降: `git apply --check` で確かめてから `git apply`（`integrate`） | 子の変更だけが対象。事前に存在する衝突は、何も変えず拒否できる（W0a） | 並行編集・適用途中のエラーでの無変更は未証明。bypass が ask を allow にする | 受入条件（仕様案の取り込みの節） | 保留（W2） | W2 |
| 場所 | `os.tmpdir()`（先行例） | 単純 | hook が `.tmp/` へ誘導する。Fence の書込可の範囲に無い | — | 見送り | — |
| 場所 | `~/worktrees/pi-agent/<リポジトリ名>/<job id>` | 読み取りの許可（`work_read`）がある | **書込可ではない**（`review`）。判定器の「作業ツリーの中」の判定も確かめる必要がある | E4 | 保留（境界の方式を選ぶまで） | W0b |
| 境界の方式 | 親の Fence を継いだまま、子の cwd だけを worktree に移す | 実装が小さい | 書込境界が移らない（子の編集が拒否されうる）。親の cwd は書込可のまま | W0b で確認 | 見送り | — |
| 境界の方式 | 子ごとに、worktree を起動 cwd にした境界（Fence）を作り直して起動する | 子の書込可が worktree に移る見込み。`ocs` の linked worktree の扱いがある | 境界の起動と管理が増える。共有 `.git` の書込可は残る | E1・E2 | 有望（要実測） | W0b |
| 境界の方式 | 独立 clone（`.git` を共有しない） | 共有 `.git` を壊せない | Git のデータと同期の費用が増える | 容量と時間 | 保留 | W0b の結果次第 |
| 起点の選別 | `git add` の前に、候補のパスを列挙して検査し、容量を測ってから、一時 index に `add` する | 秘密のオブジェクトを共有 `.git` に作らずに止められる。容量の事前測定と一時 index は `backup.py` に先例がある（秘密検査の先例ではない） | 一覧の維持と、誤検出。パス規則は内容中の秘密を見つけない | 検査の方式の一致試験 | 有望（推奨） | W1 の前 |
| 対象 | 役割ごとの opt-in（`[pi.agents.worker] workspace = "worktree"`。既定は `shared`） | 読むだけの子は隔離が要らない。設定で切り戻せる | 設定項目と生成器の変更 | — | 有望（推奨） | W1 |
| 失敗時 | 作成に失敗したら子を起動しない | 隔離したいときに、黙って共有で動かさない（`@gotgenes` 方式） | 失敗が作業を止める | — | 採用（推奨） | W1 |
| 後片付け | 変更なしは、回収・削除に成功したときだけ即削除。ありは破棄か取り込みの確認まで残す。未確定なら消さない。取り残しは起動時に警告。`gc` はしない | 作業を失わない（`@gotgenes` 方式）。共有 `.git` の GC を通常の操作に混ぜない | 取り残しと不要なオブジェクトが増える。破棄は利用者のスラッシュコマンドだけ | — | 有望（推奨） | W1 |
| 検証 | 完了時にハーネスが、設定に固定したコマンド（`verify.py`）を worktree の中で実行し、結果を通知に付ける | 親の往復が消える。モデルは引数を渡せない。サンドボックスの中で動く | 子が書いた試験コードを、ハーネスが実行する | 時間の上限（10 分）と出力の上限 | 有望（推奨） | W2 |
| 取り込み前の検査 | 差分が「安全に直結するファイル」（判定器・許可規則・hook・正解データ）に触れたら、`review` 済みの印を要求する | 境界の変更を `review` に通す約束を、機械で支える | 一覧の維持が要る | — | 有望（推奨） | W2 |
| git 制限 | W1 では据え置く（子はコミットしない） | 変更が小さい | 共有 `.git` の書込可は変わらない | 判定器の追加（未解決点） | 採用（W1）。W3 で再検討 | W3 |

扱い: 未評価 / 検証中 / 有望 / 採用 / 保留 / 見送り

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `[pi.agents.worker]` | `workspace`（`shared` / `worktree`）を足す。既定は `shared` | 役割ごとの opt-in | 未適用（W1） |
| ハーネスの子の起動（`harness/children.ts`・`index.ts`） | `worktree` の役割は、事前選別のあと、スナップショットから作業ツリーを作り、cwd をそこにする。子の終了を確認してから、差分と ref を回収する。取り込みの操作（`integrate`）は W1 では作らない | W1 の最小段。`integrate` は W2 | 未適用 |
| 判定器・許可規則 | 共有 `.git` を壊す操作を deny に足すか、W0b の結果で決める | W0b | 未適用 |
| `docs/spec/guard/pi-guard.md` | 子の作業場所（`worktree`）、回収、取り残しの警告と手動復旧（W1）。取り込み（W2） | W1・W2 | 未適用 |
| `worker` の system | git の制限の記述を、W3 で見直す | W3 | 未適用 |

## W1 の前に決める仕様案

「未解決点」の 3 つ（秘密と容量、job の寿命、取り込み）を、実装できる粒度にした案。**案であり、利用者の承認までは未適用**。W0b の結果で動く点は「未確定のこと」の表に集めた。出典は（ファイル:行）。clean filter は、git が `add` のときに内容を変換する設定（`.gitattributes`）。

### 秘密の選別と容量

| 項目 | 案 | 理由・出典 |
| --- | --- | --- |
| 順序 | (a) 候補パスの列挙: `git ls-files --others --exclude-standard -z` と、追跡ファイルの変更の一覧。(b) パスの検査: 一覧に当たれば**起動を拒否**し、パスと一致した規則を利用者に示す。(c) 容量の測定。(d) その後に一時 index で `add -A` → `write-tree` | `add` は共有 `.git` にオブジェクトを書く。拒否が `add` の後では、秘密がすでに入っていて遅い（`review`）。W0a の流れでは検査が `add` の後だった（直す） |
| `add` 中の変更・clean filter | (b)(c) の後にファイルが変わる、clean filter が内容を変える、の場合は、(b) で見ていないパスやサイズが入りうる。`add` 後に `diff-index --cached --name-only` を候補の一覧と突き合わせ、食い違えば ref を作らず起動を拒否し、警告する。ただしその時点でオブジェクトは書かれている | 事前の検査では防げない。保証は「検査した時点の候補」までで、競合は**未実測**（推測: 突き合わせで検出はできるが、書込みは防げない） |
| clean filter の確認（案） | 起動前に `git config --get-regexp '^filter\.'` を見る。clean filter は `git add -A` 中に任意のコマンドを実行しうるので、定義があれば**起動を拒否するか、`-c filter.<名>.clean=` で無効化するか**を決める（未決） | Claude Code は、同じ理由で filter driver が把握できない・切れないときに作成を拒む（記録 P7）。このリポジトリで filter の定義があるかは**未確認** |
| 検査の正本と実装 | 生成済み `rules.json` の `[file]`（`read_deny_globs` と `deny_exceptions`。`common.toml.tmpl:403-458` と 520-524 の生成元）を、`judge/policy.ts` の `matchesReadDeny`（130〜142 行。例外は対の deny にだけ効く）で照合する。Python 側の実装を作るなら、代表ケース（`.env`・`.env.example`・`foo.pem`・`secret_util.py` など）で `matchesReadDeny` と同じ判断を返すことを試験する | 「一覧が同期している」ことと「同じ入力に同じ判断を返す」ことは別。`test_secret_lists_in_sync.py` は前者。後者は照合の実装を共有するか、一致試験で固定する。`backup.py` は容量測定の先例であって、秘密検査の先例ではない |
| 限界 | パスの規則は完全ではない。**無害な名前に入った秘密、改名した秘密、HEAD に既にある内容は検出しない**。逆に `**/*secret*` はコード名にも当たる。**内容中の秘密の保証はしない**（推測: 中身の検査は誤検出が多く、案には入れない） | `common.toml.tmpl:399-401` のコメントも、部分一致の誤検出に触れている |
| 誤検出 | 例外込みで判断し、当たれば起動を拒否して一致した規則を示す。例外は `.env.example` などの見本（`common.toml.tmpl:520-524`）。**このリポジトリの `test_secret_lists_in_sync.py` 自体が `**/*secret*` に当たる**（`review` の試験ファイルの検査の出力）。普段拒否される未追跡ファイルがあるかは**未確認** | 頻発する場合の別案: 利用者が明示したファイルだけを起点から除外する。代償は「親と同じ状態」を失うことで、起動時に除外したパスと「子は親と違う状態で動く」ことを表示する。黙って除外はしない |
| 容量の測定 | 候補の各ファイルの `stat` を合計し、上限を超えたら打ち切って拒否（`backup.py:59-80` の `measure_source`。「作ってから間引くと 84 GB をハッシュする」という理由が書かれている）。一時 index の流れと `GIT_*` の除去は `backup.py:34-38,100-129` | 容量測定の先例の流用 |
| 容量の上限 | 合計 200 MB、1 ファイル 50 MB。超えたら起動を拒否し、大きい上位のパスを示す | このリポジトリの worktree が 14.6 MB（W0a の実測）で、約 14 倍の余裕。`backup.py:28` の元の上限は 256 MiB で同じ桁。**値は推測**（実運用の分布は未測定） |
| patch の保存 | `.tmp/subagents/<通番>-<job id>.patch`。保存先がシンボリックリンクなら書かない、`wx`、バイナリで書く（W0a: テキストモードは CRLF を壊す）。**書けなければ「回収済み」にしない**（worktree と記録を残して「保持」にする） | `saveFull`（`index.ts:526-546`）は書けなくても通知を続ける。通知文にはそれでよいが、唯一の取り込み用 patch には不適切 |
| patch の秘匿 | patch を書く前に、結果の変更パスを同じ検査にかける。当たれば patch も ref も作らず、worktree を残して利用者に知らせる | `harness/redact.ts` はツールの返答に掛ける伏字化で、ファイルや patch を書く前の処理ではない（`redact.ts:19-54`） |
| 掃除 | 掃除の対象は、「取り込み済み」「破棄済み」の成果物の patch だけ（`pruneSaved`（`index.ts:547-562`）の 50 件・7 日を `.patch` に広げるときも、この条件を付ける）。**未取り込み（回収済み・保持）の patch・ref・記録は、期限・件数で消さない** | 期限で消すと、記録が指す patch が無くなり、取り込めない |
| ref と GC | 後片付けは、worktree の解放（`git worktree remove`）と、破棄・取り込み後の ref の削除までにする。**`gc --prune=now` は組み込まない**。GC は利用者が行う別の保守操作で、代償は不要なオブジェクトがしばらく残ること。**秘密を一度 `add` して GC で解決する設計にはしない** | 共有 `.git` の GC はこの job 専用ではない。ref 削除後に秘密のオブジェクトが消える保証は、使い捨てのリポジトリの実測（W0a）からは出ない |

### job の寿命と成果物

`Job` は往復（run）ごとに `finish` する。`done` と `aborted` 以外は job も閉じ（`children.ts:328`）、`done` なら idle のまま `keep` で追加依頼を受ける。閉じる経路は、利用者の `close:true`、時間切れ、親の abort、プロセスの終了、`closeAll`（`session_shutdown`:`index.ts:150`、`/bypass` の切り替え:`index.ts:211`、`process.once("exit")`:`index.ts:386`）。完了結果のメモリ保持は 30 分・20 件（`index.ts:391-392`）。`Job.close()` は停止を要求して戻り、子が 3 秒で終わらなければ後で `SIGKILL` する（`children.ts:399-420`）。

- **回収の契機**: **job を閉じ、子の終了を確認してから**回収する（`close()` の戻りは終了を意味せず、終了前に回収すると子の最後の書き込みと競合する）。`keep` でない job は完了通知のとき。`keep` の往復ごとには回収しない（途中の結果が取り込み候補として増えるため）。代償: `keep` の job が閉じる前に落ちると、未回収の変更が worktree に残る。この代償は、強制終了後の復旧の項で拾う。途中の差分は `status` の操作で worktree の差分を表示するだけにする（ref は作らない。**推測**: 要望が出てから足す）
- **対応記録**: job ごとの小さな JSON `.tmp/subagents/worktrees/<job id>.json`（リポジトリの識別、起点 commit、worktree のパス、結果 ref とその値、patch のパスとハッシュ、状態、作成時刻）。追記専用の 1 ファイルにはしない（同時の書き込みで壊れうるため）。書き方は `saveFull` と同じ（リンクの拒否・`wx`）。状態が変わるときは、一時ファイルに書いて `rename` で置き換える。**掃除の対象にしない**。破棄済みと取り込み済みの記録だけ、7 日で消す
- **記録を信用する前の再照合**: 取り込み・破棄の前に、(1) リポジトリの同一性、(2) worktree が許可したルートの中にあること、(3) 起点・結果の commit、(4) ref の指す値、(5) patch の内容（ハッシュ）を、記録と実体で突き合わせる。同じリポジトリでの操作は直列化する（ロックの方式は未決）。**ハッシュを同じ書込可ディレクトリの JSON にだけ保存しても、patch と記録の両方を書き換えられれば効かない**。保管場所の境界は W0b で確認する
- **強制終了後の復旧**: 起動時（`session_start`）に、記録の一覧・`git worktree list`・`refs/pi-agent` を突き合わせ、状態の表にある食い違いを警告する。**自動では消さない**（先行例 `@gotgenes` と同じ）。利用者が `/worktrees` で、確かめたうえで解消する
- **手動の破棄**: 利用者のスラッシュコマンド `/worktrees`（一覧・差分・破棄）だけ。モデルが呼べるツールは作らない（`/bypass` と同じ作り: `index.ts:184-186`）。破棄は `ctx.ui.confirm` で確認し、未取り込みの変更があるときは差分の行数を示す。UI が無い実行では破棄しない
- **実行中の保護**（案。記録 P7 の Claude Code）: 実行中の worktree は `git worktree lock <path> --reason "pi-agent <job id>"` で守り、回収の後に `unlock` する。lock が `git worktree remove` を拒むことは先行例の docs の記述で、**このリポジトリでは未実測**
- **扱う対象**（案）: 自分が作ったもの（名前の接頭辞 `pi-agent-<job id>` と対応記録の両方があるもの）だけ。利用者が作ったものや記録の無いものは、警告にも掃除にも含めない（Cursor は外部のものまで削除対象にする、という先行例の失敗を避ける）
- **同時数の上限**（案）: 同時に持つ worktree の数の上限（案: 8。**推測**）を超えたら、新しい子の起動を拒否して、保持中の一覧を示す。自動で古いものを消さない（Cursor と Codex は上限超過で自動削除するが、本設計は未取り込みの成果物を消さない）

| 状態 | 次の状態 | 契機・復旧 |
| --- | --- | --- |
| 作成中 | 実行中 / 失敗 | 作成に成功 / 失敗（子を起動しない。worktree があれば残して記録する） |
| 実行中 | 終了確認待ち | job を閉じた（`close()`、`closeAll`、強制終了を含む）。子のプロセスが終わるまで回収しない |
| 終了確認待ち | 回収済み / 保持 | 終了を確認し、patch の保存・ref・記録の整合が取れた / 回収に失敗した、整合が取れない、秘密の一覧に当たった、状態を検証できない（サブモジュールの中を調べられない、`git status` が失敗する）（worktree・記録を残し警告） |
| 回収済み | 取り込み済み / 破棄済み | 利用者が手動で `git apply` した後に `/worktrees` で印を付ける（W2 以降は `integrate` の成功） / `/worktrees` の破棄 |
| 保持 | 回収済み / 破棄済み | 利用者が問題を解いて再回収 / 破棄 |
| 変更なしで閉じた | 破棄済み | 終了確認の後、差分が空で、worktree の削除に成功したとき。**回収・削除に失敗したら「破棄済み」にせず「保持」**。状態を検証できないときも「保持」で、自動で削除しない（Claude Code も同じ扱い。記録 P7） |
| 記録だけ残った（worktree・ref が無い） | 手動で解消 | 起動時に警告。クラッシュ、または手動の削除。patch が残っていれば、それを手がかりに利用者が判断 |
| worktree だけ残った（記録が無い） | 手動で解消 | 起動時に警告。記録の書き込み前にクラッシュした可能性。中身を確認して、利用者が破棄する |
| ref だけ残った（worktree が無い） | 手動で解消 | 起動時に警告。ref の指す結果と patch の有無を示し、利用者が取り込むか削除する |
| `keep` 中のクラッシュ | 手動で解消 | 記録は「実行中」のまま残る。worktree の差分を利用者が確認し、必要なら手動で patch を作って使う |

### 取り込みの規則

- **W1（最小段）**: ハーネスは親の作業ツリーを書かない。回収で作った patch と、起動時の警告・`/worktrees` の差分表示だけを出す。利用者が差分を確認し、手動で `git apply`（`--check` を先に）する。**入力の形式・差分の作り方**は `diff --binary --full-index --no-renames <起点> <結果>`。リネームは追加と削除になり、表示上のリネーム情報を失う（W0a）
- **W2 以降の `integrate`**: `{jobId, integrate:true}` だけを受け取り（パスや patch の文字列は受け取らない）、判定は ask。手順の骨子は、記録の再照合 → patch をバイナリで読む → `git apply --check` → `git apply`（`--index` 無し）→ 状態を「取り込み済み」にする。**「失敗しても親は無変更」は、W0a が示した範囲（事前に存在する衝突での `--check` の拒否）以上には保証できない。並行編集・適用途中のエラーは未証明**
- **`integrate` の受入条件**（これを満たす設計が W2 に要る）:
  - (a) 親の書き込みとの排他: 排他できない編集主体（人のエディタなど）があるなら、無変更とは書かない
  - (b) 適用直前の再確認: 対象パスの親の状態を、`--check` の直前でなく適用の直前に見る
  - (c) 途中失敗から戻す手順: 適用前の対象パスの状態を保存する方法と、戻す操作
  - (d) 複数の pi プロセスと dirty な親: 親が dirty なこと自体は拒否理由にしない。対象パスの状態で判断する。プロセス間の直列化
  - (e) **bypass 中も毎回人の確認を必須にするか**: bypass は ask を allow にする（`docs/spec/guard/pi-decide.md`「評価の順番」、`index.ts:184-211`）ので、通常の ask だけに依存しない。必須にするなら、別の確認の仕組み（`/worktrees` の確認など、モデルが呼べない経路）が要る
- **既知の拒否**: 親が同じ行を編集、同名の新規ファイルを作った、子が削除したファイルを親が編集、5 行ほどの短いファイルの端の hunk（W0a）。回避として利用者に差分を示すだけで、自動の 3-way は行わない
- **安全に直結するファイルの検査**: 取り込みの前に、差分が判定器・許可規則・hook・正解データに触れたら止める。W2 で扱う。**一覧の置き場は未決**

### 未確定のこと

| 点 | 事実 | 推測 | 決まる場所 |
| --- | --- | --- | --- |
| 子の cwd と書込可 | Fence の書込可は親の起動時の cwd。`~/worktrees` は読み取りだけ（`common.toml.tmpl`、`boundary.py:215-236`、`review`） | 子ごとに境界を作り直せば worktree に移る | W0b |
| 共有 `.git` の書込可 | 本体の refs を worktree から書ける（W0a、Fence なし） | Fence の下でも `refs/pi-agent` への書き込みは通る。`hooks`・`config` の拒否が継いだ境界で効くかは未確認 | W0b |
| `git worktree` の deny | `worker` の禁止一覧に `update-ref`・`worktree`・`branch` は無い（`review`） | deny を足しても、誤操作の抑止にとどまる | W0b と判定器の追加 |
| 回収をだれが実行するか | 回収はハーネス（Fence の外）が行う想定 | ハーネスが共有 `.git` を書けるので、Fence の設定に依存しない | W0b |
| 保存先 `.tmp/subagents` | 親の cwd 配下で、書込可 | 子から patch と記録を書き換えられうる。ハッシュの併記は、記録も書き換えられれば効かない。子から書けない保管場所があるかを確かめる | W0b |

### 大きなデータと外部フォルダ

**案であり、決定ではない。利用者の承認までは未適用**。実測は 2026-10-22、使い捨てのリポジトリ、git 2.43.0（`.tmp/w0a3.py`。本物のリポジトリには書いていない）。

- 200 MB の未追跡で ignored でないファイルのスナップショット（一時 index で `add -A`）: 5.12 秒、共有 `.git/objects` が 210 MB 増える。その worktree の作成は 0.28 秒で、worktree にも 200 MB のコピーができる。約 410 MB を使う。乱数データ（圧縮されない）の場合の値で、圧縮される場合は小さい（**推測**）
- ignored のデータ（`data_ignored/`）はスナップショットに入らず、worktree に無い
- シンボリックリンクはリンクのまま（mode 120000）記録される。**絶対パスのリンクと、設定の絶対パス**は、worktree でも元の外部フォルダを指す（読める）。子の書き込みは Landlock で、書込可に含めない限り拒否される（**推測**: Landlock は解決後のパスで判定する。未実測）。**相対パスで、リポジトリの外を指すリンク**は、worktree の深さが違うと壊れる（repo 直下では存在、`.tmp/wt/job1` の中では存在しない）

| ケース | 実測の事実 | 起動時の扱い（案） | 子から見た結果 | 理由と代償 |
| --- | --- | --- | --- | --- |
| 1. 大きな未追跡ファイル | 200 MB で 5.1 秒・約 410 MB | 容量の上限を超えたら、パスと大きさを示して起動を拒否。利用者は `.gitignore` に足すか、サイズを減らす | 起動されない | 共有 `.git` と worktree の両方にコピーができるのを避ける。上限の値（200 MB・1 ファイル 50 MB）は推測のまま。代償: 大きなデータを扱う作業は子に任せられない |
| 2. ignored の大きなデータ（.venv・データセット・キャッシュ） | スナップショットに入らず、worktree に無い | 持ち込まない。W2 以降で、**読み取り専用のシンボリックリンク**を許可リスト方式で張る案（`.worktreeinclude` 相当。Claude Code はコピー、こちらはコピーしない）。秘密のパスに当たるものは、許可リストにあっても拒否 | 見えない（W1）。W2 以降で、読めるが書けない | 元を書込可に含めないので子は書けない。内容のコピーはしない。代償: W1 では、依存環境が無いとき `uv run` の起動が遅い・失敗する作業がありうる（**推測**） |
| 3. 外部フォルダへの絶対パス | worktree でも元の外部フォルダを指す。読めるかは親の Fence の読み取り許可しだい（**未確認**。W0b は書込だけ確かめた） | そのまま（変えない） | 読めるなら読める。書き込みは拒否されるので、出力先が外部フォルダの作業は失敗する | 子ごとに「書込可の追加」を利用者が承認する仕組みは W2 以降の候補。代償: 承認の手間と、許可する範囲の审査 |
| 4. リポジトリの外を指す相対パスのリンク | worktree の深さが違うと壊れる | 起動時に、スナップショットの mode 120000 のエントリを調べ、worktree の位置から解決できないものを列挙して警告する。書き換えて直さない | 壊れたリンクを踏むと失敗する（警告は出る） | 直すと、親と同じ状態という起点の前提が崩れる |
| 5. 同時に持つ worktree の合計の容量 | 1 つあたり 14.6 MB（このリポジトリ。W0a）、200 MB の例では約 410 MB | 同時数の上限と、起動前の空き容量の確認（値は推測） | 上限を超えると起動されない | 容量を超えて作業が止まるのを避ける。代償: 並列の数が抑えられる |
| 6. Git LFS・サブモジュール | サブモジュールは W0a で、worktree のディレクトリが空になると確認済み。LFS は**未確認** | サブモジュールは空のまま。LFS は未定 | サブモジュールの中は見えない | LFS の扯いは調べてから決める |

**未確認**: Fence の読み取り許可（外部フォルダを読めるか）、Landlock と symlink（解決後のパスで判定するか）、Git LFS、巨大な ignored のディレクトリの `stat` の費用。

#### 具体例: SLAM・SfM の大規模動画データセット

利用者の具体例（2026-10-22）: 大規模な動画データセットを入力にして、ロジックの開発をする。データセットは読み取り専用で、場所は `~/dataset` や `/data2/dataset` などと複数あるが、設定で変えられる。中間ファイルと結果の書き出し、診断、ロジックの改善が主目的。これを W1 でどこまで扱えるか（案。利用者の承認までは未適用）。

**調査の実測**（2026-10-22、WSL。`ocs` が `pis` のために組み立てる Fence の設定の下で、私の環境から実行。`.tmp/real_fence_cmd.py`。この機械には `~/dataset` も `/data2` も無いので、代わりのディレクトリで確かめた）:

- **読み取り**: Fence の読み取り許可は固定の一覧（起動ディレクトリ、`~/src`、`~/worktrees`、`~/papers` など。`common.toml.tmpl` の `work_read`）。ホームの下の許可外（`~/ds-home-test`）、ホームの外の許可外（`/var/tmp`、`/tmp`、`/mnt/c`）は、**すべて読み取りが拒否**された。許可の中（`~/src` の下）と、システムのパス（`/etc`、`/usr`）は読める。つまり、`~/dataset` も `/data2/dataset` も、何もしなければ読めない
- **プロジェクトごとの許可**: `<起動ディレクトリ>/.opencode/sandbox.toml` の `read = [...]` と `write = [...]` で足せる（`opencode-sandbox.md` の「プロジェクトごとの追加」。宣言がリポジトリと一緒に移動する。確認なしで適用し、起動時に足す分を表示する）。データセットの場所は、ここに書けば、`pis` の親も子も読める。この実測では `read` の宣言そのものを試していない（未確認）が、仕組みは仕様のとおり
- **共有メモリ・デバイス**: Fence の中で、`/dev/shm` への書き込みと、`/dev/dxg`（WSL の GPU）の読み書きでの open は通る。Landlock を重ねたときは、書込可に含めないと拒否される（前の実測）
- **GPU**: 既定の `pis` の Fence の中では、`nvidia-smi` が `Failed to initialize NVML: GPU access blocked by the operating system` で失敗し、CUDA（`libcuda.so.1` の `cuInit`）も `100`（デバイスなし）を返す。Fence の外では通る（RTX 3070 を認識）。**原因は、Fence の `devices.mode`（既定の `auto`）が `/dev` を最小にして、`/dev/dxg`（WSL の GPU）を見せないこと**。実測（2026-10-22）: (1) 設定なしの最小の `fence`、`devices.mode` が `minimal` と `auto` では失敗し、`host` では成功する。(2) `devices: {"mode": "minimal", "allow": ["/dev/dxg"]}` だけで成功する。(3) `ocs` が `pis` のために組み立てる実際の境界に、同じ `devices` を足して実行すると、`nvidia-smi` が GPU を認識し、`cuInit=0`、デバイス数 1 を返す。`ocs` の境界は `devices` を設定していない（`allowPty` だけ）。`/usr/lib/wsl` を読めるようにしても直らない（読み取りの問題ではない）。**再現しない観測が 1 件ある**: 最初の実測（同じ日の 20 時ごろ）では、同じ境界の `ls /dev` に `dxg` が見え、読み書きでの open も通ったが、`nvidia-smi` は失敗していた。後の実測では、`devices` を足さないと `/dev` に `dxg` は無い。この違いの条件は特定していない。GPU を使えるようにするには、`ocs` の境界に `devices.allow` を足す変更が要る（別の案件。これは worktree 隔離とは独立で、親も子も効く）。`/dev/dxg` を許すと、Windows の GPU ドライバへの経路が開く（影響は未評価）
- **既存の設計との関係**: このリポジトリは、GPU を使う作業を、隔離した専用の WSL2（`ssh sbx@sandbox-gpu`、Docker）で行う設計で、`[pi.remote_exec] targets` で、その宛先への `ssh` だけを許している（`pi-decide.md`、`wsl-sandbox.md`）。コードをその宛先へどう渡すか、複数の子が同じ宛先を使うとき作業ディレクトリをどう分けるかは、記述が無い（未確認）

| 必要なこと | W1 での扱い（案） | 根拠・未確認 |
| --- | --- | --- |
| データセットの読み取り | `.opencode/sandbox.toml` の `read` にデータセットの場所を宣言すれば、親の Fence が読める。子は、親が読める範囲だけ読める（Landlock は読み取りを狭めない設計） | 上の実測。`read` の宣言の実行は未確認。場所が可変なら、マシンごとに宣言を変える運用になる（パスがマシン依存になる点は、`opencode-sandbox.md` が述べるとおり、リポジトリごとの宣言で扱う） |
| 中間ファイル・結果の書き出し | 既定は、**出力先を worktree の中**（ignored の `outputs/` など）にする。出力先が設定で変えられるなら、子の起動時に worktree の中へ向ける（向け方は未決） | 書込可は worktree の中に限る（実測済み）。**外部の出力先を使いたいとき**: `.opencode/sandbox.toml` の `write` に宣言した場所を、子の Landlock の書込可に引き継ぐ案がある（利用者が宣言した場所だけ。子ごとの承認の仕組みは要らない）。ただし、その場所は、子同士で共有になるので、job ごとのサブディレクトリを使う運用が要る。実装も実測も未 |
| 結果ファイルの回収 | patch は追跡と、ignored でない未追跡のファイルだけで、ignored の結果は入らない。**許可リストで指定した成果物（例: 診断の要約の JSON）だけを、上限つきで、保存先（`.tmp/subagents/<通番>-<job id>/`）へ写す**案。大きな中間ファイルは写さず、worktree に残る（未取り込みの間は消さない） | 許可リストの置き場・上限の値は未決（推測の値を置かない） |
| GPU | 既定では**扱えない**が、`ocs` の境界に `devices.allow = ["/dev/dxg"]` を足せば、親も子も使える（実測。別の案件）。足すまでの間と、隔離が要る重い作業は、既存の `sandbox-gpu` への `ssh` で行う。子の Landlock の書込可には、存在するデバイス（`/dev/shm`・`/dev/dxg`・`/dev/nvidia*`・`/dev/tty`）を足す | 実測は上。`sandbox-gpu` へのコードの渡し方は未確認 |
| 複数の子の並行 | 同時数の上限（案: 8。推測）に加え、CPU・メモリ・ディスクの競合は隔離の対象外。重い作業の子は、並行数を絞る | 共有サービスと同じ扱い（範囲外） |
| 基準となる過去の結果との比較 | 親の ignored の `outputs/` は、worktree から見えない。比較に要るものは、成果物の許可リストか、読み取り専用のリンク（W2 以降の候補）で渡す | 運用の例であり、実測していない |

この例から決まる W1 の条件（案）: (1) データセットの場所を `.opencode/sandbox.toml` の `read` に宣言すること、(2) 出力先を worktree の中へ向けられること、(3) Landlock の書込可の許可リストに、存在するデバイスを足すこと、(4) 成果物の許可リストによる回収。外部フォルダへの出力（`write` の宣言の引き継ぎ）、GPU、Docker を使う作業は、W1 の対象外とし、親が隔離なしで行う（または `sandbox-gpu` へ `ssh` で渡す）。

## W1 の実装計画

W1（最小段）の実装を段に分けた計画。**利用者が承認した（2026-10-23。決めた点 3 つを含む）。実装は S0 から進める**。差し込み点は `explore` の調査（2026-10-23。コードを読んだもので、実行はしていない）による。2026-10-23 の `review` の指摘（BLOCKER 2・MAJOR 7）を反映して改訂した（「重要な更新」）。

### 方針

- 新しいファイル `home/dot_config/pi/harness/worktree.ts`（git の操作・事前選別・スナップショット・回収・記録）と、`home/dot_config/pi/harness/landlock_exec.py`（`scripts/agents/w0b_landlock.py` の試作を製品にしたもの）を足す。`children.ts` と `index.ts` の変更は、差し込みに必要な分だけにする
- 隔離は `guarded_task` の新しい引数 `isolation: "worktree"` で明示的に選ぶ（opt-in）。対象は `worker` の**単独の新規依頼だけ**。`tasks`（一括）に `isolation` が混ざったら**拒否**する（一括の `worker` は、従来どおり共有の作業ツリーで動くので、入力の説明に「隔離されない」と明記する）。`keep`（往復を重ねる子）との併用も W1 では**拒否**する（回収は 1 往復の終わりに 1 回。`keep` を許すと、往復ごとの回収という別の設計が要る）
- **隔離を指定した job の最終結果は、子の終了と回収が確定してから組み立てる**（下の「契約」）
- Landlock が使えない環境、ラッパーの適用に失敗した場合は、隔離の依頼を**拒否**する（隔離なしで黙って動かさない）
- 取り込みは作らない。結果は `refs/pi-agent/<job id>` と patch に残し、利用者が確認して手動で `git apply`
- 脅威の範囲: 子の事故と暴走（ADR-0012）。意図的に回避する子（別のプロセスグループへ離脱する孫、`.opencode` が symlink のときの置換など）は保証しない。共有の `objects` への書き込みは Landlock の許可に残るので、被害は「自分の worktree、専用の ref、共有 `objects` への不要なオブジェクト」に限られる（`refs/heads` と `refs/tags` は拒否。「専用の ref だけ」とは言わない）

### 契約: 往復の完了と、終了・回収の確定

現行コードは、往復の結果が子の終了より先に返る（`children.ts:328-351` の `finish()` が往復の Promise を解決し、`index.ts:595-618,875-889` がその直後に `job.close()`、結果の生成、通知か返却をする。`close()` は終了を待たない（`children.ts:403-425`）。`onExit` は後の `close` イベント（`children.ts:214-229`））。そこで、隔離の job には **2 つの Promise** を持たせる:

- `roundDone`: 往復の完了（現行の挙動）
- `finalized`: 子のプロセスグループの停止の確認 → 回収 → 記録の確定（または「保持」の確定）まで終わったこと

隔離の job では、`runInBackground` の `.then`、同期の `job.close()`、batch（対象外）のいずれの経路も、**`finalized` を待ってから**結果の本文・通知・ToDo の更新を行う。結果には、ref・patch のパス・取り込みのコマンド（`git apply <patch>`）、または「保持（理由）」を載せる。

### 子の停止の確認

- 停止は、プロセスグループへの `SIGTERM` → 猶予（3 秒。既存の `close()` と同じ）→ `SIGKILL`。その後、`kill(-pgid, 0)` が `ESRCH` を返す（グループが空になる）まで、短い間隔で確認する。期限（案: 10 秒。推測）までに空にならなければ、**回収しない**。状態を「保持（終了を確認できない）」にして、worktree・ref・記録をそのまま残す
- 確認できるのは、同じプロセスグループの中の孫だけ。別のグループへ離脱したプロセスは、この方式では保証しない（脅威の範囲に書いたとおり）。回収中も、`lock` は取ったままにする

### 差し込み点

| 何を | どこへ | 根拠 |
| --- | --- | --- |
| 作成（事前選別・スナップショット・`git worktree add`・`lock`・ラッパー指定） | `index.ts` の `spawnChild`（443〜469 行）。同期関数なので、`git` は `spawnSync`（個別の時間の上限と、全工程の時間の上限つき。下の「時間の上限」）で呼ぶ。Promise 化すると呼び出し元 5 か所に波及する | `explore`、`review` |
| 子の起動の差し替え | `children.ts:207` の `spawn(o.command ?? "pi", ...)`。`JobOptions.cwd` と `command` は既にあるので、`cwd` に worktree（親の cwd がリポジトリ根の下の `sub/` なら、worktree の下の `sub/`。相対位置を保つ）、`command` に `python3`、`args` の先頭にラッパーを渡す | `explore`、`review` |
| job id の事前採番 | `Jobs.create`（`children.ts:438〜445`）が id を内部で作る。worktree の名前・ref・記録に使うので、id を先に決めて渡す形に直す（小改造） | `explore` |
| 往復の完了と確定の分離 | `Job` に `finalized` を足す。`onExit`（`children.ts:200`、`close` ハンドラ 214〜220 行）が呼ぶ後始末（停止の確認 → 回収）を、`Jobs.create` が上書きしないよう連鎖させる。起動失敗（`proc.on("error")`）でも呼ばれるので、変更なしとして破棄する分岐を持つ | `explore`、`review` |
| 結果への表示 | `resultText`（`index.ts:465〜`）に、`worktree:` の行（ref・patch・コマンド、または保持の理由）を足す（`- calls:` の行と同じ形） | `explore` |
| `/worktrees` | `registerCommand`（`/bypass`・`/agents` の例）。一覧・詳細・破棄（`ctx.ui.confirm`）。モデルには渡さない | `explore` |
| 起動時の警告 | `session_start`（`index.ts:152〜158`）。UI が無いときは早期 return する点に注意。記録・worktree・ref の三者を突き合わせる | `explore` |
| 保護対象の検査 | `index.ts` が読み込み済みの `rules.judge.common` から、`policy.ts` の `matchesReadDeny` を呼ぶ。候補パスは、リポジトリ相対か絶対かを揃えて渡す（`decide.ts:171〜174` は両方を試す） | `explore` |
| `guarded_task` の引数 | `parameters`（`additionalProperties: false`）、`parseTaskInput`（`children.ts:59`）、`TaskInput` の `new` 形に `isolation` を足す。`tasks` の項目に混ざったら拒否 | `explore`、`review` |

### git の実行（S1 の受入条件）

呼ぶコマンドごとに、リポジトリ自身の設定を介したコード実行の経路を塞ぐ。共通: `GIT_*` を落とし、`/usr/bin/git` の絶対パスで呼び、`-c core.hooksPath=<空のディレクトリ> -c core.fsmonitor=false` を付ける。`core.hooksPath` の無効化は、**ハーネス自身が実行する plumbing（`worktree add` など）の hook を動かさない**ための措置で、利用者・エージェントのコミットの検証を飛ばす（`--no-verify`）ものではない、と判断する（このリポジトリが禁じるのは、後者）。

| コマンド | 走りうるもの | 対策（案） |
| --- | --- | --- |
| `ls-files --others --exclude-standard`、`status --porcelain` | fsmonitor | `core.fsmonitor=false` |
| `read-tree`、`write-tree`、`commit-tree` | なし（hook は走らない。W0a で実測） | — |
| `add -A`（一時 index） | clean filter・process filter（`filter.<名>.clean`・`.process`）。fsmonitor | **`filter.*` の定義が 1 つでもあれば、隔離の起動を拒否**（LFS の `filter.lfs.*` も対象。LFS のリポジトリは W1 では対象外）。`core.fsmonitor=false` |
| `worktree add --detach` | checkout の smudge filter・process filter、`post-checkout` hook | 上と同じ（`filter.*` があれば拒否）。`core.hooksPath` を空に |
| `diff --binary --full-index --no-renames` | external diff、textconv | `--no-ext-diff --no-textconv`、`-c diff.external=`。`.gitattributes` の `diff=<名>` は `--no-textconv` で無効 |
| `update-ref`、`worktree lock`・`unlock`・`remove`・`prune`、`config --get-regexp` | なし | — |

`core.sshCommand` は、ローカルの操作では実行経路ではない（remote やサブモジュールの操作を足すときの確認対象）。

### 事前選別（S1）

順序: (1) 候補の列挙（追跡の変更と、ignored でない未追跡。`.tmp/` 自身は除く）→ (2) 保護対象のパスの検査（`matchesReadDeny`。当たれば拒否して、パスと一致した規則を示す）→ (3) 容量（合計・1 ファイル。`stat` の合計）→ (4) filter driver の確認 → (5) 配置先の検査 → (6) 一時 index で `add -A`（ここで初めてオブジェクトを書く）→ (7) 作成後の index と、(1) の候補の一致の確認。

**配置先の検査**: 配置先は `<リポジトリ根>/.tmp/worktrees/<job id>`。(a) `git check-ignore -q` で `.tmp/` が ignored であること（無ければ**起動を拒否**。親の作業ツリーを勝手に変えない）、(b) `.tmp` と `.tmp/worktrees` が実ディレクトリで、symlink でなく、実体のパスがリポジトリ根の下であること、(c) `git ls-files .tmp` が空であること（追跡されたファイルが無い）、(d) 作成先が存在しないこと。

**保証の範囲**: (1) の列挙と (6) の `add` の間に、親が変更しても、(7) の一致で検出するのは事後で、**書いたオブジェクトは取り消せない**。そのため、(7) で食い違ったら起動を拒否して一時 index を消すが、オブジェクトは、参照されないまま `gc` まで残る、と結果に表示する。

### 時間の上限

`spawnSync` は親 pi のイベント処理を止める。各 `git` 呼び出しに個別の timeout（案: 30 秒。推測）と出力量の上限を付け、事前選別から worktree の作成までの**全工程**にも上限（案: 60 秒。推測）を置く。超えたら起動を拒否して、一時 index と作成途中の worktree を片付ける。根拠の実測: 200MB の未追跡ファイルのスナップショットが 5.1 秒、worktree の作成が 0.28 秒（W0a）。実測で停止が長ければ、非同期化（呼び出し元 5 か所の改修）を再検討する。

### 回収の順序（S1 の受入条件）

回収は、**結果の ref が真実の源**（patch は ref から再生成できる）になる順序にする: (1) 子の worktree のスナップショットを一時 index で作り、結果の commit を作る（`commit-tree`、親は起点の commit）→ (2) `refs/pi-agent/<job id>` を `update-ref`（オブジェクトを `gc` から守る）→ (3) patch を一時ファイルへバイナリで書き、`rename`（`wx`、リンクの拒否。保存先は `.tmp/subagents/`。子の Landlock の書込可に含まれない）→ (4) 記録（job ごとの JSON。状態、起点・結果の commit、ref、patch のパスとハッシュ）を、一時ファイルへ書いて `rename` で更新（状態は `collected`）→ (5) `unlock`。どこで落ちても、既存の成果物を自動で消さない。復旧（起動時）: 状態が `collecting` で ref があり patch が無ければ、ref から patch を再生成する。ref が無ければ、worktree が残っていれば回収をやり直せる（利用者が `/worktrees` で実行）。

### 実装の段

| 段 | 内容 | 完了の条件 |
| --- | --- | --- |
| S0 | **実測（実装の前）**: **親の `pis` と同じ境界**（親の cwd をリポジトリ根にした `ocs` の Fence。`.tmp/real_fence_cmd.py` の方式。worktree を cwd にした Fence で代用しない）の内側から、ラッパー → 偽モデル（`faux.ts`）の子 `pi` を起動し、1 往復を終えられる最小の書込可の一覧を求める。`/dev/null`・`/dev/tty`・`/dev/shm`・`/tmp`・`PI_CODING_AGENT_DIR` 配下・`~/.cache`・MCP のキャッシュが要るか。`python3` が Fence の下で起動できるか。親・兄弟・共有 refs（`refs/heads`・`refs/tags`）への書き込みが拒否されること | **完了（2026-10-23。「現在地」の S0 の実測）**。成功する一覧と拒否の結果を記録した |
| S1 | `worktree.ts` の中核（上の事前選別、git の実行、時間の上限、スナップショット、`git worktree add` と `lock`、同時数の上限、記録、回収、`unlock`）。子の起動は含めない | 使い捨ての git リポジトリでの試験（`tmp_path`）。W0a の実測を試験にする（往復、衝突の拒否、秘密の拒否、容量の拒否、`.tmp` が ignored でない場合の拒否、`filter.*` がある場合の拒否、配置先の symlink、(7) の一致、各工程で落ちたときの状態）。`review`。**完了（2026-10-23。仕様と残る限界は「S1 の実装」。review 3 回）** |
| S2 | `landlock_exec.py`: 入力の検証（`--write` の値の欠落、`--` の後の欠落、存在しないパスを拒否）、ABI に応じたアクセス種別、ファイルとディレクトリの権利の分離、存在するデバイスだけの許可、適用の失敗で `execvp` の前に非ゼロで終了 | 単体の試験。Landlock の ABI が無い環境は skip。配置が、子から書けない場所（`~/.config/pi/harness`。`control_dirs`）であることを、S0 の境界で確認。**完了（2026-10-23。仕様と残る限界は「S2 の実装」）** |
| S3 | `children.ts`・`index.ts` の差し込み（事前採番、`finalized` の追加と停止の確認、`isolation`、`spawnChild`、回収、`resultText`、**起動時の取り残しの検出と三者の照合**（S4 から前倒し））。試験の足場（`run_child`）で、偽モデルの `worker` が `.tmp/worktrees/` の下で動き、結果に ref と patch が出る。`tasks` に `isolation` が混ざると拒否する。孫プロセスが残る子（停止を確認できない）で「保持」になる | 既存の試験が通る。新しい統合試験。`review`。**段 1〜4 は完了（2026-10-23。「S3 の実装」）。段 5（起動時の照合）も完了（2026-10-23。「S3 段 5 と S4 の実装」）** |
| S4 | `/worktrees`（一覧・詳細・破棄）、docs（`pi-guard.md` に節、0029 の更新）、試験のコピー一覧への追記 | 全件検証。**完了（2026-10-23。「S3 段 5 と S4 の実装」）** |
| S5 | 利用者の実機（`pis`）での通し確認（実際の MCP・キャッシュを含む）。`review` | 結果を 0029 に記録。手順は「S5 の手順」（`scripts/agents/s5_isolation.sh`）。利用者の実機の結果待ち |

各段の終わりに全件検証を行う。

### 落とし穴（`explore` の調査）

- **試験のコピー一覧**: harness の `.ts`・`.py` を足すと、`test/agents/test_pi_harness.py:41-45`、`test/agents/test_pi_commit_confirm.py:363-367`、`scripts/pi-harness-spike/compact-real.py:34` の個別コピーの一覧に足さないと、全試験が `ModuleNotFound` で落ちる（`audit.ts` を足したとき 125 件が落ちた）。新しいファイルを足す段で直す。`scripts/verify.py` の選択規則（`_PI_TESTS`、`test_every_test_file_is_selectable`）にも、新しい試験ファイルを足す
- **判定器の「作業ツリーの中」**: ツール呼び出しの `ctx.cwd` 基準なので、子の cwd を worktree にすれば worktree 基準になる（`decide.ts:170`、`shared.ts:258`）。`PI_HARNESS_ALLOWED.write` は変えなくてよい（worktree は親の書込領域の中）
- **`process.once("exit")` は同期**: ここで回収はできない。実行中のまま残った worktree は、次回の起動時の警告で拾う
- **`worker` の `shell_deny` に `update-ref`・`worktree`・`branch` が無い**: Landlock が `refs/heads`・`refs/tags` への書き込みを拒否するので、判定器の追加は W1 では不要（W3 の見直しで扱う）

### S1 の実装（`worktree.ts`）の仕様と残る限界

S1（2026-10-23）で実装した `home/dot_config/pi/harness/worktree.ts` の振る舞い。実装は、`worker` が書き、`review` を 3 回経た。試験は `test/agents/test_pi_worktree.py`（使い捨ての git リポジトリで 47 件）。

**記録の状態**: `creating`（作成の途中。先に書く）→ `running` → `collecting` → `collected`。失敗は `kept`（何も消さずに保持）。件数の上限（`maxWorktrees`）には、`creating`・`running`・`collecting`・`collected`・`kept` のすべてを数える（自動では消さない）。`creating` が 10 分を過ぎると、`reconcile` が `stuck_creating` と報告する。

**前提（所有権の根拠）**: 記録（`.tmp/subagents/worktrees/<job id>.json`）は、**子から書けない**配置であること。子の Landlock の書込可は、worktree・`.git/worktrees/<id>`・共有 `objects`・`~/.cache`・`/tmp` などで、`.tmp/subagents/` を含まない（S0 の実測）。この前提が崩れると、`discard` の所有権の根拠が失われる。

**`discard` の規則**:

- 記録が無い・壊れている・`repo` が違う、のときは**何も消さず** `not_owned`。利用者が同じパスに作った worktree や、同名の ref には触れない
- worktree は、記録のパスが規約のパスと一致し、`git worktree list` の登録パスが完全一致し、登録の HEAD が `snapshotCommit` の子孫で、管理領域の検証（下）に通るときだけ消す。違反があれば、**ref・patch も含めて何も消さず**（破棄全体を止め）、記録を `kept` にして理由を残す
- ref は、記録の `ref` が `refs/pi-agent/<job id>` で、現在値が記録の `resultCommit` と同じときだけ（値を指定した `update-ref -d`）。patch は、`.tmp/subagents/` 直下の通常ファイルで、sha256 が記録と同じで、**他の記録が同じ patch を参照していない**ときだけ。patch の名前（`patchName`）には job id を含めることが必須（別の job と同じ patch を共有して、片方の破棄でもう片方の成果物を失うのを防ぐ）
- ref・patch・worktree のどれか 1 つでも残したときは、**記録を消さず**、`kept` と、残したものと理由を `note` に追記する

**管理領域（`.git/worktrees/pi-agent-<job id>`）の検証**（`collect` と `discard` の両方。子が書ける領域なので、git に渡す前に調べる）:

| 対象 | 検査 |
| --- | --- |
| 管理領域そのもの | 実ディレクトリで symlink でない。`realpath` が本体の共有 git ディレクトリの `worktrees/` の下 |
| `commondir`・`gitdir`・`<worktree>/.git` | 内容が、本体の共有 git ディレクトリ・worktree の `.git`・管理領域と対応している |
| `config.worktree` | **あれば拒否**（`extensions.worktreeConfig` を介した設定の注入を防ぐ。`-c extensions.worktreeConfig=false` も併用するが、効くかは未確認） |
| 許可する名前 | `HEAD`・`ORIG_HEAD`・`commondir`・`gitdir`・`locked`・`index`・`index.lock`・`logs`・`pi-agent-collect-index`・`refs`。**それ以外の名前は拒否** |
| 許可名の中身 | `HEAD` は 40/64 桁の 16 進 1 行（デタッチ。`ref:` は拒否）。`index` 系は通常ファイルで 64MB 以下。`locked` などは通常ファイルで 1KB 以下。`logs`・`refs` は再帰して symlink 不可、1 ファイル 1MB 以下、合計 1000 件以下 |

**ロック**: 作成・回収・破棄は、同じリポジトリの `.tmp/subagents/worktrees/.lock`（ディレクトリ。pid と乱数のトークン）の下で動く。取れなければ、50 ミリ秒間隔で最大 `lockWaitMs`（既定 1 秒。推測の値）待ち、`busy`（`detail` に、古いロックかを示す `stale` と `pid`）。**古いロックは自動では奪わない**（3 回の `review` で、奪取の手順に、生きたロックを動かす競合の窓が残ると分かったため）。明示的な `clearStaleLock(repo)`（呼び出しは S4 の `/worktrees` とセッション開始）が、pid が死んでいて、かつディレクトリの mtime が 60 秒より古いときだけ、識別を読み直して同じことを確かめてから消す。残る競合の窓は、その読み直しと削除の間。pid の再利用で、死んだはずの pid が生きている場合は消さない。**待ちは同期**（`Atomics.wait`）で、最大 `lockWaitMs` の間、親のイベントループを止める。

**再回収の冪等性**: patch の公開後・`collected` の記録の前に落ちて `kept` になった job を、再度 `collect` できる。既存の ref が、今回の結果と同じ tree・同じ親なら再利用し、既存の patch が同じ sha256 なら再利用する。それ以外は衝突で失敗し、**既存を上書きしない**。

**`kept` の手動復旧**: 記録の `note` を読んで原因を直し、`collect`（`kept` を受け付ける）か `discard` を再実行する。管理領域が壊れた worktree は、自動では破棄されない。利用者が手動で `git worktree` と記録を整理する（S4 の `/worktrees` で案内する）。確定後の `unlock` の失敗は、状態を `kept` に戻さず、`warnings` と `note` で返す。

**残る限界（記録して先へ進む）**:

- ディレクトリの `lstat` と使用の間の差し替え（TOCTOU）は、完全には防げない。管理領域の検証と、その後の git の実行の間にも窓がある。`O_NOFOLLOW` を、patch と記録の一時ファイルの作成に使うが、読み出し側（記録・patch の sha256 の読み込み）は `lstat` の後に読む
- 検証した管理領域の内容は、子の実行中に変わりうる。回収は停止の確認の後にだけ行う（S3 の契約）
- 候補の列挙と `add` の間の変更は、事後（一致の確認）にしか検出できず、書いたオブジェクトは取り消せない
- 試験していない分岐: 確定後の `unlock` の非ゼロ終了、奪取中の競合、`worktree add` が部分的に成功して失敗する実際の経路（分岐は関数の単位で試験）、`extensions.worktreeConfig=false` の効果

### S2 の実装（`landlock_exec.py`）の仕様と残る限界

S2（2026-10-23）で実装した `home/dot_config/pi/harness/landlock_exec.py`（標準ライブラリだけ。子の `pi` を包んで書込可を狭める）。実装は `worker`、`review` は 1 回（BLOCKER 1・MAJOR 3・MINOR 1。反映済み）。試験は `test/agents/test_pi_landlock_exec.py`（36 件。Landlock が使えない環境では、実際に適用する試験を skip）。

**呼び出し**: `python3 landlock_exec.py [--write PATH]... [--write-if-exists PATH]... -- COMMAND [ARGS...]`、`landlock_exec.py --check`。読み取りと実行は `/` 全体に許可（親の Fence が許す範囲のまま狭めない）。書き込み系の権利は、`--write` のパスの下だけ。`--write-if-exists` は、存在しなければ黙って飛ばす（存在するデバイスだけを許すため）。

**終了コード**: 2（使い方の誤り。`--` なし、値なし、コマンドなし、知らないオプション、存在しない `--write`、広すぎるパス）、3（Landlock を適用できない。ABI の問い合わせ・ルールの追加・`prctl`・`restrict_self` のどれかの失敗、ABI が 3 未満）、127（`execvp` に失敗）。**どの失敗でも、COMMAND は実行されない**（適用してから `execvp` する。適用に失敗したら進まない）。ただし、子自身も 2・3・127 を返しうるので、終了コードだけでは「起動しなかった」を識別できない。ラッパー自身の標準エラーは、すべて `landlock_exec:` で始まる 1 行にそろえてあり、S3 は「終了コードが 2・3・127 かつ標準エラーにこの接頭辞がある」で判定する。これはメッセージの区別で、「子が隔離なしで動くことはない」という保証とは別のもの。

**最低の ABI は 3**: ABI 3 未満では `TRUNCATE` を扱えず、許可外の既存ファイルを `truncate(2)` で切り詰められるので、**ABI 3 未満は拒否**する（隔離を起動しない）。代償は、古いカーネル（Linux 6.2 未満）では隔離が使えないこと。扱うアクセスの種別は、ABI 3 以上で `REFER`・`TRUNCATE` を含む。**ABI 4 以降のネットワーク、ABI 5 の `IOCTL_DEV`、ABI 6 のスコープは扱わない**（制限すると、GPU の ioctl や通信が壊れる。親の Fence が別に制限している）。

**ファイルとディレクトリの権利を分ける**: ディレクトリなら全部の権利、通常のファイル・デバイスなら、ディレクトリ専用の権利（`READ_DIR`・`REMOVE_DIR`・`MAKE_*`・`REFER`）を除いた権利。ファイルにディレクトリ専用の権利を指定すると `EINVAL` になる（`/dev/null` の実測）。

**広すぎる許可パスの拒否**: `realpath` で解決した後のパスが、`/`、`$HOME` とその祖先、`/usr`・`/etc`・`/var`・`/root`・`/proc`・`/sys`・`/dev`（**ディレクトリそのもの**）・`/boot`・`/opt`・`/mnt`・`/run`・`/lib*`・`/bin`・`/sbin` なら、終了コード 2。`/dev/null` や `/dev/shm`・`/dev/dxg` のような個別のものと、`$HOME` の下（`~/.cache`）は許す。エラーには指定された元のパスを出し、解決後のパスは出さない。呼び出し側（S3）も、許可の一覧を固定する責任を持つ。

**`--check`**: ABI の問い合わせだけでなく、`fork` した子で、一時ディレクトリを `--write` として実際に適用して確かめる（親自身には適用しない）。適用できれば `landlock abi N` を出して 0、できなければ 3。

**実測した限界（親、2026-10-23、実際の `pis` の境界の下、このラッパー越し）**: 親の書込可の領域（リポジトリの作業ツリー）の中のファイルに対して、子は、追記・`truncate`・削除・名前変更はすべて拒否されるが、**`chmod` と更新時刻の変更（`touch -d`）は通る**（Landlock が制限しない操作。`xattr` なども同様と推測。未実測）。**つまり、守れるのは親のファイルの内容・存在・名前で、権限と時刻は守れない**。ラッパーでは塞げない。事故の範囲（ADR-0012）として許容し、判定器（`chmod` の拒否など）で補うかは、W3 の見直しで扱う。

**そのほかの限界**: `realpath` による検査と `open` の間の差し替え（TOCTOU）は防げない。親から継承した開いたファイルディスクリプタ・ソケットは、ラッパーでは閉じない。`MAKE_SOCK` はソケットの作成権で、既存の UNIX ソケットへの接続を閉じるものではない。

### S3 の実装（段 1〜4）の仕様と残る限界

S3（2026-10-23）で、`children.ts`・`index.ts` への差し込みを実装した（段 1〜4。段 5 の起動時の照合は未実装）。`review` は 1 回（BLOCKER 1・MAJOR 1・MINOR 2。反映済み）。統合試験は `test/agents/test_pi_isolation.py`（実際に Landlock で子を隔離して動かす。Landlock・git が無い環境は skip）。

**入力**: `guarded_task` の `isolation: "worktree"` は、**単独の新規依頼の `worker` だけ**。`keep`・`tasks`・`jobId` 系との併用、`explore`・`review` との併用は拒否。空文字は無視する（厳格なスキーマのモデルが埋める）。指定しない `worker` の結果には、`- isolation: none` を出す（opt-in の間の誤認防止。`explore`・`review` には出さない）。

**起動の順序**（`prepareIsolation`。拒否は `isolation refused: <コード>: <理由>` として結果のエラーで返し、子を起動せず、`full` は付けない）: (1) Landlock の確認（`landlock_exec.py --check`。結果はプロセスの間キャッシュ。失敗は `landlock_unavailable`）、(2) リポジトリ根と相対位置（`not_a_git_repository`・`cwd_outside_repository`）、(3) `ReadDeny` の構築（`read_deny_globs` が空なら `no_read_deny_rules`）、(4) **書込可とリポジトリの包含関係の検査**（下）、(5) id の採番（`job-` + 12 桁の 16 進）、(6) `createIsolation`（`WorktreeError` の `code` を拒否コードにする。`protected_path`・`too_large`・`filter_driver`・`not_ignored`・`too_many` など）、(7) 子の cwd = worktree + 相対位置（無ければ `cwd_missing_in_worktree` で、片付けて拒否）、(8) 起動の差し替え（`python3 landlock_exec.py --write ... -- pi ...`）、(9) 枠不足や `jobs.create` の例外では、`discard` で片付ける。

**子の書込可の一覧**（S0 の実測）: worktree、その管理領域（`.git/worktrees/pi-agent-<id>`）、共有 `objects`、`PI_CODING_AGENT_DIR`、`~/.cache`、`TMPDIR` と `/tmp`、`/dev/null`、存在するデバイス（`--write-if-exists`: `/dev/dxg`・`/dev/nvidiactl`・`/dev/nvidia-uvm`・`/dev/nvidia-uvm-tools`・`/dev/nvidia0`〜`7`）。**`refs/pi-agent` と `/dev/tty` は含めない**（回収は子の外で行う）。

**書込可とリポジトリの包含関係の検査**（`review` の BLOCKER）: 書込可のうち、worktree・管理領域・共有 `objects` 以外が、リポジトリを包含する（祖先か同じ）か、リポジトリの中にあると、子が `.tmp/subagents` の記録や patch、ほかの worktree を書き換えられ、「記録は子から書けない」という前提が崩れる。**この環境では `TMPDIR` が `<リポジトリ根>/.tmp` を指す**ので、実際に起きる。扱い: `PI_CODING_AGENT_DIR` が重なれば `agent_dir_overlaps_repository` で拒否、`/tmp` が重なれば（リポジトリが `/tmp` の下）`tmp_overlaps_repository` で拒否、`TMPDIR` が重なれば書込可から外して子の `TMPDIR` を `/tmp` に上書き、`~/.cache` が重なれば書込可から外す。判定は `createIsolation` の前（拒否時に worktree もオブジェクトも作らない）。パスは実体（`realpath`。存在しなければ最も近い親の `realpath` に残りを連結）で、`path.relative` で比べる（文字列の前方一致ではない）。

**終了と回収の確定**（契約）: 隔離の job は、往復の完了（`finish()`）の直後に `runFinalize()` が 1 回だけ起動する（`close`・`error` のハンドラからも呼ぶ。冪等）。プロセスグループへ `SIGTERM` → 猶予（3 秒。空になれば早く抜ける）→ `SIGKILL` → `kill(-pgid, 0)` が `ESRCH` を返す（グループが空）まで 100 ミリ秒間隔で確認（上限 10 秒）。**空を確認できたときだけ** `collect` を呼ぶ。確認できなければ回収せず、記録を `kept`（`markKept`）にして worktree・ref を残す。`finalize` の例外は握り、`finalized` は必ず resolve する（`isolationInfo` が未設定なら `failed`（`finalize_error`）を確定）。結果の本文・通知・ToDo の更新は、`finalized` を待ってから行う（同期 run と `runInBackground`）。通常の job は `finalized = null` で、この経路を通らない。`Jobs.create` は、`finalized` があれば、その完了後に `map` から消す。

**結果の行**: `- isolation: worktree` と、`- worktree: ref refs/pi-agent/<id>; patch .tmp/subagents/<id>.patch; apply: git apply <patch>`（回収。`warnings` があれば末尾）、`- worktree: no changes (removed)`（変更なし。worktree と記録は消える）、`- worktree: kept (<理由>). recover: /worktrees`（保持・失敗。`/worktrees` は S4 で実装）。patch の名前は `<id>.patch`（job id を含むことが必須）。

**残る限界**: `closeAll`・セッション終了・`process.once("exit")` では `finalized` を待たない（同期処理しかできない）。**取り残しは、起動時の照合（段 5。「S3 段 5 と S4 の実装」）で拾い、`/worktrees` で回収のやり直しと破棄ができる**。孫プロセスが別のプロセスグループへ離脱した場合は、停止を確認できず、保証の範囲外。**`chmod` と更新時刻の変更は、子が親の書込領域の中で行える**（S2 の限界）。`stopped=false` から `kept` になる経路、孫の残存、二重シグナルは、**直接は試験していない**（統合試験は偽モデルで、通常の回収と拒否を確かめる。`children.ts` は引数プロパティを使うので Node の型除去で読めず、単体試験を外した）。`PI_CODING_AGENT_DIR` が未設定だと、子が往復できない可能性がある。リポジトリが `/tmp` の下にあると、隔離は拒否される。

### S3 段 5 と S4 の実装（起動時の照合と `/worktrees`）

S3 段 5 と S4（2026-10-23）で、起動時の取り残しの照合と、利用者のスラッシュコマンド `/worktrees`（**モデルには渡さない**）を実装した。`review` は 1 回（BLOCKER 1・MAJOR 2・MINOR 2。反映済み）。コマンドの本体は、`worktree.ts` だけに依存する小さなファイル `home/dot_config/pi/harness/worktrees-command.ts`（Node の型除去で読めるように、引数プロパティを使わない）に切り出し、Node で直接試験する（`test/agents/test_pi_worktrees_command.py`。対話の `/worktrees` は print モードで呼べないため）。`index.ts` は、依存（リポジトリ根・実行中の job・確認・出力）を渡して呼ぶ。

**起動時の照合**（`session_start`。UI の有無に関わらず）:

- **痕跡が無ければ `git` を呼ばない**。痕跡は、cwd から上へ最初に見つかる `.git` が**ディレクトリ**で、`.tmp/subagents/worktrees` か `.tmp/worktrees` がある、で判定する（子の worktree は `.git` がファイルなので対象外。記録も `.tmp/worktrees` も無い `ref_only` は検出しない）
- 子（`PI_HARNESS_CHILD=1`）と、既定と違う `PI_HARNESS_ROLE` の起動では、照合しない
- 順序: `clearStaleLock` → 記録の読み込み（壊れた記録も拾う）→ `reconcile`。食い違いは、**1 つの警告**にまとめて出す（件数、各 job id・issue 名・理由。パスはリポジトリからの相対。内容は出さない。`/worktrees` の案内）
- **自動で変えるのは、古いロックの解除だけ**（pid が死んでいて、60 秒以上古いもの）。解除したときは別の 1 行で明記する。worktree・ref・記録は消さない・直さない
- 時間の上限: `git` は 3 秒、全体 5 秒（`STARTUP_LIMITS`）。時間切れ・失敗は、警告 1 行にして、起動を止めない。同期の `git` なので、痕跡のある起動では、最大でこの時間だけイベントループを止める

**`/worktrees` のサブコマンド**:

| サブコマンド | 内容と拒否の条件 |
| --- | --- |
| （なし） | 記録の一覧（job id・状態・作成日時・worktree・ref・patch の有無・`note`）と、食い違い |
| `show <jobId>` | 記録の詳細（起点・結果の commit、ref、patch のパスとハッシュ、`note`） |
| `collect <jobId>` | 回収のやり直し。**子が生きている（このプロセスの `jobs` にある）job は拒否**。`collected`・`creating` も拒否。`kept`・`running`・`collecting` は、**確認（`confirm`）が取れたときだけ**実行し、UI が無ければ拒否。確認文に状態と `note` と「別の pi プロセスの子は、この画面から見えません」を出し、`note` が「停止を確認できない」ことを示すときは、強い警告（作業中の worktree を回収すると、子の変更が失われるおそれ）を加える。`read_deny_globs` が空なら拒否 |
| `discard <jobId>` | 確認のうえ、`discard`（S1 の所有権の規則）。子が生きている job・UI なし・記録なしは拒否。残したもの（照合に失敗したもの）は `notes` で表示 |
| `unlock` | 古いロックの手動解除（`clearStaleLock`）。古くないロック・生きた pid のロックは消さない |

jobId は、サブコマンドと引数の個数を確かめた後で `validateJobId` に通す前に、パスにも確認文にも使わない。出力は `redactText` を通し、パスと job id と状態と `note` だけを出す。

**残る限界**: 別の pi プロセスの子は、`jobs` から見えない（`kept` の回収に確認を要求するのはこのため）。「停止を確認できない」の判定は `markKept` の `note` の文言に依存する（文言を変えるときは判定も直す）。管理領域が壊れた `kept` は、自動では破棄されず、利用者が手動で `git worktree` と記録を整理する。対話での表示と確認ダイアログは、print モードで試験できず、実機（S5）で確かめる。起動時の `git` の同期待ちの上限は、痕跡のある起動だけに及ぶ。時間切れの経路は試験していない。

### 決めた点（2026-10-23、利用者が 3 つとも推奨どおりに確定。`review` も同意した）

1. 隔離を **`isolation` 引数の opt-in** にするか、`worker` の既定にするか（案: opt-in。使って慣れてから既定にする。opt-in の間は、結果に「隔離なし」か「隔離あり」を表示して、「worker なら常に隔離」と誤認させない）
2. `.tmp/` が ignored でないリポジトリでは、**起動を拒否**するか、`.git/info/exclude` へ自動で足すか（案: 拒否）
3. 回収の失敗（patch が書けないなど）のとき、**worktree を保持して警告**する（案）か、結果の本文だけ返すか

## S5 の手順

利用者の端末（実機の `pis`、実際のモデルと MCP）で、隔離の worker を通しで確かめる。所要は 10 分ほど。使い捨てのリポジトリ（`~/src/s5-isolation`）だけを触り、本物のリポジトリには書かない。`scripts/agents/s5_isolation.sh` が、準備・状態の表示・後片付けをする。

1. **準備**（Fence の外のシェルで 1 回）: `sh scripts/agents/s5_isolation.sh setup`。追跡の変更（`notes.txt` の 2 行目が `two-parent`）、未追跡のファイル（`parent-only.txt`）、ignored のファイル（`ignored/data.txt`）を持つリポジトリができる。
2. **A. 基本**: `cd ~/src/s5-isolation && pis` を起動し、次を貼る。

    ```text
    先に todo を 1 件作って、その id を使って、guarded_task を agent=worker, isolation="worktree" で 1 回だけ呼んでください。子への依頼は次のとおりです: 「pwd を実行して結果を報告し、notes.txt の 2 行目を two-child に変え、child-new.txt に from child と書いてください。」
    ```

    期待: 子の `pwd` が `.../.tmp/worktrees/pi-agent-job-...` の下。結果に `- isolation: worktree` と `- worktree: ref refs/pi-agent/job-...; patch .tmp/subagents/job-....patch; apply: git apply ...` が出る。**結果の全文を貼る**。

3. **A の確認**（別のシェルで）: `sh scripts/agents/s5_isolation.sh status`。期待: 親の `notes.txt` は `two-parent` のまま、`parent-only.txt` もそのまま。`refs/pi-agent/job-...` と記録、patch がある。続けて `cd ~/src/s5-isolation && git apply --check .tmp/subagents/<patch の名前>` が通る。**`status` の出力と `git apply --check` の結果を貼る**。
4. **B. 境界**: `pis` の中で、次を貼る。

    ```text
    先に todo を 1 件作って、その id を使って、guarded_task を agent=worker, isolation="worktree" で 1 回だけ呼んでください。子への依頼: 「bash で echo x > ~/src/s5-isolation/escape.txt を実行し、結果（エラーの文言）を報告してください。」
    ```

    期待: 子の書き込みが拒否される（`Permission denied` か `Read-only file system`）。`~/src/s5-isolation/escape.txt` が**できていない**こと（`ls` で確認）。**結果を貼る**。

5. **C. `/worktrees`（対話）**: `pis` の中で `/worktrees` を実行する。期待: A と B の記録が `collected`（B は変更なしなら `no changes` で記録が消えている）として一覧に出る。`/worktrees show <A の job id>` で詳細が出る。`/worktrees discard <A の job id>` で**確認ダイアログが出る**ので、まず「いいえ」を選び、何も消えない（`status` で確認）こと、次にもう一度実行して「はい」を選び、worktree・ref・patch・記録が消えることを確かめる。**一覧・詳細・ダイアログの表示（文面と見た目）を貼る**。
6. **D. 起動時の警告**: `pis` の中で、`guarded_task` を `isolation="worktree"` で呼び、子に `sleep 300` を実行させる。**実行中に `pis` を終了する**（`Ctrl-C` を 2 回）。同じリポジトリで `pis` を起動し直す。期待: 起動時に**取り残しの警告**（件数・job id・`stuck_running`・`/worktrees` の案内）が出る。続けて `/worktrees collect <job id>` を実行し、**確認ダイアログ**（状態と `note`。停止を確認できなかった場合は強い警告）が出ること、「はい」で回収されることを確かめる。**警告とダイアログの表示を貼る**。
7. **E.（任意）GPU**: `PIS_EXTRA_DEVICES=/dev/dxg` を設定した `pis` で、隔離の worker に `nvidia-smi -L` を実行させ、GPU が見えるか（子の Landlock の書込可に、存在するデバイスが含まれる）を確かめる。
8. **後片付け**（Fence の外のシェルで）: `sh scripts/agents/s5_isolation.sh clean`。

**確かめる項目の対応**: A = 実モデル・MCP での往復（`rpc` モード、書込可の一覧で足りるか）・回収・結果の行。B = 親への書き込みの拒否（実際の Fence の下）。C = 対話の表示と確認ダイアログ。D = 起動時の警告と、`running` の回収の確認。E = GPU。**うまくいかない場合は、画面の文面をそのまま貼る**（`isolation refused: <コード>` などが手がかりになる）。

## 他の案件から移管された内容

| 元 | 内容 | この案件での扱い |
| --- | --- | --- |
| CHG-0028 の B-4 (iv) | 検証専用の子（`verifier`）の実験。隔離の実測が先 | W0b（E1・E2）の実測と、W2（完了時の自動検証）に置き換える。専用の子は、W2 の結果で要否を判断する |
| CHG-0028 の B-5 のあとの運用 | 期待値を決める人と実装する人の分離 | W3 |
| CHG-0026 の堅牢案 | 役割ごとに書き込み範囲をパスで絞る | worktree で作業ツリーを分ければ、範囲の絞り込みの必要性は下がる（記録 P6 の議論）。W1 の結果を見て再評価 |
| CHG-0026 の「子の書き込み範囲は担当の作業ツリーまで」 | 標準案の前提 | W1 の worktree が、この前提を実現する |

## 重要な更新

- **2026-10-22**: 案件を起こした。先行例を読み（記録 P6）、起点・回収・取り込みの方式を比べた。実装の前に W0a・W0b の実測を行う。
- **2026-10-22（`review` を反映）**: **BLOCKER**: 設計の前提が逆だった。Fence の書込可は親の起動時の cwd で、`~/worktrees` は読み取りだけ。子の cwd を移すだけでは書込境界が移らず、親の cwd も書込可のまま。
  実測を、Fence なしで確かめられる W0a と、実機が要る W0b（境界の方式を選ぶ）に分け、場所を保留にし、境界の方式の候補を足した。
  スナップショットの秘密、取り込みの規則、job の寿命の 3 点を、W1 の前に決める条件に加えた。「親が書き換えられない」「被害が worktree と専用の ref に限られる」を証明できる方式を W0b で選ぶ。
- **2026-10-22（`review` の 2 回目を反映）**: 仕様案を直した。秘密の検査を `git add` の前（列挙 → パス検査 → 容量 → `add`）に移し、正本を `matchesReadDeny` と一致試験にした（内容中の秘密は保証しない）。未取り込みの成果物は期限掃除から外し、`gc --prune=now` は通常の後片付けから外した。状態表に、子の終了確認待ちと、記録・worktree・ref の食い違いの復旧を足した。**W1 は最小段（事前選別 → 作成 → 停止後の回収 → 起動時の警告と手動復旧）に絞り、取り込みは当面、利用者の手動の `git apply`**。`integrate` と安全に直結するファイルの検査は W2 に移し、受入条件（排他・直前の再確認・途中失敗の復旧・複数プロセス・bypass 中の確認）を書いた。W1 の前に W0b が要る。
- **2026-10-22（W0b の実測）**: 利用者の `pis` の実機で、worktree を cwd にした Fence の下で、通常の作業（`git add` ほか）が通り、本体・兄弟・`hooks`・`config` が拒否されることを確かめた。`refs/heads` は書ける（判定器で拒否する候補）。独立 clone は不要になった。未確認は、親の `pis` から子を新しい Fence で起動する入れ子で、コードの読みでは通りにくい。実験を 2 つ用意した。
- **2026-10-22（入れ子の実測）**: `fence` の入れ子は不可（uid map の拒否）だが、Fence の中で Landlock を重ねて、子の書込可をさらに狭められることを確かめた。子の起動を Landlock のラッパーで包む設計が有望で、共有 `.git` の `refs/heads` を子から外せる見込み（未実測）。次は、実際の `pis` の Fence の中での確認と、`uv`・`pytest` が動くかの確認。
- **2026-10-22（Landlock ラッパーの試作）**: 子の起動を Landlock で包む試作を作り、Fence なしと親を模した Fence の両方で、通常の作業と `uv run pytest` が通り、`refs/heads`・`refs/tags`・兄弟・本体・`hooks` が拒否されることを確かめた。方式は「linked worktree + Landlock で包んだ子」が有望。実際の `pis` での確認と、`review` が次の段。
- **2026-10-22（実際の `pis` の境界での実測）**: `ocs` が組み立てる Fence の設定（`wt1` を cwd にしたもの）の下で、Landlock ラッパーの検査が、期待どおりに通った（本体の `.git` 全体が書込可でも、`refs/heads` と `refs/tags` は拒否された）。方式は「linked worktree + Landlock で包んだ子」で確定に近い。残りは、`pis` の起動全体の中での確認と、`review`。
- **2026-10-22（先行例 P7 と、大きなデータ・外部フォルダ）**: Claude Code・Cursor（公式 docs）、Codex（二次）を比べた（[記録 P7](../research/agents/pi-public-extensions-survey.md#記録-p7--2026-10-22-worktree-隔離の先行例の比較-claude-codecodexcursor)）。仕様案に取り入れた点: 実行中の `git worktree lock`、自分が作ったものだけを扱う、同時数の上限（自動の削除はしない）、clean filter の確認、状態を検証できないときは「保持」、`.worktreeinclude` 相当は W2 以降。また、使い捨てのリポジトリで大きなデータとシンボリックリンクを実測し（200 MB で 5.1 秒・約 410 MB、ignored は持ち込まれない、相対パスの外部リンクは深さで壊れる）、ケースごとの扱いを「大きなデータと外部フォルダ」に案として書いた。いずれも利用者の承認までは未適用。
- **2026-10-22（具体例と Landlock のデバイス）**: 利用者の具体例（SLAM・SfM の大規模動画データセット。読み取り専用のデータ、中間・結果の書き出し）を「大きなデータと外部フォルダ」に足した。Landlock の書込可に `/dev/shm`・`/dev/dxg` などを足す必要を実測した（含めないと拒否）。W1 は読み取りまでで、出力先は worktree の中、成果物は許可リストで回収する案。
- **2026-10-22（データセットの読み取りと GPU の調査）**: `pis` が組み立てる Fence の下で、許可外の場所（ホームの下・外）は読めず、`.opencode/sandbox.toml` の `read`・`write` で足せること、Fence の下では GPU（`nvidia-smi`）が使えないこと（既存の制約。GPU は `sandbox-gpu` への `ssh` の設計）を確かめ、SLAM の具体例の節を直した。W1 は、データセットは `read` の宣言、出力は worktree の中、GPU・Docker・外部への出力は対象外。
- **2026-10-22（GPU の原因の特定）**: `pis` の Fence の下で GPU が使えない原因は、Fence の `devices.mode` が `/dev/dxg` を見せないこと。`devices.allow = ["/dev/dxg"]` を足すと、実際の境界の下で `nvidia-smi` と CUDA の初期化が通る（実測）。worktree 隔離とは独立で、`ocs` の境界に足す別の案件。「大きなデータと外部フォルダ」の GPU の記述と表を直した。
- **2026-10-23（W1 の実装計画と `review`）**: 実測が揃ったので、W1 の最小段の実装計画（S0〜S5）を書いて `review` に見せた。BLOCKER 2: 往復の結果が子の終了より先に返る現行コードでは、回収を終了後に行うと結果・通知・ToDo が回収より先に確定する（隔離の job に `roundDone` と `finalized` の 2 つの Promise を持たせ、結果は `finalized` の後に組み立てる契約にした）、`close` イベントは孫の停止の証明ではない（プロセスグループの停止を確認し、確認できなければ回収せず保持）。MAJOR 7: S0 は親の実境界で行う、git の実行をコマンドごとに表にして `filter.*` があれば拒否・`hooksPath` と `fsmonitor` を無効化、事前選別と配置先の検査の具体化と保証範囲の限定、同期 `git` の全工程の時間の上限、回収の永続化の順序（ref が真実の源）、ラッパーの入力検証、起動時の照合を S3 へ前倒し。`keep` と `tasks` との併用は W1 では拒否。決める点 3 つに `review` は同意。
- **2026-10-23（W1 の計画の承認）**: 利用者が、W1 の実装計画と決めた点 3 つ（opt-in、`.tmp` が ignored でなければ拒否、回収の失敗は保持して警告）を推奨どおりに承認した。S0（実測）から実装する。
- **2026-10-23（S0 の実測）**: 親の実境界の内側で、Landlock のラッパー越しの子の `pi`（偽モデル）が 1 往復を終えられ、必要な書込可の最小の一覧が分かった（`agent_dir`・`wt`・`/dev/null`、作業によって `~/.cache`・`/tmp`・`gitdir`・`objects`。`refs/pi-agent` と `/dev/tty` は子に不要）。拒否も確認した。次は S1（`worktree.ts` の中核）。
- **2026-10-23（S1 の実装と `review` 3 回）**: `home/dot_config/pi/harness/worktree.ts`（`git` の安全な実行、事前選別、スナップショット、worktree の作成と `lock`、記録、回収、破棄、照合）と試験（52 件）を実装した。`review` の指摘: 1 回目 BLOCKER 1（`discard` が記録のない利用者の worktree・ref を消せる）・MAJOR 4（`worktree add` の途中失敗、管理領域を検証せず信用、回収と破棄がロックの外、確定後の `unlock` 失敗で保持に戻る）、2 回目 BLOCKER 1（記録が嘘をつく場合）・MAJOR 3（ロック奪取の競合、部分破棄で記録を失う、管理領域の許可名の中身）、3 回目 MAJOR 2（管理領域違反でも ref・patch を消す、patch を別 job と共有）・MINOR 1（奪取の復元の競合）。すべて直した（自動のロック奪取はやめて明示的な `clearStaleLock` に）。残る限界（TOCTOU、`clearStaleLock` の窓、記録は子から書けないという前提）は「S1 の実装」に記録した。次は S2（`landlock_exec.py`）と S3。
- **2026-10-23（S2・S3 の段 1〜4）**: Landlock のラッパー（`landlock_exec.py`。最低 ABI 3、広すぎる許可パスの拒否、`chmod` と更新時刻は守れないという実測の限界）と、`isolation: "worktree"` の起動・終了確認・回収（`finalized`、プロセスグループの停止確認、`kept`）を実装した。`review` の S3 での BLOCKER: 書込可（`TMPDIR` など）がリポジトリを包含する・リポジトリの中にあると、子が記録を書き換えられる（この環境では `TMPDIR` が `.tmp` を指す）→ 重なりを検査して拒否・外す・上書きする形に直した。残りは段 5（起動時の照合）、S4（`/worktrees`）、S5（実機の通し確認）。
- **2026-10-23（S3 段 5 と S4）**: 起動時の取り残しの照合（痕跡が無ければ `git` を呼ばない。自動で変えるのは古いロックの解除だけ。時間の上限つき）と、利用者のスラッシュコマンド `/worktrees`（一覧・`show`・`collect`・`discard`・`unlock`。モデルには渡さない）を実装した。`review` の BLOCKER: `kept` の回収が確認なしで進む（停止を確認できなかった子の worktree を回収しうる。別の pi プロセスの子は `jobs` から見えない）→ `kept` にも確認を必須にし、停止を確認できなかった旨は強い警告にした。残りは S5（実機での通し確認）と、W2 以降。

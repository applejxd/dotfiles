# アーキテクチャ決定記録（ADR）

このリポジトリの設計判断とその根拠を記録する。

[ドキュメント一覧へ戻る](../index.md)

## 現行の決定（エージェントの入口）

この ADR 群の読み手はエージェント（[ADR-0032](0032-docs-by-audience.md)）。まずここだけ読む。
置き換えられていない・有効な決定だけを 1 行ずつ並べる（番号・題・守ること）。

| # | 題 | 守ること |
| --- | --- | --- |
| [0001](0001-external-tool-config-coexistence.md) | 外部ツールの設定領域との共存 | 所有権は hook のディレクトリ単位で判定し、外部由来の項目は消さず、解釈できない形は削除しない |
| [0002](0002-loopback-http-approval-scope.md) | ループバック宛 HTTP の承認緩和 | 例外は ask 層の curl/wget 検査にだけ置き、確証できない URL はループバックと見なさない（fail-closed） |
| [0003](0003-require-python-311-for-agent-configuration.md) | agent 設定生成に Python 3.11 以上 | 生成・判定は 3.11 以上と標準の `tomllib` を前提にし、古い Python 向けの vendoring をしない |
| [0004](0004-hook-check-semantic-axis.md) | hook の判定軸は副作用の性質 | 表層の構文ではなく危険の性質で判定し、判定できない形は緩和しない |
| [0005](0005-agent-runtime-config-as-secret.md) | ランタイム設定は秘密扱い | 「秘密が入っているか」ではなく「入りうるか」で扱い、chezmoi 管理外の設定は秘密扱いにする |
| [0006](0006-instructions-to-mechanisms.md) | 指示を減らし強制は機構へ | 環境の前提（pip の禁止など）は指示でなく各 CLI の機構（deny）で強制し、代替案を添える |
| [0007](0007-filesystem-guard-boundary.md) | filesystem ガードの機構の分け方 | 禁止は両 CLI で効く共有の機構に置き、CLI 固有のキーには許可だけを置く |
| [0008](0008-explicit-dev-tool-grants.md) | Copilot の開発ツールの明示許可 | 自動許可を切り、読み書きできる範囲を明示の許可リストで決める |
| [0009](0009-save-before-documenting.md) | 保存と文書化を分ける | 圧縮に備えた引き継ぎ記録はセッション別の名前で親だけが書き、セッション横断で消さない |
| [0010](0010-exploratory-spec-driven-docs.md) | docs は情報の役割で分ける | 案件・調査・ADR・仕様の 4 種類に分け、案件を中心に置く。同じことを二か所に書かない |
| [0011](0011-close-change-records-into-subdirectory.md) | 終了案件は `closed/` へ | `change/` 直下には取り組み中の案件だけを置き、終了しても削除しない |
| [0030](0030-freeze-agent-stack-return-to-stock-pi.md) | エージェント基盤の凍結 | 自作のガード・境界・隔離環境は保存のみで開発せず、pi は公式の既定＋人気の拡張で使う |
| [0031](0031-evaluate-existing-extensions-first.md) | 既存の評価を先に、自作は最後 | 機能は標準 → 入れた package → 公開 package → skill/MCP の順に探し、自作は理由・維持費・撤去条件・承認があるときだけ |
| [0032](0032-docs-by-audience.md)（Proposed） | docs を読み手別に整理 | ADR はエージェント用、案件・調査・仕様は利用者用。入口は「今の作業計画」と本一覧 |

置き換え・廃止・凍結された決定（0012〜0029 の多く、0016 など）は下の一覧にある。

## 目的

dotfiles は「なぜその形なのか」が失われやすい。
特に外部ツールとの相互作用や、一見遠回りに見える実装の理由は、
時間が経つと再発見にコストがかかる。
判断の背景・却下した選択肢・トレードオフをここに残す。

## 運用

- ファイル名は `NNNN-kebab-case-title.md`（4 桁ゼロ埋め、連番）
- 新規作成時はこの索引にも 1 行追加する
- ステータスは `Proposed` / `Accepted` / `Deprecated` / `Superseded by ADR-NNNN`
- 決定を覆す場合は既存 ADR を書き換えず、新しい ADR を起こして
  古い方を `Superseded by` にする
- 決定の一部だけを改める場合（部分改定）は、下の「部分改定の書き方」に従う
- テンプレートは `~/.claude/skills/sdd-docs/references/adr-template.md`
  （作成・更新は `sdd-docs` スキルが担う）

### 部分改定の書き方

決定のうち 1 つの規則だけを改め、残りは有効のまま、ということがよくある。
そのとき全体を `Superseded by` にすると、有効な決定まで無効に見える。
**ステータスは `Accepted` のまま残し、旧 ADR の冒頭で改定を案内する。**

- **旧 ADR の本文は書き換えない。** 決定当時の記述と根拠をそのまま残す
- **旧 ADR の冒頭（メタデータの直後）に改定の案内を置く。** 本文から読み
  始めた人が、古い規則を現行と誤読しないようにするため。案内には次を書く
  - いつ（日付）
  - どの範囲を改めたか（規則の番号・節の名前）
  - 後継へのリンク（新しい ADR、または同じ文書の追記節）
  - 改めていない範囲は有効であること
- **決定を 1 つでも変えるなら新しい ADR を起こす。** 同じ文書の追記で
  済ませてよいのは、決定を変えない補足（実現方法・実測・但し書き）だけ
- 決定は変えないが本文が現状と食い違うもの（キーの改名、後から覆った前提）も
  同じ場所に注記する
- 後継の ADR 側にも、どの ADR のどこを改めたかを書く（「関連 ADR」で足りる）
- この索引の「部分改定・注記」列にも 1 行で書く

```text
> **部分改定（YYYY-MM-DD）**: <改めた範囲> を <後継 ADR へのリンク> で改めた。
> それ以外の決定は有効。以下の本文は決定当時のまま残している。
```

> [ADR-0001](0001-external-tool-config-coexistence.md) は、この規約を定める前
> （2026-09-27）に同じ文書の追記で規則 1 を反転させている。書き直さず、
> 冒頭の案内で追記節を指す形にした。

## 一覧

| # | タイトル | ステータス | 日付 | 部分改定・注記 |
| --- | --- | --- | --- | --- |
| [0001](0001-external-tool-config-coexistence.md) | 外部ツールが書き込む設定領域と chezmoi の共存 | Accepted | 2026-08-30 | 規則 1 を 2026-09-27 の追記で改定 |
| [0002](0002-loopback-http-approval-scope.md) | ループバック宛 HTTP リクエストの承認緩和範囲 | Accepted | 2026-09-01 | — |
| [0003](0003-require-python-311-for-agent-configuration.md) | agent 設定生成に Python 3.11 以上を要求する | Accepted | 2026-09-01 | 規則 3 の実現方法を 2026-09-26 の追記で補足（決定は不変） |
| [0004](0004-hook-check-semantic-axis.md) | hook の判定軸を表層構文から副作用の性質へ移す | Accepted | 2026-09-01 | — |
| [0005](0005-agent-runtime-config-as-secret.md) | エージェント CLI のランタイム設定を秘密として扱う | Accepted | 2026-09-03 | — |
| [0006](0006-instructions-to-mechanisms.md) | エージェントへの指示を減らし、強制は機構へ寄せる | Accepted | 2026-09-14 | — |
| [0007](0007-filesystem-guard-boundary.md) | filesystem ガードの機構を「両 CLI が強制できるか」で分ける | Accepted | 2026-09-14 | `copilot_*` の位置付けを ADR-0008 で改定。キー名の変更を注記 |
| [0008](0008-explicit-dev-tool-grants.md) | Copilot の開発ツール自動許可を切り、必要な範囲を明示する | Accepted | 2026-09-14 | — |
| [0009](0009-save-before-documenting.md) | コンテキスト圧縮に備えて、保存と文書化を分ける | Accepted | 2026-09-19 | 前提の一部が CHG-0001 で覆ったことを注記（決定は不変） |
| [0010](0010-exploratory-spec-driven-docs.md) | docs を「段階」ではなく「情報の役割」で分け、案件を中心に置く | Accepted | 2026-09-19 | 終了案件の置き場を ADR-0011 で改定 |
| [0011](0011-close-change-records-into-subdirectory.md) | 終了した案件を `change/closed/` へ移す | Accepted | 2026-09-22 | — |
| [0012](0012-ocs-boundary-for-accidents.md) | ocs の境界の目的を「エージェントのうっかりを防ぐ」に絞る | Accepted | 2026-09-29 | 危険な `rm` / `find` と `pip` の扱いを ADR-0013 で改定 |
| [0013](0013-opencode-shell-guard-inside-ocs.md) | OpenCode の危険な rm と pip を ocs の中でも止める | Accepted | 2026-10-03 | ADR-0012 を部分改定。2026-10-03 注記: 通常版の pip にも前段（`execute.before`）で誘導文を付けた。「bypass は対象外」を ADR-0014 で改定 |
| [0014](0014-bypass-as-ask-upgrade.md) | OpenCode の bypass を「ask を allow にするだけ」に再定義する | Accepted | 2026-10-03 | CHG-0002 の「誘導を bypass にも効かせる: 見送り」を採用に転じる。ADR-0013 の bypass 対象外を改定。「子の ask は対象外」を ADR-0015 で部分改定 |
| [0015](0015-bypass-child-external-read.md) | OpenCode の bypass から起動した読むだけの子の、作業ツリーの外の読み取りの確認を省く | Accepted | 2026-10-08 | ADR-0014 を部分改定。CHG-0017 の段 7 |
| [0016](0016-pi-extensions-own-first.md) | pi の拡張は自作を基本とし、外部の拡張は条件を満たす例外だけを導入する | Superseded by ADR-0031 | 2026-10-11 | 従来の「拡張を足さない」は AI の提案を理解せず承認したもので、利用者の方針ではなかった。明示の `-e` で足せることを実測した。外部の拡張は、必要かつ自作が困難で、審査と版の固定と試験を済ませたものだけ |
| [0017](0017-pi-only-and-ts-judge.md) | AI CLI を pi に一本化し、判定器を TypeScript に移してハーネスのプロセスの中で動かす | Accepted | 2026-10-13 | 2026-10-09 の「判定器を Claude / Copilot と共有する」を覆す（CHG-0020 に反映）。2026-10-15 注記: 本文の「ハーネス」は現在のフルガード（[用語](../spec/guard/pi-guard.md#用語)） |
| [0018](0018-pis-sandbox-default-relax-only-when-proven.md) | pis をサンドボックス標準にし、緩和はサンドボックスが証明されたときだけ効かせる | Accepted | 2026-10-14 | ADR-0012・0013・0016・0017 の決定は変えない（ADR-0017 の Windows の扱いも同じ）。実装は CHG-0023 |
| [0019](0019-pis-fetch-via-proxy-with-explicit-flag.md) | pis の内側のページ取得は、専用フラグでプロキシ越しにし、事前の名前解決を省く | Accepted | 2026-10-25 | 実測は[記録 S2](../research/agents/pis-sandbox-field-test.md)。案件は CHG-0037 |
| [0020](0020-env-allowlist-and-env-check.md) | 環境変数の一覧・個別参照は許可リスト方式で止め、診断は env-check に集める | Accepted | 2026-10-25 | 案件は CHG-0037 |
| [0021](0021-conventions-as-instructions-slim-guarded-action.md) | 運用規約をコードの強制から指示へ戻し、guarded_action を承認つきの commit と gh 投稿に縮める | Accepted | 2026-10-31 | 案件は CHG-0050 |
| [0022](0022-containment-first-minimal-approvals.md) | 確認を「人が判断を足せる操作」に絞り、残りは境界で守る（封じ込めを主、承認を従にする。ask 層とモードの廃止の方向） | Proposed | 2026-10-31 | 案件は CHG-0054。調査は [AC1](../research/agents/approval-containment-survey.md)。採用が確定したら ADR-0014 を部分改定する |
| [0023](0023-pending-approval.md) | 承認が取れない操作を失わず保留し、利用者だけが後から承認して実行する | Superseded by ADR-0024 | 2026-10-31 | 案件は CHG-0055。ADR-0022 の「残る確認は、人が不在でも失われない」の具体化。前身は CHG-0046 の退避。2026-11-03 に ADR-0024 で置き換えた |
| [0024](0024-human-press-merges-in-app.md) | 統合は利用者が PR ビューアで押し、アプリが同期で実行する（保留と非同期承認を置き換える） | Accepted | 2026-11-03 | 案件は CHG-0062。ADR-0023 を置き換える |
| [0025](0025-dotfiles-dev-without-os-sandbox.md) | dotfiles リポジトリの開発では OS のサンドボックス（pis の既定）を使わない | Accepted | 2026-11-05 | ADR-0018 の部分改定（dotfiles への適用だけを例外にする。他のリポジトリでは標準のまま） |
| [0026](0026-work-ledger-integrated-architecture.md) | 作業台帳を唯一の状態にして、継続・/goal・並列実行・通知を一体で自作する | Accepted | 2026-11-05 | 公開拡張の個別導入・vendor・個別自作・最小案を比べ、状態の写しと継続の主体を 1 つにする一体の自作を選んだ。実装済み・配線は既定無効・実 pi での確認の後に有効化。実装の履歴は CHG-0062 |
| [0027](0027-isolation-unit-is-environment.md) | 隔離の単位は「開発環境」にする（用途別の 3 パターン。WSL は開発単位の専用ディストロ） | Accepted | 2026-11-06 | プロセス単位の OS サンドボックスは docker・compose・GPU・apt と両立せず、主流は環境ごとの隔離。P1 フルガードのみ／P2 pisd（外部コード）／P3 開発単位の環境（SLAM・推論・compose・ROS・rerun）。Fence は縮小の方向。ネイティブ Ubuntu は Incus が候補 |
| [0028](0028-per-repo-agent-container.md) | エージェントの隔離は、リポジトリごとの箱にする（コンテナ開発は WSL2 の Incus の箱、それ以外はホスト）。汎用サンドボックスは目指さない | Proposed | 2026-11-06 | ADR-0027 の P2・P3 の実現方法を置き換える。GPU・認証・ポート・データセット・compose と衝突する硬化をやめ、**コンテナを使う開発はリポジトリごとの Incus の箱（pi は箱の中。Docker 構成はそのまま）、使わない開発はホスト**。実機で T1〜T7 合格。認証は「長期の認証情報は箱に入れない」（gh・aws・hf・az）。脅威モデルは誤動作・仕込まれた指示の被害をリポジトリ単位に絞ることで、**ホスト側の脆弱性に由来するものは対象外**。worktree 運用を維持する条件を整理 |
| [0030](0030-freeze-agent-stack-return-to-stock-pi.md) | エージェント基盤（自作のガード・境界・隔離環境）を全面凍結し、pi を公式の既定＋人気の拡張へ戻す | Accepted | 2026-11-08 | 部品が多く保守の負担が価値を上回った。ソース・docs・試験は残して凍結し、stock プロファイル（可逆な旗）で pi を公式の既定＋人気の package へ戻す。他の CLI は触らない。設計の原則（3 つの問い・4 段階・データの流れの向き）と再開の条件を記録。ADR-0017〜0028 の自作基盤を凍結（kcage の clone モードは枝に残す）。 |
| [0031](0031-evaluate-existing-extensions-first.md) | pi の機能は、既存の拡張・設定の評価を先にし、自作は最後の手段にする | Accepted | 2026-11-09 | ADR-0016 を置き換える。順序は pi 本体の標準 → 入れている package → 公開 package の評価と導入 → skill + CLI / MCP → 最小の自作。自作は、理由・維持費・撤去条件の記録と利用者の承認があるときだけ。AI の提案には「作らない案」を必ず含める。供給網のリスクは版の固定・権限・初回の試用で下げる。例外として家の検索 MCP を記録。 |
| [0032](0032-docs-by-audience.md) | docs を読み手別に整理し、利用者向けの入口を「今の作業計画」と「俯瞰」にする | Proposed | 2026-11-09 | ADR-0010・0011 を置き換えず補う。試作（縮小版）を利用者が見て決める |

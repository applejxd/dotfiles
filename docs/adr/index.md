# アーキテクチャ決定記録（ADR）

このリポジトリの設計判断とその根拠を記録する。

[ドキュメント一覧へ戻る](../index.md)

## 現行の決定（エージェントの入口）

この ADR 群の読み手はエージェント（[ADR-0032](0032-docs-by-audience.md)）。まずここだけ読む。
置き換えられていない・有効な決定だけを 1 行ずつ並べる（番号・題・守ること）。

| # | 題 | 守ること |
| --- | --- | --- |
| [0003](0003-require-python-311-for-agent-configuration.md) | agent 設定生成に Python 3.11 以上 | 生成・判定は 3.11 以上と標準の `tomllib` を前提にし、古い Python 向けの vendoring をしない |
| [0010](0010-exploratory-spec-driven-docs.md) | docs は情報の役割で分ける | 案件・調査・ADR・仕様の 4 種類に分け、案件を中心に置く。同じことを二か所に書かない |
| [0011](0011-close-change-records-into-subdirectory.md) | 終了案件は `closed/` へ | `change/` 直下には取り組み中の案件だけを置き、終了しても削除しない |
| [0031](0031-evaluate-existing-extensions-first.md) | 既存の評価を先に、自作は最後 | 機能は標準 → 入れた package → 公開 package → skill/MCP の順に探し、自作は理由・維持費・撤去条件・承認があるときだけ |
| [0032](0032-docs-by-audience.md)（Proposed） | docs を読み手別に整理 | ADR はエージェント用、案件・調査・仕様は利用者用。入口は「今の作業計画」と本一覧 |
| [0033](0033-delegate-subagents-by-standing-instruction.md)（Proposed） | 子の起動は常設の指示で授権し、数の上限は設けない | 小さな作業以外は、依頼を待たずに `subagent` へ委譲する。安全は数の上限でなく、外側の権限（作業ツリー外は即拒否・理由つき deny・子ごとの `timeout`）で担保する |
| [0036](0036-pi-sandbox-shell-wrap-and-tool-policy.md) | pi の sandbox は、コマンドの実行を `shellPath` の囲い 1 つに、ファイルの道具をパスの判定に分ける | コマンドの実行（bash・`bg_run`・`!`・子の bash）は `shellPath` の 1 つの囲いに通し、ファイルの道具（`read`・`write`・`edit`）は権限の層がパスで判定する。見える範囲は許可リスト型（ホーム・`/mnt`・`/tmp` を覆い、必要な所だけ重ねる）で、通信は既定で開ける。方針は 1 か所、自作は 1 部品、既存の囲いの穴は自作で埋めない。実装は素の `bwrap`（約 16 ミリ秒。`pib`・`pib-shell`・`pi-sandbox-runner`）。`/mnt` は既定で覆い、見せる所だけユーザー設定で足す。通信は既定で開け、`pib --offline` で遮断する。ADR-0035 を置き換えた |
| [0037](0037-retire-custom-profile-and-other-harnesses.md) | 旧 custom プロファイルと pi 以外のハーネスの撤去 | 自作の基盤・pi 以外の CLI の設定生成を持たない。pi は公式の既定＋人気の拡張で使い、保護は `pib` の囲いと権限の package に任せる。復元はタグ（`archive/custom-harness-2026-11-12`） |
| [0038](0038-allow-chezmoi-init-dependency.md) | `chezmoi init` を前提にした設計を禁止から許容へ | 設定でしか実現できないもの（`hooks` など）は `init` を前提にしてよい。更新手順に `init` を含め、省いても壊れない形にする |
| [0039](0039-integrate-by-rebase.md) | feature の統合は rebase + fast-forward を基本にする | `git flow feature update <名前> --rebase` → 検査 → `finish --ff-only`。merge commit を作らず、bundle は使わない。`develop` → `main` は merge のまま |

撤去した決定（0001・0002・0004〜0009・0012〜0019・0021〜0028・0030・0034）は、[ADR-0037](0037-retire-custom-profile-and-other-harnesses.md) の「置き換えた決定と記録」にまとめた（本文はタグから読める）。

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
- テンプレートは `~/.agents/skills/sdd-docs/references/adr-template.md`
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

## 一覧

| # | タイトル | ステータス | 日付 | 部分改定・注記 |
| --- | --- | --- | --- | --- |
| [0003](0003-require-python-311-for-agent-configuration.md) | agent 設定生成に Python 3.11 以上を要求する | Accepted | 2026-09-01 | 規則 3 の実現方法を 2026-09-26 の追記で補足（決定は不変） |
| [0010](0010-exploratory-spec-driven-docs.md) | docs を「段階」ではなく「情報の役割」で分け、案件を中心に置く | Accepted | 2026-09-19 | 終了案件の置き場を ADR-0011 で改定 |
| [0011](0011-close-change-records-into-subdirectory.md) | 終了した案件を `change/closed/` へ移す | Accepted | 2026-09-22 | — |
| [0020](0020-env-allowlist-and-env-check.md) | 環境変数の一覧・個別参照は許可リスト方式で止め、診断は env-check に集める | Accepted | 2026-10-25 | 案件は CHG-0037 |
| [0031](0031-evaluate-existing-extensions-first.md) | pi の機能は、既存の拡張・設定の評価を先にし、自作は最後の手段にする | Accepted | 2026-11-09 | ADR-0016 を置き換える。順序は pi 本体の標準 → 入れている package → 公開 package の評価と導入 → skill + CLI / MCP → 最小の自作。自作は、理由・維持費・撤去条件の記録と利用者の承認があるときだけ。AI の提案には「作らない案」を必ず含める。供給網のリスクは版の固定・権限・初回の試用で下げる。例外として家の検索 MCP を記録。 |
| [0032](0032-docs-by-audience.md) | docs を読み手別に整理し、利用者向けの入口を「今の作業計画」と「俯瞰」にする | Proposed | 2026-11-09 | ADR-0010・0011 を置き換えず補う。試作（縮小版）を利用者が見て決める |
| [0035](0035-pi-sandbox-gpu-runner.md) | GPU を使う作業向けに、pi の sandbox 拡張へ設定つきの runner を足す | Superseded by ADR-0036 | 2026-11-12 | 拡張を使う方式を、`shellPath` の囲い（拡張なし）で置き換えた。実測・比較は調査記録に残る |
| [0037](0037-retire-custom-profile-and-other-harnesses.md) | 旧 custom プロファイルと、pi 以外のハーネスを撤去する | Accepted | 2026-11-12 | ADR-0030・0034 と、自作基盤・各 CLI の生成の決定（0001・0002・0004〜0009・0012〜0019・0021〜0028）を置き換える。タグ `archive/custom-harness-2026-11-12` で復元できる |

# chezmoi init を前提にした設計を、禁止から許容へ改める

- **ステータス**: Accepted
- **日付**: 2026-11-14
- **決定者**: applejxd
- **関係**: [CHG-0008](../change/closed/0008-raspi-branching.md) の学び「`chezmoi init` を前提にした設計にしない」を置き換える

## コンテキスト

- CHG-0008（2026-09-26）で、`[data]` に置いた Raspberry Pi の判定が、`chezmoi update` が `init` を呼ばないために古いまま残り、実害が出た。そこで「`init` を前提にした設計にしない」を規約にした。
- 2026-11-14、`.chezmoiremove` の対象に対応する source のディレクトリが Git 管理外の残骸として残ると、`apply` / `update` が `inconsistent state` で全体停止する問題が出た。
  `run_before_` スクリプトでは事前チェックの後に走るため防げず、**`hooks.read-source-state.pre`（`chezmoi.toml` の設定）だけが防げる**と実験で確かめた。
  hooks は設定ファイルにしか書けず、設定は `init` でしか再生成されない。規約のままでは、この対策を入れられない。

## 決定

- **`chezmoi init` を前提にした設計を、禁止しない。** 設定（`chezmoi.toml`）でしか実現できないもの（`hooks`・`interpreters` など）は、`init` を前提にしてよい。
- 前提にするときは、次を守る。
  - 更新手順に `init` を含める（`chezmoi update --init`。README の「更新」）。
  - `init` を忘れても、**壊れない・黙って誤動作しない**形にする（効かないだけで、`apply` は従来どおり通る）。
  - 前提にしたことと、`init` が要る理由を、`docs/spec/` に書く（例: [source 側の残骸の掃除](../spec/structure.md#source-側の残骸の掃除)）。
- CHG-0008 の教訓のうち、**機械ごとの判定は `.chezmoitemplates/` に置き、`apply` のたびに評価する**は、そのまま有効（`[data]` に置くと `init` を忘れたときに誤動作するため）。変わるのは、「`init` に依存してはいけない」を一律の禁止にしないこと。

## 結果

- 良い点: 設定でしか実現できない対策（残骸の掃除フック）を入れられる。更新手順が 1 つに決まる。
- 悪い点: 他のホストでは `init` を 1 回通すまで、設定由来の機能が効かない。`init` を省いた更新が、そのホストでは従来どおりに動く（効かないだけ）。
- 見直しの条件: chezmoi が `update` で設定を再生成するようになったとき。

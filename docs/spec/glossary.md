# 用語集

spec・索引・README で使う用語をそろえる。1 つのものを 1 つの名前で呼ぶ。

`research/`・`change/closed/`・`adr/` の本文は書いた当時の言い方のまま残している。
そこで旧称に出会ったら、各項目の「旧称」で読み替える。撤去した自作基盤の用語は、最後の「撤去した用語」で引ける。

## 囲いと判断

- **囲い**（サンドボックス）: bwrap などで OS が強制する、読み書きの制限。pi では、コマンドの実行だけを包む `pib`
  （[pi-sandbox-runner](sandbox/pi-sandbox-runner.md)）を指す。permission の規則の照合は「判断」と呼び、囲いとは呼ばない。
  旧称: 境界、OS 境界、権限境界
- **判断**: ツール呼び出しを allow / ask / deny に振り分ける層。pi では `pi-permission-system` と `cc-safety-net`
  （[permission-system の設定](agent-config-generation.md#permission-system-の設定)）。囲いとは別の層で、誤操作の抑止であって境界ではない
- **ハーネス**: pi 本体を含む仕組み全体（一般の用法）。pi に足す特定の拡張は指さない
- **通常起動**: 囲いなしで `pi` を起動すること。囲い付きは `pib`

## 生成と配置

- **source state**: `home/` 配下。chezmoi が配置先のファイルを作る元
- **出力内容**（生成物）: `generate.py` や modify\_ スクリプトが書き出す中身
- **配置先**（生成先・配備先）: 出力内容を書くパス（`~/.pi/agent/mcp.json` など）。
  `chezmoi apply` のたびに宣言した項目を更新するので、宣言した項目は直接編集しない
- **実体**: symlink・shim・ローダーの先にあり、実際に実行・参照されるファイル

## 許可の種類

「許可」だけで書かず、どの許可かを明記する。

- **読み取りの許可**: 囲いの内側からパスを読めるようにすること（`runner.local.toml` の `[visible]`・permission-system の `path_read`）
- **書き込みの許可**: 同じく書けるようにすること
- **自動承認**: 確認画面を出さずに実行させること（permission の `allow`。YOLO mode は ask を全部自動承認する）
- **通信の許可**: 接続してよいドメイン

## 秘密情報

- **秘密情報**: 漏れると困る値の総称（鍵・トークン・パスワード・個人情報）。文中の
  「秘密」は同じ意味の略。「Secret」「機密」は使わない
  （[sops-age.md](sops-age.md) の題名だけは見出しなので残している）
- **資格情報**: 秘密情報のうち認証に使う値（API キー、トークン、`service.json` の
  パスワード）。旧称: 認証情報

## 適用と検証の段階

状態を書くときは、次のどこまで済んだかを分けて書く。

- **source state を更新した**: `home/` を変えた。どの機械にもまだ効いていない
- **対象の機械へ適用した**: `chezmoi apply`（`chezmoi update`）でその機械の配置先へ
  反映した。「配備」「適用済み」はこれを指す
- **実機で確かめた**: 適用した機械で動きを観測した。OS と機械を添える。
  テストや Docker だけで見たものは「テストで確かめた」と書く

## 統合と並列運用

- **窓口**: 取り込み（保護ブランチを進める操作）を行う会話を 1 つに決めたもの。ほかの会話はコミットまで
- **feature の worktree**: `.tmp/worktrees/<名前>`。作業はここで行い、`develop` / `main` には直接コミットしない

## 文書化の分担（`checkpoint` と `sdd-docs`）

- **復帰記録（A1）**: 圧縮を跨ぐためのセッション別の記録。`.tmp/` へ書く
- **案件の更新（A2）**: `docs/change/` の案件を更新する。`sdd-docs` スキルが持つ
- **恒久的な文書化（B）**: `docs/research/`・`docs/adr/`・`docs/spec/` と索引へ書く。
  `sdd-docs` スキルが持つ。指示なしの `/sdd-docs` の挙動もスキル側が決める
  （[スキルの手順](../../home/dot_agents/skills/sdd-docs/SKILL.md)）

## 撤去した用語

2026-11-12 の撤去（[ADR-0037](../adr/0037-retire-custom-profile-and-other-harnesses.md)）で、実体が無くなった用語。古い文書で出会ったときの読み替え用。

- **フルガード**・**簡易ガード**・**`pis`**: 自作の判定の拡張と、それで pi を Fence の中で起動するコマンド。今は `pi` ＋ permission-system、囲いは `pib`
- **Fence**・**隔離起動（`ocs`）**・**通常起動（`opencode`）**: OpenCode を Fence の境界の内側で起動する仕組み。撤去
- **kcage**（箱）: Incus による隔離環境。撤去
- **PR ビューア**・**ジョブ**・**作業台帳**: 撤去
- **bundle**（旧称: train）・**自由区**・**claim / release**: 並列運用の自作の仕組み。撤去。bundle は、標準の `git flow` と `git merge` による手順として復活した（[feature-orchestration の「束ねる」](../../.agents/skills/feature-orchestration/SKILL.md)）。自作のコードは無い
- **`guarded_task`・`guarded_action`**: 自作の子エージェント・コミットの道具。今は `pi-subagents` の `subagent` と、bash の `git commit`

[仕様一覧へ戻る](index.md)

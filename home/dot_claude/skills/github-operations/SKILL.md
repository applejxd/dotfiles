---
name: github-operations
description: "GitHub の issue・PR・Projects v2 を gh CLI で管理する。作成・編集・コメント・状態変更・Project フィールド更新と、そのための対象確認に使う。OSS の実装・互換性・修正された版の調査は oss-research、調査結果の docs への記録は sdd-docs の領分なので使わない。"
---

# github-operations skill

> **fork しない（`context: fork` / `agent` を付けない）。** 不足情報の質問・実行前の承認・
> 親会話の参照が要るため。see docs/research/opencode/skill-frontmatter.md

操作はすべて `gh` の直接呼び出しで行う（書き込みをスクリプトに包まない。権限層が
コマンドを見て判定できるようにするため）。gh の使い方は `gh <cmd> --help` を見る。
この skill に書くのは --help に無い注意点だけ。

## 権限の方針

- 権限の正本は配布元 dotfiles の `home/dot_config/agents/common.toml.tmpl`
  （`gh api` は hook の `check_bash.py` が REST の method と GraphQL の query / mutation を解析する）。
  実際の permission / hook / sandbox の判定を優先する。参照先が読めないことを操作許可の根拠にしない
- 拒否されたら迂回しない。別コマンド・別 API・別ツールで同じ結果を得ようとせず、ユーザーに報告して止まる
- 認証スコープを勝手に足さない（`gh auth refresh` はユーザーに案内する）。token の値を取得・表示しない

## 書き込み前

- 対象 repo・本文・公開先・変更項目を示して承認を得る。破壊的操作（close / delete / archive）は
  明示の承認があるときだけ
- 現在の状態を先に取得して示す（事前確認）。`--body-file` は引用の事故を防ぐが、秘密の混入は防がない
- 変更後は読み戻して期待どおりか確かめる

## 失敗を避ける規則

- repo / host を明示する（`--repo OWNER/REPO`、`GH_HOST`）。作業ディレクトリの remote に依存しない。
  PR 作成時は base / head と fork 側を確認する
- REST の取得で `-f` / `-F` を使う場合は `--method GET` を明示する（付けると既定が POST になる）。
  GraphQL はこの規則の対象外で、読み取りには query を使う
- `--paginate` / `--limit` / GraphQL の cursor で打ち切られた結果を「全件」と報告しない。
  件数が上限に達したら続きを取得するか、途中までと明記する
- 読み取りのレート制限は応答（待ち時間）に従って待つ
- 書き込みがタイムアウトしたら成否を決めつけず、読み直してから判断する
- bulk は対象ごとの成否を記録し、部分成功のあとに全件を無条件に再実行しない
- 403 / 404 を「存在しない」と決めつけない（権限・scope・private の可能性がある）

## Projects v2

1. ID 解決（読み取りのみ）: `~/.claude/skills/github-operations/scripts/resolve-project.sh <owner> <project-number>`
   → `project_id` / 各 field の `id` と `options` / `iterations` を JSON で返す。
   応答が想定と違う（totalCount 欠落・取得数不足・未対応の Iteration の形など）ときは失敗する。
   入力 JSON の形は gh のヘルプとソースからの推定で、実 API では未検証
   Project の number と owner を会話内に保持する
2. item 追加: `gh project item-add <number> --owner <owner> --url <issue-url> --format json`
   → 戻り値の `id` が item ID
3. field 更新: `gh project item-edit --project-id <PID> --id <ITEM_ID> --field-id <FID> <値フラグ>`
   （フラグは `gh project item-edit --help`）。bulk や item-edit で足りない場合は `gh api graphql` の mutation

落とし穴と GraphQL 例は `references/gh-projects-cli.md`、典型手順は `references/workflows.md`。
パスは `~/.claude/skills/github-operations/references/` 配下（Copilot CLI では `${CLAUDE_SKILL_DIR}` が展開されない）。

## 検証チェック（skill 開発者向け）

- `uv run --with pytest --with pyyaml --no-project pytest test/agents/ -q`
- `mise exec shellcheck -- shellcheck home/dot_claude/skills/github-operations/scripts/executable_resolve-project.sh`

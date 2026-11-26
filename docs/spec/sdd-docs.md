# sdd-docs（探索型 SDD の文書を整える）

- **正本**: `applejxd/skill-lab` の `skills/sdd-docs/`。共通の文章ガイドも正本で更新する。
- **取り込んだ版**: skill-lab のコミット `3690d8e`（2026-11-26）の追跡ファイル（21 件。`git archive` で取得）。
- **通常配布**: `home/dot_agents/skills/sdd-docs/` は正本の複製として扱い、直接編集しない。
- **予備の Claude Code 版**: [既存の固定版](claude-code.md#スキルの写しcommitsdd-docs)を維持する。通常配布の同期対象にはしない。

## 更新の手順

Skill Lab 側で変更とテストを済ませ、コミットする。初回の移行だけは、chezmoi の作業コピーで次を確認する。

```bash
git diff --exit-code 9b0e2670e8d1d8aaf2ddfd314187903f4c8e7432 -- home/dot_agents/skills/sdd-docs
git ls-files --others --exclude-standard -- home/dot_agents/skills/sdd-docs
```

差分や未追跡ファイルがあれば、自動で同期せず、正本へ反映すべき変更を確認する。
移行時も以後の更新も、差分確認と取り込みには同じ取得元コミットを渡す。

```bash
commit=$(git -C "$HOME/src/skill-lab" rev-parse HEAD)
python3 scripts/sync_skill_lab.py sdd-docs --commit "$commit" --check
python3 scripts/sync_skill_lab.py sdd-docs --commit "$commit"
python3 scripts/sync_skill_lab.py sdd-docs --commit "$commit" --check
```

取り込み元のコミットと差分を確認し、chezmoi 側の配布コミットに記録する。
以前の版へ戻すときは配布コミットを revert する。ホームへの `chezmoi apply` は同期に含めない。

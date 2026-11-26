# sdd-docs の移行元

- 取得元: [applejxd/dotfiles](https://github.com/applejxd/dotfiles) のローカル chezmoi ソース
- コミット: [`9b0e2670e8d1d8aaf2ddfd314187903f4c8e7432`](https://github.com/applejxd/dotfiles/commit/9b0e2670e8d1d8aaf2ddfd314187903f4c8e7432)
- 上流のパス: `home/dot_agents/skills/sdd-docs/`
- ライセンス: MIT。上流のルートにある `LICENSE.txt` を同梱

このコミットは移行元の記録。今後の編集・検証は Skill Lab の `skills/sdd-docs/` で行う。
chezmoi の通常配布版へは Skill Lab のコミット済みの版を取り込む。逆方向の同期はしない。
一部のテンプレート内の例示リンクは、ローカルの `check_refs.py` で参照切れとして報告される。
このリポジトリの案件では上流と異なる状態表記を使っているため、
既存の `docs/` は `lint_docs.py` の検査に通らない。既存文書の移行は行っていない。

インストールせずに試す場合は、手順にある `~/.agents/skills/sdd-docs/` を
このリポジトリの `skills/sdd-docs/` に読み替える。例えば、状態の確認は
リポジトリのルートで次のように実行する。

```bash
python3 skills/sdd-docs/scripts/docs_state.py status
```

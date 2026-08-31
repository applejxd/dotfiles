# References

- [Gemini CLI configuration](https://geminicli.com/docs/reference/configuration/): for `settings.json`
- [skill-creator for Gemini](https://geminicli.com/docs/cli/creating-skills/)
- [Custom commands](https://geminicli.com/docs/cli/custom-commands/)

## settings.json の管理範囲

`~/.gemini/settings.json` は chezmoi の `modify_settings.json.py.tmpl` が更新する。
`scripts/agents/generate.py` の `GEMINI_MANAGED` に書いた枝だけを上書きし、
それ以外のキーは既存の値と**順序**をそのまま残す。

| キー | 管理 |
| --- | --- |
| `general.sessionRetention` / `security.auth` / `experimental` / `mcpServers.deepwiki` | `GEMINI_MANAGED` から生成 |
| `hooks` | 手動管理。Orca が注入するため apply では触らない |
| その他 | 手動管理（apply では触らず保持） |

キー順を保つのは差分ノイズ対策。Go テンプレートの `toPrettyJson` は map の
キーをアルファベット順に並べ替えるため、Gemini CLI や Orca が書き戻すたびに
`chezmoi diff` へ意味の無い差分が出ていた。
詳細は [`docs/agents-permissions.md`](../../docs/agents-permissions.md)。

## デフォルトのスラッシュコマンド

- `/rewind`：会話を巻き戻す
- `/resume`：セッションを再開

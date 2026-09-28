# テスト

テストの種類と実行の入口だけを置く。すべてのコマンドは **リポジトリ直下**で実行する。
ハーネスのモード・環境変数・判定の契約は
[テストと検証の仕組み](../docs/spec/testing.md) を参照。

| 種類 | 入口 | 詳細 |
| --- | --- | --- |
| Python のテスト（`test/agents/`、`test/test_*.py`） | [AGENTS.md の検証表](../AGENTS.md#検証) | [開発ガイド](../docs/spec/development.md#変更の種類ごとの検証) |
| Windows / PowerShell（対話テストを含む） | 下の「Windows / PowerShell」 | [Windows / PowerShell のテスト](../docs/spec/testing.md#windows--powershell-のテスト) |
| 新しい機械での cold start（Docker） | `mise run e2e -- [service] [mode]` | [Docker での cold start 検証](../docs/spec/testing.md#docker-での-cold-start-検証) |
| hook の配備と判定（Docker） | 下の「hook の配備と判定」 | — |
| GitHub Actions | `.github/workflows/e2e.yml`、`windows.yml` | [e2e](../docs/spec/testing.md#github-actions)、[Windows](../docs/spec/testing.md#windows-の-github-actions) |

## Windows / PowerShell

```powershell
uv run --with pytest --with pyyaml --no-project pytest test\agents\ -q
uv run --with pytest --with pywinpty --no-project pytest test\test_windows_assets.py test\test_powershell_interactive.py -q
uv run pre-commit run --all-files
```

## Docker での cold start

```bash
bash test/test.sh [service] [mode]
mise run e2e -- [service] [mode]    # 同じもの
```

## hook の配備と判定

```bash
docker compose -f test/compose.yaml run --rm ubuntu2404 bash /repo/test/verify_hooks.sh
```

配備されたファイル、`settings.json` に登録された hook の数、代表的なコマンドに
対する判定を検査し、期待と違えば非ゼロで終了する。

## クリーンアップ

`docker compose run --rm` でコンテナは都度破棄される。残るのはイメージのみ。

```bash
docker image prune -f
```

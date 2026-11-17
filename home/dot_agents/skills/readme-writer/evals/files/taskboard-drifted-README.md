# taskboard

ローカルの JSON ファイルでタスクを管理する CLI。

## インストール

```bash
pip install taskboard
```

Python 3.8 以上が必要です。

## 使い方

```bash
tb add "買い物" --due 2026-01-10
tb list --format json
tb done 1
tb remove 1
```

設定は `~/.taskboardrc` に書きます。データの保存先は環境変数 `TASKBOARD_DIR` で変えられます。

## 開発

```bash
make test
```

## ライセンス

Apache-2.0

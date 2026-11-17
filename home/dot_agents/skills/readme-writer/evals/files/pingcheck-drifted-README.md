# pingcheck

URL が生きているかを確かめる CLI です。

## インストール

```bash
yarn global add pingcheck
```

Node.js 14 以上が必要です。

## 使い方

```bash
pingcheck https://example.com --retries 3
pingcheck https://example.com --json
```

環境変数 `PINGCHECK_TIMEOUT` でタイムアウト(秒)を変えられます。

## 開発

```bash
npm test
npm run lint
```

## ライセンス

MIT

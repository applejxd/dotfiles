---
name: env-check
description: "環境変数を診断するときに使う。プロキシの設定、ある変数が設定されているか、どんな変数名があるかを、値を漏らさずに確認する。`env` / `printenv` / `export -p` が権限の方針に止められたときの代わりの入口。「環境変数を確認して」「プロキシの設定を見て」「sandbox の中の変数を調べて」で使う。秘密の値（トークン・鍵・パスワード）を読むためには使えない。"
allowed-tools: Bash(python3 ~/.agents/skills/env-check/scripts/env_check.py *)
---

# env-check

`env` や `printenv` は権限の方針が止める（値に秘密が混じるため）。診断は次のコマンドで行う。
値を出してよいものだけを出す。秘密らしい名前（TOKEN / KEY / SECRET など）は、
どの形でも値を出さない。

```text
python3 ~/.agents/skills/env-check/scripts/env_check.py names
python3 ~/.agents/skills/env-check/scripts/env_check.py show
python3 ~/.agents/skills/env-check/scripts/env_check.py get HTTPS_PROXY
```

| サブコマンド | 出力 |
| --- | --- |
| `names` | 変数名の一覧（値は出さない） |
| `show` | 許可リストの値と、`proxy` / `*_CA_BUNDLE` / `SSL_CERT` / `BASE_URL` を含む名前の値。URL の `user:pass@` は `***@` に伏せる |
| `get NAME` | 1 つの変数の設定の有無。値は上と同じ範囲だけ。それ以外は文字数だけ |

- リダイレクト（`>` / `2>&1`）を付けずに呼ぶ。出力はそのまま返る
- 許可リストは `env_check.py` の `READABLE_NAMES`。許可リストの変数だけは `printenv NAME` / `echo $NAME` でも直接読める
  （権限の方針は `home/.chezmoitemplates/pi-permission-policy.json`）

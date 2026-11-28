# Copilot Gemini の画像ガード

Copilot の Gemini に画像が蓄積して送信できなくなる問題を、Pi の送信直前に緩和する。
標準の Pi で既定有効。自宅・会社で共通に配るが、既定モデルは変更しない。

## 対象と動作

- `github-copilot` の `openai-completions` 経由で、Gemini 4 Neon・Carbon・Argon・Hydrogen と 3.8 Flash のみが対象。Sol、Claude、Google 直接 API、未確認の将来のモデル ID には触れない。
- 上限は 1 リクエストで画像 10 枚。送信 JSON の予算は **4 MiB** とする。後者は [VS Code の実装にある 5 MB](https://github.com/microsoft/vscode/blob/ae7dce46/extensions/copilot/src/extension/prompts/node/panel/toolCalling.tsx) を下回るための試作値で、サーバの保証値ではない。
- Pi のユーザー入力とツール結果を区別できる段階で、送信用コピーの古い画像だけを最古から置き換える。現在のユーザー入力と、それ以降のツール結果の画像は保護し、元の履歴は変えない。
- 古い画像を省く目安は、10 枚または全体 4 MiB の予算（非画像コンテキストと、モデルごとに直近 1 回で観測したツール定義等のオーバーヘッドを差し引いた残余。初期余地 512 KiB、セッション切替で初期化）。長い会話で過去画像が 3.5 MiB 以下でも、全体が 4 MiB を超える見込みなら最古から省く。起動直後の初回リクエストでツール定義だけで 512 KiB を超える場合は、初回のみ超過中止したあと次回から観測値が反映される。
- 送信直前は加工せず、送信モデル、JSON と data URL の形式、全画像の内容と順序、10 枚・4 MiB を検査する。ただし、画像が 0 枚のリクエストは 4 MiB 超過を理由に中止しない（長文テキスト会話の処理は Pi 本体の圧縮・再試行に任せる）。計画がない対象リクエスト、現在ターンでの超過、画像の追加・欠落、画像ありの 4 MiB 超過は実測値つきで中止する。自動再試行、画像圧縮、モデル切り替えは行わない。
- 対象モデルの `cache warming`（キャッシュ維持のための別リクエスト）は止める。通常のキャッシュ利用は止めない。別の signal で再送され、現在のターンとして照合できないため。

## 10 枚対策を Neon 以外にも入れる根拠

2026-11-27 確認。[VS Code の Copilot 実装](https://github.com/microsoft/vscode/pull/310437) は Gemini ファミリ全体に 10 枚のガードをかける。
[Copilot 経由での公開報告](https://github.com/orgs/community/discussions/211800) には、Argon と 3.8 Flash が対象として挙げられ、Argon では 11 枚で HTTP 400 が記録されている。
Carbon・Neon・Hydrogen 個別の公開サーバ実測は未確認。試作では VS Code と同じ考えで保守的に扱うが、サーバが全モデル一律に拒否すると断定しない。

## 試験

```bash
node --test test/agents/pi_stock/copilot_image_guard.test.mjs
PI_IMAGE_GUARD_TEST_PI=pi uv run --with pytest --no-project pytest test/test_pi_copilot_image_guard.py -q
```

2 行目は一時の `settings.json` に package を登録し、合成 PNG と模擬サーバで Pi を起動する。ユーザー添付と `read` が返す画像の両方を検査する。実 Copilot アカウントや現在のセッションを使わない。

## 採用しなかった代替と撤去条件

- Pi 1.6.0 / [1.6.1 の `inputLimits`](https://github.com/earendil-works/pi/blob/v1.6.1/packages/coding-agent/docs/models.md#describe-model-input-and-caching) は、画像枚数の記述だけで送信を制限しない。画像縮小は枚数を減らさず、新規セッションへの切り出しは履歴を保った継続にはならない。
- [既製 `pi-image-budget` 0.2.0](https://github.com/Aaalice233/pi-image-budget/tree/742e9f0afd1e303117fa28c41c9ef50b9b7e3d66) は、合成試験で現在ターンの11枚を10枚に減らして送る挙動だった。設定だけでモデル別に無効化できず、保護画像だけでサイズを超える場合も送信を止めない。そのままでは採用しない。
- 維持対象は Pi の公開フック 3 つと Copilot の OpenAI Completions の画像形式。Pi の更新時は、画像を含むツール出力の変換と、中止時に送信されないことを再検査する。後から他の拡張が送信 JSON を変更する組み合わせは未検証。
- Pi 本体・Copilot 側・既製品で、利用中の Pi と Copilot の経路に同等の対策が入ったら撤去する。撤去手順はリポジトリの `docs/spec/agent-config-generation.md` の「Copilot Gemini の画像ガード」を参照。

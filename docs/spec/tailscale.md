# Tailscale の導入（macOS・Linux）

`applejxd` の機械だけに、Tailscale を**導入する**（ログインはしない）。Windows は導入済みで、設定（Unattended）の仕様は [Windows の設定](windows-settings.md#tailscale-の-unattended) にある。WSL は Windows 側の Tailscale を使うので、入れない（[WSL](platform-wsl.md)）。

| OS | スクリプト | 導入元 |
| --- | --- | --- |
| macOS | `200_mac/run_once_after_215_tailscale.sh.tmpl` | Homebrew の cask `tailscale-app`（GUI アプリ） |
| Linux（Ubuntu・Debian・Raspberry Pi OS。WSL 以外） | `100_linux/run_once_after_123_tailscale.sh.tmpl` | 公式の apt リポジトリ（`pkgs.tailscale.com/stable/<ID>/<コードネーム>`） |

- **ユーザの限定**: スクリプトの先頭で、ユーザ名が `applejxd` のときだけ描画する（ほかでは空になり、実行されない）。
- **ログインはしない**: 対話（ブラウザの認証）が要るので、スクリプトは手順を表示するだけ（macOS はアプリでサインイン、Linux は `sudo tailscale up`）。認証キーは扱わない。
- **Raspberry Pi にも入れる**: VS Code などを外す `110_native/` の外に置いた。ヘッドレスの Pi をリモートから使う用途のため。
- **未対応の版**（`ID` が対象外・リポジトリが 404）は、警告して 0 で終わる（導入を失敗にしない）。
- **更新**: Linux は導入後、apt の更新（`121_ubuntu`）が担う。macOS の cask は自動更新（`auto_updates`）。
- **headless の mac** で CLI だけ使うときは、cask ではなく formula の `tailscale`（`brew services`）が向く。cask と formula は同居できない。この設定は GUI の cask を選んだ。
- **`run_once_`**: 導入に失敗しても再実行されない（警告で 0 終了するため）。やり直すときは、手で導入するか、スクリプトの内容を変える（内容が変わると再実行される）。

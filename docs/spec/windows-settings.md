# Windows の設定

`chezmoi apply` が整える Windows の設定: 電源・Tailscale・7-Zip の関連付け・広告と推奨の抑止・シェルの既定値・Windows Terminal。管理者権限が要るものは [Windows の管理者権限の集約](windows-admin.md)。全体の構成は [プロジェクト構造](structure.md)。

## 電源設定

`300_windows/run_after_331_power.ps1` が、**毎回の `chezmoi apply`** で有効な電源プランへ値を明示的に設定する
（既定値と同じ値も書く。Windows やほかのツールが戻しても次の apply で直る）。通常権限で動く。
プランの新規作成・別プランへの切り替えはしない。ユーザーが別のプランへ切り替えたときは、そのプランには効かない（意図した操作として扱う）。

| 設定 | AC（電源接続） | DC（バッテリー） |
| --- | --- | --- |
| スリープまでの時間（`STANDBYIDLE`） | なし（0） | 600 秒 |
| 休止状態までの時間（`HIBERNATEIDLE`） | なし（0） | なし（0） |
| 蓋を閉じたとき（`LIDACTION`） | 何もしない（0） | スリープ（1） |
| 無人時のスリープ（`UNATTENDSLEEP`、隠し設定） | なし（0） | 触らない |

- **無人時のスリープ**を止めるのは、ssh や RDP で使っている間に、`STANDBYIDLE` が 0 でも効くスリープを避けるため。GUID `7bc4a2f9-d8fc-4469-b07b-33eb785aaca0` で指定する
- `LIDACTION` と `UNATTENDSLEEP` は任意の設定。蓋の無い機種や、存在しない設定は、失敗しても警告で続ける
- 必須の `STANDBYIDLE` と `HIBERNATEIDLE` は、失敗すると apply を止める
- ディスプレイの消灯（`monitor-timeout`）は設定しない
- **適用のあとに、設定した値を読み取って確かめる**: `powercfg /q` の出力の末尾の 2 つの `0x…`（AC・DC）を読む（表示の言語に依らない。範囲のある設定は `最小・最大・増分` が前に付くので、末尾 2 つだけを使う）。
  違う値が見つかれば警告する（グループポリシーなどが上書きしている可能性）が、`apply` は止めない。蓋・無人時のスリープのように、機種に無く読めない任意の設定は確かめない。
  実機で、実際の実行は警告なし、期待値を変えた複製では警告が出ることを確かめた
- **グループポリシー**で電源設定が固定されている機械では、`powercfg` の値が上書きされる（未確認）
- 実機の確認は [記録](../research/chezmoi/structure-windows-notes.md)

## Tailscale の Unattended

`300_windows/run_after_350_tailscale.ps1.tmpl`（`applejxd` のみ）が、**毎回の `chezmoi apply`** で
`tailscale set --unattended` を実行する（冪等）。ログオン前・サインアウト後も接続が維持される。
サービス自体は winget の導入（`309_admin`）で自動起動になる。

- **初回のブラウザ認証は自動化しない**（対話が要るため）。未ログイン（`BackendState` が `Running` 以外）のときは
  `tailscale up --unattended` を実行する旨を表示して 0 で終わる。認証キーは使わない
- 認証後の次の apply から `set --unattended` が効く。未ログインのうちに `set` だけが通るかは**未確認**（スクリプトは未ログイン時に呼ばない）
- Windows 実機での動作は**未検証**

## 7-Zip の関連付け

`300_windows/320_regkey/run_once_after_322_7zip.ps1` は、7-Zip を**既定アプリの一覧に選べる形で登録する**（`HKCU` のみ）。
Windows 11 は、スクリプトから既定のアプリを設定させない（`UserChoice` は保護されており、書き込めない）。そのため、

- `7-Zip.<ext>`（`7z` `zip` `rar` `lzh` `tar` `gz`）の ProgID に、ダブルクリックで解凍するコマンド（`7zG.exe x "%1" -o*`）とアイコンを置く
- `.<ext>\OpenWithProgids` に登録して「このアプリで開く」の候補に出す
- `RegisteredApplications` と `Capabilities` に「7-Zip (extract)」を登録して、設定 → アプリ → 既定のアプリに出す

までを自動化する。**ダブルクリックで解凍させるには、設定で一度だけ「7-Zip (extract)」を既定に選ぶ必要がある**（手動）。

- 経緯と実機の確認は [記録](../research/chezmoi/structure-windows-notes.md)

## 広告と推奨の抑止

Windows 11 の広告・推奨・おすすめ表示を止める。HKCU の値は `320_regkey/run_after_324_suggestions.ps1` が**毎回の apply**で当てる
（機能更新で戻されることがあるため。値が 0 のものは書かないので軽い）。

| 対象 | 設定（いずれも 0） |
| --- | --- |
| ロック画面・設定・スタートの提案、アプリの自動導入 | `ContentDeliveryManager` の `SubscribedContent-*Enabled`、`SystemPaneSuggestionsEnabled`、`SilentInstalledAppsEnabled`、`PreInstalledAppsEnabled` など 18 個 |
| スタートのおすすめ・アカウント通知、OneDrive の案内 | `Explorer\Advanced` の `Start_IrisRecommendations`、`Start_AccountNotifications`、`ShowSyncProviderNotifications` |
| 検索ボックスのハイライト | `SearchSettings\IsDynamicSearchBoxEnabled` |
| 「デバイスの設定を完了しましょう」 | `UserProfileEngagement\ScoobeSystemSettingEnabled` |
| 診断データに基づくおすすめ・広告 ID | `Privacy\TailoredExperiencesWithDiagnosticDataEnabled`、`AdvertisingInfo\Enabled` |
| 言語リストの公開（1 = 拒否） | `Control Panel\International\User Profile\HttpAcceptLanguageOptOut` |

- Windows が書き込みを拒む値は、警告して残りを続ける
- **タスクバーの天気（ウィジェット）は、レジストリを直接書いても止められない。自動化もしない（手動）。** 試した方法と結果は [記録](../research/chezmoi/structure-windows-notes.md)。
  - **ローカルグループポリシー経由なら書ける（実測）。** `gpsvc`（ポリシーを適用する SYSTEM のサービス）が書くため。
    `AllowNewsAndInterests` は Policy CSP の公式ポリシー（Pro・Windows 11 21H2 以降。値 0 でタスクバーを含むウィジェット全体を無効。
    [Policy CSP - NewsAndInterests](https://learn.microsoft.com/en-us/windows/client-management/mdm/policy-csp-newsandinterests)）
  - **自動化しない理由:** 309（昇格子）に外部の `.exe`（LGPO）の取得と実行を足す必要があり、保守（配布物のハッシュ）と攻撃面が増えるのに対し、効果は 1 設定の一度きりだから
  - **手動の手順（新しい機で 1 回）:** タスクバーを右クリック → タスクバーの設定 → ウィジェットをオフにする。
    または、管理者の PowerShell で LGPO（`winget install Microsoft.SecurityComplianceToolkit.LGPO`）を使う:
    `Set-Content widgets.txt -Encoding ASCII -Value 'Computer','SOFTWARE\Policies\Microsoft\Dsh','AllowNewsAndInterests','DWORD:0',''`、
    `LGPO /t widgets.txt`、`gpupdate /target:computer /force`（戻すときは `DWORD:0` を `DELETE` にして同じ手順）。**全アカウントに効く**
  - 自動化する設計（未実施）は [記録](../research/chezmoi/structure-windows-notes.md)
- 抑止しないもの: タスクビューボタン、タスクバーの検索ボックスの形、Copilot のボタン（好みで決める）

## シェルの既定値

`300_windows/320_regkey/run_once_after_323_shell_defaults.ps1` が、`HKCU` に次の 2 つを設定する（管理者権限は要らない）。

| 設定 | 値 | 理由 |
| --- | --- | --- |
| Windows PowerShell 5.1 の実行ポリシー（CurrentUser） | `RemoteSigned` | 5.1 の既定は `Restricted` で、配布するプロファイル（`.ps1`）が読み込まれない。PowerShell 7 の既定は `RemoteSigned` なので対象外 |
| 既定のターミナルアプリ（`HKCU\Console\%%Startup` の `DelegationConsole` / `DelegationTerminal`） | Windows Terminal | 「Windows に決定させる」でも通常は Windows Terminal になるが、明示して固定する |

- 実行ポリシーは、`Unrestricted` / `Bypass` / `RemoteSigned` が設定済みなら**下げない**（利用者が選んだ緩い設定を残す）
- **グループポリシー**（`...\Policies\Microsoft\Windows\PowerShell`）で固定されていれば、警告して何もしない
- `Set-ExecutionPolicy` は使わず、レジストリへ直接書く（モジュールの読み込みに依存しないため）
- 既定のターミナルは、Windows Terminal（`wt.exe`）がある機械だけ設定する
- 検証の記録は [記録](../research/chezmoi/structure-windows-notes.md)

## Windows Terminal

`settings.json`（Store 版の `%LOCALAPPDATA%\Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe\LocalState\`）は
GUI で設定を変えるたびに Windows Terminal が書き換えるため、ファイル全体は管理しません。
`home/AppData/Local/Packages/Microsoft.WindowsTerminal_8wekyb3d8bbwe/LocalState/modify_settings.json.py`（chezmoi の `modify_`）が、既存の内容に足すだけの変更をします。

- LANG2 キー（`vk(26)`）を何もしない操作に割り当てる（下記）
- 配色と外観を揃える（下記）

### LANG2 キーの割り当て

Google 日本語入力 + PowerShell（PSReadLine）で、LANG2（英数、`VK_IME_OFF` = 0x1A）を
押すと `@` が入力される不具合があります
（[PSReadLine#2206](https://github.com/PowerShell/PSReadLine/issues/2206)）。
Windows Terminal 側でこのキーを `adjustOpacity`（`opacity: 0`、`relative: true`）に
割り当て、PowerShell へ渡さないようにします。IME オフ自体はそのまま効きます。

- **新形式**（トップレベルに `keybindings` 配列がある）: `actions` に
  `id: User.ignoreImeOff` の操作、`keybindings` に `vk(26)` の割り当てを足します。
- **旧形式**: `actions` に `keys: vk(26)` を持つ操作を足します。
- 足すのは無いものだけなので、何度 apply しても結果は変わりません。
- `vk(26)` が別の操作（`id: null` の解除を含む）に割り当て済みなら、変更せず
  `warning: Windows Terminal: ...` を表示します。
- JSONC（コメント・末尾カンマ）のまま読み、配列の末尾へ文字列として挿入します。
  コメント・キーの順序・インデント・改行コード・BOM は変えません。
  JSON としてどうしても読めないときは、警告して元の内容をそのまま返します。
- 非 Store 版（`%LOCALAPPDATA%\Microsoft\Windows Terminal\settings.json`）は対象外です。

### 配色と外観

`profiles.defaults` の次のキーと、配色 `Iceberg` だけを揃えます。値は `modify_settings.json.py` の `APPEARANCE` と `SCHEME` が正本です。

| キー | 値 |
| --- | --- |
| `colorScheme` | `Iceberg` |
| `font.face` / `font.size` | `Cica` / 12 |
| `opacity` / `useAcrylic` | 100 / `true` |

- 無いキーは足し、値が違うキーだけ値を置き換えます。**ほかのキー（`font.weight` など）、コメント、書式は変えません**
- `schemes` に `Iceberg` があれば、上書きしません（利用者が編集した配色を残すため）
- 以前は `run_after_341_terminal.py.tmpl` が `json.load` で読み、`profiles.defaults` 全体を置き換えていました。コメント入りの `settings.json` では失敗し、
  GUI で付けた既定設定も消えるため、LANG2 の `modify_` に統合して 341 と `config/windows/terminal.json` を廃止しました
- LANG2 の割り当てを足せなかった（別の操作が割り当て済みなど）ときも、外観は揃えます
- `useAcrylic: true` と `opacity: 100` の組み合わせは透明効果が出ない。好みで決める（未決）

検証は `test/test_windows_terminal_settings.py` です。

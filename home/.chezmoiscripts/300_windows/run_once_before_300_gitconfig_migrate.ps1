Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# 旧構成の ~/.gitconfig (chezmoi が丸ごと管理していたもの) を退避する。
# 残すと XDG 側 (~/.config/git/config) より優先され、設定が二重になる。
# 無くなれば create_dot_gitconfig が空の ~/.gitconfig を作る。
# 目印の行が無いファイル (CLI が書いた設定) には触らない。
# see docs/spec/structure.md#gitconfig-の管理

$target = Join-Path $HOME '.gitconfig'
$marker = '# for overwriting by local config'

if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { return }
if (-not (Select-String -LiteralPath $target -Pattern $marker -SimpleMatch -Quiet)) { return }

$backup = "$target.chezmoi-old"
if (Test-Path -LiteralPath $backup) {
    $backup = "$backup." + (Get-Date -Format 'yyyyMMddHHmmss')
}
Move-Item -LiteralPath $target -Destination $backup
Write-Host "旧 ~/.gitconfig を退避しました: $backup"
Write-Host '  CLI で足した設定があれば、必要な分を新しい ~/.gitconfig へ移してください。'

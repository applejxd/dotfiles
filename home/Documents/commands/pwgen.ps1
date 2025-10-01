function pwgen {
    <#
    .SYNOPSIS
        Unix の pwgen コマンドを再現する PowerShell 関数

    .DESCRIPTION
        読みやすいランダムパスワードを生成します。

    .PARAMETER Length
        生成するパスワードの長さ（デフォルト: 8）

    .PARAMETER Count
        生成するパスワードの数（デフォルト: 160）

    .PARAMETER n
        数字を少なくとも1つ含める

    .PARAMETER numerals
        数字を少なくとも1つ含める（-n のエイリアス）

    .PARAMETER c
        大文字を少なくとも1つ含める

    .PARAMETER capitalize
        大文字を少なくとも1つ含める（-c のエイリアス）

    .PARAMETER A
        大文字を含めない

    .PARAMETER no_capitalize
        大文字を含めない（-A のエイリアス）

    .PARAMETER B
        紛らわしい文字を避ける（0, O, 1, l, I など）

    .PARAMETER ambiguous
        紛らわしい文字を避ける（-B のエイリアス）

    .PARAMETER s
        完全にランダムな文字列を生成（記号を含む）

    .PARAMETER secure
        完全にランダムな文字列を生成（-s のエイリアス）

    .PARAMETER y
        記号を少なくとも1つ含める

    .PARAMETER symbols
        記号を少なくとも1つ含める（-y のエイリアス）

    .PARAMETER v
        母音を含めない（発音不可能だが安全）

    .PARAMETER no_vowels
        母音を含めない（-v のエイリアス）

    .PARAMETER H
        SHA1ハッシュを使用してランダムパスワードを生成

    .PARAMETER sha1
        SHA1ハッシュを使用（-H のエイリアス）

    .PARAMETER HashPath
        SHA1ハッシュのソースファイル

    .PARAMETER C
        パスワードを列形式で出力

    .PARAMETER columns
        パスワードを列形式で出力（-C のエイリアス）

    .PARAMETER h
        ヘルプを表示

    .PARAMETER help
        ヘルプを表示（-h のエイリアス）

    .EXAMPLE
        pwgen
        8文字のパスワードを160個生成

    .EXAMPLE
        pwgen 16
        16文字のパスワードを160個生成

    .EXAMPLE
        pwgen 16 1
        16文字のパスワードを1個生成

    .EXAMPLE
        pwgen -s 20 1
        完全ランダムな20文字のパスワードを1個生成

    .EXAMPLE
        pwgen -n -c 12 5
        数字と大文字を含む12文字のパスワードを5個生成
    #>

    [CmdletBinding()]
    param(
        [Parameter(Position = 0)]
        [int]$Length = 16,

        [Parameter(Position = 1)]
        [int]$Count = 10,

        [Parameter()]
        [Alias('numerals')]
        [switch]$n,

        [Parameter()]
        [Alias('c')]
        [switch]$Capitalize,

        [Parameter()]
        [Alias('A')]
        [switch]$NoCapitalize,

        [Parameter()]
        [Alias('B')]
        [switch]$Ambiguous = $true,

        [Parameter()]
        [Alias('s')]
        [switch]$Secure,

        [Parameter()]
        [Alias('y')]
        [switch]$Symbols = $true,

        [Parameter()]
        [Alias('v')]
        [switch]$NoVowels,

        [Parameter()]
        [switch]$SHA1Hash,

        [Parameter()]
        [string]$HashPath,

        [Parameter()]
        [switch]$Columns,

        [Parameter()]
        [Alias('help')]
        [switch]$h
    )

    # ヘルプの表示
    if ($h) {
        Write-Host @"
Usage: pwgen [OPTIONS] [LENGTH] [COUNT]
Generate pronounceable passwords.

  -c, --capitalize        Include at least one capital letter
  -A, --no-capitalize     Don't include capital letters
  -n, --numerals          Include at least one number
  -0, --no-numerals       Don't include numbers
  -y, --symbols           Include at least one special symbol
  -s, --secure            Generate completely random passwords
  -B, --ambiguous         Avoid ambiguous characters (0, O, 1, l, I)
  -v, --no-vowels         Do not use vowels
  -H, --sha1=path/to/file Use sha1 hash of file
  -C, --columns           Print in columns
  -h, --help              Show this help

Default: pwgen 8 160
"@
        return
    }

    # 文字セットの定義
    $lowercase = 'abcdefghijklmnopqrstuvwxyz'
    $uppercase = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    $numbers = '0123456789'
    $symbolChars = '!@#$%^&*()-_=+[]{}|;:,.<>?'
    $vowels = 'aeiouAEIOU'
    $ambiguousChars = '0O1lI'

    # SHA1ハッシュベースの生成
    if ($SHA1Hash -or $HashPath) {
        if (-not $HashPath) {
            Write-Error "SHA1 hash requires a file path with -HashPath parameter"
            return
        }
        if (-not (Test-Path $HashPath)) {
            Write-Error "File not found: $HashPath"
            return
        }

        $sha1 = [System.Security.Cryptography.SHA1]::Create()
        $fileBytes = [System.IO.File]::ReadAllBytes($HashPath)
        $hashBytes = $sha1.ComputeHash($fileBytes)
        $hashHex = ($hashBytes | ForEach-Object { $_.ToString('x2') }) -join ''

        Write-Host $hashHex.Substring(0, [Math]::Min($Length, $hashHex.Length))
        return
    }

    # 完全ランダムモード
    if ($Secure) {
        $charset = $lowercase + $uppercase + $numbers + $symbolChars

        for ($i = 0; $i -lt $Count; $i++) {
            $password = -join (1..$Length | ForEach-Object {
                $charset[(Get-Random -Maximum $charset.Length)]
            })
            Write-Host $password
        }
        return
    }

    # 通常モード：文字セットの構築
    $charset = $lowercase

    # オプションに応じて文字セットを調整
    if (-not $NoCapitalize) {
        $charset += $uppercase
    }

    if ($n) {
        $charset += $numbers
    }

    if ($Symbols) {
        $charset += $symbolChars
    }

    # 母音を除外
    if ($NoVowels) {
        $charset = ($charset.ToCharArray() | Where-Object { $vowels -notcontains $_ }) -join ''
    }

    # 紛らわしい文字を除外
    if ($Ambiguous) {
        $charset = ($charset.ToCharArray() | Where-Object { $ambiguousChars -notcontains $_ }) -join ''
    }

    # パスワード生成
    $passwords = @()
    for ($i = 0; $i -lt $Count; $i++) {
        $password = ''
        $hasUpper = $false
        $hasNumber = $false
        $hasSymbol = $false

        # 要件を満たすまでループ
        $maxAttempts = 100
        $attempts = 0
        do {
            $password = -join (1..$Length | ForEach-Object {
                $charset[(Get-Random -Maximum $charset.Length)]
            })

            $hasUpper = (-not ($Capitalize -and -not $NoCapitalize)) -or ($password -cmatch '[A-Z]')
            $hasNumber = (-not $n) -or ($password -match '[0-9]')
            $hasSymbol = (-not $Symbols) -or ($password -match '[!@#$%^&*()\-_=+\[\]{}|;:,.<>?]')

            $attempts++
        } while ((-not $hasUpper -or -not $hasNumber -or -not $hasSymbol) -and $attempts -lt $maxAttempts)

        # 要件を満たせなかった場合は強制的に文字を挿入
        if (-not $hasUpper -and $Capitalize -and -not $NoCapitalize) {
            $pos = Get-Random -Maximum $password.Length
            $password = $password.Remove($pos, 1).Insert($pos, $uppercase[(Get-Random -Maximum $uppercase.Length)])
        }

        if (-not $hasNumber -and $n) {
            $pos = Get-Random -Maximum $password.Length
            $password = $password.Remove($pos, 1).Insert($pos, $numbers[(Get-Random -Maximum $numbers.Length)])
        }

        if (-not $hasSymbol -and $Symbols) {
            $pos = Get-Random -Maximum $password.Length
            $password = $password.Remove($pos, 1).Insert($pos, $symbolChars[(Get-Random -Maximum $symbolChars.Length)])
        }

        $passwords += $password
    }

    # 出力
    if ($Columns) {
        # 列形式で出力
        $termWidth = $Host.UI.RawUI.WindowSize.Width
        $colWidth = $Length + 2
        $numCols = [Math]::Floor($termWidth / $colWidth)
        if ($numCols -lt 1) { $numCols = 1 }

        for ($i = 0; $i -lt $passwords.Count; $i += $numCols) {
            $line = ''
            for ($j = 0; $j -lt $numCols -and ($i + $j) -lt $passwords.Count; $j++) {
                $line += $passwords[$i + $j].PadRight($colWidth)
            }
            Write-Host $line.TrimEnd()
        }
    } else {
        # 単純にリスト出力
        $passwords | ForEach-Object { Write-Host $_ }
    }
}

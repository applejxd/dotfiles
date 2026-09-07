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

    .PARAMETER sha1
        SHA1ハッシュのソースファイル（-HashPath のエイリアス）

    .PARAMETER HashPath
        SHA1ハッシュのソースファイル

    .PARAMETER columns
        パスワードを列形式で出力

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
        [switch]$NoNumerals,

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
        [Alias('sha1')]
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
      --no-numerals        Don't include numbers
  -y, --symbols           Include at least one special symbol
  -s, --secure            Generate completely random passwords
  -B, --ambiguous         Avoid ambiguous characters (0, O, 1, l, I)
  -v, --no-vowels         Do not use vowels
      --sha1 path/to/file  Use sha1 hash of file
      --columns            Print in columns
  -h, --help              Show this help

Default: pwgen 16 10
"@
        return
    }

    if ($Length -lt 1) {
        throw 'Length must be at least 1.'
    }
    if ($Count -lt 1) {
        throw 'Count must be at least 1.'
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
            throw 'SHA1 hash requires a file path with -HashPath parameter.'
        }
        if (-not (Test-Path $HashPath)) {
            throw "File not found: $HashPath"
        }

        $sha1 = [System.Security.Cryptography.SHA1]::Create()
        $fileBytes = [System.IO.File]::ReadAllBytes($HashPath)
        $hashBytes = $sha1.ComputeHash($fileBytes)
        $hashHex = ($hashBytes | ForEach-Object { $_.ToString('x2') }) -join ''

        Write-Output $hashHex.Substring(0, [Math]::Min($Length, $hashHex.Length))
        return
    }

    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    function Get-CryptoRandomIndex {
        param([Parameter(Mandatory)][int]$Maximum)

        $buffer = New-Object byte[] 4
        $range = [uint64][uint32]::MaxValue + 1
        $limit = $range - ($range % [uint64]$Maximum)
        do {
            $rng.GetBytes($buffer)
            $value = [uint64][BitConverter]::ToUInt32($buffer, 0)
        } while ($value -ge $limit)
        return [int]($value % [uint64]$Maximum)
    }

    function New-RandomPassword {
        param(
            [Parameter(Mandatory)][string]$CharacterSet,
            [string[]]$RequiredSets = @()
        )

        if ($RequiredSets.Count -gt $Length) {
            throw "Length $Length is too short for $($RequiredSets.Count) required character classes."
        }

        $characters = @()
        foreach ($requiredSet in $RequiredSets) {
            $characters += $requiredSet[(Get-CryptoRandomIndex $requiredSet.Length)]
        }
        while ($characters.Count -lt $Length) {
            $characters += $CharacterSet[(Get-CryptoRandomIndex $CharacterSet.Length)]
        }
        for ($i = $characters.Count - 1; $i -gt 0; $i--) {
            $swapIndex = Get-CryptoRandomIndex ($i + 1)
            $temporary = $characters[$i]
            $characters[$i] = $characters[$swapIndex]
            $characters[$swapIndex] = $temporary
        }
        return -join $characters
    }

    try {
        # 完全ランダムモード
        if ($Secure) {
            $charset = $lowercase
            $requiredSets = @()
            if (-not $NoCapitalize) {
                $charset += $uppercase
            }
            if ($Capitalize -and -not $NoCapitalize) {
                $requiredSets += $uppercase
            }
            if (-not $NoNumerals) {
                $charset += $numbers
            }
            if ($n -and -not $NoNumerals) {
                $requiredSets += $numbers
            }
            if ($Symbols) {
                $charset += $symbolChars
                $requiredSets += $symbolChars
            }
            if ($NoVowels) {
                $charset = ($charset.ToCharArray() | Where-Object {
                    -not $vowels.Contains([string]$_)
                }) -join ''
                $requiredSets = @(
                    $requiredSets | ForEach-Object {
                        ($_.ToCharArray() | Where-Object {
                            -not $vowels.Contains([string]$_)
                        }) -join ''
                    }
                )
            }
            if ($Ambiguous) {
                $charset = ($charset.ToCharArray() | Where-Object {
                    -not $ambiguousChars.Contains([string]$_)
                }) -join ''
                $requiredSets = @(
                    $requiredSets | ForEach-Object {
                        ($_.ToCharArray() | Where-Object {
                            -not $ambiguousChars.Contains([string]$_)
                        }) -join ''
                    }
                )
            }
            if (-not $charset -or $requiredSets -contains '') {
                throw 'The selected options produced an empty character set.'
            }
            for ($i = 0; $i -lt $Count; $i++) {
                Write-Output (
                    New-RandomPassword -CharacterSet $charset -RequiredSets $requiredSets
                )
            }
            return
        }

        # 通常モード：文字セットの構築
        $charset = $lowercase
        $requiredSets = @()

        # オプションに応じて文字セットを調整
        if (-not $NoCapitalize) {
            $charset += $uppercase
        }
        if ($Capitalize -and -not $NoCapitalize) {
            $requiredSets += $uppercase
        }

        if ($n -and -not $NoNumerals) {
            $charset += $numbers
            $requiredSets += $numbers
        }

        if ($Symbols) {
            $charset += $symbolChars
            $requiredSets += $symbolChars
        }

        # 母音を除外
        if ($NoVowels) {
            $charset = ($charset.ToCharArray() | Where-Object { -not $vowels.Contains([string]$_) }) -join ''
            $requiredSets = @(
                $requiredSets | ForEach-Object {
                    ($_.ToCharArray() | Where-Object { -not $vowels.Contains([string]$_) }) -join ''
                }
            )
        }

        # 紛らわしい文字を除外
        if ($Ambiguous) {
            $charset = ($charset.ToCharArray() | Where-Object { -not $ambiguousChars.Contains([string]$_) }) -join ''
            $requiredSets = @(
                $requiredSets | ForEach-Object {
                    ($_.ToCharArray() | Where-Object { -not $ambiguousChars.Contains([string]$_) }) -join ''
                }
            )
        }

        if (-not $charset -or $requiredSets -contains '') {
            throw 'The selected options produced an empty character set.'
        }

        # パスワード生成
        $passwords = @()
        for ($i = 0; $i -lt $Count; $i++) {
            $passwords += New-RandomPassword -CharacterSet $charset -RequiredSets $requiredSets
        }

        # 出力
        if ($Columns) {
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
            Write-Output $passwords
        }
    }
    finally {
        $rng.Dispose()
    }
}

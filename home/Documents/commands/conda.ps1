function condals { conda env list }

function condarun {
  $selectedLine = conda env list | Select-Object -Skip 2 | fzf
  if (-not [string]::IsNullOrWhiteSpace($selectedLine)) {
    $envName = ($selectedLine -split '\s+')[0]
    conda activate $envName
  }
}

function condarm {
  $selectedLine = conda env list | Select-Object -Skip 2 | fzf
  if (-not [string]::IsNullOrWhiteSpace($selectedLine)) {
    $envName = ($selectedLine -split '\s+')[0]
    conda env remove -n $envName
  }
}

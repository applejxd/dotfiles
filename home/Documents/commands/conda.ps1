function condals { conda env list }

function condarun {
  $env_name = (conda env list | Select-Object -Skip 2 | Select-Object -SkipLast 1 | fzf).Split(" ")[0]
  if (![string]::IsNullOrEmpty($env_name)) {
    conda activate "$env_name"
  }
}

function condarm {
  $env_name = (conda env list | Select-Object -Skip 2 | Select-Object -SkipLast 1 | fzf).Split(" ")[0]
  if (![string]::IsNullOrEmpty($env_name)) {
    conda env remove -n "$env_name"
  }
}
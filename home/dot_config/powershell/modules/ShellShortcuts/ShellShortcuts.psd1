@{
  RootModule = 'ShellShortcuts.psm1'
  ModuleVersion = '1.0.0'
  GUID = '088600e6-172b-40cc-844a-994bbc1e3af2'
  Description = 'bash/zsh の shellrc.sh の alias と小さい関数に相当する (対話シェル用。使うときに自動で読み込まれる)'
  PowerShellVersion = '5.1'
  FunctionsToExport = @('up', 'upp', 'uppp', 'jcd', 'cleanup', 'll', 'la', 'lla', 'lal', 'lt', 'ltl', 'Invoke-ShellCat', 'y', 'wcc', 'fcr', 'search', 'sha1', 'v', 'shellf', 'mise-select')
  CmdletsToExport = @()
  VariablesToExport = @()
  AliasesToExport = @()
}

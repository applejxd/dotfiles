@{
  RootModule = 'ShellGit.psm1'
  ModuleVersion = '1.0.0'
  GUID = 'c8aa91e2-3f83-418b-9062-52831e9528e5'
  Description = 'fzf と git を組み合わせた関数 (bash/zsh の fzf/git.sh に相当する)'
  PowerShellVersion = '5.1'
  FunctionsToExport = @('fbr', 'fbrm', 'fshow', 'cdworktree', 'fadd', 'xgw', 'gwcode')
  CmdletsToExport = @()
  VariablesToExport = @()
  AliasesToExport = @()
}

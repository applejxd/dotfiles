@{
  RootModule = 'ShellArchive.psm1'
  ModuleVersion = '1.0.0'
  GUID = '11f18700-05f2-4c67-a978-142b2a19b027'
  Description = '圧縮・展開の関数 (bash/zsh の functions/archive.sh に相当する)'
  PowerShellVersion = '5.1'
  FunctionsToExport = @('extract', 'zpack', 'zunpack')
  CmdletsToExport = @()
  VariablesToExport = @()
  AliasesToExport = @()
}

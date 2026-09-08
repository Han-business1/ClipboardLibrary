$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python .\tools\generate_icon.py
python -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name ClipboardLibrary `
  --workpath .\build-v150 `
  --distpath .\dist-v150 `
  --icon .\clipboard_library.ico `
  --version-file .\version_info.txt `
  .\clipboard_library.py
if ($LASTEXITCODE -ne 0) { throw "应用程序打包失败，退出码：$LASTEXITCODE" }

$isccCandidates = @(
  "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
  "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe",
  "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "未找到 Inno Setup 6 (ISCC.exe)。" }
& $iscc .\installer.iss
if ($LASTEXITCODE -ne 0) { throw "安装程序编译失败，退出码：$LASTEXITCODE" }

Write-Host "`n构建完成：$PSScriptRoot\release\剪贴板库-安装程序-v1.5.0.exe"

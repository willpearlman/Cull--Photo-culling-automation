# Build the Windows app folder (dist\Cull) and, if Inno Setup is installed, the installer
# (dist\CullSetup.exe). Run from the repo:  powershell -File packaging\build.ps1
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
Set-Location $repo

$py = Join-Path $repo '.venv\Scripts\python.exe'
& $py -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\cull.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# The exe looks for exiftool\exiftool.exe; the Windows build ships it as ExifTool.exe.
$tool = Join-Path $repo 'dist\Cull\_internal\exiftool'
if (Test-Path "$tool\ExifTool.exe") { Rename-Item "$tool\ExifTool.exe" 'exiftool.exe' -Force }
if (Test-Path "$repo\dist\Cull\_internal\.env") { throw ".env must never be bundled" }

$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
    & $iscc packaging\installer.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
} else {
    Write-Host "Inno Setup not found: built dist\Cull only (no installer)."
}

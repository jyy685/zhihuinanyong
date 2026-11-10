param([string]$OutputDirectory = 'dist')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m PyInstaller --noconfirm --clean --onefile --windowed --name ZhihuiNanyong --add-data "$PSScriptRoot/docs/COOKIE_GUIDE.md;docs" --add-data "$PSScriptRoot/docs/images;docs/images" --version-file "$PSScriptRoot/packaging/version_info.txt" --distpath $OutputDirectory --workpath build --specpath packaging "$PSScriptRoot/app.py"
if ($LASTEXITCODE -ne 0) { throw 'EXE build failed.' }
Write-Host "Created: $OutputDirectory/ZhihuiNanyong.exe"

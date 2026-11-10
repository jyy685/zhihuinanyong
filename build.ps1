$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m PyInstaller --noconfirm --clean --onefile --windowed --name ZhihuiNanyong --add-data "$PSScriptRoot/docs/COOKIE_GUIDE.md;docs" --version-file "$PSScriptRoot/packaging/version_info.txt" --distpath dist --workpath build --specpath packaging "$PSScriptRoot/app.py"
if ($LASTEXITCODE -ne 0) { throw 'EXE build failed.' }
Write-Host 'Created: dist/ZhihuiNanyong.exe'

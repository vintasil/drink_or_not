$content = @'
@echo off
REM 在 Windows 上打成 dist\drink_or_not.exe。
REM
REM     build\build_windows.bat
REM
REM 需要先装好 uv(https://docs.astral.sh/uv/)。

setlocal
cd /d "%~dp0.."

echo ==^> 同步依赖
uv sync || exit /b 1

echo ==^> 生成素材(已存在则跳过)
if not exist assets\manifest.json uv run python script\prepare_assets.py || exit /b 1
if not exist assets\frames\idle_00.png uv run python script\generate_frames.py || exit /b 1

echo ==^> PyInstaller 打包
uv run --with pyinstaller pyinstaller "%CD%\build\drink_or_not.spec" --noconfirm --clean --workpath "%CD%\build\.work" --distpath "%CD%\dist" || exit /b 1

echo.
echo 产物: %CD%\dist\drink_or_not.exe
echo 自测: %CD%\dist\drink_or_not.exe --debug-idle
endlocal
'@

$path = Join-Path (Get-Location) "build\build_windows.bat"
[System.IO.File]::WriteAllText($path, $content, [System.Text.Encoding]::GetEncoding("GBK"))
Write-Host "已写入 $path"
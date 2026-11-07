@echo off
setlocal
cd /d "%~dp0\.."

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 Python，无法构建 exe。
  pause
  exit /b 1
)

echo 安装/更新 PyInstaller ...
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
  echo [错误] PyInstaller 安装失败。
  pause
  exit /b 1
)

echo 构建 exe ...
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build labpbr2bedrock.spec
if errorlevel 1 (
  echo [错误] 构建失败。
  pause
  exit /b 1
)

echo.
echo 完成：dist\labpbr2bedrock.exe
pause

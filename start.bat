@echo off
setlocal
cd /d "%~dp0"

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
  where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  echo [错误] 未找到 Python 3.10 或更高版本。
  echo 请先从 https://www.python.org/downloads/ 安装，勾选 Add Python to PATH。
  echo.
  pause
  exit /b 1
)

echo 正在运行 labpbr2bedrock ...
echo 首次运行会自动创建 config.json、input\、output\。
echo.
%PY% run.py %*
set "CODE=%ERRORLEVEL%"

echo.
if "%CODE%"=="0" (
  echo 完成。产物在 output\ 文件夹。
) else (
  echo 运行结束，退出码 %CODE%。
)
echo.
pause
exit /b %CODE%

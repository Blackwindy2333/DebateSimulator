@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1

echo [1/3] 准备虚拟环境...
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv || goto :err
)

echo [2/3] 安装依赖...
call ".venv\Scripts\activate.bat"
python -m pip install -q --disable-pip-version-check -r requirements.txt || goto :err

echo [3/3] 启动服务...
python -m app
goto :eof

:err
echo.
echo 启动失败，请检查上方错误信息。
pause

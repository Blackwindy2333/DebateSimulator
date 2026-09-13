@echo off
setlocal
cd /d "%~dp0"
title DebateSimulator
chcp 65001 >nul
set PYTHONUTF8=1

echo ==========================================
echo    AI 辩论模拟器  DebateSimulator
echo ==========================================
echo.

set "VENV_DIR=%~dp0.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

if exist "%VENV_PY%" goto :deps

echo [1/3] 创建虚拟环境 .venv

set "PY_BOOT="
where python >nul 2>nul
if errorlevel 1 goto :try_py
set "PY_BOOT=python"
goto :got_py

:try_py
where py >nul 2>nul
if errorlevel 1 goto :no_py
set "PY_BOOT=py"

:got_py
echo        使用 %PY_BOOT%
"%PY_BOOT%" -m venv "%VENV_DIR%"
if errorlevel 1 goto :venv_fail
if not exist "%VENV_PY%" goto :venv_fail
goto :deps

:deps
echo [2/3] 检查并安装依赖
"%VENV_PY%" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :pip_fail

echo [3/3] 启动服务
echo        浏览器会在一两秒后自动打开；在此窗口按 Ctrl+C 可停止服务。
echo.
"%VENV_PY%" -u -m app
echo.
echo 服务已停止。
goto :end

:no_py
echo.
echo [错误] 未找到 Python。
echo        请安装 Python 3.10 或更高版本，安装时务必勾选 "Add Python to PATH"。
echo        下载地址：https://www.python.org/downloads/
goto :end

:venv_fail
echo.
echo [错误] 创建虚拟环境失败。
echo        请确认磁盘可写，且 Python 安装完整。
goto :end

:pip_fail
echo.
echo [错误] 依赖安装失败。
echo        请检查网络连接后重新运行本脚本。
goto :end

:end
echo.
echo 按任意键关闭此窗口...
pause >nul

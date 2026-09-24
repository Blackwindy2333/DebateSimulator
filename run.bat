@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title DebateSimulator
rem 批处理文件使用系统 ANSI (GBK) 编码保存，中文 Windows 下 cmd 才能正确解析
chcp 936 >nul 2>nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo ==========================================
echo    AI 辩论模拟器  DebateSimulator
echo ==========================================
echo.

set "VENV_DIR=%~dp0.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

rem 端口：从 config/config.json 的 runtime.port 读取；读不到或非数字则退回 8000
set "PORT=8000"
if not exist "config\config.json" goto :port_ready
set "PORT_CAND="
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "try{$j=ConvertFrom-Json -InputObject ([IO.File]::ReadAllText('config\config.json'));$j.runtime.port}catch{}"`) do set "PORT_CAND=%%a"
echo %PORT_CAND%|findstr /r "^[0-9][0-9]*$" >nul && set "PORT=%PORT_CAND%"

:port_ready
echo [1/4] 检查端口 %PORT% 是否已被占用
set "OLD_PIDS="
rem 用 PowerShell 取监听进程，避免 netstat 文本分列在中文系统上不稳定
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | Sort-Object -Unique"`) do (
    set "OLD_PIDS=!OLD_PIDS! %%p"
)

if not defined OLD_PIDS (
    echo        端口空闲，继续。
    goto :setup
)

for %%p in (!OLD_PIDS!) do (
    set "PNAME="
    for /f "usebackq tokens=1" %%n in (`tasklist /FI "PID eq %%p" /FO CSV /NH 2^>nul`) do set "PNAME=%%~n"
    echo        端口 %PORT% 已被进程 %%p [!PNAME!] 占用，正在关闭...
    taskkill /F /PID %%p >nul 2>nul
    if errorlevel 1 (
        echo        [警告] 结束进程 %%p 失败，可能需要管理员权限。
    ) else (
        echo        已关闭进程 %%p。
    )
)
rem 等端口真正释放（timeout 在输入被重定向时会报错，故用 ping 代替）
ping -n 2 127.0.0.1 >nul

set "STILL="
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess"`) do set "STILL=%%p"
if defined STILL (
    echo.
    echo [错误] 端口 %PORT% 仍被进程 !STILL! 占用。
    echo        请手动关闭后再运行本脚本，或在 config/config.json 中修改 runtime.port。
    goto :end
)
echo        端口已释放，继续。

:setup
if exist "%VENV_PY%" goto :deps

echo [2/4] 创建虚拟环境 .venv

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

:deps
echo [3/4] 检查并安装依赖
"%VENV_PY%" -m pip --version >nul 2>nul
if errorlevel 1 (
    echo        检测到虚拟环境缺少 pip，正在修复...
    "%VENV_PY%" -m ensurepip --upgrade >nul 2>nul
    "%VENV_PY%" -m pip --version >nul 2>nul
    if errorlevel 1 (
        echo        ensurepip 无法修复，重建虚拟环境...
        rmdir /s /q "%VENV_DIR%" >nul 2>nul
        goto :setup
    )
)
"%VENV_PY%" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :pip_fail

echo [4/4] 启动服务
echo        浏览器会在一两秒后自动打开；在此窗口按 Ctrl+C 可停止服务。
echo.
"%VENV_PY%" -u -m app
echo.
echo 服务已停止。
goto :end

:no_py
echo.
echo [错误] 未找到 Python。
echo        请安装 Python 3.10 或更高版本，安装时务必勾选 Add Python to PATH。
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

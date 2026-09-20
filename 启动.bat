@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_EXE="
set "PYTHON_ARGS="
if exist "C:\Program Files\Python312\python.exe" set "PYTHON_EXE=C:\Program Files\Python312\python.exe"
if defined PYTHON_EXE goto :python_ready
where py >nul 2>nul
if errorlevel 1 goto :try_python
set "PYTHON_EXE=py"
set "PYTHON_ARGS=-3.12"
goto :python_ready

:try_python
where python >nul 2>nul
if errorlevel 1 goto :python_missing
set "PYTHON_EXE=python"
goto :python_ready

:python_missing
echo [通话评测实验室] 未找到 Python 3.12。请先安装 Python，再运行 pip install -r requirements.txt
pause
exit /b 1

:python_ready

netstat -ano | findstr ":8090" | findstr "LISTENING" >nul
if errorlevel 1 (
  echo [通话评测实验室] 正在启动本地服务，首次加载依赖可能需要几十秒...
  start "" /min "%PYTHON_EXE%" %PYTHON_ARGS% server\main.py
)

powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(120); do { try { $r=Invoke-RestMethod -Uri 'http://127.0.0.1:8090/api/health' -TimeoutSec 1; if($r.status -eq 'ok') { exit 0 } } catch {}; Start-Sleep -Seconds 1 } while((Get-Date) -lt $deadline); exit 1" >nul 2>nul
if not errorlevel 1 goto :ready

echo [通话评测实验室] 120 秒内未通过健康检查。请在终端运行 "%PYTHON_EXE%" %PYTHON_ARGS% server\main.py 查看错误。
pause
exit /b 1

:ready
echo [通话评测实验室] 服务已就绪，正在打开工作台...
start "" "http://127.0.0.1:8090"

@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 如果 8090 端口已经在监听，说明服务已起，直接开浏览器
netstat -ano | findstr ":8090" | findstr "LISTENING" >nul
if errorlevel 1 (
  echo 正在启动 Signal Desk 服务...
  start "" /min "C:\Program Files\Python312\python.exe" server\main.py
  timeout /t 3 /nobreak >nul
)

start "" "http://127.0.0.1:8090"

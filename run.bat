@echo off
setlocal
cd /d "%~dp0"
set NO_PROXY=localhost,127.0.0.1
set no_proxy=localhost,127.0.0.1
python app.py
pause

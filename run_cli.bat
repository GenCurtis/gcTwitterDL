@echo off
chcp 65001 >nul
cd /d "%~dp0"
python sync_down.py menu
echo.
pause

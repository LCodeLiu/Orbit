@echo off
rem Orbit - 调试启动脚本（保留控制台输出）
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
python run.py
if errorlevel 1 (
    echo.
    echo [Orbit] 启动失败。请先运行 install.bat，或执行：
    echo     python run.py --diagnose
    pause
)

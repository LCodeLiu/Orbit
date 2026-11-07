@echo off
rem Orbit - 依赖安装脚本
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Orbit - 安装依赖
echo ============================================================
echo.

python --version
if errorlevel 1 (
    echo [错误] 未找到 python。请确认 Python 3.10+ 已加入 PATH。
    pause
    exit /b 1
)

echo.
echo [检测] 正在检查 Python 版本和依赖包...
python -c "import sys; sys.exit(0 if sys.version_info>=(3,10) and __import__('PySide6') and __import__('pyaudiowpatch') and __import__('soundfile') and __import__('mutagen') and __import__('numpy') else 1)"
if errorlevel 1 (
    echo [检测] 当前环境不满足要求或依赖缺失，开始安装...
    echo.
    echo 正在安装 PySide6 / PyAudioWPatch / numpy / soundfile / mutagen ...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [错误] 依赖安装失败。请检查网络或 pip 配置。
        pause
        exit /b 1
    )
    echo [完成] 依赖安装完成。
) else (
    echo [检测] 当前环境已满足要求，跳过依赖安装。
    echo [提示] 如需确保依赖版本符合 requirements.txt，可手动运行：
    echo        python -m pip install -r requirements.txt
)

echo.
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [提示] 未找到 FFmpeg。WAV / FLAC 可不依赖 FFmpeg；
    echo        ALAC / MP3 / AAC / OGG 需要 FFmpeg 在 PATH 中，
    echo        或在 设置 -^> 系统集成 中指定 ffmpeg.exe。
) else (
    ffmpeg -version | findstr /b "ffmpeg version"
)

echo.
echo 环境准备完成。双击 start.bat（控制台），
echo 或双击 run.py（控制台）/run.pyw（无控制台） 启动 Orbit。
pause
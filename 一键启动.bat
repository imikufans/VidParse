@echo off
chcp 65001 >nul
title VidParse - 运行中(关闭此窗口即停止服务)
cd /d "%~dp0"

echo ============================================================
echo   VidParse 多平台视频解析工具
echo   正在启动服务，浏览器将自动打开...
echo   关闭此窗口即可停止服务
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3 并加入 PATH
    pause
    exit /b 1
)

if not exist "webui.py" (
    echo [错误] 未找到 webui.py，请确认本文件夹内容完整。
    pause
    exit /b 1
)

python webui.py --port 8080
if errorlevel 1 (
    echo.
    echo [提示] 服务异常退出。若端口被占用，可编辑本文件更换端口。
    pause
)

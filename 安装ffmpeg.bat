@echo off
chcp 65001 >nul
title 安装 ffmpeg（音视频合成依赖）
cd /d "%~dp0"

echo ============================================================
echo   ffmpeg 安装助手
echo   （用于 B站/YouTube 高清音视频合成，工具已内置则无需运行）
echo ============================================================
echo.

if exist "bin\ffmpeg.exe" (
  echo [√] 检测到已安装 ffmpeg，无需重复安装。
  echo.
  pause
  exit /b 0
)

if not exist "bin" mkdir bin

echo [1/3] 正在下载 ffmpeg（约 19MB，请稍候）...
powershell -NoProfile -Command ^
  "$ErrorActionPreference='Stop'; try { ^
    $url='https://files.pythonhosted.org/packages/9b/4f/737258e8efa9264bcd7eb9615b0be6a58e4ad1d15c259982dbe53b071ce4/imageio_ffmpeg-0.8.1-py3-none-win32.whl'; ^
    Invoke-WebRequest -Uri $url -OutFile '_ffmpeg_setup.whl' -TimeoutSec 600; ^
    Write-Host '  下载完成' ^
  } catch { Write-Host ('  下载失败: '+$_.Exception.Message); exit 1 }"
if errorlevel 1 goto :fail

echo [2/3] 正在解压 ffmpeg.exe ...
powershell -NoProfile -Command ^
  "$ErrorActionPreference='Stop'; try { ^
    Add-Type -AssemblyName System.IO.Compression.FileSystem; ^
    $zip=[System.IO.Compression.ZipFile]::OpenRead((Resolve-Path '_ffmpeg_setup.whl')); ^
    $entry=$zip.Entries | Where-Object { $_.Name -like 'ffmpeg*.exe' } | Select-Object -First 1; ^
    if(-not $entry){ throw 'wheel 中未找到 ffmpeg.exe' }; ^
    [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path (Get-Location) 'bin\ffmpeg.exe'), $true); ^
    $zip.Dispose(); Write-Host ('  已解压: '+$entry.FullName) ^
  } catch { Write-Host ('  解压失败: '+$_.Exception.Message); exit 1 }"
if errorlevel 1 goto :fail

del /q "_ffmpeg_setup.whl" >nul 2>&1

echo [3/3] 验证安装...
if exist "bin\ffmpeg.exe" (
  "bin\ffmpeg.exe" -version >nul 2>&1
  if not errorlevel 1 (
    echo.
    echo [√] ffmpeg 安装成功！现在可以使用「音视频合成」功能了。
  ) else (
    echo [!] ffmpeg.exe 已下载但无法运行，可能是系统兼容性问题。
  )
) else (
  goto :fail
)

echo.
pause
exit /b 0

:fail
echo.
echo [×] 自动安装失败。请手动下载 ffmpeg.exe 放到 bin\ 目录：
echo     https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
echo     解压后把 bin\ffmpeg.exe 复制到本工具的 bin\ 文件夹即可。
echo.
pause
exit /b 1

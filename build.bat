@echo off
setlocal

REM ============================================================
REM  托盘监控 - 构建脚本
REM  用法: build.bat          构建当前版本
REM        build.bat --open   构建后打开输出目录
REM ============================================================

cd /d "%~dp0"

REM 读取版本号
for /f "tokens=2 delims== " %%a in ('findstr /C:"__version__" src\tray_monitor.py') do (
    set VERSION=%%~a
)
set VERSION=%VERSION:"=%
set VERSION=%VERSION:'=%

if "%VERSION%"=="" (
    echo [ERROR] 无法从 src\tray_monitor.py 读取版本号
    exit /b 1
)

echo.
echo ============================================================
echo   构建托盘监控 v%VERSION%
echo ============================================================
echo.

REM 清理旧构建
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM 创建发布目录
set RELEASE_DIR=release\v%VERSION%
if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"

REM PyInstaller 打包
echo [1/2] PyInstaller 打包中...
pyinstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name tray_monitor ^
    --icon icons\lobster.ico ^
    --add-data "icons;icons" ^
    src\tray_monitor.py

if errorlevel 1 (
    echo [ERROR] PyInstaller 打包失败
    exit /b 1
)

REM 复制到发布目录
echo [2/2] 复制到 %RELEASE_DIR%...
copy /y dist\tray_monitor.exe "%RELEASE_DIR%\tray_monitor.exe" >nul

REM 复制配置文件和文档
if exist config.json (
    copy /y config.json "%RELEASE_DIR%\config.json" >nul
) else (
    if exist config.example.json copy /y config.example.json "%RELEASE_DIR%\config.example.json" >nul
)
copy /y CHANGELOG.md "%RELEASE_DIR%\CHANGELOG.md" >nul
copy /y README.md "%RELEASE_DIR%\README.md" >nul
if exist start.vbs copy /y start.vbs "%RELEASE_DIR%\start.vbs" >nul
if exist start.bat copy /y start.bat "%RELEASE_DIR%\start.bat" >nul

REM 清理构建临时文件
rmdir /s /q build
rmdir /s /q dist

echo.
echo ============================================================
echo   构建完成!
echo   输出: %RELEASE_DIR%\tray_monitor.exe
echo   版本: v%VERSION%
echo ============================================================
echo.

REM 可选：打开输出目录
if "%1"=="--open" explorer "%RELEASE_DIR%"

endlocal

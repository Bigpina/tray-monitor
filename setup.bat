@echo off
echo ========================================
echo   托盘监控程序 - 安装依赖
echo ========================================
echo.
python -m pip install -r "%~dp0requirements.txt"
echo.
echo ========================================
echo   安装完成！
echo   双击 start.vbs 启动（无窗口）
echo   双击 start.bat 启动（调试模式）
echo ========================================
pause

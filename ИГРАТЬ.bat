@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Крутагидон Online

where py >nul 2>&1
if %errorlevel%==0 (
    py launcher.py
    goto :end
)
where python >nul 2>&1
if %errorlevel%==0 (
    python launcher.py
    goto :end
)

echo.
echo   Python не найден.
echo.
echo   1. Открой https://www.python.org/downloads/
echo   2. Скачай и запусти установщик
echo   3. ОБЯЗАТЕЛЬНО поставь галочку "Add Python to PATH"
echo   4. После установки запусти этот файл снова
echo.
start https://www.python.org/downloads/

:end
echo.
pause

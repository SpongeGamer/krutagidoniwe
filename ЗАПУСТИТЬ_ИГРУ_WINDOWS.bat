@echo off
cd /d "%~dp0"
echo Установка зависимостей (нужна только при первом запуске)...
py -m pip install -r requirements.txt
if errorlevel 1 pause & exit /b 1
echo.
echo Крутагидон запущен: http://localhost:8000
start http://localhost:8000
py -m uvicorn backend.server:app --host 0.0.0.0 --port 8000
pause

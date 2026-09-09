@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Крутагидон Online
setlocal enabledelayedexpansion

rem ==================================================================
rem  Ищем рабочий Python. Заглушку из Microsoft Store (она просто
rem  открывает Магазин вместо запуска) отсекаем проверкой на версию.
rem ==================================================================
set "PYEXE="

py -3 -c "import sys" >nul 2>&1
if !errorlevel! equ 0 set "PYEXE=py -3"

if not defined PYEXE (
    python -c "import sys" >nul 2>&1
    if !errorlevel! equ 0 set "PYEXE=python"
)
if not defined PYEXE (
    python3 -c "import sys" >nul 2>&1
    if !errorlevel! equ 0 set "PYEXE=python3"
)

rem Python мог встать без прописи в PATH — проверяем обычные места.
if not defined PYEXE (
    for %%P in (
        "%LocalAppData%\Programs\Python\Python313\python.exe"
        "%LocalAppData%\Programs\Python\Python312\python.exe"
        "%LocalAppData%\Programs\Python\Python311\python.exe"
        "%ProgramFiles%\Python313\python.exe"
        "%ProgramFiles%\Python312\python.exe"
        "%ProgramFiles%\Python311\python.exe"
    ) do (
        if not defined PYEXE if exist %%P set "PYEXE=%%P"
    )
)

if defined PYEXE goto :run

rem ==================================================================
rem  Python не нашёлся — ставим сами, без походов на сайт.
rem ==================================================================
echo.
echo   Python не найден. Сейчас установлю его сам — это разовое дело.
echo   Займёт пару минут, ничего нажимать не надо.
echo.

rem Способ 1: штатный менеджер пакетов Windows 10/11.
where winget >nul 2>&1
if %errorlevel%==0 (
    echo   [1/2] Ставлю Python через магазин приложений Windows...
    winget install --id Python.Python.3.12 -e --source winget ^
        --accept-package-agreements --accept-source-agreements --silent
    call :findpython
    if defined PYEXE goto :installed
)

rem Способ 2: качаем официальный установщик и ставим тихо.
echo   [2/2] Скачиваю установщик с python.org...
set "PYSETUP=%TEMP%\python-krutagidon.exe"
set "PYURL=https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try{[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;Invoke-WebRequest -Uri '%PYURL%' -OutFile '%PYSETUP%' -UseBasicParsing;exit 0}catch{exit 1}"

if not exist "%PYSETUP%" goto :manual

echo   Устанавливаю (окна может не быть — это нормально)...
"%PYSETUP%" /passive InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0
del /q "%PYSETUP%" >nul 2>&1

call :findpython
if defined PYEXE goto :installed

:manual
echo.
echo   Автоматически не вышло — видимо, антивирус или нет интернета.
echo.
echo   Поставь вручную:
echo   1. Открой https://www.python.org/downloads/
echo   2. Скачай и запусти установщик
echo   3. ОБЯЗАТЕЛЬНО поставь галочку "Add Python to PATH"
echo   4. Запусти этот файл снова
echo.
start https://www.python.org/downloads/
goto :end

:installed
echo.
echo   Python установлен. Запускаю игру...
echo.

:run
echo   Готовлю игру, первый запуск занимает полминуты...
echo.
%PYEXE% launcher.py
goto :end

rem ------------------------------------------------------------------
:findpython
set "PYEXE="
py -3 -c "import sys" >nul 2>&1
if !errorlevel! equ 0 set "PYEXE=py -3"
if not defined PYEXE (
    python -c "import sys" >nul 2>&1
    if !errorlevel! equ 0 set "PYEXE=python"
)
rem Свежая установка ещё не в PATH текущего окна — смотрим по путям.
if not defined PYEXE (
    for %%P in (
        "%LocalAppData%\Programs\Python\Python313\python.exe"
        "%LocalAppData%\Programs\Python\Python312\python.exe"
        "%LocalAppData%\Programs\Python\Python311\python.exe"
        "%ProgramFiles%\Python313\python.exe"
        "%ProgramFiles%\Python312\python.exe"
        "%ProgramFiles%\Python311\python.exe"
    ) do (
        if not defined PYEXE if exist %%P set "PYEXE=%%P"
    )
)
exit /b

:end
echo.
echo   Окно можно закрыть.
pause

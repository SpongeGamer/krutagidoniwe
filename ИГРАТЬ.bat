@echo off
rem  Fail namerenno bez kirillicy: cmd.exe lomaet russkij tekst v .bat.
rem  Ves tekst dlya igroka pechatayut launcher.py i ustanovka.ps1.
cd /d "%~dp0"
title Krutagidon Online
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

call :zapusk
if defined PYEXE goto :eof

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ustanovka.ps1"
if errorlevel 1 (
    pause
    goto :eof
)

call :zapusk
if defined PYEXE goto :eof

echo.
echo Python ustanovlen, no ne najden. Perezapusti etot fail.
pause
goto :eof

rem  Probnyj zapusk otsekaet zaglushku Microsoft Store:
rem  ona est v PATH, no vypolnyat kod ne umeet.
:zapusk
set "PYEXE="
for %%C in ("py -3" "python" "python3") do (
    if not defined PYEXE (
        %%~C -c "" >nul 2>&1 && set "PYEXE=%%~C"
    )
)
if defined PYEXE %PYEXE% launcher.py
exit /b

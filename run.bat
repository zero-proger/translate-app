@echo off
rem Windows launch script. Works from any directory.
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
) else (
    echo [INFO] .venv не найден, запускаю системный Python
    python main.py
)

if errorlevel 1 (
    echo.
    echo [ERROR] Приложение завершилось с ошибкой.
    echo Запустите: python bootstrap.py
    pause
)
endlocal

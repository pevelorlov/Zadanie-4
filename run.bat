@echo off
set "PROJECT_DIR=%~dp0"

if not exist "%PROJECT_DIR%.venv\Scripts\python.exe" (
    echo Не найдено виртуальное окружение .venv.
    echo Сначала выполните: python -m venv .venv
    pause
    exit /b 1
)

"%PROJECT_DIR%.venv\Scripts\python.exe" "%PROJECT_DIR%main.py"
pause

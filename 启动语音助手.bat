@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
rem Use a short-path venv: SAPI/System.Speech fails with very long interpreter paths.
set "PY=C:\va-venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%~dp0.venv311\Scripts\python.exe"
if not exist "%PY%" set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not exist "%PY%" set "PY=python"
echo [launcher] python=%PY%
"%PY%" -u assistant.py %*
pause

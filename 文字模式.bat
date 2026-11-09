@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
rem 优先用短路径 venv：TTS 的 SAPI/System.Speech 在长路径解释器下会异常
set "PY=C:\va-venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%~dp0.venv311\Scripts\python.exe"
if not exist "%PY%" set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -u assistant.py --text %*
pause

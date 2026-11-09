@echo off
cd /d C:\Users\Administrator\Documents\deepseek-harness\default-workspace\voice_assistant
set PYTHONIOENCODING=utf-8
"C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" tools\test_wake.py > tools\test_wake.out 2>&1
echo WAKE_EXIT=%ERRORLEVEL% >> tools\test_wake.out

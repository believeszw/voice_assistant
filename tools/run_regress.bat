@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PY=C:\va-venv\Scripts\python.exe
if not exist "%PY%" set PY=C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe
cd /d C:\Users\Administrator\Documents\deepseek-harness\default-workspace\voice_assistant
"%PY%" -u tools\test_frontend.py > tools\test_frontend.out 2>&1
"%PY%" -u tools\test_barge.py > tools\test_barge.out 2>&1
"%PY%" -u tools\test_barge_ux.py > tools\test_barge_ux.out 2>&1
"%PY%" -u tools\test_demo_fixes.py > tools\test_demo_fixes.out 2>&1
"%PY%" -u tools\test_compound.py > tools\test_compound.out 2>&1
"%PY%" -u tools\test_wake2.py > tools\test_wake2.out 2>&1
"%PY%" -u tools\test_tts_local.py > tools\test_tts_local.out 2>&1
type tools\text_in.txt | "%PY%" -u assistant.py --text --dry-run > tools\test_text.out 2>&1
echo DONE

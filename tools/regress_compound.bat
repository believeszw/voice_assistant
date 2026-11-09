@echo off
setlocal
cd /d "C:\Users\Administrator\Documents\deepseek-harness\default-workspace\voice_assistant"
set PYTHONIOENCODING=utf-8
set PY=C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe
(
echo === test_compound ===
"%PY%" tools\test_compound.py
echo === test_wake2 ===
"%PY%" tools\test_wake2.py
echo === test_barge_ux ===
"%PY%" tools\test_barge_ux.py
echo === text mode ===
"%PY%" assistant.py --text --dry-run < tools\text_in2.txt
echo DONE
) > tools\regress2.out 2>&1

@echo off
setlocal
set PATH=C:\Program Files (x86)\Microsoft Visual Studio\Installer;%PATH%
where vswhere.exe
call "D:\Program Files (x86)\visualstudio\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 (
  echo VCVARS_FAIL
  exit /b 1
)
where cl.exe
set PYDIR=C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python
set PATH=%PYDIR%;%PYDIR%\Scripts;%PATH%
cd /d C:\Users\Administrator\Documents\deepseek-harness\default-workspace\voice_assistant\tools\wap2_src\webrtc-audio-processing-v2.1
if exist build rmdir /s /q build
meson setup build --backend ninja --buildtype release
echo MESON_SETUP_EXIT=%ERRORLEVEL%
meson compile -C build
echo MESON_COMPILE_EXIT=%ERRORLEVEL%

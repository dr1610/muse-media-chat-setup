@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 python -m venv .venv
)
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" bridge.py --init
if errorlevel 1 goto fail
pause
exit /b 0
:fail
echo Setup failed. Check that Python 3.10 or newer is available through py or python.
pause
exit /b 1

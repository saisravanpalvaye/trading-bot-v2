@echo off
REM Called by Windows Task Scheduler: run_intraday.bat pre_market | market_open
REM Output is appended to intraday\logs\YYYY-MM-DD.log
cd /d "%~dp0"
if not exist logs mkdir logs
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set D=%%i
REM UTF-8 so the ✓ / emoji in output don't crash Python when writing to a file
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo. >> "logs\%D%.log"
python brain.py --mode %1 >> "logs\%D%.log" 2>&1

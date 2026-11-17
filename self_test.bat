@echo off
REM Checks that the installation works end-to-end on generated FM sheets.
cd /d "%~dp0"
if not exist .venv\installed.flag (echo Run run_app.bat once first. & pause & exit /b 1)
call .venv\Scripts\activate.bat
python app.py --selftest
pause

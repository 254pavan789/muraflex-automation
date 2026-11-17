@echo off
REM MURAFLEX AUTOMATION - install / repair the AI package (anthropic) used for Claude AI reading.
REM Close the app window first, then double-click this file.
cd /d "%~dp0"
title MURAFLEX AUTOMATION - install AI package
if not exist .venv\Scripts\activate.bat (echo Run run_app.bat once first. & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install --upgrade "anthropic>=0.40"
if errorlevel 1 python -m pip install --upgrade "anthropic>=0.40" --trusted-host pypi.org --trusted-host files.pythonhosted.org
echo.
python -c "import anthropic; print('AI package OK - version', anthropic.__version__)" || echo AI package still missing - see the error above (often the office proxy blocks pypi.org).
echo.
echo Now start the app again with run_app.bat
pause

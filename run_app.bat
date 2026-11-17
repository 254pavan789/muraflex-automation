@echo off
REM MURAFLEX AUTOMATION - start the app (first run installs everything).
REM Other PCs on the office network open the "Team link" shown in this window - nothing to install on them.
cd /d "%~dp0"
title MURAFLEX AUTOMATION - keep this window open
call :ensure_env || goto :fail
python -c "import waitress" 2>nul || pip install "waitress>=3.0" >nul 2>&1
python -c "import anthropic" 2>nul || call :install_ai
python app.py
pause
exit /b 0

:install_ai
echo Installing the AI package (anthropic)...
python -m pip install "anthropic>=0.40" && exit /b 0
echo Retrying through the office proxy / firewall...
python -m pip install "anthropic>=0.40" --trusted-host pypi.org --trusted-host files.pythonhosted.org && exit /b 0
echo.
echo *** AI package could not be installed. The app still works without AI (OCR is used). ***
echo *** Run install_ai.bat, or ask IT to allow pypi.org / files.pythonhosted.org.        ***
echo.
exit /b 0

:ensure_env
if not exist .venv (
    echo Creating Python environment...
    py -3 -m venv .venv 2>nul || python -m venv .venv || exit /b 1
)
call .venv\Scripts\activate.bat
if not exist .venv\installed.flag (
    echo Installing packages ^(first run only, 2-3 minutes^)...
    python -m pip install --upgrade pip >nul
    pip install -r requirements.txt || exit /b 1
    echo ok> .venv\installed.flag
)
exit /b 0

:fail
echo.
echo Setup failed - check the internet connection and that Python 3.9-3.13 is installed.
pause

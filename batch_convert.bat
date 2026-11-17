@echo off
REM Drag FM PDFs or a folder of PDFs onto this file -> one workbook per PDF (tabs GLASS + DOOR), saved next to each PDF.
cd /d "%~dp0"
if "%~1"=="" (
    echo Drag one or more FM PDFs, or a folder, onto batch_convert.bat
    pause
    exit /b 1
)
if not exist .venv (py -3 -m venv .venv 2>nul || python -m venv .venv)
call .venv\Scripts\activate.bat
if not exist .venv\installed.flag (
    pip install -r requirements.txt && echo ok> .venv\installed.flag
)
python app.py --batch %*
pause

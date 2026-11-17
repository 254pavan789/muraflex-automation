@echo off
REM Builds a stand-alone folder (no Python needed on the target PC): dist\MuraflexAutomation\
cd /d "%~dp0"
call .venv\Scripts\activate.bat || (echo Run run_app.bat once first. & pause & exit /b 1)
pip install -r requirements-dev.txt
pyinstaller --noconfirm --name MuraflexAutomation --add-data "glassx\web;glassx\web" ^
    --collect-all rapidocr --collect-all onnxruntime --collect-all pymupdf --collect-all anthropic --collect-all waitress app.py
echo.
echo Built: dist\MuraflexAutomation\MuraflexAutomation.exe
pause

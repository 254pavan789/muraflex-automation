@echo off
REM MURAFLEX AUTOMATION - let other PCs on the office network open the app.
REM Run ONCE on the PC that runs the app (it asks for administrator rights).
REM Opens TCP ports 8080-8109 in Windows Firewall for private office addresses only (10.x, 172.16-31.x, 192.168.x).
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Asking for administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
netsh advfirewall firewall delete rule name="MURAFLEX AUTOMATION" >nul 2>&1
netsh advfirewall firewall add rule name="MURAFLEX AUTOMATION" dir=in action=allow protocol=TCP localport=8080-8109 profile=any remoteip=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 description="MURAFLEX AUTOMATION web app (office network only)"
if %errorlevel% neq 0 (
    echo.
    echo Could not add the firewall rule. Ask IT to allow inbound TCP port 8080 for this PC.
    pause
    exit /b 1
)
echo.
echo Done. Other office PCs can now open the Team link shown in the MURAFLEX AUTOMATION window.
pause

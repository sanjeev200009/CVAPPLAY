@echo off
echo Stopping CV Apply background processes...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq CV Apply*" 2>nul
wmic process where "commandline like '%%cvapply.daemon%%'" delete 2>nul
echo Done.
pause

@echo off
title CV Apply - Automated Job Engine
cd /d "C:\CVAPPLY"
if not exist "C:\CVAPPLY\logs" mkdir "C:\CVAPPLY\logs"
"C:\CVAPPLY\.venv\Scripts\python.exe" -u -m cvapply.daemon --submit --interval 0.25 --batch-limit 10 >> "C:\CVAPPLY\logs\engine.log" 2>&1


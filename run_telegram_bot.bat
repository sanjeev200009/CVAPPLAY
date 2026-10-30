@echo off
title CV Apply - Telegram Instant Apply Bot
cd /d "C:\CVAPPLY"
"C:\CVAPPLY\.venv\Scripts\python.exe" -u -m cvapply.main --telegram-listen --submit

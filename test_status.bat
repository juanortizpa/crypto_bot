@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python bot_crypto.py status
pause

@echo off
cd /d "%~dp0"
if not exist .venv (python -m venv .venv || (echo Instala Python 3.10+ desde python.org & pause & exit /b 1))
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
if not exist .env (copy .env.example .env >nul & echo Rellena .env y vuelve a ejecutar & notepad .env & exit /b 0)
python bot.py
pause

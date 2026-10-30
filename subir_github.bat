@echo off
setlocal
cd /d "%~dp0"
where git >nul 2>&1 || (echo Git no esta instalado: https://git-scm.com/download/win & pause & exit /b 1)
if not exist .git git init -b main
git add -A
git status --short | findstr /i "\.env$" && (echo ERROR: el .env iba a subirse. Cancelado. & pause & exit /b 1)
git -c user.name="joseceny82-max" -c user.email="joseceny82@gmail.com" commit -m "Discord -> Telegram alerts bot + API para el panel" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_019YzoHyHyRrzgci6yS71p7S"
git remote remove origin >nul 2>&1
git remote add origin https://github.com/joseceny82-max/bot-telegram-alertas-.git
git branch -M main
git push -u origin main
echo.
if errorlevel 1 (echo ERROR al subir. Copia lo de arriba y pegaselo a Claude.) else (echo SUBIDO OK)
pause

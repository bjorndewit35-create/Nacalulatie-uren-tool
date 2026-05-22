@echo off
REM Start de nacalculatie-tool (maakt de eerste keer een venv en installeert alles).
cd /d "%~dp0"

if not exist "venv" (
  echo Eenmalige installatie...
  python -m venv venv
  call venv\Scripts\python.exe -m pip install --upgrade pip
  call venv\Scripts\pip.exe install -r requirements.txt
)

echo Tool draait op http://127.0.0.1:5000  (stoppen met Ctrl+C)
call venv\Scripts\python.exe app.py
pause

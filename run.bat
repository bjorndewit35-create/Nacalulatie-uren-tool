@echo off
REM Start de nacalculatie-tool (maakt de eerste keer een venv en installeert alles).
cd /d "%~dp0"

if not exist "venv" (
  echo Eenmalige installatie...
  python -m venv venv
  call venv\Scripts\python.exe -m pip install --upgrade pip
  call venv\Scripts\pip.exe install -r requirements.txt
)

echo De tool start en opent automatisch je browser (http://127.0.0.1:5000).
echo Laat dit venster open terwijl je de tool gebruikt; sluiten = tool stoppen.
call venv\Scripts\python.exe app.py
pause

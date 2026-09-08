@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw clipboard_library.py
) else (
  python clipboard_library.py
)

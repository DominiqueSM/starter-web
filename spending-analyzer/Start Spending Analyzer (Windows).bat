@echo off
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw -3 app\main.py & exit /b)
where pythonw >nul 2>nul && (start "" pythonw app\main.py & exit /b)
where py >nul 2>nul && (py -3 app\main.py & exit /b)
where python >nul 2>nul && (python app\main.py & exit /b)
echo Python 3.10+ is required. Install it from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH" during install), then double-click this file again.
pause

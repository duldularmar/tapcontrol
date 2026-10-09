@echo off
rem TapControl launcher - double-click to start the app
cd /d "%~dp0"
python main.py
if errorlevel 1 (
  echo.
  echo TapControl failed to start. Try installing dependencies:
  echo   python -m pip install -r requirements.txt
  pause
)

@echo off
rem TapControl test runner
cd /d "%~dp0"
python -m unittest discover -s tapcontrol/tests -v
echo.
pause

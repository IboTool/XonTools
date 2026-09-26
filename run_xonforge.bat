@echo off
setlocal
cd /d "%~dp0"

echo Starting XonForge ...
echo Open http://localhost:8501 if the browser does not open on its own.
echo Close this window or press Ctrl+C to stop the server.
echo.

python -m streamlit run xonforge/app/dashboard.py --browser.gatherUsageStats false
if errorlevel 1 (
  echo.
  echo Failed to start. Install with:  pip install -e ".[png,dev,xonforge]" -c constraints.txt
  pause
)

@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
if not exist "frontend\dist\index.html" goto missing
if not exist "data\demo.sqlite3" ".venv\Scripts\python.exe" -m backend.seed
if errorlevel 1 exit /b 1
echo Commerce Insight - LOCAL ONLY / Separate demo, public reports and uploaded transactions
echo Open http://127.0.0.1:5000 in your browser. Press Ctrl+C to stop.
".venv\Scripts\python.exe" -m backend.app
exit /b %errorlevel%
:missing
echo Please run setup.cmd first. See README.md for details.
exit /b 1

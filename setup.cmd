@echo off
setlocal
cd /d "%~dp0"
echo [1/5] Preparing the project-local Python environment...
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto fail
echo [2/5] Installing backend dependencies...
".venv\Scripts\python.exe" -m pip install -r backend\requirements-lock.txt
if errorlevel 1 goto fail
echo [3/5] Preparing simulated data. Existing database is preserved.
if not exist "data\demo.sqlite3" ".venv\Scripts\python.exe" -m backend.seed
if errorlevel 1 goto fail
echo [4/5] Installing and building the frontend...
pushd frontend
call npm.cmd ci --no-fund --no-audit
if errorlevel 1 goto frontend_fail
call npm.cmd run build
if errorlevel 1 goto frontend_fail
popd
echo [5/5] Running backend tests...
".venv\Scripts\python.exe" -m unittest discover -s backend\tests -v
if errorlevel 1 goto fail
echo Setup complete. Run start.cmd, then open http://127.0.0.1:5000
exit /b 0
:frontend_fail
popd
:fail
echo Setup failed. Read the error above and README.md. No existing database was reset.
exit /b 1

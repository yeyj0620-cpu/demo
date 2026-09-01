@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Opinion Workbench - One-click Launcher
cd /d "%~dp0"

set "PY=py"
where py >nul 2>nul || set "PY=python"

rem --- already running? just open browser and exit ---
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/status' -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1" >nul 2>&1
if %errorlevel%==0 (
    echo Server is already running. Opening browser...
    start "" "http://127.0.0.1:8000"
    timeout /t 3 /nobreak >nul
    exit /b 0
)

rem --- first run: create venv + install deps ---
if not exist ".venv\Scripts\python.exe" (
    echo First run: creating virtual environment, please wait...
    %PY% -m venv .venv || goto :fail
    echo Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
)

rem --- start server in a minimized window ---
echo Starting server...
start "Opinion Workbench Server" /min ".venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000

rem --- wait until ready, then open browser ---
echo Waiting for the server, then opening browser...
powershell -NoProfile -Command "$ok=$false; for($i=0;$i -lt 40;$i++){ try{ $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/status' -TimeoutSec 1; if($r.StatusCode -eq 200){$ok=$true;break} }catch{}; Start-Sleep -Milliseconds 500 }; if($ok){ Start-Process 'http://127.0.0.1:8000' } else { Write-Host 'Timeout: please open http://127.0.0.1:8000 manually' }"

echo.
echo Done. Close the "Opinion Workbench Server" window to stop the service.
pause
exit /b 0

:fail
echo Launch failed. Check Python and network, then retry.
pause
exit /b 1

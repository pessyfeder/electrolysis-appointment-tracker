@echo off
REM Launches the app against a throwaway data folder instead of your real
REM one, so anything you click through while testing (clients, appointments,
REM the admin password) never touches your actual scheduler.db.
setlocal
set "APPDATA=%TEMP%\ElectrolysisSchedulerTestData"
if not exist "%APPDATA%" mkdir "%APPDATA%"

echo ============================================================
echo  TEST MODE - using throwaway data, NOT your real appointments
echo  Data folder: %APPDATA%
echo  First run will ask you to set a NEW admin password (fine to
echo  make up anything - it only applies to this test data).
echo  Delete the folder above any time to wipe all test data.
echo ============================================================
echo.

"%~dp0dist\ElectrolysisScheduler\ElectrolysisScheduler.exe"
endlocal

@echo off
REM Rebuilds the app, then zips the whole dist\ElectrolysisScheduler folder
REM into release\ElectrolysisScheduler.zip. Zipping keeps the .exe and its
REM required _internal\ folder together as one file, so moving/sharing the
REM build can't accidentally leave _internal\ behind (the app won't start
REM without it).
setlocal

echo Closing any running instance...
taskkill /F /IM ElectrolysisScheduler.exe >nul 2>&1

echo Building...
"C:\Users\User\AppData\Local\Programs\PythonEmbed313\python.exe" -m PyInstaller --noconfirm ElectrolysisScheduler.spec
if errorlevel 1 (
    echo Build failed.
    exit /b 1
)

echo Zipping release...
if not exist "release" mkdir "release"
if exist "release\ElectrolysisScheduler.zip" del "release\ElectrolysisScheduler.zip"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\ElectrolysisScheduler' -DestinationPath 'release\ElectrolysisScheduler.zip'"
if errorlevel 1 (
    echo Zip failed.
    exit /b 1
)

echo Done: release\ElectrolysisScheduler.zip
endlocal

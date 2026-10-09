@echo off
:: Builds "YT Downloader.exe" (no Python needed to run the result).
::
::   packaging\build_windows.bat        (double-click it, or run from anywhere)
::
:: Bundled tools, looked up in this order:
::   ffmpeg.exe / ffprobe.exe   packaging\bin\  ->  PATH
::   deno.exe                   packaging\bin\  (optional, adds ~100 MB)
::
:: Get ffmpeg with:  winget install Gyan.FFmpeg
:: or download the "essentials" build from https://www.gyan.dev/ffmpeg/builds/
:: and copy ffmpeg.exe + ffprobe.exe into packaging\bin\

setlocal enabledelayedexpansion
title YT Downloader - Windows build
cd /d "%~dp0.."
set "ROOT=%cd%"
set "APP_NAME=YT Downloader"
set "VENV=build\venv"
set "BIN_DIR=%ROOT%\packaging\bin"

echo.
echo  YT Downloader: Windows build
echo  ============================

where python >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Install it from https://python.org
    echo          and tick "Add Python to PATH" during setup.
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo  [OK] %%v

:: 1. Isolated build environment
echo.
echo  Installing dependencies...
if not exist "%VENV%\Scripts\python.exe" python -m venv "%VENV%"
"%VENV%\Scripts\python.exe" -m pip install --quiet --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install --quiet ".[build]"
if errorlevel 1 ( echo  [ERROR] Installing dependencies failed. & pause & exit /b 1 )
echo  [OK] Dependencies installed

:: 2. Tools to bundle
echo.
echo  Looking for ffmpeg...
set "EXTRA="
for %%T in (ffmpeg ffprobe) do (
    set "FOUND="
    if exist "%BIN_DIR%\%%T.exe" (
        set "FOUND=%BIN_DIR%\%%T.exe"
    ) else (
        for /f "delims=" %%P in ('where %%T 2^>nul') do if not defined FOUND set "FOUND=%%P"
    )
    if defined FOUND (
        echo  [OK] %%T: !FOUND!
        set EXTRA=!EXTRA! --add-binary "!FOUND!;."
    ) else (
        echo  [WARNING] %%T not found. MP3 conversion and HD video won't work in the app.
        echo            Run: winget install Gyan.FFmpeg   ^(then open a new terminal^)
    )
)
if exist "%BIN_DIR%\deno.exe" (
    echo  [OK] deno: %BIN_DIR%\deno.exe
    set EXTRA=!EXTRA! --add-binary "%BIN_DIR%\deno.exe;."
)

:: 3. Build
echo.
echo  Building the exe (1-2 minutes)...
if exist "dist\%APP_NAME%.exe" del /q "dist\%APP_NAME%.exe"
"%VENV%\Scripts\python.exe" -m PyInstaller ^
  --noconfirm --clean --log-level WARN ^
  --windowed --onefile ^
  --name "%APP_NAME%" ^
  --paths "%ROOT%" ^
  --add-data "%ROOT%\ytdl\web\static;ytdl\web\static" ^
  --collect-all yt_dlp ^
  --collect-all yt_dlp_ejs ^
  --collect-data certifi ^
  --specpath build ^
  !EXTRA! ^
  "%ROOT%\packaging\app_entry.py"
if errorlevel 1 ( echo. & echo  [ERROR] Build failed, see the output above. & pause & exit /b 1 )

echo.
echo  Done!  %ROOT%\dist\%APP_NAME%.exe
echo  Copy it anywhere; it needs no installer and no Python.
echo  (Uses the Microsoft Edge WebView2 runtime, which Windows 10/11 already have.)
explorer dist
pause

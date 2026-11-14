@echo off
rem ------------------------------------------------------------------
rem Kids Discovery World - publish helper.
rem
rem Double-click this file. A window opens with three buttons:
rem   1. Check content      - just the checks, nothing is changed
rem   2. Build + show changes - what kids would download, no commit
rem   3. Publish            - check, build, bump the version, commit, push
rem
rem You only need Python and Git installed. No tokens are stored anywhere:
rem git push uses the credentials Windows Git already has.
rem ------------------------------------------------------------------
cd /d "%~dp0.."
title Kids Discovery World - Publish content

where python >nul 2>nul
if errorlevel 1 (
    echo Python is not installed or is not on PATH.
    echo Install Python from python.org (tick "Add python.exe to PATH"), then try again.
    echo.
    pause
    exit /b 1
)

python tools\publish.py %*

if errorlevel 1 (
    echo.
    echo The helper finished with an error - read the messages above.
    pause
)

@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title CFD Bot - GitHub Updater

set "PRIMARY_REPO_URL=https://github.com/bonexd/cfd_bot.git"
set "FALLBACK_REPO_URL=https://github.com/bloodvitr/cfd_bot.git"
set "REPO_URL="
set "BOOTSTRAP_ONLY=0"
if /I "%~1"=="--bootstrap-only" set "BOOTSTRAP_ONLY=1"

call :select_repo
echo Checking primary update source: %PRIMARY_REPO_URL%
git ls-remote "%PRIMARY_REPO_URL%" HEAD >nul 2>&1
if not errorlevel 1 (
  set "REPO_URL=%PRIMARY_REPO_URL%"
  echo Using primary GitHub source: %PRIMARY_REPO_URL%
  exit /b 0
)

echo Primary repo is not available yet.
echo Falling back to: %FALLBACK_REPO_URL%
git ls-remote "%FALLBACK_REPO_URL%" HEAD >nul 2>&1
if not errorlevel 1 (
  set "REPO_URL=%FALLBACK_REPO_URL%"
  exit /b 0
)

echo Neither GitHub update source is reachable.
exit /b 1

:ensure_git
if errorlevel 1 goto :fail

call :select_repo
if errorlevel 1 goto :fail

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo ZIP copy detected. Creating Git metadata...
  set "BOOTSTRAP_DIR=%TEMP%\cfd_bot_git_%RANDOM%_%RANDOM%"
  git clone --no-checkout --depth 1 "%REPO_URL%" "!BOOTSTRAP_DIR!"
  if errorlevel 1 (
    echo Could not download Git metadata from GitHub.
    if exist "!BOOTSTRAP_DIR!" rmdir /s /q "!BOOTSTRAP_DIR!" >nul 2>&1
    goto :fail
  )
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Move-Item -LiteralPath '!BOOTSTRAP_DIR!\.git' -Destination '%CD%\.git'"
  if errorlevel 1 (
    echo Could not attach Git metadata to this folder.
    if exist "!BOOTSTRAP_DIR!" rmdir /s /q "!BOOTSTRAP_DIR!" >nul 2>&1
    goto :fail
  )
  if exist "!BOOTSTRAP_DIR!" rmdir /s /q "!BOOTSTRAP_DIR!" >nul 2>&1
  git remote set-url origin "%REPO_URL%" >nul 2>&1
  git branch --set-upstream-to=origin/main main >nul 2>&1
  echo GitHub tracking attached successfully.
)

if "%BOOTSTRAP_ONLY%"=="1" (
  exit /b 0
)

echo.
echo Updating from GitHub...

git remote set-url origin "%REPO_URL%" >nul 2>&1
git fetch origin main --prune
if errorlevel 1 goto :fail

set "DIRTY=0"
for /f "delims=" %%A in ('git status --porcelain') do set "DIRTY=1"
if "!DIRTY!"=="1" (
  echo Local file changes detected. Saving them to Git stash...
  git stash push -u -m "Automatic backup before UPDATE.bat"
  if errorlevel 1 goto :fail
)

for /f %%A in ('git rev-list --count origin/main..HEAD 2^>nul') do set "AHEAD=%%A"
if not defined AHEAD set "AHEAD=0"
if not "!AHEAD!"=="0" (
  set "BACKUP_BRANCH=local-backup-%RANDOM%-%RANDOM%"
  git branch "!BACKUP_BRANCH!" HEAD
  if errorlevel 1 goto :fail
  echo Local commits preserved on branch !BACKUP_BRANCH!.
)

git checkout -B main origin/main
if errorlevel 1 goto :fail
git reset --hard origin/main
if errorlevel 1 goto :fail
git branch --set-upstream-to=origin/main main >nul 2>&1

echo.
echo Updated successfully.
git log -1 --oneline
if "!DIRTY!"=="1" (
  echo.
  echo Your previous local file changes were preserved in Git stash.
  echo Run: git stash list
  echo to see them. They were not reapplied automatically.
)
exit /b 0

:ensure_git
where git >nul 2>&1
if not errorlevel 1 exit /b 0

echo Git was not found. Attempting to install Git for Windows...
where winget >nul 2>&1
if errorlevel 1 (
  echo Git is required for GitHub updates and WinGet is unavailable.
  echo Install Git for Windows, then run UPDATE.bat again.
  exit /b 1
)

winget install -e --id Git.Git --source winget --accept-package-agreements --accept-source-agreements --silent
if errorlevel 1 (
  echo Automatic Git installation failed.
  exit /b 1
)

if exist "%ProgramFiles%\Git\cmd\git.exe" set "PATH=%ProgramFiles%\Git\cmd;%PATH%"
if exist "%LocalAppData%\Programs\Git\cmd\git.exe" set "PATH=%LocalAppData%\Programs\Git\cmd;%PATH%"

where git >nul 2>&1
if errorlevel 1 (
  echo Git was installed but this window cannot see it yet.
  echo Close this window and run UPDATE.bat again.
  exit /b 1
)
exit /b 0

:fail
echo.
echo GitHub update/setup failed. Your .env and ignored logs were not deleted.
exit /b 1

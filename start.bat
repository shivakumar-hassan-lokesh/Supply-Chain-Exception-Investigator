@echo off
REM One-step launcher for the Supply Chain Exception Investigator website (Windows).
REM Double-click this file, or run start.bat in a terminal.
setlocal
cd /d "%~dp0"

REM 1. Python 3.10+
set "PY="
where py >nul 2>&1 && py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo ERROR: Python 3.10 or newer is required. Install it from https://www.python.org/downloads/
  echo        and tick "Add python.exe to PATH" during installation. Then run start.bat again.
  pause & exit /b 1
)

REM 2. Virtual environment
if not exist ".venv\Scripts\python.exe" (
  echo Creating a private Python environment in .venv ^(first run only^)...
  %PY% -m venv .venv || (echo ERROR: could not create .venv & pause & exit /b 1)
)
set "VPY=.venv\Scripts\python.exe"

REM 3. Dependencies
"%VPY%" -c "import flask, openai, anthropic, dotenv" >nul 2>&1
if errorlevel 1 (
  echo Installing dependencies ^(first run only, about a minute^)...
  "%VPY%" -m pip install --quiet --upgrade pip
  "%VPY%" -m pip install --quiet -r requirements.txt || (echo ERROR: dependency install failed & pause & exit /b 1)
)

REM 4. Configuration
if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo.
  echo Created .env. Open it in Notepad, set LLM_PROVIDER and paste your API key
  echo ^(OPENAI_API_KEY or ANTHROPIC_API_KEY^), save, then run start.bat again.
  notepad ".env"
  pause & exit /b 0
)

REM 5. Database
if not exist "data\supply_chain.db" "%VPY%" -m scagent init-db >nul

REM 6. Start (opens your browser)
"%VPY%" -m scagent web --port 8000 --open
pause

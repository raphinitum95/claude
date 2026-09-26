@echo off
rem Double-click to start QA Regression. It opens in a window of its own; closing this black window stops it.
rem The first time, it sets itself up inside this folder (a few minutes, needs the internet) and puts a "QA Regression" icon
rem on the desktop. Nothing goes into Program Files and no admin rights are needed. To start over, delete the .venv folder.
setlocal
title QA Regression
cd /d "%~dp0"
set "HERE=%~dp0"
set "PYTHONPATH=%HERE%src"
set "VENV_PY=%HERE%.venv\Scripts\python.exe"

if not exist "%VENV_PY%" goto setup
rem A new version of the folder may need new packages: reinstall when pyproject.toml differs from the one last installed.
fc /b "pyproject.toml" ".venv\installed-pyproject.toml" >nul 2>&1 || goto install
goto start

:setup
echo Setting up QA Regression in this folder. This happens once and takes a few minutes.
echo.
set "BASE_PY="
for %%C in ("py -3" "python" "python3") do if not defined BASE_PY %%~C -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1 && set "BASE_PY=%%~C"
if not defined BASE_PY goto nopython
%BASE_PY% -m venv .venv || goto failed

:install
echo Installing what QA Regression needs. This needs the internet.
"%VENV_PY%" -m pip install --disable-pip-version-check --quiet --upgrade pip || goto failed
"%VENV_PY%" -m pip install --disable-pip-version-check --quiet -e . || goto failed
copy /y "pyproject.toml" ".venv\installed-pyproject.toml" >nul
rem Desktop icon, minimised black window. Paths go through environment variables so a quote in a folder name cannot break it.
set "SHORTCUT_TARGET=%HERE%Start QA Regression.bat"
set "SHORTCUT_ICON=%HERE%src\regrunner\web\static\app.ico"
powershell -NoProfile -Command "$s = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop') + '\QA Regression.lnk'); $s.TargetPath = $env:SHORTCUT_TARGET; $s.WorkingDirectory = $env:HERE; $s.IconLocation = $env:SHORTCUT_ICON; $s.WindowStyle = 7; $s.Save()" >nul 2>&1 && echo Added a "QA Regression" icon to your desktop. Use it to start QA Regression from now on.
echo Set up finished.
echo.

:start
echo QA Regression is running and opens in its own window.
echo Keep this window open while you use it. Close this window to stop QA Regression.
"%VENV_PY%" -m regrunner serve --app || goto failed
goto :eof

:nopython
echo Python 3.9 or newer is needed and was not found on this computer.
echo Get it from https://www.python.org/downloads/ and run the installer. No admin rights are needed:
echo   - untick "Use admin privileges when installing py.exe"
echo   - tick "Add python.exe to PATH"
echo Then double-click "Start QA Regression" again.
goto failed

:failed
echo.
echo QA Regression could not start. The messages above say why.
echo If you cannot fix it, send a screenshot of this window to whoever gave you QA Regression.
pause
exit /b 1

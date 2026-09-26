@echo off
rem Double-click to start QA Regression. A browser tab opens; close this window to stop it.
cd /d "%~dp0"
if exist ".venv\Scripts\regrunner.exe" (
  ".venv\Scripts\regrunner.exe" serve --open
) else (
  echo QA Regression has not been set up in this folder yet.
  echo Ask whoever maintains it to follow the "Set up" section of README.md, then try again.
  pause
)

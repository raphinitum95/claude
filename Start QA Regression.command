#!/bin/bash
# Double-click this file to start QA Regression. A browser tab opens; close this window to stop it.
cd "$(dirname "$0")" || exit 1
if [ -x ".venv/bin/regrunner" ]; then
  exec .venv/bin/regrunner serve --open
fi
echo "QA Regression has not been set up in this folder yet."
echo "Ask whoever maintains it to follow the 'Set up' section of README.md, then try again."
read -r -p "Press Enter to close this window."

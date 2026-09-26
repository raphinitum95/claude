#!/bin/bash
# Double-click this file to start QA Regression. It opens in a window of its own; closing this Terminal window stops it.
# The first time, it sets itself up inside this folder (a few minutes, needs the internet). No admin rights are needed.
# To start over, delete the .venv folder.
cd "$(dirname "$0")" || exit 1
export PYTHONPATH="$PWD/src"
VENV_PY=".venv/bin/python"

failed() {
  echo
  echo "QA Regression could not start. The messages above say why."
  read -r -p "Press Enter to close this window."
  exit 1
}

if [ ! -x "$VENV_PY" ]; then
  echo "Setting up QA Regression in this folder. This happens once and takes a few minutes."
  BASE_PY=""
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>/dev/null; then
      BASE_PY="$candidate"; break
    fi
  done
  if [ -z "$BASE_PY" ]; then
    echo "Python 3.9 or newer is needed and was not found. Get it from https://www.python.org/downloads/ then try again."
    failed
  fi
  "$BASE_PY" -m venv .venv || failed
fi

# A new version of the folder may need new packages: reinstall when pyproject.toml differs from the one last installed.
if ! cmp -s pyproject.toml .venv/installed-pyproject.toml; then
  echo "Installing what QA Regression needs. This needs the internet."
  "$VENV_PY" -m pip install --disable-pip-version-check --quiet --upgrade pip || failed
  "$VENV_PY" -m pip install --disable-pip-version-check --quiet -e . || failed
  cp pyproject.toml .venv/installed-pyproject.toml
fi

# Once per setup: a "QA Regression" app on the desktop (can be dragged to the Dock). It is a tiny app bundle that opens this
# launcher, so nothing is installed. It is made again when this folder moves; if you delete it, it stays deleted.
if [ "$(cat .venv/desktop-app-made 2>/dev/null)" != "$PWD" ] && [ -d "$HOME/Desktop" ]; then
  APP="$HOME/Desktop/QA Regression.app"
  rm -rf "$APP"
  mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
  cp src/regrunner/web/static/app.icns "$APP/Contents/Resources/app.icns"
  cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>QA Regression</string>
  <key>CFBundleIdentifier</key><string>local.qa-regression.launcher</string>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>CFBundleIconFile</key><string>app.icns</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
</dict></plist>
PLIST
  {
    echo '#!/bin/bash'
    printf 'LAUNCHER=%q\n' "$PWD/Start QA Regression.command"
    echo 'if [ -f "$LAUNCHER" ]; then exec open "$LAUNCHER"; fi'
    echo 'osascript -e "display alert \"QA Regression was moved or deleted\" message \"Double-click Start QA Regression.command in its new folder: it makes a new one.\""'
  } > "$APP/Contents/MacOS/launch"
  chmod +x "$APP/Contents/MacOS/launch"
  touch "$APP"
  printf '%s' "$PWD" > .venv/desktop-app-made
  echo "Added a \"QA Regression\" app to your desktop. Use it (or drag it to the Dock) to start QA Regression from now on."
fi

echo "QA Regression is running and opens in its own window."
echo "Closing the QA Regression window stops it and closes this one. Closing this one stops it straight away."
"$VENV_PY" -m regrunner serve --app --exit-when-closed || failed

# Stopped cleanly (the UI window was closed): close this Terminal window too. Terminal would otherwise leave it open saying
# "[Process completed]". Only this window is closed (matched by its tty); after a failure it stays open so the messages can be read.
THIS_TTY="$(tty 2>/dev/null)"
if [ -n "$THIS_TTY" ] && [ "$TERM_PROGRAM" = "Apple_Terminal" ]; then
  osascript - "$THIS_TTY" >/dev/null 2>&1 <<'OSA' &
on run argv
  delay 0.5
  tell application "Terminal"
    repeat with w in windows
      repeat with t in tabs of w
        if tty of t is (item 1 of argv) then
          close w saving no
          return
        end if
      end repeat
    end repeat
  end tell
end run
OSA
  disown
fi
exit 0

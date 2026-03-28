#!/bin/bash
set -e

# Get the absolute path of the directory where setup.sh is located
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Dictation.app"
RUN_SCRIPT="$PROJECT_DIR/run.sh"

echo "⚙️  Creating $APP_NAME..."

# Create the AppleScript content
APPLE_SCRIPT="tell application \"Terminal\"
    activate
    do script \"$RUN_SCRIPT\"
end tell"

# Compile into a macOS Application
osacompile -e "$APPLE_SCRIPT" -o "$APP_NAME"

echo "✅ Created $APP_NAME in $PROJECT_DIR"

echo "⚙️  Adding to Login Items..."

# Try to add to Login Items. 
# NOTE: This may fail with 'Not authorised' if your Terminal doesn't have 
# Permission to control 'System Events'. If it fails, follow the manual steps.
if osascript -e "tell application \"System Events\" to make login item at end with properties {path:\"$PROJECT_DIR/$APP_NAME\", name:\"Dictation\", hidden:false}" 2>/dev/null; then
    echo "✅ Successfully added to Login Items!"
else
    echo "⚠️  Could not automatically add to Login Items due to macOS privacy restrictions."
    echo "👉 Please add it manually:"
    echo "   1. Open System Settings > General > Login Items"
    echo "   2. Click [+] and select: $PROJECT_DIR/$APP_NAME"
fi

#!/bin/bash

APP_NAME="Dictation"

echo "🗑️ Removing '$APP_NAME' from Login Items..."

if osascript -e "tell application \"System Events\" to delete (every login item whose name is \"$APP_NAME\")" 2>/dev/null; then
    echo "✅ Successfully removed '$APP_NAME' from Login Items."
else
    echo "❌ Failed to remove '$APP_NAME' from Login Items. You may need to do it manually in System Settings > General > Login Items."
fi

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -d "$PROJECT_DIR/$APP_NAME.app" ]]; then
    echo "🧹 Removing $APP_NAME.app..."
    rm -rf "$PROJECT_DIR/$APP_NAME.app"
fi

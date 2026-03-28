#!/bin/bash

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$PROJECT_DIR/.dictation.pid"

if [[ -f "$PIDFILE" ]]; then
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "🛑 Stopping Dictation (PID $PID)..."
        kill "$PID"
    else
        echo "⚠️ Found PID file, but process $PID is not running. Cleaning up."
        rm -f "$PIDFILE"
    fi
else
    echo "ℹ️ No PID file found. Is the app running?"
fi

#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_NAME="dictation"
PIDFILE="$SCRIPT_DIR/.dictation.pid"

# ── 0. Guard against duplicate runs ─────────────────────────────────────────
if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "✅ Dictation is already running (PID $(cat "$PIDFILE")). Exiting."
    exit 0
fi

cleanup() { rm -f "$PIDFILE"; }
trap cleanup EXIT

# ── 1. Check / install conda ────────────────────────────────────────────────
if ! command -v conda &>/dev/null; then
    echo "⚙️  Conda not found. Installing via Homebrew..."

    if ! command -v brew &>/dev/null; then
        echo "❌ Homebrew is not installed. Install it from https://brew.sh" >&2
        exit 1
    fi

    brew install --cask miniconda
    eval "$("$(brew --prefix)"/Caskroom/miniconda/base/bin/conda shell.bash hook)"
    conda init --all >/dev/null 2>&1 || true
    echo "✅ Conda installed via Homebrew."
else
    echo "✅ Conda found: $(conda --version)"
    # Ensure conda functions (activate, etc.) are available in this shell
    eval "$(conda shell.bash hook)"
fi

# ── 2. Check / create the 'dictation' environment ───────────────────────────
if conda env list | grep -qw "$ENV_NAME"; then
    echo "✅ Conda environment '$ENV_NAME' already exists."
else
    echo "⚙️  Creating conda environment '$ENV_NAME' from environment.yml..."
    conda env create -f "$SCRIPT_DIR/environment.yml"
    echo "✅ Environment '$ENV_NAME' created."
fi

# ── 3. Activate and run ─────────────────────────────────────────────────────
echo "🚀 Activating '$ENV_NAME' and running main.py..."
source activate "$ENV_NAME"
python "$SCRIPT_DIR/main.py" &
echo $! > "$PIDFILE"
wait $!

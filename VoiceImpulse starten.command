#!/bin/bash
# VoiceImpulse — Starter
# Doppelklick im Finder startet die App

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/app"
ENV_FILE="$SCRIPT_DIR/backend/.env"
PYTHON="/opt/homebrew/bin/python3.12"

# API Key aus backend/.env laden falls noch nicht in config
if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs) 2>/dev/null
fi

cd "$APP_DIR"
exec "$PYTHON" main.py

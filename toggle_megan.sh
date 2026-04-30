#!/bin/bash
# CMD+SHIFT+M — Megan starten oder stoppen

DIR="/Users/maikeichholz/Desktop/eigene KI/megan"
PYTHON="$DIR/venv/bin/python3"
PID_FILE="/tmp/megan_main.pid"

stop_megan() {
    # Per PID-File stoppen
    if [ -f "$PID_FILE" ]; then
        kill -KILL "$(cat $PID_FILE)" 2>/dev/null
        rm -f "$PID_FILE"
    fi
    # Sicherheitsnetz: alles was megan.py oder afplay heißt killen
    pkill -KILL -f "$DIR/megan.py"  2>/dev/null
    pkill -KILL -f "$DIR/overlay.py" 2>/dev/null
    pkill -KILL -f "$DIR/server.py"  2>/dev/null
    pkill -KILL -f "afplay"           2>/dev/null
    osascript -e 'display notification "Megan ist offline." with title "Megan"'
}

start_megan() {
    # Server zuerst (Status-API + Overlay-Polling)
    "$PYTHON" "$DIR/server.py" >> /tmp/megan-server.log 2>&1 &
    sleep 1
    # megan.py startet — spawnt overlay.py automatisch
    "$PYTHON" "$DIR/megan.py" >> /tmp/megan-voice.log 2>&1 &
    echo $! > "$PID_FILE"
    osascript -e 'display notification "Megan startet…" with title "Megan"'
}

if pgrep -f "$DIR/megan.py" > /dev/null 2>&1; then
    stop_megan
else
    start_megan
fi

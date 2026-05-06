#!/bin/bash
# CMD+SHIFT+M — Megan starten oder stoppen
DIR="/Users/andreasdrosdov/Desktop/Claude/Projekte/Voice Impulse Projekt"
PID_FILE="/tmp/megan_main.pid"

stop_megan() {
    if [ -f "$PID_FILE" ]; then
        kill -KILL "$(cat $PID_FILE)" 2>/dev/null
        rm -f "$PID_FILE"
    fi
    pkill -KILL -f "megan.py"   2>/dev/null
    pkill -KILL -f "overlay.py" 2>/dev/null
    pkill -KILL -f "server.py"  2>/dev/null
    pkill -KILL -f "afplay"      2>/dev/null
    osascript -e 'display notification "Megan ist offline." with title "Megan"'
}

start_megan() {
    python3 "$DIR/server.py" >> /tmp/megan-server.log 2>&1 &
    sleep 1
    python3 "$DIR/megan.py" >> /tmp/megan-voice.log 2>&1 &
    echo $! > "$PID_FILE"
    osascript -e 'display notification "Megan startet…" with title "Megan"'
}

if pgrep -f "megan.py" > /dev/null 2>&1; then
    stop_megan
else
    start_megan
fi

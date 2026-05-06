#!/bin/bash
DIR="/Users/andreasdrosdov/Desktop/Claude/Projekte/Voice Impulse Projekt"
PYTHON="/opt/homebrew/bin/python3.12"
cd "$DIR"

"$PYTHON" server.py &
sleep 1
"$PYTHON" megan.py &

wait

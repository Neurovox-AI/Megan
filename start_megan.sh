#!/bin/bash
# Startet server.py + megan.py
DIR="/Users/andreasdrosdov/Desktop/Claude/Projekte/Voice Impulse Projekt"
cd "$DIR"

python3 server.py &
sleep 1
python3 megan.py &

wait

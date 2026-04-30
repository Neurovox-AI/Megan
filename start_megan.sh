#!/bin/bash
# LaunchAgent Script — startet server.py + Cloudflare Tunnel beim Login
cd "/Users/maikeichholz/eigene KI/megan"
source venv/bin/activate

# Server starten
python3 server.py &

# Cloudflare Tunnel (macht den Server von außen erreichbar)
cloudflared tunnel --url http://localhost:8080 &

wait

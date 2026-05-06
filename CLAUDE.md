# Voice Impulse / Megan – Projektstand

## Was ist Megan?
Ein persönlicher Desktop-KI-Assistent für macOS mit Sprachsteuerung.
Nutzer halten die rechte Option-Taste und sprechen — Megan versteht, antwortet und führt Aktionen aus.

---

## WICHTIG: Auto-Push Regel

**Nach JEDER Änderung, die du machst, führst du automatisch folgende Befehle aus:**

```bash
git add .
git commit -m "kurze Beschreibung der Änderung"
git push
```

Kein Ausnahme. Jede Datei, jede kleine Änderung, sofort pushen.
Wir arbeiten zu zweit – der andere muss immer den aktuellen Stand haben.

---

## Projektstruktur (aktuell)

```
Voice Impulse Projekt/
├── megan.py            ← Haupt-App (Stimme, KI, Tools, iPhone API)
├── overlay.py          ← Siri-Style Overlay (Bottom Bar, animierte Blase)
├── server.py           ← Flask Server Port 8080 (Status API + iPhone PWA)
├── start_megan.sh      ← Startet server.py + megan.py
├── toggle_megan.sh     ← Toggle-Script (start/stop)
├── backend/            ← FastAPI Backend (Andreas, unberührt)
├── app/                ← Alte App-Schicht (unberührt)
└── frontend/           ← Homepage (Kollege)
```

---

## Starten

```bash
# Manuell:
/opt/homebrew/bin/python3.12 server.py &
/opt/homebrew/bin/python3.12 megan.py

# Per Script:
./start_megan.sh

# Toggle (start/stop):
./toggle_megan.sh
```

Server läuft auf: `http://localhost:8080`
iPhone PWA: `http://<lokale-IP>:8080`

---

## Technologie-Stack

| Bereich | Technologie |
|---------|-------------|
| Haupt-App | Python (megan.py) |
| Speech-to-Text | mlx_whisper `whisper-large-v3-turbo` (lokal, Apple Silicon) |
| KI | Anthropic Claude `claude-sonnet-4-6` |
| Text-to-Speech | edge-tts `de-AT-IngridNeural` (Microsoft Neural) |
| Overlay | pywebview + AppKit (Siri-Style Bottom Bar) |
| Status-Server | Flask Port 8080 |
| iPhone API | HTTP Server Port 8081 (in megan.py) |

---

## Trigger / Bedienung

| Aktion | Taste |
|--------|-------|
| PTT — einmal sprechen | Rechte Option-Taste **halten** → loslassen |
| Dauermodus an | Rechte Option-Taste **2x tippen** |
| Dauermodus aus | Rechte Option-Taste **2x tippen** |
| Megan unterbrechen | Rechte Option-Taste während sie spricht |

**Voraussetzung:** Python3.12 muss in Systemeinstellungen → Bedienungshilfen erlaubt sein.

---

## Konfiguration (.env)

`megan.py` lädt automatisch aus `backend/.env`:

```
ANTHROPIC_API_KEY=...
```

---

## Verfügbare Tools (was Megan kann)

| Tool | Beschreibung |
|------|-------------|
| `run_shell` | Shell-Befehl ausführen |
| `open_app` | App öffnen (`open -a`) |
| `open_website` | URL öffnen, optional in bestimmtem Browser (`browser: "Safari"`) |
| `search_web` | Google-Suche öffnen, optional in bestimmtem Browser |
| `set_volume` | Lautstärke 0-100 |
| `control_music` | Spotify/Apple Music play/pause/next/previous |
| `show_notification` | Mac-Benachrichtigung |
| `save_memory` | Fakt über Andreas dauerhaft speichern (`~/.megan_memory.json`) |
| `forget_memory` | Gespeicherten Fakt löschen |
| `mouse_click` | Mausklick auf Koordinaten |
| `type_text` | Text über Tastatur eingeben |
| `press_key` | Tastenkombination drücken |
| `take_screenshot` | Screenshot für Claude sichtbar machen |
| `scroll` | Scrollen |

**Screen-Keywords** (lösen automatisch Screenshot aus):
`sieh`, `schau`, `guck`, `bildschirm`, `screen`, `zeig`, `was ist offen`, etc.

---

## Gedächtnis

- Datei: `~/.megan_memory.json`
- Wird automatisch in den System-Prompt geladen (max. 20 letzte Einträge)
- Megan speichert/löscht per Tool-Call

---

## Whisper Einstellungen

```python
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
language = "de"
no_speech_threshold = 0.4
initial_prompt = "Gesprochener deutscher Text, Sprachassistent, Alltagssprache."
```

---

## Zuständigkeiten

| Bereich | Wer |
|---------|-----|
| `megan.py`, `server.py`, `overlay.py` | Gemeinsam |
| `backend/` | Andreas |
| `app/ui/`, `frontend/` | Kollege |

---

## Erledigte Arbeiten

- [x] Kollegen App-Design übernommen (megan.py, overlay.py, server.py)
- [x] ElevenLabs → edge-tts (Ingrid) ersetzt
- [x] Whisper small → large-v3-turbo für besseres Deutsch
- [x] `initial_prompt` für bessere Transkription
- [x] `open_website` + `search_web` mit Browser-Parameter (Safari, Chrome etc.)
- [x] `.env` aus `backend/.env` automatisch geladen
- [x] Accessibility-Berechtigung für python3.12 eingerichtet
- [x] App getestet — alle Tools funktionieren

## Offene Punkte

- [ ] `toggle_megan.sh` als Shortcut im System einrichten
- [ ] Stimme Seraphina als Option testen (mehrsprachig)
- [ ] Windows-Support (Phase 2)
- [ ] Frontend/Homepage (Kollege)

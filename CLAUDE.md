# Voice Impulse – Projektstand

## Was ist Voice Impulse?
Ein verbraucherfreundlicher Desktop-Agent mit Sprachsteuerung.
Nutzer sprechen oder tippen Befehle – der Agent führt sie direkt aus.
Entwickelt auf Basis der Marktanalyse vom 14. April 2026.

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

## Zuständigkeiten

| Bereich | Ordner | Wer |
|---------|--------|-----|
| Backend API & Logik | `backend/` | Andreas |
| App Engine & Python | `app/*.py` | Andreas |
| App UI (Desktop Design) | `app/ui/` | Kollege |
| Frontend (Homepage & Web) | `frontend/` | Kollege |

**Faustregel:**
- Alles mit `.py` → Andreas
- Alles mit `.html`, `.css`, `.js` → Kollege

---

## Projektstruktur

```
Voice Impulse Projekt/
├── backend/              ← Python FastAPI Backend (Andreas)
│   ├── 01_audio_transkription/
│   ├── 02_intent_engine/
│   ├── 03_dateisystem/
│   ├── 04_notizen_todos/
│   ├── 05_drafts/
│   ├── 06_kalender/
│   ├── 07_bestaetigung/
│   ├── 08_aktionsverlauf/
│   ├── 09_fehlerbehandlung/
│   ├── 10_sprachausgabe/
│   ├── 11_aktivierung/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── chat.py
│   └── start.py
│
├── app/                  ← Neue App-Schicht
│   ├── engine.py         ← Andreas
│   ├── api.py            ← Andreas
│   ├── main.py           ← Andreas
│   ├── config.py         ← Andreas
│   └── ui/               ← Kollege (Desktop App Design)
│       ├── dashboard.html
│       ├── settings.html
│       ├── setup.html
│       └── style.css
│
├── frontend/             ← Kollege (Homepage & Web)
│
├── API_DOKU.md           ← Dokumentation für den Frontend-Kollegen
└── CLAUDE.md             ← Diese Datei

```

---

## Backend – Module

| Ordner | Funktion |
|--------|----------|
| `01_audio_transkription/` | Sprache → Text (Whisper, läuft lokal) |
| `02_intent_engine/` | Text → Intent + Parameter (Claude API) |
| `03_dateisystem/` | Dateien suchen, öffnen, recent files |
| `04_notizen_todos/` | Notizen & To-dos erstellen/lesen |
| `05_drafts/` | E-Mail & Nachrichten-Entwürfe (kein Auto-Send) |
| `06_kalender/` | Kalendereinträge via AppleScript (macOS) |
| `07_bestaetigung/` | Bestätigungsflow vor jeder Aktion |
| `08_aktionsverlauf/` | Protokoll aller Aktionen |
| `09_fehlerbehandlung/` | Fehlermeldungen, Rückfragen |
| `10_sprachausgabe/` | Text → Sprache (edge-tts, Stimme: Ingrid) |
| `11_aktivierung/` | Wake Word + Push-to-Talk Einstellungen |

---

## Wichtige Dateien

| Datei | Zweck |
|-------|-------|
| `backend/main.py` | FastAPI App, alle Router eingebunden |
| `backend/config.py` | API Keys, Suchpfade, Modell-Einstellungen |
| `backend/database.py` | SQLite Setup (notes, todos, drafts, history) |
| `backend/chat.py` | Konversations-Endpunkt `/chat` |
| `backend/start.py` | Starter-Skript für die Desktop-App |
| `backend/.env` | API Keys (nicht ins Git!) |
| `backend/activation_settings.json` | Wake Word & PTT Einstellungen |

---

## Technologie-Stack

| Bereich | Technologie |
|---------|-------------|
| Backend Framework | Python FastAPI |
| Datenbank | SQLite (lokal) |
| Speech-to-Text | faster-whisper (lokal, Modell: small) |
| Intent-Erkennung | Anthropic Claude API (claude-sonnet-4-6) |
| Text-to-Speech | edge-tts (Microsoft Neural, Stimme: Ingrid) |
| Kalender | AppleScript (macOS) |

---

## Server starten

```bash
cd backend
python3 start.py
# oder direkt:
uvicorn main:app --port 8000
```

Server läuft auf: `http://localhost:8000`
Interaktive Doku: `http://localhost:8000/docs`

---

## Hauptendpunkte

| Endpunkt | Beschreibung |
|----------|-------------|
| `POST /chat` | Kompletter Konversationsflow (Text rein, Antwort + Aktion raus) |
| `POST /transcribe` | Audio → Text (Whisper lokal) |
| `POST /intent` | Text → Intent + Parameter |
| `POST /execute` | Aktion ausführen nach Bestätigung |
| `POST /speak` | Text vorlesen lassen |
| `GET /activation/settings` | Wake Word & PTT Einstellungen |
| `PATCH /activation/settings` | Einstellungen ändern |
| `WS /activation/ws` | WebSocket für Wake-Word-Events |

---

## Stimme

- Aktuelle Stimme: **Ingrid** (`de-AT-IngridNeural`)
- Getestete Stimmen: Katja, Amala, Seraphina, Ingrid, Leni
- Seraphina ist mehrsprachig (Deutsch, Englisch, Russisch, uvm.)
- Stimme ändern: `VOICE` in `10_sprachausgabe/tts.py`

---

## Wake Word & Push-to-Talk

```bash
# Name setzen (Wake Word wird automatisch angepasst)
PATCH /activation/settings
{ "agent_name": "Megan" }
→ Wake Word wird automatisch "hey megan"

# Wake Word aktivieren
POST /activation/wakeword/start

# PTT-Taste setzen
PATCH /activation/settings
{ "ptt_key": "cmd+shift+m" }
```

---

## Getestete Befehle (funktionieren alle)

- "Öffne die letzte PDF"
- "Erstelle eine Notiz mit dem Titel Ideen"
- "Schreib Roman eine Nachricht dass das Meeting verschoben wird"
- "Lege morgen um 14 Uhr einen Termin an"
- "Ich muss Roman kontaktieren, die Rechnung bezahlen und das Meeting vorbereiten"
- "Verfasse eine E-Mail an Sascha und frag nach dem Preis"

---

## Erledigte Arbeiten

### 2026-04-29 — App UI Dark Theme (Kollege)
- `app/ui/style.css` — komplettes Dark Theme: `--bg:#060402`, Cream-Text `#F5EDE2`, Glass-Surfaces `rgba(255,255,255,0.04)`, Rose/Pink Akzente, ambient body glow
- `app/ui/dashboard.html` — alle Stat-Cards, Nav-Buttons und Usage-Bar im Dark Design
- `app/ui/settings.html` — Section-Cards, Inputs, Toggles und Toast im Dark Theme
- `app/ui/setup.html` — Plan-Cards mit Rose-Border bei Selektion, Info-Rows im Dark Glass Stil

---

## Nächste Schritte (offen)

- [ ] Seraphina als optionale mehrsprachige Stimme einbauen
- [ ] Wake-Word "Ja?"-Begrüßungston nach Erkennung
- [ ] Windows-Support (Phase 2)
- [ ] Cloud-Sync für Notizen (Phase 2)
- [ ] Frontend bauen (Kollege)

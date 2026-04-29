# Voice Impulse – API Dokumentation für die Desktop-App
Basis-URL: `http://localhost:8000`
Alle Anfragen: `Content-Type: application/json`

---

## Typischer Ablauf

```
1. Nutzer spricht → Audio aufnehmen
2. POST /transcribe → Text zurückbekommen
3. POST /intent → Intent + Parameter erkennen
4. POST /execute/prepare → Bestätigungsobjekt holen
5. App zeigt Bestätigung an → Nutzer bestätigt
6. POST /execute → Aktion ausführen
7. GET /history → Verlauf anzeigen
```

---

## 1. Audio transkribieren

**POST /transcribe**
Audio-Datei hochladen, Text zurückbekommen.

```
Request: multipart/form-data
  file: <audio-datei> (wav, mp3, m4a, webm)

Response:
{
  "text": "Öffne die letzte PDF",
  "confidence": 0.92,
  "language": "de"
}
```

---

## 2. Intent erkennen

**POST /intent**
Transkribierten Text analysieren.

```
Request:
{ "text": "Lege morgen um 14 Uhr einen Termin mit Max an" }

Response:
{
  "intent": "create_event",
  "parameters": {
    "event_title": "Termin mit Max",
    "event_datetime_raw": "morgen um 14 Uhr",
    "recipient": "Max",
    ... (andere Parameter als null)
  },
  "confidence": 0.95,
  "datetime_parsed": "2026-04-17T14:00:00"
}
```

**Alle möglichen Intents:**
| Intent | Bedeutung |
|--------|-----------|
| `open_file` | Datei öffnen |
| `search_file` | Datei suchen |
| `show_recent` | Zuletzt verwendete Dateien |
| `create_note` | Neue Notiz erstellen |
| `append_note` | Notiz ergänzen |
| `create_todo` | To-do erstellen |
| `draft_message` | Nachrichten-Entwurf |
| `draft_email` | E-Mail-Entwurf |
| `create_event` | Kalendereintrag |
| `show_history` | Verlauf anzeigen |
| `unknown` | Nicht erkannt → Rückfrage zeigen |

---

## 3. Aktion vorbereiten (Bestätigung)

**POST /execute/prepare?intent={intent}&datetime_parsed={iso-datum}**
Gibt ein Objekt zurück das der App zeigt was gleich passiert.

```
Request: { ...parameter-objekt aus /intent response... }

Response:
{
  "intent": "create_event",
  "parameters": { ... },
  "description": "Termin anlegen: Termin mit Max – 2026-04-17T14:00:00",
  "requires_confirmation": true,
  "datetime_parsed": "2026-04-17T14:00:00"
}
```

**requires_confirmation: true** → App muss dem Nutzer eine Bestätigungsmeldung zeigen.
**requires_confirmation: false** → App kann direkt zu /execute gehen.

---

## 4. Aktion ausführen

**POST /execute**
Führt die Aktion aus – NUR nach Nutzerbestätigung aufrufen.

```
Request:
{
  "payload": { ...objekt von /execute/prepare... },
  "approved": true
}

Response (Erfolg):
{
  "status": "executed",
  "intent": "create_note",
  "summary": "Notiz erstellt: Meeting Ideen",
  "data": { ...erstelltes Objekt... }
}

Response (abgelehnt):
{
  "status": "rejected",
  "intent": "create_note",
  "summary": "Aktion wurde vom Nutzer abgelehnt."
}
```

---

## 5. Dateien

**GET /files/recent**
Zuletzt verwendete Dateien.
```
Response: [{ "name": "...", "path": "...", "modified_at": "...", "filetype": "pdf" }]
```

**GET /files/search?q={suchbegriff}&filetype={optional}**
Dateien suchen.
```
GET /files/search?q=Rechnung&filetype=pdf
Response: [{ "name": "Rechnung_April.pdf", "path": "...", ... }]
```

**POST /files/open**
Datei mit Standard-App öffnen.
```
Request: { "path": "/Users/.../Datei.pdf" }
Response: { "status": "ok", "opened": "/Users/.../Datei.pdf" }
```

---

## 6. Notizen

**GET /notes** → Alle Notizen
**POST /notes** → Neue Notiz
```
Request: { "title": "Ideen", "content": "Inhalt der Notiz" }
```
**PATCH /notes/{id}** → Inhalt anhängen
```
Request: { "content": "Neuer Absatz" }
```

---

## 7. To-dos

**GET /todos** → Alle To-dos
**POST /todos** → Einzelnes To-do
```
Request: { "text": "Roman kontaktieren", "due_date": null }
```
**POST /todos/from-text** → Mehrere To-dos aus Text extrahieren
```
Request: { "text": "Ich muss Roman kontaktieren und die Rechnung bezahlen" }
Response: [{ "id": 1, "text": "Roman kontaktieren", ... }, ...]
```
**PATCH /todos/{id}/done** → Als erledigt markieren

---

## 8. Entwürfe

**GET /drafts** → Alle Entwürfe (optional ?type=email oder ?type=message)
**POST /drafts/email** → E-Mail-Entwurf
```
Request: { "recipient": "Sascha", "subject": null, "body_instruction": "frag nach dem Preis" }
Response: { "id": 1, "type": "email", "recipient": "Sascha", "subject": "...", "body": "...", "created_at": "..." }
```
**POST /drafts/message** → Nachrichten-Entwurf
```
Request: { "recipient": "Max", "body_instruction": "sag ihm dass ich später komme" }
```
**DELETE /drafts/{id}** → Entwurf löschen

---

## 9. Kalender

**POST /calendar/event** → Termin anlegen
```
Request: {
  "title": "Meeting mit Max",
  "datetime_iso": "2026-04-17T14:00:00",
  "duration_minutes": 60,
  "location": null
}
```
**GET /calendar/events** → Nächste 7 Tage

---

## 10. Verlauf

**GET /history?limit=20&intent=optional** → Aktionsverlauf
**DELETE /history/{id}** → Einzelnen Eintrag löschen
**DELETE /history?confirm=true** → Gesamten Verlauf löschen

---

## Fehlerbehandlung

| HTTP Code | Bedeutung | Was die App tun soll |
|-----------|-----------|----------------------|
| `400` | Fehlende/ungültige Parameter | Fehlermeldung anzeigen |
| `404` | Nicht gefunden | Meldung anzeigen |
| `422` | Rückfrage nötig (fehlender Parameter) | Rückfrage-Dialog öffnen |
| `500` | Interner Fehler | Neutrale Fehlermeldung |
| `502/503` | KI-Dienst nicht erreichbar | "Verbindung prüfen" anzeigen |

**422-Antwort (Rückfrage):**
```json
{
  "status": "needs_clarification",
  "missing": ["recipient"],
  "question": "An wen soll die E-Mail gehen?"
}
```
→ App zeigt dem Nutzer die `question` an und schickt die Antwort erneut an `/intent`.

---

## Backend starten (für die App)

```python
# In der Desktop-App beim Start aufrufen:
import subprocess
subprocess.Popen(["python3", "start.py"], cwd="pfad/zum/backend")
```

Oder direkt:
```bash
python3 /pfad/zum/backend/start.py
```

import json
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import anthropic
from dateutil import parser as dateutil_parser
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MIN_CONFIDENCE

router = APIRouter(prefix="/intent", tags=["Intent Engine"])

def _get_client():
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

VALID_INTENTS = [
    "open_file",
    "search_file",
    "show_recent",
    "create_note",
    "append_note",
    "create_todo",
    "draft_message",
    "draft_email",
    "create_event",
    "show_history",
    "unknown",
]

SYSTEM_PROMPT = f"""Du bist ein Intent-Parser für einen Desktop-Assistenten.
Analysiere den Nutzer-Text und gib NUR ein JSON-Objekt zurück – kein erklärender Text.

Erlaubte Intents: {', '.join(VALID_INTENTS)}

JSON-Format:
{{
  "intent": "<intent>",
  "parameters": {{
    "filename": null,
    "path": null,
    "filetype": null,
    "recipient": null,
    "subject": null,
    "body_instruction": null,
    "note_title": null,
    "note_content": null,
    "todo_text": null,
    "event_title": null,
    "event_datetime_raw": null,
    "event_duration_minutes": null,
    "event_location": null
  }},
  "confidence": 0.0
}}

Regeln:
- confidence zwischen 0.0 und 1.0
- Nicht erkannte Parameter als null lassen
- Datum/Uhrzeit IMMER als rohen Text in event_datetime_raw speichern (z.B. "morgen um 14 Uhr")
- Wenn unklar, intent = "unknown" mit confidence < 0.5
"""


class IntentRequest(BaseModel):
    text: str


class IntentResult(BaseModel):
    intent: str
    parameters: dict
    confidence: float
    datetime_parsed: Optional[str] = None


@router.post("", response_model=IntentResult)
async def parse_intent(req: IntentRequest):
    """
    Nimmt transkribierten Text entgegen und gibt Intent + Parameter zurück.
    """
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text darf nicht leer sein.")

    try:
        message = _get_client().messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": req.text}],
        )
    except anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"KI-Dienst nicht erreichbar: {str(e)}")

    raw = message.content[0].text.strip()

    # JSON aus der Antwort extrahieren (Claude gibt manchmal Text darum herum)
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("Kein JSON gefunden")
        data = json.loads(raw[start:end])
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=500, detail="Ungültige Antwort vom KI-Dienst.")

    intent = data.get("intent", "unknown")
    if intent not in VALID_INTENTS:
        intent = "unknown"

    confidence = float(data.get("confidence", 0.5))
    if confidence < MIN_CONFIDENCE:
        intent = "unknown"

    parameters = data.get("parameters", {})
    datetime_parsed = None

    raw_dt = parameters.get("event_datetime_raw")
    if raw_dt:
        datetime_parsed = _parse_natural_datetime(raw_dt)

    return IntentResult(
        intent=intent,
        parameters=parameters,
        confidence=confidence,
        datetime_parsed=datetime_parsed,
    )


def _parse_natural_datetime(text: str) -> Optional[str]:
    """
    Wandelt natürliche Zeitangaben in ISO-8601 um.
    Beispiele: 'morgen um 14 Uhr', 'nächsten Montag', 'in einer Stunde'
    """
    import re
    now = datetime.now()
    text_lower = text.lower()

    # Basis-Datum bestimmen
    if "übermorgen" in text_lower:
        base = now + timedelta(days=2)
    elif "morgen" in text_lower:
        base = now + timedelta(days=1)
    elif "heute" in text_lower:
        base = now
    elif "in einer stunde" in text_lower:
        return (now + timedelta(hours=1)).isoformat()
    elif "in zwei stunden" in text_lower:
        return (now + timedelta(hours=2)).isoformat()
    else:
        base = now

    # Uhrzeit extrahieren: "14 Uhr", "14:30 Uhr", "14:30", "um 9"
    time_match = re.search(r'(\d{1,2})(?:[:\.](\d{2}))?\s*uhr', text_lower)
    if not time_match:
        time_match = re.search(r'um\s+(\d{1,2})(?:[:\.](\d{2}))?', text_lower)

    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        return base.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()

    try:
        parsed = dateutil_parser.parse(text, default=base, dayfirst=True)
        return parsed.isoformat()
    except Exception:
        return base.replace(hour=9, minute=0, second=0, microsecond=0).isoformat()

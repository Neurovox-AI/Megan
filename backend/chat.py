"""
Voice Impulse – Chat Endpunkt
Der zentrale Konversations-Endpunkt:
Text rein → Aktion ausführen → gesprochene Antwort raus
"""
import json
import anthropic
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

router = APIRouter(prefix="/chat", tags=["Konversation"])
_client = None

def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


class ChatRequest(BaseModel):
    text: str                        # Vom Nutzer gesprochener / getippter Text
    speak_response: bool = True      # Antwort auch vorlesen?
    auto_execute: bool = False       # Direkt ausführen ohne Bestätigung?


class ChatResponse(BaseModel):
    spoken_text: str                 # Was Voice Impulse antwortet (wird vorgelesen)
    intent: str
    status: str                      # "executed" | "needs_confirmation" | "needs_clarification" | "unknown"
    confirmation_payload: Optional[dict] = None   # Wird gesetzt wenn Bestätigung nötig
    data: Optional[dict] = None      # Ergebnis der Aktion


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """
    Vollständiger Konversations-Flow:
    1. Text → Intent erkennen
    2. Fehlende Parameter prüfen
    3. Aktion ausführen (wenn auto_execute=True) oder Bestätigung anfragen
    4. Natürliche Antwort formulieren
    5. Antwort vorlesen
    """
    from intent import parse_intent, IntentRequest
    from errors import handle_missing_parameters, handle_unknown_intent
    from tts import speak_text

    # 1. Intent erkennen
    intent_result = await parse_intent(IntentRequest(text=req.text))

    # 2. Unbekannten Intent behandeln
    if intent_result.intent == "unknown":
        response = handle_unknown_intent(req.text, intent_result.confidence)
        spoken = f"Das habe ich leider nicht verstanden. Meintest du vielleicht: {response.suggestions[0]}?"
        if req.speak_response:
            await speak_text(spoken)
        return ChatResponse(
            spoken_text=spoken,
            intent="unknown",
            status="unknown",
        )

    # 3. Fehlende Parameter prüfen
    clarification = handle_missing_parameters(intent_result.intent, intent_result.parameters)
    if clarification:
        if req.speak_response:
            await speak_text(clarification.question)
        return ChatResponse(
            spoken_text=clarification.question,
            intent=intent_result.intent,
            status="needs_clarification",
        )

    # 4. Bestätigung oder direkt ausführen
    from confirmation import prepare_action, execute_action, ActionPayload, ExecuteRequest

    payload = ActionPayload(
        intent=intent_result.intent,
        parameters=intent_result.parameters,
        description=_build_description(intent_result.intent, intent_result.parameters, intent_result.datetime_parsed),
        requires_confirmation=intent_result.intent in {
            "create_event", "draft_email", "draft_message",
            "create_note", "create_todo", "open_file"
        },
        datetime_parsed=intent_result.datetime_parsed,
    )

    # Wenn Bestätigung nötig und auto_execute=False → Rückfrage
    if payload.requires_confirmation and not req.auto_execute:
        spoken = _confirmation_question(intent_result.intent, intent_result.parameters, intent_result.datetime_parsed)
        if req.speak_response:
            await speak_text(spoken)
        return ChatResponse(
            spoken_text=spoken,
            intent=intent_result.intent,
            status="needs_confirmation",
            confirmation_payload=payload.model_dump(),
        )

    # 5. Aktion ausführen
    result = await execute_action(ExecuteRequest(payload=payload, approved=True))

    # 6. Natürliche Antwort formulieren
    spoken = await _generate_response(intent_result.intent, result.status, result.data, intent_result.parameters)

    if req.speak_response:
        await speak_text(spoken)

    return ChatResponse(
        spoken_text=spoken,
        intent=intent_result.intent,
        status=result.status,
        data=result.data,
    )


@router.post("/confirm", response_model=ChatResponse)
async def confirm_action(payload: dict, approved: bool = True):
    """
    Wird aufgerufen nachdem der Nutzer eine Bestätigung gegeben hat.
    """
    from confirmation import execute_action, ActionPayload, ExecuteRequest
    from tts import speak_text

    action_payload = ActionPayload(**payload)
    result = await execute_action(ExecuteRequest(payload=action_payload, approved=approved))

    if not approved:
        spoken = "Okay, ich habe die Aktion abgebrochen."
    else:
        spoken = await _generate_response(
            action_payload.intent, result.status, result.data, action_payload.parameters
        )

    await speak_text(spoken)
    return ChatResponse(
        spoken_text=spoken,
        intent=action_payload.intent,
        status=result.status,
        data=result.data,
    )


# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

def _confirmation_question(intent: str, params: dict, datetime_parsed: Optional[str]) -> str:
    """Formuliert eine natürliche Bestätigungsfrage."""
    questions = {
        "create_note": f"Soll ich eine Notiz mit dem Titel '{params.get('note_title', 'Ohne Titel')}' erstellen?",
        "create_todo": f"Soll ich '{params.get('todo_text', '')}' auf die To-do-Liste setzen?",
        "draft_email": f"Soll ich einen E-Mail-Entwurf für {params.get('recipient', '?')} erstellen?",
        "draft_message": f"Soll ich eine Nachricht an {params.get('recipient', '?')} entwerfen?",
        "create_event": f"Soll ich den Termin '{params.get('event_title', 'Neuer Termin')}' am {datetime_parsed or '?'} anlegen?",
        "open_file": f"Soll ich die Datei '{params.get('filename', '?')}' öffnen?",
    }
    return questions.get(intent, "Soll ich das wirklich tun?")


async def _generate_response(intent: str, status: str, data: Optional[dict], params: dict) -> str:
    """Formuliert eine natürliche Antwort über Claude."""
    if status == "error":
        return "Das hat leider nicht geklappt. Bitte versuch es noch einmal."

    # Kurze Template-Antworten für schnelle Reaktion
    templates = {
        "create_note": f"Erledigt. Ich habe die Notiz '{data.get('title') or 'Ohne Titel'}' gespeichert.",
        "create_todo": f"Fertig. '{data.get('text', '')}' steht jetzt auf deiner To-do-Liste.",
        "draft_email": f"Ich habe einen E-Mail-Entwurf für {data.get('recipient', '?')} erstellt. Betreff: {data.get('subject', '')}",
        "draft_message": f"Entwurf erstellt. Die Nachricht an {data.get('recipient', '?')} ist bereit zum Senden.",
        "create_event": f"Termin eingetragen.",
        "open_file": f"Wird geöffnet.",
        "search_file": "Hier sind die gefundenen Dateien.",
        "show_recent": "Hier sind deine zuletzt verwendeten Dateien.",
        "show_history": "Hier ist dein Aktionsverlauf.",
    }

    base = templates.get(intent, "Erledigt.")

    # Für wichtigere Aktionen eine leicht individuellere Antwort über Claude
    if intent in ("draft_email", "draft_message") and data:
        try:
            msg = _get_client().messages.create(
                model=CLAUDE_MODEL,
                max_tokens=80,
                system=(
                    "Du bist Voice Impulse, ein freundlicher Sprachassistent. "
                    "Formuliere eine kurze, natürliche Bestätigung auf Deutsch (1 Satz, max. 15 Wörter). "
                    "Kein 'Ich habe' am Anfang – direkt und natürlich."
                ),
                messages=[{"role": "user", "content": f"Aktion: {intent}, Empfänger: {data.get('recipient')}, Betreff: {data.get('subject')}"}],
            )
            return msg.content[0].text.strip()
        except Exception:
            return base

    return base


def _build_description(intent: str, params: dict, datetime_parsed: Optional[str]) -> str:
    descriptions = {
        "open_file": f"Datei öffnen: {params.get('filename') or params.get('path', '?')}",
        "search_file": f"Datei suchen: {params.get('filename', '?')}",
        "show_recent": "Zuletzt verwendete Dateien anzeigen",
        "create_note": f"Neue Notiz: {params.get('note_title') or 'Ohne Titel'}",
        "create_todo": f"To-do: {params.get('todo_text', '?')}",
        "draft_email": f"E-Mail-Entwurf für {params.get('recipient', '?')}",
        "draft_message": f"Nachricht an {params.get('recipient', '?')}",
        "create_event": f"Termin: {params.get('event_title', '?')} – {datetime_parsed or '?'}",
        "show_history": "Verlauf anzeigen",
        "unknown": "Unbekannte Aktion",
    }
    return descriptions.get(intent, intent)

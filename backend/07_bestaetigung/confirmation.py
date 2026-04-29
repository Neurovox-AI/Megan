import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Optional

router = APIRouter(prefix="/execute", tags=["Bestätigung"])

# Intents die immer eine Bestätigung benötigen
REQUIRES_CONFIRMATION = {
    "create_event",
    "draft_email",
    "draft_message",
    "create_note",
    "create_todo",
    "open_file",
}


class ActionPayload(BaseModel):
    intent: str
    parameters: dict
    description: str             # Lesbare Beschreibung für den Nutzer
    requires_confirmation: bool
    datetime_parsed: Optional[str] = None


class ExecuteRequest(BaseModel):
    payload: ActionPayload
    approved: bool               # True = Nutzer hat bestätigt, False = abgelehnt


class ActionResult(BaseModel):
    status: str                  # "executed" | "rejected" | "error"
    intent: str
    summary: str
    data: Optional[Any] = None


@router.post("/prepare", response_model=ActionPayload)
async def prepare_action(intent: str, parameters: dict, datetime_parsed: Optional[str] = None):
    """
    Bereitet eine Aktion vor – gibt ein Bestätigungs-Objekt zurück.
    Der Client zeigt dieses dem Nutzer an, bevor etwas ausgeführt wird.
    """
    description = _build_description(intent, parameters, datetime_parsed)
    needs_confirmation = intent in REQUIRES_CONFIRMATION

    return ActionPayload(
        intent=intent,
        parameters=parameters,
        description=description,
        requires_confirmation=needs_confirmation,
        datetime_parsed=datetime_parsed,
    )


@router.post("", response_model=ActionResult)
async def execute_action(req: ExecuteRequest):
    """
    Führt eine vorbereitete Aktion aus – NUR wenn der Nutzer bestätigt hat.
    Bei Ablehnung wird die Aktion verworfen ohne Eintrag im Verlauf.
    """
    if not req.approved:
        return ActionResult(
            status="rejected",
            intent=req.payload.intent,
            summary=f"Aktion '{req.payload.intent}' wurde vom Nutzer abgelehnt.",
        )

    result = await _dispatch(req.payload)

    # Verlauf protokollieren
    await _log_to_history(req.payload, result)

    return result


async def _dispatch(payload: ActionPayload) -> ActionResult:
    """Leitet die Aktion an das zuständige Modul weiter."""
    intent = payload.intent
    params = payload.parameters

    try:
        if intent == "open_file":
            from files import open_file, OpenFileRequest
            path = params.get("path") or params.get("filename", "")
            await open_file(OpenFileRequest(path=path))
            return ActionResult(status="executed", intent=intent, summary=f"Datei geöffnet: {path}")

        elif intent == "create_note":
            from notes import create_note, NoteCreate
            note = await create_note(NoteCreate(
                title=params.get("note_title"),
                content=params.get("note_content", ""),
            ))
            return ActionResult(status="executed", intent=intent, summary=f"Notiz erstellt: {note.title or 'Ohne Titel'}", data=note.model_dump())

        elif intent == "create_todo":
            from notes import create_todo, TodoCreate
            todo = await create_todo(TodoCreate(text=params.get("todo_text", "")))
            return ActionResult(status="executed", intent=intent, summary=f"To-do erstellt: {todo.text}", data=todo.model_dump())

        elif intent == "draft_email":
            from drafts import create_email_draft, EmailDraftCreate
            draft = await create_email_draft(EmailDraftCreate(
                recipient=params.get("recipient", ""),
                subject=params.get("subject"),
                body_instruction=params.get("body_instruction", ""),
            ))
            return ActionResult(status="executed", intent=intent, summary=f"E-Mail-Entwurf erstellt für: {draft.recipient}", data=draft.model_dump())

        elif intent == "draft_message":
            from drafts import create_message_draft, MessageDraftCreate
            draft = await create_message_draft(MessageDraftCreate(
                recipient=params.get("recipient", ""),
                body_instruction=params.get("body_instruction", ""),
            ))
            return ActionResult(status="executed", intent=intent, summary=f"Nachricht-Entwurf erstellt für: {draft.recipient}", data=draft.model_dump())

        elif intent == "create_event":
            from calendar_module import create_event, EventCreate
            if not payload.datetime_parsed:
                raise HTTPException(status_code=400, detail="Datum/Uhrzeit konnte nicht erkannt werden.")
            event = await create_event(EventCreate(
                title=params.get("event_title", "Neuer Termin"),
                datetime_iso=payload.datetime_parsed,
                duration_minutes=params.get("event_duration_minutes", 60),
                location=params.get("event_location"),
            ))
            return ActionResult(status="executed", intent=intent, summary=f"Termin angelegt: {event.title}", data=event.model_dump())

        else:
            return ActionResult(status="error", intent=intent, summary=f"Intent '{intent}' kann nicht ausgeführt werden.")

    except HTTPException as e:
        return ActionResult(status="error", intent=intent, summary=e.detail)
    except Exception as e:
        return ActionResult(status="error", intent=intent, summary=f"Fehler: {str(e)}")


def _build_description(intent: str, params: dict, datetime_parsed: Optional[str]) -> str:
    """Erzeugt eine lesbare Beschreibung der geplanten Aktion."""
    descriptions = {
        "open_file": f"Datei öffnen: {params.get('filename') or params.get('path', '?')}",
        "search_file": f"Datei suchen: {params.get('filename', '?')}",
        "show_recent": "Zuletzt verwendete Dateien anzeigen",
        "create_note": f"Neue Notiz erstellen: {params.get('note_title') or 'Ohne Titel'}",
        "append_note": f"Notiz ergänzen: {params.get('note_title', '?')}",
        "create_todo": f"To-do erstellen: {params.get('todo_text', '?')}",
        "draft_email": f"E-Mail-Entwurf für {params.get('recipient', '?')}: {params.get('body_instruction', '')}",
        "draft_message": f"Nachricht an {params.get('recipient', '?')}: {params.get('body_instruction', '')}",
        "create_event": f"Termin anlegen: {params.get('event_title', '?')} – {datetime_parsed or params.get('event_datetime_raw', '?')}",
        "show_history": "Aktionsverlauf anzeigen",
        "unknown": "Befehl unbekannt",
    }
    return descriptions.get(intent, f"Aktion: {intent}")


async def _log_to_history(payload: ActionPayload, result: ActionResult):
    """Schreibt die ausgeführte Aktion in den Verlauf."""
    try:
        from database import get_db
        async with get_db() as db:
            await db.execute(
                "INSERT INTO history (intent, parameters, result, summary) VALUES (?, ?, ?, ?)",
                (payload.intent, json.dumps(payload.parameters), result.status, result.summary),
            )
            await db.commit()
    except Exception:
        pass  # Verlauf-Fehler sollen die Hauptaktion nicht blockieren

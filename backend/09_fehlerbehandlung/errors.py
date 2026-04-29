from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional


# ─── Custom Exceptions ────────────────────────────────────────────────────────

class ClarificationNeeded(Exception):
    """Wird geworfen wenn ein notwendiger Parameter fehlt."""
    def __init__(self, missing: list[str], question: str):
        self.missing = missing
        self.question = question


class UnknownIntentError(Exception):
    """Wird geworfen wenn kein Intent erkannt wurde."""
    def __init__(self, text: str, suggestions: list[str] = None):
        self.text = text
        self.suggestions = suggestions or []


class ServiceUnavailableError(Exception):
    """Wird geworfen wenn ein externer Dienst (STT, LLM) nicht erreichbar ist."""
    def __init__(self, service: str, detail: str = ""):
        self.service = service
        self.detail = detail


# ─── Response Models ──────────────────────────────────────────────────────────

class ClarificationResponse(BaseModel):
    status: str = "needs_clarification"
    missing: list[str]
    question: str


class UnknownIntentResponse(BaseModel):
    status: str = "unknown_intent"
    original_text: str
    suggestions: list[str]
    message: str


class ErrorResponse(BaseModel):
    status: str = "error"
    code: int
    message: str
    detail: Optional[str] = None


# ─── Handler-Funktionen ───────────────────────────────────────────────────────

def handle_missing_parameters(intent: str, params: dict) -> Optional[ClarificationResponse]:
    """
    Prüft ob für einen Intent alle Pflichtparameter vorhanden sind.
    Gibt eine ClarificationResponse zurück wenn etwas fehlt, sonst None.
    """
    required = {
        "draft_email": (["recipient", "body_instruction"], "An wen soll die E-Mail gehen und was soll sie beinhalten?"),
        "draft_message": (["recipient", "body_instruction"], "An wen soll die Nachricht gehen?"),
        "create_event": (["event_title", "event_datetime_raw"], "Für wann soll der Termin sein?"),
        "create_note": (["note_content"], "Was soll in der Notiz stehen?"),
        "create_todo": (["todo_text"], "Was soll auf die To-do-Liste?"),
        "open_file": (["filename"], "Welche Datei soll geöffnet werden?"),
        "search_file": (["filename"], "Nach welcher Datei soll gesucht werden?"),
    }

    if intent not in required:
        return None

    needed_params, question = required[intent]
    missing = [p for p in needed_params if not params.get(p)]

    if not missing:
        return None

    return ClarificationResponse(missing=missing, question=question)


def handle_unknown_intent(text: str, confidence: float) -> UnknownIntentResponse:
    """
    Erstellt eine hilfreiche Fehlermeldung für unbekannte Befehle.
    Gibt Vorschläge was der Nutzer gemeint haben könnte.
    """
    suggestions = _guess_suggestions(text)
    message = (
        f"Ich habe den Befehl nicht verstanden (Konfidenz: {confidence:.0%}). "
        "Bitte formuliere ihn anders oder wähle einen Vorschlag."
    )
    return UnknownIntentResponse(
        original_text=text,
        suggestions=suggestions,
        message=message,
    )


def _guess_suggestions(text: str) -> list[str]:
    """Einfache Keyword-basierte Vorschläge."""
    text_lower = text.lower()
    suggestions = []

    if any(w in text_lower for w in ["datei", "ordner", "öffnen", "öffne", "zeig"]):
        suggestions.append("Öffne [Dateiname]")
    if any(w in text_lower for w in ["notiz", "aufschreiben", "schreib", "notiere"]):
        suggestions.append("Erstelle eine Notiz mit dem Inhalt: ...")
    if any(w in text_lower for w in ["todo", "aufgabe", "erledigen", "liste"]):
        suggestions.append("Füge zur To-do-Liste hinzu: ...")
    if any(w in text_lower for w in ["mail", "email", "nachricht", "schreib"]):
        suggestions.append("Schreib eine E-Mail an [Name]: ...")
    if any(w in text_lower for w in ["termin", "kalender", "uhr", "morgen"]):
        suggestions.append("Lege einen Termin an: [Titel] am [Datum] um [Uhrzeit]")

    if not suggestions:
        suggestions = [
            "Öffne [Dateiname]",
            "Erstelle eine Notiz: ...",
            "Lege einen Termin an: ...",
        ]

    return suggestions[:3]


# ─── FastAPI Error Handler registrieren ───────────────────────────────────────

def register_error_handlers(app: FastAPI):
    @app.exception_handler(ClarificationNeeded)
    async def clarification_handler(request: Request, exc: ClarificationNeeded):
        return JSONResponse(
            status_code=422,
            content=ClarificationResponse(missing=exc.missing, question=exc.question).dict(),
        )

    @app.exception_handler(UnknownIntentError)
    async def unknown_intent_handler(request: Request, exc: UnknownIntentError):
        return JSONResponse(
            status_code=422,
            content=handle_unknown_intent(exc.text, 0.0).dict(),
        )

    @app.exception_handler(ServiceUnavailableError)
    async def service_unavailable_handler(request: Request, exc: ServiceUnavailableError):
        return JSONResponse(
            status_code=503,
            content=ErrorResponse(
                code=503,
                message=f"Dienst nicht verfügbar: {exc.service}",
                detail=exc.detail,
            ).dict(),
        )

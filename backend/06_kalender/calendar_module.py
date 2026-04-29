import subprocess
import platform
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/calendar", tags=["Kalender"])


class EventCreate(BaseModel):
    title: str
    datetime_iso: str          # ISO-8601, z.B. "2026-04-17T14:00:00"
    duration_minutes: Optional[int] = 60
    location: Optional[str] = None


class EventOut(BaseModel):
    title: str
    datetime_iso: str
    duration_minutes: int
    location: Optional[str]
    status: str


@router.post("/event", response_model=EventOut, status_code=201)
async def create_event(event: EventCreate):
    """
    Legt einen Kalendereintrag im Standard-Kalender des Systems an.
    macOS: via AppleScript / EventKit
    """
    try:
        dt = datetime.fromisoformat(event.datetime_iso)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Ungültiges Datum: {event.datetime_iso}")

    if platform.system() == "Darwin":
        _create_event_macos(event.title, dt, event.duration_minutes or 60, event.location)
    else:
        raise HTTPException(status_code=501, detail="Kalender-Integration nur auf macOS verfügbar (Beta).")

    return EventOut(
        title=event.title,
        datetime_iso=event.datetime_iso,
        duration_minutes=event.duration_minutes or 60,
        location=event.location,
        status="created",
    )


@router.get("/events", response_model=list[EventOut])
async def get_upcoming_events():
    """
    Gibt bevorstehende Termine der nächsten 7 Tage zurück.
    macOS: via AppleScript
    """
    if platform.system() != "Darwin":
        raise HTTPException(status_code=501, detail="Kalender-Integration nur auf macOS verfügbar (Beta).")

    events = _get_events_macos()
    return events


def _create_event_macos(title: str, dt: datetime, duration: int, location: Optional[str]):
    """Erstellt einen Kalendereintrag via AppleScript."""
    end_dt = dt + timedelta(minutes=duration)

    start_str = dt.strftime("%A, %B %d, %Y at %I:%M:%S %p")
    end_str = end_dt.strftime("%A, %B %d, %Y at %I:%M:%S %p")

    location_line = f'set location of newEvent to "{location}"' if location else ""

    script = f"""
    tell application "Calendar"
        tell calendar "Kalender"
            set startDate to date "{start_str}"
            set endDate to date "{end_str}"
            set newEvent to make new event with properties {{summary:"{title}", start date:startDate, end date:endDate}}
            {location_line}
        end tell
    end tell
    """

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Kalender-Fehler: {result.stderr.strip() or 'Unbekannter Fehler'}"
            )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Kalender antwortet nicht (Timeout).")


def _get_events_macos() -> list[EventOut]:
    """Liest bevorstehende Ereignisse der nächsten 7 Tage via AppleScript."""
    script = """
    tell application "Calendar"
        set theEvents to {}
        set startDate to current date
        set endDate to startDate + (7 * days)
        repeat with c in calendars
            set evts to (every event of c whose start date >= startDate and start date <= endDate)
            repeat with e in evts
                set end of theEvents to (summary of e & "|" & (start date of e as string))
            end repeat
        end repeat
        return theEvents
    end tell
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []

        events = []
        for line in result.stdout.strip().split(", "):
            if "|" in line:
                parts = line.split("|", 1)
                events.append(EventOut(
                    title=parts[0].strip(),
                    datetime_iso=parts[1].strip(),
                    duration_minutes=60,
                    location=None,
                    status="existing",
                ))
        return events
    except Exception:
        return []

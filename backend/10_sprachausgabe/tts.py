import asyncio
import tempfile
import os
import subprocess
import edge_tts
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter(prefix="/speak", tags=["Sprachausgabe"])

# Deutsche Stimme – natürlich klingend
VOICE = "de-AT-IngridNeural"


class SpeakRequest(BaseModel):
    text: str
    play: bool = True   # True = direkt abspielen, False = Audio-Datei zurückgeben


@router.post("")
async def speak(req: SpeakRequest):
    """
    Wandelt Text in Sprache um und spielt ihn direkt ab.
    Läuft vollständig lokal über edge-tts (kein API-Key nötig).
    """
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text darf nicht leer sein.")

    audio_path = await _synthesize(req.text)

    if req.play:
        # Direkt auf dem Mac abspielen
        subprocess.Popen(["afplay", audio_path])
        return {"status": "playing", "text": req.text}
    else:
        # Audio-Datei zurückgeben (für die Desktop-App zum selbst Abspielen)
        return FileResponse(audio_path, media_type="audio/mpeg", filename="response.mp3")


@router.get("/voices")
async def list_voices():
    """Gibt alle verfügbaren deutschen Stimmen zurück."""
    voices = await edge_tts.list_voices()
    german = [v for v in voices if v["Locale"].startswith("de-")]
    return [{"name": v["ShortName"], "gender": v["Gender"]} for v in german]


async def _synthesize(text: str) -> str:
    """Synthetisiert Text zu einer MP3-Datei und gibt den Pfad zurück."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()

    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(tmp.name)

    return tmp.name


async def speak_text(text: str):
    """
    Hilfsfunktion: Spricht Text direkt aus.
    Wird vom /chat Endpunkt aufgerufen.
    """
    audio_path = await _synthesize(text)
    subprocess.Popen(["afplay", audio_path])

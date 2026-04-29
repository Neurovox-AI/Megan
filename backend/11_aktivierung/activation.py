"""
Voice Impulse – Aktivierungsmodul
Verwaltet Push-to-Talk und Wake-Word-Erkennung.

Wake Word: Läuft als Hintergrundprozess, hört in kurzen Chunks zu,
transkribiert via Whisper und prüft ob der konfigurierte Name gesagt wurde.

Push-to-Talk: Einstellungen werden hier gespeichert.
Die Desktop-App übernimmt den Tastendruck selbst (Electron global shortcut).
"""
import asyncio
import threading
import tempfile
import os
import json
import numpy as np
import sounddevice as sd
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/activation", tags=["Aktivierung"])

# ─── Konfiguration ────────────────────────────────────────────────────────────

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "..", "activation_settings.json")

DEFAULT_SETTINGS = {
    "wake_word": "hey impulse",        # Wird erkannt wenn Nutzer dies sagt
    "agent_name": "Impulse",           # Name des Agenten
    "ptt_key": "space",                # Push-to-Talk Taste (für Desktop-App)
    "wake_word_enabled": False,        # Ob Wake-Word aktiv ist
    "wake_word_sensitivity": 0.6,      # Wie genau der Match sein muss (0–1)
    "sample_rate": 16000,
    "chunk_seconds": 2,                # Länge jedes Aufnahme-Chunks in Sekunden
}


def load_settings() -> dict:
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            saved = json.load(f)
            return {**DEFAULT_SETTINGS, **saved}
    return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


# ─── Settings Endpoints ───────────────────────────────────────────────────────

class ActivationSettings(BaseModel):
    wake_word: Optional[str] = None
    agent_name: Optional[str] = None
    ptt_key: Optional[str] = None
    wake_word_enabled: Optional[bool] = None
    wake_word_sensitivity: Optional[float] = None


@router.get("/settings")
async def get_settings():
    """Gibt die aktuellen Aktivierungseinstellungen zurück."""
    return load_settings()


@router.patch("/settings")
async def update_settings(update: ActivationSettings):
    """
    Aktualisiert die Einstellungen.
    Nur gesetzte Felder werden überschrieben.

    Beispiel – Name auf Megan setzen:
    { "agent_name": "Megan", "wake_word": "hey megan" }
    """
    settings = load_settings()

    if update.agent_name is not None:
        settings["agent_name"] = update.agent_name
        # Wake-Word automatisch anpassen wenn kein eigenes gesetzt
        if update.wake_word is None:
            settings["wake_word"] = f"hey {update.agent_name.lower()}"

    if update.wake_word is not None:
        settings["wake_word"] = update.wake_word.lower()

    if update.ptt_key is not None:
        settings["ptt_key"] = update.ptt_key

    if update.wake_word_enabled is not None:
        settings["wake_word_enabled"] = update.wake_word_enabled
        if update.wake_word_enabled:
            _start_wake_word_listener(settings)
        else:
            _stop_wake_word_listener()

    if update.wake_word_sensitivity is not None:
        settings["wake_word_sensitivity"] = max(0.1, min(1.0, update.wake_word_sensitivity))

    save_settings(settings)
    return settings


@router.post("/wakeword/start")
async def start_wake_word():
    """Startet den Wake-Word-Listener."""
    settings = load_settings()
    settings["wake_word_enabled"] = True
    save_settings(settings)
    _start_wake_word_listener(settings)
    return {"status": "listening", "wake_word": settings["wake_word"]}


@router.post("/wakeword/stop")
async def stop_wake_word():
    """Stoppt den Wake-Word-Listener."""
    _stop_wake_word_listener()
    settings = load_settings()
    settings["wake_word_enabled"] = False
    save_settings(settings)
    return {"status": "stopped"}


@router.get("/wakeword/status")
async def wake_word_status():
    """Zeigt ob der Wake-Word-Listener läuft."""
    return {
        "running": _listener_thread is not None and _listener_thread.is_alive(),
        "wake_word": load_settings()["wake_word"],
    }


# ─── WebSocket für Echtzeit-Events ───────────────────────────────────────────

_connected_clients: list[WebSocket] = []


@router.websocket("/ws")
async def activation_websocket(websocket: WebSocket):
    """
    WebSocket-Verbindung für die Desktop-App.
    Sendet Events wenn Wake Word erkannt wird oder andere Aktivierungsereignisse.

    Events:
    { "event": "wake_word_detected", "word": "hey megan" }
    { "event": "listening_started" }
    { "event": "listening_stopped" }
    """
    await websocket.accept()
    _connected_clients.append(websocket)
    settings = load_settings()
    await websocket.send_json({
        "event": "connected",
        "agent_name": settings["agent_name"],
        "wake_word": settings["wake_word"],
        "ptt_key": settings["ptt_key"],
    })
    try:
        while True:
            await websocket.receive_text()  # Verbindung offen halten
    except WebSocketDisconnect:
        _connected_clients.remove(websocket)


async def _broadcast(event: dict):
    """Sendet ein Event an alle verbundenen Clients."""
    dead = []
    for ws in _connected_clients:
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connected_clients.remove(ws)


# ─── Wake Word Listener (Hintergrundthread) ───────────────────────────────────

_listener_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def _start_wake_word_listener(settings: dict):
    global _listener_thread, _stop_event

    if _listener_thread and _listener_thread.is_alive():
        return  # Läuft bereits

    _stop_event.clear()
    _listener_thread = threading.Thread(
        target=_wake_word_loop,
        args=(settings,),
        daemon=True,
        name="WakeWordListener",
    )
    _listener_thread.start()
    print(f"Wake-Word-Listener gestartet. Warte auf: '{settings['wake_word']}'")


def _stop_wake_word_listener():
    global _listener_thread
    _stop_event.set()
    _listener_thread = None
    print("Wake-Word-Listener gestoppt.")


def _wake_word_loop(settings: dict):
    """
    Hintergrundschleife:
    1. Mikrofon in 2-Sekunden-Chunks aufnehmen
    2. Mit Whisper transkribieren
    3. Prüfen ob Wake Word enthalten
    4. Bei Treffer → Event an Desktop-App senden
    """
    from faster_whisper import WhisperModel

    sample_rate = settings["sample_rate"]
    chunk_seconds = settings["chunk_seconds"]
    wake_word = settings["wake_word"].lower()
    sensitivity = settings["wake_word_sensitivity"]

    # Kleines Modell für schnelle Wake-Word-Erkennung
    try:
        model = WhisperModel("tiny", device="cpu", compute_type="int8")
    except Exception as e:
        print(f"Wake-Word-Modell konnte nicht geladen werden: {e}")
        return

    print(f"Höre zu... (Wake Word: '{wake_word}')")

    while not _stop_event.is_set():
        try:
            # Audio aufnehmen
            audio = sd.rec(
                int(chunk_seconds * sample_rate),
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                blocking=True,
            )
            audio = audio.flatten()

            # Stille überspringen
            rms = float(np.sqrt(np.mean(audio ** 2)))
            if rms < 0.005:
                continue

            # In Temp-Datei schreiben
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.close()
            _save_wav(tmp.name, audio, sample_rate)

            # Transkribieren
            segments, _ = model.transcribe(
                tmp.name,
                language="de",
                beam_size=1,
                vad_filter=True,
            )
            text = " ".join(s.text for s in segments).lower().strip()
            os.unlink(tmp.name)

            if not text:
                continue

            # Wake Word prüfen
            if _matches_wake_word(text, wake_word, sensitivity):
                print(f"Wake Word erkannt! ('{text}')")
                asyncio.run(_broadcast({
                    "event": "wake_word_detected",
                    "detected_text": text,
                    "wake_word": wake_word,
                }))

        except Exception as e:
            if not _stop_event.is_set():
                print(f"Wake-Word-Fehler: {e}")


def _matches_wake_word(transcription: str, wake_word: str, sensitivity: float) -> bool:
    """
    Prüft ob das Wake Word im transkribierten Text vorkommt.
    Erlaubt leichte Abweichungen (z.B. 'hey mega' statt 'hey megan').
    """
    # Exakter Match
    if wake_word in transcription:
        return True

    # Fuzzy Match: Wörter des Wake Words prüfen
    wake_words = wake_word.split()
    trans_words = transcription.split()

    if not wake_words:
        return False

    # Wie viel Prozent der Wake-Word-Wörter kommen vor?
    matches = sum(1 for w in wake_words if any(w in t or t in w for t in trans_words))
    score = matches / len(wake_words)

    return score >= sensitivity


def _save_wav(path: str, audio: np.ndarray, sample_rate: int):
    """Speichert numpy-Array als WAV-Datei."""
    import wave, struct
    audio_int16 = (audio * 32767).astype(np.int16)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())

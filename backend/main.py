from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from database import init_db

import sys, os
# Modulordner zum Python-Pfad hinzufügen
for folder in [
    "01_audio_transkription",
    "02_intent_engine",
    "03_dateisystem",
    "04_notizen_todos",
    "05_drafts",
    "06_kalender",
    "07_bestaetigung",
    "08_aktionsverlauf",
    "09_fehlerbehandlung",
    "10_sprachausgabe",
    "11_aktivierung",
]:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), folder))

from audio import router as audio_router
from intent import router as intent_router
from files import router as files_router
from notes import router as notes_router
from drafts import router as drafts_router
from calendar_module import router as calendar_router
from confirmation import router as confirmation_router
from history import router as history_router
from errors import register_error_handlers
from tts import router as tts_router
from chat import router as chat_router
from activation import router as activation_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Beim Start: Datenbank initialisieren
    await init_db()
    # Whisper-Modell vorladen (einmalig, damit erster Befehl sofort klappt)
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _preload_whisper)
    yield


def _preload_whisper():
    try:
        from audio import _get_model
        _get_model()
        print("Whisper-Modell geladen und bereit.")
    except Exception as e:
        print(f"Whisper-Vorladen übersprungen: {e}")


app = FastAPI(
    title="Voice Impulse Backend",
    description="Backend API für den Voice Impulse Desktop-Agenten",
    version="0.1.0-beta",
    lifespan=lifespan,
)

# CORS – erlaubt Anfragen vom Desktop-Client
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In Produktion auf die App-URL einschränken
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Alle Module einbinden
app.include_router(audio_router)
app.include_router(intent_router)
app.include_router(files_router)
app.include_router(notes_router)
app.include_router(drafts_router)
app.include_router(calendar_router)
app.include_router(confirmation_router)
app.include_router(history_router)
app.include_router(tts_router)
app.include_router(chat_router)
app.include_router(activation_router)

# Fehler-Handler registrieren
register_error_handlers(app)


@app.get("/", tags=["Status"])
async def root():
    return {"status": "ok", "product": "Voice Impulse", "version": "0.1.0-beta"}


@app.get("/health", tags=["Status"])
async def health():
    return {"status": "healthy"}

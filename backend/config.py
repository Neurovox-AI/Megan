import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Modelle
WHISPER_MODEL = "whisper-1"
CLAUDE_MODEL = "claude-sonnet-4-6"

# Dateisystem – Suchpfade (Reihenfolge = Priorität)
SEARCH_PATHS = [
    os.path.expanduser("~/Desktop"),
    os.path.expanduser("~/Downloads"),
    os.path.expanduser("~/Documents"),
    os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs"),  # iCloud
]

# Datenbank
DB_PATH = os.path.join(os.path.dirname(__file__), "voice_impulse.db")

# Verlauf
HISTORY_DEFAULT_LIMIT = 20

# Intent-Konfidenz-Schwelle
MIN_CONFIDENCE = 0.7

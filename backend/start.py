"""
Voice Impulse – Backend Starter
Wird von der Desktop-App beim Start aufgerufen.
Startet den Server und lädt das Whisper-Modell vorab.
"""
import subprocess
import sys
import os
import time
import urllib.request

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = 8000
UVICORN = os.path.join(os.path.expanduser("~"), "Library", "Python", "3.9", "bin", "uvicorn")


def is_running() -> bool:
    """Prüft ob der Server bereits läuft."""
    try:
        urllib.request.urlopen(f"http://localhost:{PORT}/health", timeout=2)
        return True
    except Exception:
        return False


def preload_whisper():
    """Whisper-Modell vorab laden damit der erste Befehl nicht verzögert wird."""
    print("Whisper-Modell wird vorbereitet...")
    try:
        sys.path.insert(0, os.path.join(BACKEND_DIR, "01_audio_transkription"))
        from audio import _get_model
        _get_model()
        print("Whisper bereit.")
    except Exception as e:
        print(f"Whisper konnte nicht vorgeladen werden: {e}")


def start():
    if is_running():
        print(f"Backend läuft bereits auf Port {PORT}.")
        return

    print("Voice Impulse Backend wird gestartet...")

    # Whisper vorladen (blockiert kurz, danach schnell)
    preload_whisper()

    # Server starten
    process = subprocess.Popen(
        [UVICORN, "main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=BACKEND_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Warten bis der Server antwortet (max. 15 Sekunden)
    for i in range(15):
        time.sleep(1)
        if is_running():
            print(f"Backend bereit auf http://localhost:{PORT}")
            return

    print("Backend konnte nicht gestartet werden.")
    process.terminate()


def stop():
    """Stoppt den laufenden Server."""
    try:
        import urllib.request
        urllib.request.urlopen(f"http://localhost:{PORT}/shutdown", timeout=2)
    except Exception:
        pass
    # Alternativ: Prozess per Port killen
    os.system(f"lsof -ti:{PORT} | xargs kill -9 2>/dev/null")
    print("Backend gestoppt.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    if cmd == "stop":
        stop()
    else:
        start()

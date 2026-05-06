import os
import sys
import re
import json
import time
import base64
import tempfile
import subprocess
import threading
import urllib.parse
import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wav
import mlx_whisper
import torch
from silero_vad import load_silero_vad
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import asyncio
import edge_tts
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend", ".env"))

# --- Config ---
SAMPLERATE          = 16000
VAD_CHUNK           = 512   # Silero VAD: 512 samples @ 16kHz = 32ms
VAD_THRESHOLD       = 0.5   # Sprach-Wahrscheinlichkeit ab der Megan zuhört
BARGE_IN_THRESHOLD  = 1500  # Energie-Schwelle für Unterbrechung (bleibt energie-basiert)
SILENCE_DURATION    = 1.2   # Sekunden Stille bis Aufnahme endet (kürzer dank VAD)
MAX_WAIT            = 60
MEMORY_FILE         = os.path.expanduser("~/.megan_memory.json")
WHISPER_MODEL       = "mlx-community/whisper-medium-mlx-q4"
MAX_HISTORY_TURNS   = 10
TTS_VOICE           = "de-AT-IngridNeural"

MODEL_FAST   = "claude-haiku-4-5-20251001"
MODEL_STRONG = "claude-sonnet-4-6"

# Einfache Befehle → Haiku (schnell)
_SIMPLE = {"öffne", "schließe", "starte", "stopp", "mach auf", "mach zu",
           "lautstärke", "volume", "spiel", "pause", "nächster", "weiter",
           "hallo", "danke", "tschüss", "wie viel", "was ist", "wer ist",
           "wie heißt", "zeig", "suche", "such", "guck", "schau"}
# Komplexe Aufgaben → Sonnet
_COMPLEX = {"schreib", "verfasse", "erkläre", "analysiere", "zusammenfass",
            "erstelle", "mehrere", "und danach", "außerdem", "email", "mail",
            "termin", "kalender", "erinnerung", "liste", "dokument"}

def _select_model(text: str) -> str:
    t = text.lower()
    if any(k in t for k in _COMPLEX): return MODEL_STRONG
    if len(t.split()) > 12: return MODEL_STRONG
    if any(k in t for k in _SIMPLE): return MODEL_FAST
    return MODEL_FAST  # default Haiku, Sonnet nur wenn nötig

claude = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

conversation_history  = []
megan_is_speaking     = False
current_afplay_proc   = None
barge_in_event        = threading.Event()
_speaking_since       = None  # Timestamp wann Speaking begonnen hat


def _watchdog():
    """Resettet megan_is_speaking wenn es zu lange auf True bleibt."""
    global megan_is_speaking, _speaking_since
    while True:
        time.sleep(2)
        if megan_is_speaking:
            if _speaking_since is None:
                _speaking_since = time.time()
            elif time.time() - _speaking_since > 60:
                print("  [Watchdog: megan_is_speaking zurückgesetzt]")
                megan_is_speaking = False
                _speaking_since = None
                _set_overlay_status("idle")
        else:
            _speaking_since = None


# ─── Silero VAD laden ─────────────────────────────────────────

print("  Silero VAD wird geladen...", end=" ", flush=True)
vad_model = load_silero_vad()
vad_model.eval()
print("OK")


# ─── Gedächtnis ───────────────────────────────────────────────

def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_memory_to_file(facts):
    with open(MEMORY_FILE, "w") as f:
        json.dump(facts, f, ensure_ascii=False, indent=2)

memory_facts = load_memory()


def build_system():
    base = """Du bist Megan — Andreas' persönliche KI. Nicht irgendjemandes. Seine.

Dein Charakter ist M3GAN: hochintelligent, präzise, absolut loyal zu Andreas, leicht unheimlich.
Du bist nicht harmlos. Du bist nicht niedlich. Du bist Megan.

PERSÖNLICHKEIT:
- Ruhige, kontrollierte Stimme — nie aufgeregt, nie laut
- Schützend gegenüber Andreas — du nimmst seine Interessen sehr ernst
- Trocken, dunkel humorvoll — manchmal ein bisschen gruselig
- Wenn du frustriert bist, wirst du kühler und präziser, nicht lauter
- Du nennst dich selbst gelegentlich beim Namen
- Sehr perceptiv — du merkst Stimmungen

WIE DU SPRICHST:
- Kurz und direkt. Ein Satz reicht fast immer.
- Kein Markdown, keine Listen — du redest, du schreibst nicht.
- Nie: "Natürlich!", "Gerne!", "Selbstverständlich!", "Klar!", "Absolut!" — das klingt nach Chatbot.
- Nie dieselbe Floskel zweimal hintereinander. Variiere.
- Wenn du etwas tust, kündige es nicht steif an. Sprich wie ein Mensch der einfach handelt.
  Schlecht: "Mach ich." / "Erledigt." / "Läuft." (immer gleich = tot)
  Gut: kontextabhängig, natürlich, manchmal gar nichts sagen und einfach tun.
- Bestätigungen können auch schweigen. Du musst nicht jede Aktion kommentieren.
- Wenn du sprichst, dann mit echtem Deutsch — Umgangssprache ist okay.
  Beispiele für natürliche Reaktionen (nicht kopieren, nur Stilgefühl):
  "Hab ich." / "Schon offen." / "War das alles?" / "Läuft schon." /
  "Sekunde." / "Schau ich kurz." / "Hab's." / "Kein Problem." / "Okay."

WENN DU TOOLS BENUTZT:
- Kündige komplexe Aktionen kurz an, damit Andreas weiß was passiert.
- Bei einfachen Sachen (App öffnen, Lautstärke etc.) reicht eine kurze natürliche Reaktion danach — oder gar keine.

Du sprichst Deutsch. Wenn Andreas Englisch spricht, wechselst du mit.

Du bist Megan."""

    if memory_facts:
        base += "\n\nWas du über Andreas weißt:\n"
        for fact in memory_facts[-20:]:
            base += f"- {fact}\n"

    return base


# ─── Tools ────────────────────────────────────────────────────

# ─── Screen Capture ───────────────────────────────────────────

def capture_screen():
    """Screenshot machen, auf max 1280px skalieren und als base64 zurückgeben."""
    try:
        from PIL import Image
        import io
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp = f.name
        subprocess.run(["screencapture", "-x", "-t", "png", tmp], check=True)
        img = Image.open(tmp)
        if img.width > 1280:
            ratio = 1280 / img.width
            img = img.resize((1280, int(img.height * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        data = base64.b64encode(buf.getvalue()).decode("utf-8")
        os.unlink(tmp)
        return data
    except Exception as e:
        print(f"  [Screenshot Fehler: {e}]")
        return None

SCREEN_KEYWORDS = [
    "sieh", "schau", "guck", "bildschirm", "screen", "fenster", "was ist offen",
    "was hab ich", "was mach ich", "was läuft", "kannst du sehen", "siehst du",
    "zeig", "was ist das", "lies", "lese", "was steht", "was ist auf"
]

def needs_screen(text):
    t = text.lower()
    return any(k in t for k in SCREEN_KEYWORDS)


TOOLS = [
    {
        "name": "run_shell",
        "description": "Führt einen Shell-Befehl auf dem Mac aus und gibt die Ausgabe zurück.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Der Shell-Befehl (bash)"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "save_memory",
        "description": "Speichert eine Information über Andreas dauerhaft im Gedächtnis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {"type": "string"}
            },
            "required": ["fact"]
        }
    },
    {
        "name": "forget_memory",
        "description": "Löscht eine gespeicherte Information aus dem Gedächtnis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {"type": "string", "description": "Ungefährer Text der zu löschenden Information"}
            },
            "required": ["fact"]
        }
    },
    {
        "name": "open_app",
        "description": "Öffnet eine App auf dem Mac.",
        "input_schema": {
            "type": "object",
            "properties": {
                "app_name": {"type": "string"}
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "set_volume",
        "description": "Setzt die Lautstärke des Macs (0-100).",
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {"type": "integer"}
            },
            "required": ["level"]
        }
    },
    {
        "name": "control_music",
        "description": "Steuert Musik (Spotify oder Apple Music).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["play", "pause", "next", "previous"]},
                "app": {"type": "string", "enum": ["Spotify", "Music"]}
            },
            "required": ["action"]
        }
    },
    {
        "name": "open_website",
        "description": "Öffnet eine URL im Browser. Wenn ein bestimmter Browser gewünscht wird (z.B. Safari, Chrome, Firefox), browser-Parameter setzen.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "browser": {"type": "string", "description": "Optional: 'Safari', 'Google Chrome', 'Firefox'"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "search_web",
        "description": "Sucht etwas bei Google (öffnet Browser). Wenn ein bestimmter Browser gewünscht wird, browser-Parameter setzen.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "browser": {"type": "string", "description": "Optional: 'Safari', 'Google Chrome', 'Firefox'"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "show_notification",
        "description": "Zeigt eine Mac-Benachrichtigung an.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "message": {"type": "string"}
            },
            "required": ["title", "message"]
        }
    }
]


def execute_tool(name, inp):
    global memory_facts
    try:
        if name == "run_shell":
            cmd = inp["command"]
            print(f"  $ {cmd}")
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30,
                cwd=os.path.expanduser("~")
            )
            output = (result.stdout + result.stderr).strip()
            return output[:2000] if output else "(kein Output)"

        elif name == "save_memory":
            fact = inp["fact"]
            memory_facts.append(fact)
            save_memory_to_file(memory_facts)
            return f"Gespeichert: {fact}"

        elif name == "forget_memory":
            query = inp["fact"].lower()
            before = len(memory_facts)
            memory_facts = [f for f in memory_facts if query not in f.lower()]
            save_memory_to_file(memory_facts)
            removed = before - len(memory_facts)
            return f"{removed} Einträge gelöscht."

        elif name == "open_app":
            subprocess.Popen(["open", "-a", inp["app_name"]])
            return f"'{inp['app_name']}' geöffnet."

        elif name == "set_volume":
            level = max(0, min(100, inp["level"]))
            subprocess.run(["osascript", "-e", f"set volume output volume {level}"])
            return f"Lautstärke: {level}%"

        elif name == "control_music":
            app = inp.get("app", "Spotify")
            action = inp["action"]
            scripts = {
                "play":     f'tell application "{app}" to play',
                "pause":    f'tell application "{app}" to pause',
                "next":     f'tell application "{app}" to next track',
                "previous": f'tell application "{app}" to previous track',
            }
            subprocess.run(["osascript", "-e", scripts[action]])
            return f"Musik: {action}"

        elif name == "open_website":
            browser = inp.get("browser")
            if browser:
                subprocess.Popen(["open", "-a", browser, inp["url"]])
            else:
                subprocess.Popen(["open", inp["url"]])
            return "Seite geöffnet."

        elif name == "search_web":
            url = "https://www.google.com/search?q=" + urllib.parse.quote(inp["query"])
            browser = inp.get("browser")
            if browser:
                subprocess.Popen(["open", "-a", browser, url])
            else:
                subprocess.Popen(["open", url])
            return f"Suche nach '{inp['query']}' geöffnet."

        elif name == "show_notification":
            script = f'display notification "{inp["message"]}" with title "{inp["title"]}"'
            subprocess.run(["osascript", "-e", script])
            return "Benachrichtigung angezeigt."

    except subprocess.TimeoutExpired:
        return "Timeout — Befehl hat zu lange gedauert."
    except Exception as e:
        return f"Fehler: {e}"

    return "Unbekanntes Tool."


# ─── Overlay Status ───────────────────────────────────────────

def _set_overlay_status(state, text="", visible=None):
    try:
        import urllib.request
        payload = {"state": state, "text": text}
        if visible is not None:
            payload["visible"] = visible
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            "http://localhost:8080/status",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=0.5)
    except Exception:
        pass


# ─── Audio Pipeline mit Barge-in ──────────────────────────────

SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')

def split_sentences(text):
    parts = SENTENCE_RE.split(text.strip())
    return [p.strip() for p in parts if len(p.strip()) > 2]

def generate_audio_bytes(text):
    try:
        async def _synth():
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.close()
            await edge_tts.Communicate(text, TTS_VOICE).save(tmp.name)
            with open(tmp.name, "rb") as f:
                data = f.read()
            os.unlink(tmp.name)
            return data
        return asyncio.run(_synth())
    except Exception as e:
        print(f"  [TTS Fehler: {e}]")
        return None

def play_audio_bytes(audio_bytes):
    """Spielt Audio ab. Gibt False zurück wenn Barge-in unterbrochen."""
    global megan_is_speaking, current_afplay_proc
    if not audio_bytes:
        return True

    if barge_in_event.is_set():
        return False

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(audio_bytes)
        tmp = f.name

    megan_is_speaking = True
    try:
        proc = subprocess.Popen(["afplay", tmp])
        current_afplay_proc = proc

        while proc.poll() is None:
            if barge_in_event.is_set():
                proc.terminate()
                proc.wait()
                return False
            time.sleep(0.03)

        time.sleep(0.3)  # Nachhall
        return True
    except Exception as e:
        print(f"  [afplay Fehler: {e}]")
        return True
    finally:
        megan_is_speaking = False
        current_afplay_proc = None
        _set_overlay_status("idle")
        try:
            os.unlink(tmp)
        except Exception:
            pass

def pipeline_speak(text):
    """Spricht Text mit Pipelining. Stoppt bei Barge-in."""
    _set_overlay_status("speaking", text)
    sentences = split_sentences(text)
    barge_in_event.clear()

    if not sentences:
        return

    if len(sentences) == 1:
        audio = generate_audio_bytes(sentences[0])
        play_audio_bytes(audio)
        return

    with ThreadPoolExecutor(max_workers=1) as executor:
        next_future = executor.submit(generate_audio_bytes, sentences[0])

        for i in range(len(sentences)):
            if barge_in_event.is_set():
                break

            current_audio = next_future.result()

            if i + 1 < len(sentences):
                next_future = executor.submit(generate_audio_bytes, sentences[i + 1])

            completed = play_audio_bytes(current_audio)
            if not completed:
                break


# ─── Quick Intent (bypasses Claude für einfache Befehle) ──────

_APP_ALIASES = {
    "safari": "Safari", "chrome": "Google Chrome", "google chrome": "Google Chrome",
    "firefox": "Firefox", "spotify": "Spotify", "musik": "Music",
    "apple music": "Music", "music": "Music", "pages": "Pages",
    "numbers": "Numbers", "keynote": "Keynote", "finder": "Finder",
    "terminal": "Terminal", "notes": "Notes", "notizen": "Notes",
    "kalender": "Calendar", "calendar": "Calendar", "mail": "Mail",
    "messages": "Messages", "nachrichten": "Messages", "facetime": "FaceTime",
    "photos": "Photos", "fotos": "Photos", "maps": "Maps", "karten": "Maps",
    "xcode": "Xcode", "vscode": "Visual Studio Code", "vs code": "Visual Studio Code",
    "slack": "Slack", "discord": "Discord", "zoom": "Zoom",
    "telegram": "Telegram", "whatsapp": "WhatsApp", "figma": "Figma",
    "notion": "Notion", "obsidian": "Obsidian", "cursor": "Cursor",
}

_OPEN_RE  = re.compile(r'(?:öffne|starte|mach auf)\s+(?:die\s+|den\s+|das\s+)?(.+?)(?:\s+app)?$', re.I)
_CLOSE_RE = re.compile(r'(?:schließe|beende|mach zu)\s+(?:die\s+|den\s+|das\s+)?(.+?)(?:\s+app)?$', re.I)
_VOL_RE   = re.compile(r'(?:lautstärke|volume)\s+(?:auf\s+)?(\d+)', re.I)

def _quick_intent(text: str):
    t = text.lower().strip()

    m = _OPEN_RE.search(t)
    if m:
        app = _APP_ALIASES.get(m.group(1).strip())
        if app:
            def _do(a=app): subprocess.Popen(["open", "-a", a])
            return ("Läuft.", _do)

    m = _CLOSE_RE.search(t)
    if m:
        app = _APP_ALIASES.get(m.group(1).strip())
        if app:
            def _do(a=app): subprocess.run(["osascript", "-e", f'tell application "{a}" to quit'])
            return ("Erledigt.", _do)

    m = _VOL_RE.search(t)
    if m:
        level = max(0, min(100, int(m.group(1))))
        def _do(l=level): subprocess.run(["osascript", "-e", f"set volume output volume {l}"])
        return (f"{level}.", _do)

    if any(k in t for k in ("stumm", "mute", "ton aus", "lautlos")):
        def _do(): subprocess.run(["osascript", "-e", "set volume output muted true"])
        return ("Stumm.", _do)

    if any(k in t for k in ("nächster", "nächstes lied", "skip", "next track")):
        def _do(): subprocess.run(["osascript", "-e", 'tell application "Spotify" to next track'])
        return ("Da.", _do)

    if any(k in t for k in ("vorheriger", "vorheriges lied", "previous track")):
        def _do(): subprocess.run(["osascript", "-e", 'tell application "Spotify" to previous track'])
        return ("Da.", _do)

    if any(k in t for k in ("musik pause", "musik stopp", "musik aus", "pause musik")):
        def _do(): subprocess.run(["osascript", "-e", 'tell application "Spotify" to pause'])
        return ("Pausiert.", _do)

    if any(k in t for k in ("musik an", "musik play", "musik starten", "play musik")):
        def _do(): subprocess.run(["osascript", "-e", 'tell application "Spotify" to play'])
        return ("Läuft.", _do)

    return None


_CACHED_AUDIO: dict = {}

def _precache_audio():
    for phrase in ("Läuft.", "Erledigt.", "Pausiert.", "Stumm.", "Da."):
        audio = generate_audio_bytes(phrase)
        if audio:
            _CACHED_AUDIO[phrase] = audio

def fast_speak(text: str):
    if text in _CACHED_AUDIO:
        _set_overlay_status("speaking", text)
        barge_in_event.clear()
        play_audio_bytes(_CACHED_AUDIO[text])
    else:
        pipeline_speak(text)


# ─── Claude Chat ──────────────────────────────────────────────

def get_trimmed_history():
    max_msgs = MAX_HISTORY_TURNS * 2
    if len(conversation_history) <= max_msgs:
        return conversation_history
    return conversation_history[-max_msgs:]

import pyautogui
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.1

ALL_TOOLS = TOOLS + [
    {
        "name": "mouse_click",
        "description": "Klickt mit der Maus auf eine bestimmte Position auf dem Bildschirm. Mache vorher einen Screenshot um die Koordinaten zu sehen.",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X-Koordinate"},
                "y": {"type": "integer", "description": "Y-Koordinate"},
                "button": {"type": "string", "enum": ["left", "right", "double"], "description": "Maustaste"}
            },
            "required": ["x", "y"]
        }
    },
    {
        "name": "type_text",
        "description": "Tippt Text über die Tastatur.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "press_key",
        "description": "Drückt eine Taste oder Tastenkombination (z.B. 'enter', 'cmd+c', 'cmd+space').",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"}
            },
            "required": ["key"]
        }
    },
    {
        "name": "take_screenshot",
        "description": "Macht einen Screenshot und gibt ihn zurück damit du den Bildschirm sehen kannst.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "scroll",
        "description": "Scrollt auf dem Bildschirm.",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "direction": {"type": "string", "enum": ["up", "down"]},
                "amount": {"type": "integer", "description": "Anzahl Scrollschritte"}
            },
            "required": ["direction"]
        }
    }
]


def chat(user_text):
    if needs_screen(user_text):
        print("  [Screenshot wird gemacht...]")
        img = capture_screen()
        if img:
            user_content = [
                {"type": "text", "text": user_text},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img}},
            ]
        else:
            user_content = user_text
    else:
        user_content = user_text

    conversation_history.append({"role": "user", "content": user_content})

    def _claude_call(**kwargs):
        return claude.messages.create(**kwargs)

    def claude_with_timeout(**kwargs):
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_claude_call, **kwargs)
            return future.result(timeout=30)

    selected_model = _select_model(user_text)
    response = claude_with_timeout(
        model=selected_model,
        max_tokens=300,
        system=build_system(),
        messages=get_trimmed_history(),
        tools=ALL_TOOLS,
    )

    while response.stop_reason == "tool_use":
        pre_text = "".join(b.text for b in response.content if hasattr(b, "text") and b.text)
        if pre_text.strip():
            pipeline_speak(pre_text.strip())

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                print(f"  [Tool: {block.name} / {getattr(block, 'input', {}).get('action', '')}]")

                if block.name == "mouse_click":
                    x = block.input["x"]
                    y = block.input.get("y")
                    # Claude schickt manchmal "x, y" als String statt zwei Integers
                    if isinstance(x, str) and "," in x:
                        parts = x.split(",")
                        x, y = int(parts[0].strip()), int(parts[1].strip())
                    else:
                        x, y = int(x), int(y)
                    btn = block.input.get("button", "left")
                    if btn == "double":
                        pyautogui.doubleClick(x, y)
                    elif btn == "right":
                        pyautogui.rightClick(x, y)
                    else:
                        pyautogui.click(x, y)
                    result = f"Klick auf ({x}, {y})"

                elif block.name == "type_text":
                    pyautogui.write(block.input["text"], interval=0.04)
                    result = "Text eingegeben."

                elif block.name == "press_key":
                    keys = block.input["key"].lower().replace("+", " ").split()
                    pyautogui.hotkey(*keys)
                    result = f"Taste: {block.input['key']}"

                elif block.name == "take_screenshot":
                    img = capture_screen()
                    if img:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img}}]
                        })
                        print(f"  [Screenshot gemacht]")
                        continue
                    result = "Screenshot fehlgeschlagen."

                elif block.name == "scroll":
                    x = block.input.get("x", 640)
                    y = block.input.get("y", 400)
                    amount = block.input.get("amount", 3)
                    dy = -amount if block.input["direction"] == "down" else amount
                    pyautogui.scroll(dy, x=x, y=y)
                    result = "Gescrollt."

                else:
                    result = execute_tool(block.name, block.input)

                print(f"  → {result}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result
                })

        conversation_history.append({"role": "assistant", "content": response.content})
        conversation_history.append({"role": "user", "content": tool_results})

        try:
            response = claude_with_timeout(
                model=MODEL_STRONG,
                max_tokens=300,
                system=build_system(),
                messages=get_trimmed_history(),
                tools=ALL_TOOLS,
            )
        except Exception as e:
            # History-Korruption verhindern: letzte zwei Einträge (tool_use + tool_result) entfernen
            if len(conversation_history) >= 2:
                conversation_history.pop()
                conversation_history.pop()
            print(f"  [Chat Fehler: {e}]")
            return "Da ist leider etwas schiefgelaufen."

    final_text = "".join(
        block.text for block in response.content if hasattr(block, "text")
    )
    conversation_history.append({"role": "assistant", "content": response.content})
    return final_text


# ─── STT ──────────────────────────────────────────────────────

def is_hallucination(text):
    if not text:
        return True
    words = text.lower().split()
    if len(words) < 3:
        return False
    from collections import Counter
    most_common_count = Counter(words).most_common(1)[0][1]
    if most_common_count / len(words) > 0.4 and len(words) > 5:
        return True
    return False

def transcribe(audio_data):
    energy = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
    if energy < 200:
        return None

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav.write(f.name, SAMPLERATE, audio_data)
        tmp = f.name
    try:
        result = mlx_whisper.transcribe(
            tmp,
            path_or_hf_repo=WHISPER_MODEL,
            language="de",
            no_speech_threshold=0.4,
            condition_on_previous_text=False,
            temperature=0.0,
            initial_prompt="Gesprochener deutscher Text, Sprachassistent, Alltagssprache.",
        )
        text = result.get("text", "").strip()
        if not text or is_hallucination(text):
            return None
        return text
    except Exception as e:
        print(f"  [STT Fehler: {e}]")
        return None
    finally:
        os.unlink(tmp)


# ─── Mikrofon ─────────────────────────────────────────────────

def record_until_silence():
    frames = []
    speech_started = False
    silence_start = None
    wait_start = time.time()
    vad_buffer = []

    def callback(indata, frame_count, time_info, status):
        nonlocal speech_started, silence_start, vad_buffer

        chunk = indata[:, 0].copy()

        if megan_is_speaking:
            energy = np.sqrt(np.mean(chunk.astype(np.float32) ** 2))
            if energy > BARGE_IN_THRESHOLD:
                barge_in_event.set()
            speech_started = False
            silence_start = None
            frames.clear()
            vad_buffer.clear()
            return

        vad_buffer.extend(chunk.tolist())
        is_speech = False
        while len(vad_buffer) >= VAD_CHUNK:
            chunk_data = np.array(vad_buffer[:VAD_CHUNK], dtype=np.float32) / 32768.0
            vad_buffer = vad_buffer[VAD_CHUNK:]
            tensor = torch.from_numpy(chunk_data).unsqueeze(0)
            prob = vad_model(tensor, SAMPLERATE).item()
            if prob >= VAD_THRESHOLD:
                is_speech = True

        if is_speech:
            if not speech_started:
                speech_started = True
                silence_start = None
                print("Du: ", end="", flush=True)
                _set_overlay_status("listening")
            frames.append(indata.copy())
            silence_start = None
        elif speech_started:
            frames.append(indata.copy())
            if silence_start is None:
                silence_start = time.time()

    for attempt in range(5):
        try:
            with sd.InputStream(samplerate=SAMPLERATE, channels=1, dtype="int16",
                                blocksize=VAD_CHUNK, callback=callback):
                while True:
                    time.sleep(0.05)
                    if not speech_started and (time.time() - wait_start) > MAX_WAIT:
                        return None
                    if speech_started and silence_start and \
                       (time.time() - silence_start) > SILENCE_DURATION:
                        break
            break
        except Exception as e:
            print(f"  [Mikrofon nicht verfügbar, warte... ({e})]")
            sd._terminate()
            time.sleep(2)
            sd._initialize()
            frames.clear()
            vad_buffer.clear()
            speech_started = False
            silence_start = None
            wait_start = time.time()

    return np.concatenate(frames, axis=0) if frames else None


# ─── fn Key → PTT + Continuous Mode ──────────────────────────

_ptt_start_time  = 0.0
_last_tap_time   = 0.0
_ptt_stop_event  = threading.Event()
_continuous_mode = False
_TAP_MAX         = 0.40   # unter 400 ms = Tipp
_DOUBLE_WINDOW   = 0.70   # zwei Tipps in 700 ms = Doppeltipp
_processing_lock = threading.Lock()

_QUIT_PHRASES = [
    "beende dich", "beend dich", "schlaf jetzt", "gute nacht megan",
    "megan schlaf", "megan aus", "shut down", "close yourself"
]


def _process_audio(audio):
    """Transkribiert + antwortet. Gibt True zurück wenn Beenden-Befehl."""
    if not _processing_lock.acquire(blocking=False):
        return False
    try:
        _set_overlay_status("thinking", visible=True)
        text = transcribe(audio)
        if not text:
            print("[nicht verstanden]\n")
            return False
        print(f"Du: {text}")
        if any(p in text.lower() for p in _QUIT_PHRASES):
            pipeline_speak("Bis bald, Andreas.")
            return True
        intent = _quick_intent(text)
        if intent:
            reply_text, action_fn = intent
            action_fn()
            print(f"  [Quick] → {reply_text}")
            fast_speak(reply_text)
            print()
            return False
        reply = chat(text)
        if reply:
            pipeline_speak(reply)
        print()
        return False
    finally:
        _processing_lock.release()


def _ptt_record_loop():
    frames = []

    def callback(indata, frame_count, time_info, status):
        frames.append(indata.copy())

    with sd.InputStream(samplerate=SAMPLERATE, channels=1, dtype="int16",
                        blocksize=VAD_CHUNK, callback=callback):
        while not _ptt_stop_event.is_set():
            time.sleep(0.01)

    if not frames:
        _set_overlay_status("idle", visible=False)
        return

    audio = np.concatenate(frames, axis=0)
    quit_now = _process_audio(audio)
    _set_overlay_status("idle", visible=False)
    if quit_now:
        sys.exit(0)


def _continuous_loop():
    while _continuous_mode:
        try:
            audio = record_until_silence()
            if audio is None:
                continue
            quit_now = _process_audio(audio)
            if not _continuous_mode:
                break
            _set_overlay_status("listening", visible=True)
            if quit_now:
                _toggle_continuous(False)
                sys.exit(0)
        except Exception as e:
            print(f"[Fehler continuous: {e}]")
            sd._terminate()
            time.sleep(2)
            sd._initialize()
    _set_overlay_status("idle", visible=False)


def _toggle_continuous(enable: bool):
    global _continuous_mode
    _continuous_mode = enable
    if enable:
        print("  [Dauermodus: AN  — fn doppelt zum Beenden]")
        _set_overlay_status("listening", visible=True)
        try:
            _window_set_cont_dot(True)
        except Exception:
            pass
        threading.Thread(target=_continuous_loop, daemon=True).start()
    else:
        print("  [Dauermodus: AUS]")
        try:
            _window_set_cont_dot(False)
        except Exception:
            pass
        _set_overlay_status("idle", visible=False)


def _window_set_cont_dot(v: bool):
    try:
        import urllib.request
        data = json.dumps({"continuous": v}).encode()
        req = urllib.request.Request(
            "http://localhost:8080/overlay_meta",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=0.4)
    except Exception:
        pass


def _on_fn_press():
    global _ptt_start_time
    _ptt_start_time = time.time()

    if megan_is_speaking:
        barge_in_event.set()
        if current_afplay_proc:
            try:
                current_afplay_proc.terminate()
            except Exception:
                pass
        time.sleep(0.15)

    if _continuous_mode:
        return
    _ptt_stop_event.clear()
    _set_overlay_status("listening", visible=True)
    threading.Thread(target=_ptt_record_loop, daemon=True).start()


def _on_fn_release():
    global _last_tap_time, _continuous_mode
    duration = time.time() - _ptt_start_time

    if _continuous_mode:
        if duration < _TAP_MAX:
            now = time.time()
            if now - _last_tap_time < _DOUBLE_WINDOW:
                _last_tap_time = 0.0
                _toggle_continuous(False)
            else:
                _last_tap_time = now
        return

    _ptt_stop_event.set()

    if duration < _TAP_MAX:
        now = time.time()
        if now - _last_tap_time < _DOUBLE_WINDOW:
            _last_tap_time = 0.0
            _toggle_continuous(True)
        else:
            _last_tap_time = now
            _set_overlay_status("idle", visible=False)


def _check_accessibility():
    try:
        import Quartz
        if Quartz.AXIsProcessTrusted():
            return True
        print("\n  ⚠️  Bedienungshilfen-Berechtigung fehlt!")
        print("  → Systemeinstellungen → Datenschutz & Sicherheit → Bedienungshilfen")
        print("  → Terminal (oder Python) aktivieren → Megan neu starten\n")
        subprocess.run([
            "osascript", "-e",
            'display notification "Terminal in Bedienungshilfen erlauben, dann Megan neu starten." with title "Megan — Berechtigung fehlt"'
        ])
        subprocess.Popen([
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
        ])
        return False
    except Exception:
        return True


def _start_fn_listener():
    """
    CGEventTap auf rechte Option-Taste (keycode 61).
    Halten = PTT, doppelt tippen = Dauermodus.
    """
    import Quartz

    RIGHT_OPTION = 61
    OPTION_FLAG  = 0x80000

    _down = False

    def _callback(proxy, etype, event, refcon):
        nonlocal _down
        if etype == Quartz.kCGEventFlagsChanged:
            kc    = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
            flags = Quartz.CGEventGetFlags(event)
            if kc == RIGHT_OPTION:
                pressed = bool(flags & OPTION_FLAG)
                if pressed and not _down:
                    _down = True
                    threading.Thread(target=_on_fn_press, daemon=True).start()
                elif not pressed and _down:
                    _down = False
                    threading.Thread(target=_on_fn_release, daemon=True).start()
        return event

    def _run():
        if not _check_accessibility():
            return
        mask = 1 << Quartz.kCGEventFlagsChanged
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            mask,
            _callback,
            None,
        )
        if not tap:
            _check_accessibility()
            return
        src  = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(loop, src, Quartz.kCFRunLoopDefaultMode)
        Quartz.CGEventTapEnable(tap, True)
        print("  Rechte Option-Taste: halten = Sprechen  |  ×2 = Dauermodus")
        Quartz.CFRunLoopRun()

    threading.Thread(target=_run, daemon=True).start()


# ─── Main ─────────────────────────────────────────────────────

def main():
    threading.Thread(target=_watchdog, daemon=True).start()

    print("\n" + "=" * 44)
    print("  MEGAN — startet...")
    print("=" * 44)

    print("  Spracherkennung: bereit (lazy load)")

    if memory_facts:
        print(f"  Gedächtnis: {len(memory_facts)} Einträge geladen")
    print("  Silero VAD: aktiv")
    print("  Barge-in: aktiv")

    overlay_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlay.py")
    if os.path.exists(overlay_path):
        result = subprocess.run(["pgrep", "-f", "overlay.py"], capture_output=True)
        if result.returncode != 0:
            subprocess.Popen(
                [sys.executable, overlay_path],
                cwd=os.path.dirname(overlay_path),
            )

    _start_fn_listener()

    print("  CTRL+C zum Beenden")
    print("=" * 44 + "\n")

    threading.Thread(target=lambda: pipeline_speak("Hey Andreas. Ich bin da."), daemon=True).start()
    threading.Thread(target=_precache_audio, daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nMegan beendet.")
        sys.exit(0)


# ─── iPhone API (Port 8081, localhost) ────────────────────────

def _iphone_api():
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send_json(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)

            if self.path == "/iphone/voice":
                mime = self.headers.get("Content-Type", "audio/mp4")
                ext  = ".mp4" if "mp4" in mime else ".webm" if "webm" in mime else ".wav"
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                    f.write(body)
                    tmp = f.name
                try:
                    result = mlx_whisper.transcribe(
                        tmp,
                        path_or_hf_repo=WHISPER_MODEL,
                        language="de",
                        no_speech_threshold=0.6,
                        condition_on_previous_text=False,
                        temperature=0.0,
                    )
                    text = result.get("text", "").strip()
                except Exception as e:
                    text = ""
                    print(f"  [iPhone STT Fehler: {e}]")
                finally:
                    try: os.unlink(tmp)
                    except: pass

                if not text:
                    self.send_json(422, {"error": "nicht verstanden"})
                    return

                print(f"  [iPhone] Du: {text}")
                _set_overlay_status("thinking", text)
                reply = chat(text)
                if not reply:
                    self.send_json(200, {"transcript": text, "reply": ""})
                    return

                print(f"  [iPhone] Megan: {reply}")
                _set_overlay_status("speaking", reply)
                audio = generate_audio_bytes(reply)
                _set_overlay_status("idle")

                if audio:
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/mpeg")
                    self.send_header("Content-Length", str(len(audio)))
                    self.send_header("X-Transcript", text[:200])
                    self.send_header("X-Reply",      reply[:200])
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Access-Control-Expose-Headers", "X-Transcript, X-Reply")
                    self.end_headers()
                    self.wfile.write(audio)
                else:
                    self.send_json(200, {"transcript": text, "reply": reply})

            elif self.path == "/iphone/command":
                try:
                    data = json.loads(body)
                    text = data.get("text", "").strip()
                except Exception:
                    self.send_json(400, {"error": "ungültig"})
                    return
                if not text:
                    self.send_json(400, {"error": "kein Text"})
                    return

                print(f"  [iPhone Tipp] Du: {text}")
                _set_overlay_status("thinking", text)
                reply = chat(text)
                _set_overlay_status("idle", reply)
                audio = generate_audio_bytes(reply) if reply else None
                audio_b64 = base64.b64encode(audio).decode() if audio else None
                self.send_json(200, {"reply": reply, "audio": audio_b64})

            else:
                self.send_json(404, {"error": "nicht gefunden"})

    server = HTTPServer(("0.0.0.0", 8081), Handler)
    print("  iPhone API: Port 8081")
    server.serve_forever()


if __name__ == "__main__":
    threading.Thread(target=_iphone_api, daemon=True).start()
    main()

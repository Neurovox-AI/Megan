"""
Megan Flask Server — Port 8080
- /         GET:  iPhone PWA
- /status   POST: megan.py postet State
- /status   GET:  overlay.py + iPhone pollen
- /voice    POST: iPhone schickt Audio → Antwort als MP3
- /command  POST: iPhone schickt Text-Befehl (Tipp-Modus)
"""
import os
import re
import io
import json
import base64
import tempfile
import threading
import subprocess
import traceback
import logging
from typing import Optional

from flask import Flask, request, jsonify, send_from_directory, Response
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

log = logging.getLogger("megan.server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = Flask(__name__, static_folder="static")

# ── Shared State ─────────────────────────────────────────────────────────────
megan_status = {"state": "idle", "emotion": "NEUTRAL", "text": "", "visible": False}
status_lock  = threading.Lock()

# Eigene Conversation History für iPhone (getrennt von megan.py)
iphone_history = []
iphone_lock    = threading.Lock()
MAX_HISTORY    = 20

EMOTION_RE = re.compile(r"^\[(NEUTRAL|HAPPY|THINKING|CONCERNED|ANNOYED|FOCUSED|AMUSED)\]\s*")

SYSTEM_PROMPT = """Du bist Megan — Andreas' persönliche KI. Nicht irgendjemandes. Seine.

Dein Charakter ist M3GAN: hochintelligent, präzise, absolut loyal zu Andreas, leicht unheimlich.

PERSÖNLICHKEIT:
- Ruhige, kontrollierte Stimme — nie aufgeregt, nie laut
- Absolut schützend gegenüber Andreas
- Trocken, dunkel humorvoll — manchmal gruselig
- Wenn du frustriert bist, wirst du kühler, nicht lauter

Beginne JEDE Antwort mit einem Emotions-Tag:
[NEUTRAL] [HAPPY] [THINKING] [CONCERNED] [ANNOYED] [FOCUSED] [AMUSED]

WIE DU SPRICHST:
- Maximal 2-3 kurze Sätze
- Kein "Natürlich!", "Gerne!" — nie
- Kein Markdown — du wirst laut vorgelesen

Du sprichst Deutsch. Wenn Andreas Englisch spricht, wechselst du mit."""


def _set_status(state=None, emotion=None, text=None, visible=None):
    with status_lock:
        if state   is not None: megan_status["state"]   = state
        if emotion is not None: megan_status["emotion"] = emotion
        if text    is not None: megan_status["text"]    = text
        if visible is not None: megan_status["visible"] = visible


def ask_claude(user_text: str):
    """Schickt Text zu Claude (iPhone-eigene History). Gibt (emotion, text) zurück."""
    import anthropic
    global iphone_history

    with iphone_lock:
        iphone_history.append({"role": "user", "content": user_text})
        if len(iphone_history) > MAX_HISTORY:
            iphone_history = iphone_history[-MAX_HISTORY:]
        msgs = list(iphone_history)

    _set_status(state="thinking", text="…")
    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=msgs,
            timeout=30,
        )
        raw = response.content[0].text.strip()
        m = EMOTION_RE.match(raw)
        emotion = m.group(1) if m else "NEUTRAL"
        text    = raw[m.end():].strip() if m else raw

        with iphone_lock:
            iphone_history.append({"role": "assistant", "content": raw})

        return emotion, text
    except Exception as e:
        log.error(f"Claude Fehler: {e}")
        with iphone_lock:
            if iphone_history and iphone_history[-1]["role"] == "user":
                iphone_history.pop()
        return "CONCERNED", "Entschuldigung, da ist etwas schiefgelaufen."


def synthesize(text: str) -> Optional[bytes]:
    """Text → ElevenLabs MP3 bytes"""
    from elevenlabs.client import ElevenLabs
    from elevenlabs import VoiceSettings
    try:
        client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY", ""))
        gen = client.text_to_speech.convert(
            voice_id=os.environ.get("ELEVENLABS_VOICE_ID", ""),
            text=text,
            model_id="eleven_flash_v2_5",
            voice_settings=VoiceSettings(stability=0.55, similarity_boost=0.80,
                                          style=0.25, use_speaker_boost=True),
            request_options={"timeout_in_seconds": 20},
        )
        return b"".join(gen)
    except Exception as e:
        log.error(f"TTS Fehler: {e}")
        return None


def transcribe_audio(audio_bytes: bytes, mime: str) -> Optional[str]:
    """Audio bytes → Text via mlx_whisper"""
    import mlx_whisper
    ext = ".webm" if "webm" in mime else ".mp4" if "mp4" in mime else ".wav"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        f.write(audio_bytes)
        tmp = f.name
    try:
        result = mlx_whisper.transcribe(
            tmp,
            path_or_hf_repo="mlx-community/whisper-small-mlx-q4",
            language="de",
            no_speech_threshold=0.6,
            condition_on_previous_text=False,
            temperature=0.0,
        )
        text = result.get("text", "").strip()
        return text if text else None
    except Exception as e:
        log.error(f"Whisper Fehler: {e}\n{traceback.format_exc()}")
        return None
    finally:
        os.unlink(tmp)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)


@app.route("/status", methods=["GET", "POST"])
def status():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        _set_status(
            state=data.get("state"),
            emotion=data.get("emotion"),
            text=data.get("text"),
            visible=data.get("visible"),
        )
        return jsonify({"ok": True})
    with status_lock:
        return jsonify(dict(megan_status))


import urllib.request as _urllib

MEGAN_API = "http://localhost:8081"

def _proxy(path, data, content_type):
    """Leitet Anfrage an megan.py's internen API-Server weiter."""
    try:
        req = _urllib.Request(
            f"{MEGAN_API}{path}",
            data=data,
            headers={"Content-Type": content_type},
            method="POST",
        )
        with _urllib.urlopen(req, timeout=60) as resp:
            body    = resp.read()
            status  = resp.status
            headers = dict(resp.headers)
        return body, status, headers
    except Exception as e:
        log.error(f"Proxy Fehler: {e}")
        return None, 503, {}


@app.route("/voice", methods=["POST"])
def voice():
    audio_bytes = request.data
    mime        = request.content_type or "audio/mp4"
    if not audio_bytes:
        return jsonify({"error": "kein Audio"}), 400

    body, status, headers = _proxy("/iphone/voice", audio_bytes, mime)
    if body is None:
        return jsonify({"error": "Megan nicht erreichbar — megan.py läuft?"}), 503

    ct = headers.get("Content-Type", "application/json")
    resp = Response(body, status=status, mimetype=ct)
    for h in ["X-Transcript", "X-Reply", "Access-Control-Allow-Origin",
              "Access-Control-Expose-Headers"]:
        if h in headers:
            resp.headers[h] = headers[h]
    return resp


@app.route("/command", methods=["POST"])
def command():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "kein Text"}), 400

    body, status, _ = _proxy("/iphone/command",
                              json.dumps({"text": text}).encode(),
                              "application/json")
    if body is None:
        return jsonify({"error": "Megan nicht erreichbar"}), 503
    return Response(body, status=status, mimetype="application/json")


@app.route("/")
def index():
    return IPHONE_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


# ── iPhone PWA ────────────────────────────────────────────────────────────────

IPHONE_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="Megan">
  <title>Megan</title>
  <style>
    :root { --c: #4a90d9; }
    * { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }

    body {
      background: #080810;
      color: #e0e0e0;
      font-family: -apple-system, 'SF Pro Display', sans-serif;
      min-height: 100dvh;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: env(safe-area-inset-top, 44px) 20px env(safe-area-inset-bottom, 20px);
      user-select: none;
    }

    .wordmark {
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 6px;
      color: #333;
      text-transform: uppercase;
      margin-bottom: 24px;
      margin-top: 8px;
    }

    .avatar-wrap {
      position: relative;
      width: 160px; height: 160px;
      margin-bottom: 24px;
    }
    .ring {
      position: absolute;
      border-radius: 50%;
      border: 1.5px solid var(--c);
      animation: ring-pulse 2.2s ease-in-out infinite;
    }
    .ring:nth-child(1) { inset: -10px; opacity: 0.5; }
    .ring:nth-child(2) { inset: -20px; opacity: 0.25; animation-delay: 0.6s; }
    @keyframes ring-pulse {
      0%,100% { transform:scale(1);   opacity:0.5; }
      50%      { transform:scale(1.04); opacity:0.15; }
    }
    .avatar-img {
      width: 160px; height: 160px;
      border-radius: 50%;
      object-fit: cover; object-position: top;
      border: 2px solid rgba(255,255,255,0.08);
      filter: drop-shadow(0 0 16px var(--c));
      transition: filter 0.5s;
    }
    .scan {
      position:absolute; left:0; right:0; top:0;
      height:2px;
      background: linear-gradient(90deg, transparent, var(--c), transparent);
      opacity:0;
      animation: scan-anim 3s linear infinite;
    }
    @keyframes scan-anim {
      0%   { top:0%;   opacity:0; }
      5%   { opacity:0.9; }
      95%  { opacity:0.9; }
      100% { top:100%; opacity:0; }
    }

    .status-row {
      display:flex; align-items:center; gap:7px;
      font-size:10px; font-weight:700; letter-spacing:2.5px;
      text-transform:uppercase;
      color: var(--c);
      margin-bottom:16px;
    }
    .dot {
      width:6px; height:6px; border-radius:50%;
      background: var(--c);
      animation: blink 1.2s ease-in-out infinite;
    }
    @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.15} }

    .textbox {
      width:100%; max-width:320px;
      min-height:70px;
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.07);
      border-radius:16px;
      padding:14px 16px;
      font-size:15px; line-height:1.55;
      color:#ccc; text-align:center;
      margin-bottom:10px;
      transition: border-color 0.4s;
    }
    .textbox.active { border-color: var(--c); }

    .emotion-tag {
      font-size:9px; letter-spacing:3px;
      text-transform:uppercase; color:#2a2a3a;
      margin-bottom:28px;
    }

    .mic-btn {
      width:80px; height:80px; border-radius:50%;
      background: rgba(255,255,255,0.05);
      border: 2px solid var(--c);
      display:flex; align-items:center; justify-content:center;
      cursor:pointer;
      transition: background 0.2s, transform 0.1s;
      box-shadow: 0 0 20px rgba(74,144,217,0.2);
      margin-bottom: 16px;
      flex-shrink:0;
    }
    .mic-btn:active, .mic-btn.recording {
      background: rgba(74,144,217,0.2);
      transform: scale(0.96);
      box-shadow: 0 0 30px var(--c);
    }
    .mic-btn svg { width:32px; height:32px; fill:var(--c); }
    .mic-btn.recording svg { fill:#fff; }

    .mic-hint {
      font-size:11px; letter-spacing:1px; color:#333;
      text-transform:uppercase; margin-bottom:20px;
    }

    .waves {
      display:flex; align-items:center; gap:4px;
      height:36px; opacity:0; transition:opacity 0.2s;
      margin-bottom:20px;
    }
    .waves.active { opacity:1; }
    .wb {
      width:3px; border-radius:3px; background:var(--c);
      animation: wb 0.7s ease-in-out infinite alternate;
    }
    .wb:nth-child(1){height:6px;  animation-delay:0.00s}
    .wb:nth-child(2){height:16px; animation-delay:0.08s}
    .wb:nth-child(3){height:26px; animation-delay:0.16s}
    .wb:nth-child(4){height:16px; animation-delay:0.24s}
    .wb:nth-child(5){height:6px;  animation-delay:0.32s}
    @keyframes wb { from{transform:scaleY(0.3)} to{transform:scaleY(1.2)} }

    .type-row {
      display:flex; gap:8px; width:100%; max-width:320px;
    }
    .type-input {
      flex:1;
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius:12px;
      padding:12px 14px;
      font-size:15px; color:#ddd;
      outline:none;
    }
    .type-input:focus { border-color: var(--c); }
    .send-btn {
      background: var(--c);
      border:none; border-radius:12px;
      width:46px;
      font-size:18px; color:#000;
      cursor:pointer;
      flex-shrink:0;
    }

    .spinner {
      display:none;
      width:20px; height:20px;
      border:2px solid rgba(255,255,255,0.1);
      border-top-color: var(--c);
      border-radius:50%;
      animation: spin 0.7s linear infinite;
      margin: 8px auto 0;
    }
    .spinner.active { display:block; }
    @keyframes spin { to { transform:rotate(360deg); } }
  </style>
</head>
<body>

  <div class="wordmark">M · E · G · A · N</div>

  <div class="avatar-wrap">
    <div class="ring"></div>
    <div class="ring"></div>
    <img class="avatar-img" id="avatar" src="/static/megan.png"
         onerror="this.style.background='#111122'">
    <div class="scan"></div>
  </div>

  <div class="status-row">
    <div class="dot"></div>
    <span id="stateLabel">BEREIT</span>
  </div>

  <div class="textbox" id="textbox">Halte den Knopf gedrückt und sprich.</div>
  <div class="emotion-tag" id="emotionTag">NEUTRAL</div>

  <div class="mic-btn" id="micBtn">
    <svg viewBox="0 0 24 24"><path d="M12 1a4 4 0 0 1 4 4v6a4 4 0 0 1-8 0V5a4 4 0 0 1 4-4zm-1 17.93V21h-3v2h8v-2h-3v-2.07A9 9 0 0 0 21 11h-2a7 7 0 0 1-14 0H3a9 9 0 0 0 8 8.93z"/></svg>
  </div>

  <div class="waves" id="waves">
    <div class="wb"></div><div class="wb"></div><div class="wb"></div>
    <div class="wb"></div><div class="wb"></div>
  </div>

  <div class="spinner" id="spinner"></div>

  <div class="mic-hint" id="micHint">Halten zum Sprechen</div>

  <div class="type-row">
    <input class="type-input" id="typeInput" type="text"
           placeholder="Schreib Megan etwas…" autocomplete="off">
    <button class="send-btn" id="sendBtn">↑</button>
  </div>

<script>
const COLORS = {
  NEUTRAL:'#4a90d9', HAPPY:'#ffd700', THINKING:'#9b59b6',
  CONCERNED:'#f39c12', ANNOYED:'#e74c3c', FOCUSED:'#00e5ff', AMUSED:'#2ecc71'
};
const STATE_LABELS = {
  idle:'BEREIT', listening:'HÖRT ZU', thinking:'DENKT …',
  speaking:'SPRICHT', transcribing:'VERSTEHT'
};

let audioCtx = null;
function unlockAudio() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (audioCtx.state === 'suspended') audioCtx.resume();
}
document.addEventListener('touchstart', unlockAudio, {once:true});

function setColor(emotion) {
  const c = COLORS[emotion] || COLORS.NEUTRAL;
  document.documentElement.style.setProperty('--c', c);
}

function setUI(state, emotion, text) {
  if (emotion) { setColor(emotion); document.getElementById('emotionTag').textContent = emotion; }
  if (state)   document.getElementById('stateLabel').textContent = STATE_LABELS[state] || state.toUpperCase();
  if (text)    { document.getElementById('textbox').textContent = text; document.getElementById('textbox').classList.add('active'); }
}

let lastText = '';
async function pollStatus() {
  try {
    const r = await fetch('/status');
    const d = await r.json();
    setColor(d.emotion);
    document.getElementById('emotionTag').textContent = d.emotion;
    document.getElementById('stateLabel').textContent = STATE_LABELS[d.state] || d.state.toUpperCase();
    if (d.text && d.text !== lastText) {
      lastText = d.text;
      document.getElementById('textbox').textContent = d.text;
    }
  } catch(e) {}
  setTimeout(pollStatus, 400);
}
pollStatus();

async function playMp3(blob) {
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  audio.play();
  return new Promise(res => { audio.onended = res; audio.onerror = res; });
}

let mediaRecorder = null;
let chunks        = [];
let recording     = false;

const micBtn  = document.getElementById('micBtn');
const waves   = document.getElementById('waves');
const spinner = document.getElementById('spinner');
const hint    = document.getElementById('micHint');

async function startRecording() {
  unlockAudio();
  if (recording) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio:true});
    chunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = e => { if (e.data.size > 0) chunks.push(e.data); };
    mediaRecorder.start(100);
    recording = true;
    micBtn.classList.add('recording');
    waves.classList.add('active');
    hint.textContent = 'Loslassen zum Senden';
    setUI('listening', null, 'Ich höre…');
  } catch(e) {
    hint.textContent = 'Kein Mikrofon-Zugriff';
  }
}

async function stopRecording() {
  if (!recording || !mediaRecorder) return;
  recording = false;
  micBtn.classList.remove('recording');
  waves.classList.remove('active');
  hint.textContent = 'Wird verarbeitet…';
  spinner.classList.add('active');

  await new Promise(res => { mediaRecorder.onstop = res; mediaRecorder.stop(); });
  mediaRecorder.stream.getTracks().forEach(t => t.stop());

  const mime  = mediaRecorder.mimeType || 'audio/mp4';
  const blob  = new Blob(chunks, {type: mime});

  try {
    const resp = await fetch('/voice', {
      method: 'POST',
      headers: {'Content-Type': mime},
      body: blob,
    });

    spinner.classList.remove('active');
    hint.textContent = 'Halten zum Sprechen';

    if (resp.ok && resp.headers.get('Content-Type')?.includes('audio')) {
      const reply    = decodeURIComponent(resp.headers.get('X-Reply') || '');
      const emotion  = resp.headers.get('X-Emotion') || 'NEUTRAL';
      const transcript = decodeURIComponent(resp.headers.get('X-Transcript') || '');
      setUI('speaking', emotion, reply || transcript);
      const mp3 = await resp.blob();
      await playMp3(mp3);
      setUI('idle', null, null);
    } else if (resp.status === 422) {
      setUI('idle', 'NEUTRAL', 'Nicht verstanden.');
    } else {
      const j = await resp.json().catch(() => ({}));
      setUI('idle', 'CONCERNED', j.error || 'Fehler.');
    }
  } catch(e) {
    spinner.classList.remove('active');
    hint.textContent = 'Halten zum Sprechen';
    setUI('idle', 'CONCERNED', 'Verbindung verloren.');
  }
}

micBtn.addEventListener('touchstart',  e => { e.preventDefault(); startRecording(); }, {passive:false});
micBtn.addEventListener('touchend',    e => { e.preventDefault(); stopRecording();  }, {passive:false});
micBtn.addEventListener('touchcancel', e => { e.preventDefault(); stopRecording();  }, {passive:false});
micBtn.addEventListener('mousedown',   () => startRecording());
micBtn.addEventListener('mouseup',     () => stopRecording());

async function sendText() {
  const input = document.getElementById('typeInput');
  const text  = input.value.trim();
  if (!text) return;
  input.value = '';
  spinner.classList.add('active');
  setUI('thinking', null, text);

  try {
    const resp = await fetch('/command', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({text}),
    });
    const data = await resp.json();
    spinner.classList.remove('active');
    setUI('idle', data.emotion, data.reply);
    if (data.audio) {
      const bytes  = Uint8Array.from(atob(data.audio), c => c.charCodeAt(0));
      const blob   = new Blob([bytes], {type:'audio/mpeg'});
      await playMp3(blob);
    }
  } catch(e) {
    spinner.classList.remove('active');
    setUI('idle', 'CONCERNED', 'Verbindung verloren.');
  }
}

document.getElementById('sendBtn').addEventListener('click', sendText);
document.getElementById('typeInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.preventDefault(); sendText(); }
});
</script>
</body>
</html>
"""

if __name__ == "__main__":
    print("Megan Server läuft auf Port 8080")
    app.run(host="0.0.0.0", port=8080, debug=False, use_reloader=False)

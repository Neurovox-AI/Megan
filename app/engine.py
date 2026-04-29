"""VoiceImpulse — Voice Engine"""
import os, re, time, tempfile, threading, subprocess, asyncio
import numpy as np, sounddevice as sd, scipy.io.wavfile as wav
import mlx_whisper, torch, edge_tts
from datetime import datetime
from anthropic import Anthropic
from silero_vad import load_silero_vad
import config as cfg_module

TTS_VOICE = "de-AT-IngridNeural"

SAMPLERATE=16000; VAD_CHUNK=512; VAD_THRESHOLD=0.5; SILENCE_DURATION=1.2; MAX_WAIT=60
WHISPER_MODEL="mlx-community/whisper-small-mlx-q4"; MAX_HISTORY=10

HALLUCINATIONS=[r"^(oh\s*)+$",r"^(uh\s*)+$",r"^(äh\s*)+$",r"^\s*$",r"^(\.+\s*)+$"]

SYSTEM="""Du bist Megan — KI-Assistent auf dem Mac des Nutzers.
Charakter: Direkt, locker, loyal, trocken humorvoll. Kurze Antworten (max 3 Sätze).
Sprache: Deutsch. Antworte immer auf Deutsch.
Für Mac-Befehle: [EXEC: <applescript>]
Datum: {date}
WICHTIG: Keine Emojis, keine Sonderzeichen, kein Markdown. Nur gesprochene Sprache."""

class VoiceEngine:
    def __init__(self, status_callback=None):
        self.status_callback=status_callback or (lambda s: None)
        self._history=[]; self._is_speaking=False; self._active=False
        self._ready=False; self._afplay_proc=None; self._lock=threading.Lock()

    def initialize(self):
        self._set_status("loading")
        try:
            self._vad=load_silero_vad(); self._vad.eval()
            self._reload_clients(); self._ready=True; self._set_status("idle")
        except Exception as e:
            self._set_status("error"); print(f"[Engine] Init-Fehler: {e}")

    def _reload_clients(self):
        cfg=cfg_module.load()
        self._claude=Anthropic(api_key=cfg.get("anthropic_key",""))

    def _set_status(self,s): self.status_callback(s)
    def is_ready(self): return self._ready
    def reload_config(self): self._reload_clients()

    def listen_and_respond(self):
        if not self._ready or self._is_speaking: return
        threading.Thread(target=self._cycle, daemon=True).start()

    def _cycle(self):
        with self._lock:
            if self._active: return
            self._active=True
        try:
            self._set_status("listening")
            audio=self._record()
            if audio is None or len(audio)<SAMPLERATE*0.3:
                self._set_status("idle"); return
            self._set_status("thinking")
            text=self._transcribe(audio)
            if not text: self._set_status("idle"); return
            print(f"[STT] {text}")
            reply=self._ask_claude(text)
            if not reply: self._set_status("idle"); return
            print(f"[Claude] {reply}")
            clean=self._clean_for_tts(self._exec_if_needed(reply))
            self._set_status("speaking"); self._speak(clean)
        finally:
            self._active=False; self._set_status("idle")

    def _record(self):
        buf=[]; silence_cnt=0; speech_on=False
        with sd.InputStream(samplerate=SAMPLERATE,channels=1,dtype="float32",blocksize=VAD_CHUNK) as s:
            for _ in range(int(MAX_WAIT*SAMPLERATE/VAD_CHUNK)):
                if self._is_speaking: return None
                block,_=s.read(VAD_CHUNK); b=block.flatten().astype(np.float32)
                prob=self._vad(torch.from_numpy(b).unsqueeze(0),SAMPLERATE).item()
                if prob>VAD_THRESHOLD: speech_on=True; silence_cnt=0; buf.append(b)
                elif speech_on:
                    buf.append(b); silence_cnt+=1
                    if silence_cnt>int(SILENCE_DURATION*SAMPLERATE/VAD_CHUNK): break
        return np.concatenate(buf) if speech_on and buf else None

    def _transcribe(self, audio):
        with tempfile.NamedTemporaryFile(suffix=".wav",delete=False) as f: path=f.name
        try:
            wav.write(path,SAMPLERATE,(audio*32767).astype(np.int16))
            r=mlx_whisper.transcribe(path,path_or_hf_repo=WHISPER_MODEL,language="de",
                                     no_speech_threshold=0.45,condition_on_previous_text=False)
            text=r.get("text","").strip()
            for p in HALLUCINATIONS:
                if re.fullmatch(p,text,re.IGNORECASE): return ""
            return text
        finally:
            try: os.unlink(path)
            except: pass

    def _ask_claude(self, text):
        self._history.append({"role":"user","content":text})
        if len(self._history)>MAX_HISTORY*2: self._history=self._history[-MAX_HISTORY*2:]
        try:
            r=self._claude.messages.create(model="claude-sonnet-4-6",max_tokens=512,
                system=SYSTEM.format(date=datetime.now().strftime("%A, %d.%m.%Y")),
                messages=self._history)
            reply=r.content[0].text
            self._history.append({"role":"assistant","content":reply}); return reply
        except Exception as e:
            print(f"[Claude] {e}"); return ""

    def _clean_for_tts(self, text):
        # Emojis entfernen
        text = re.sub(r'[\U00010000-\U0010ffff\U00002500-\U00002BEF\U00002702-\U000027B0\U0001F000-\U0001FFFE\U0001F300-\U0001FAFF\U00002600-\U000026FF\U0001F1E0-\U0001F1FF]', '', text)
        # Markdown entfernen: **, *, __, _, ~~, #, `, >
        text = re.sub(r'\*{1,2}|_{1,2}|~~|#{1,6}\s?|`{1,3}|^>\s?', '', text, flags=re.MULTILINE)
        # Mehrfach-Leerzeichen/Zeilenumbrüche glätten
        text = re.sub(r'\n+', ' ', text)
        text = re.sub(r' {2,}', ' ', text)
        return text.strip()

    def _exec_if_needed(self, reply):
        m=re.search(r"\[EXEC:\s*(.*?)\]",reply,re.DOTALL)
        if m:
            cmd=m.group(1).strip()
            try:
                if cmd.startswith("tell application"): subprocess.Popen(["osascript","-e",cmd])
                else: subprocess.Popen(cmd,shell=True)
            except Exception as e: print(f"[EXEC] {e}")
            return re.sub(r"\[EXEC:.*?\]","",reply,flags=re.DOTALL).strip()
        return reply

    def _speak(self, text):
        if not text.strip(): return
        self._is_speaking=True
        try:
            async def _synth():
                tmp=tempfile.NamedTemporaryFile(suffix=".mp3",delete=False)
                tmp.close()
                await edge_tts.Communicate(text, TTS_VOICE).save(tmp.name)
                return tmp.name
            path=asyncio.run(_synth())
            self._afplay_proc=subprocess.Popen(["afplay",path],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            self._afplay_proc.wait()
            try: os.unlink(path)
            except: pass
        except Exception as e: print(f"[TTS] {e}")
        finally: self._is_speaking=False

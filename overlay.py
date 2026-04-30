"""
Megan Overlay v4 — Siri-Style Bottom Bar.
Schmales Fenster am Bildschirmrand, ignoriert Mauseingaben via AppKit.
Animierte Flüssig-Blase + dunkler Gradient.
"""
import threading
import time
import json
import urllib.request
import webview

try:
    from AppKit import NSScreen
    _f = NSScreen.mainScreen().frame()
    SCREEN_W = int(_f.size.width)
    SCREEN_H = int(_f.size.height)
except Exception:
    SCREEN_W, SCREEN_H = 1470, 956

OVERLAY_H  = 160
STATUS_URL = "http://localhost:8080/status"


def _get_status():
    try:
        with urllib.request.urlopen(STATUS_URL, timeout=0.8) as r:
            return json.loads(r.read())
    except Exception:
        return {"state": "idle", "emotion": "NEUTRAL", "visible": False}


def _set_ignore_mouse():
    """Macht das Fenster komplett maus-transparent via AppKit."""
    time.sleep(1.2)
    try:
        from AppKit import NSApp
        for w in NSApp.windows():
            if w.title() == "":
                w.setIgnoresMouseEvents_(True)
                w.setLevel_(8)  # NSFloatingWindowLevel
                break
    except Exception as e:
        print(f"[overlay setIgnoresMouseEvents: {e}]")


def _control_loop(win):
    time.sleep(0.9)
    last_visible = None
    last_state   = None
    last_emotion = None

    while True:
        try:
            data    = _get_status()
            visible = data.get("visible", False)
            state   = data.get("state", "idle")
            emotion = data.get("emotion", "NEUTRAL")

            if visible != last_visible:
                last_visible = visible
                win.evaluate_js(f"setActive({'true' if visible else 'false'})")

            if state != last_state or emotion != last_emotion:
                last_state   = state
                last_emotion = emotion
                win.evaluate_js(f"setState('{state}','{emotion}')")
        except Exception:
            pass
        time.sleep(0.1)


HTML = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>
*{{margin:0;padding:0;box-sizing:border-box;}}

html,body{{
  width:{SCREEN_W}px;
  height:{OVERLAY_H}px;
  background:transparent;
  overflow:hidden;
  -webkit-user-select:none;
  pointer-events:none;
}}

/* Dunkle Leiste — erscheint/verschwindet */
.bar{{
  position:fixed;
  bottom:0;left:0;right:0;
  height:{OVERLAY_H}px;
  background:linear-gradient(to top,
    rgba(0,0,0,0.88) 0%,
    rgba(0,0,0,0.60) 55%,
    transparent 100%
  );
  display:flex;
  flex-direction:column;
  align-items:center;
  justify-content:flex-end;
  padding-bottom:20px;
  gap:10px;
  opacity:0;
  transform:translateY(20px);
  transition:opacity 0.36s cubic-bezier(.4,0,.2,1),
             transform 0.36s cubic-bezier(.4,0,.2,1);
}}
.bar.on{{
  opacity:1;
  transform:translateY(0);
}}

/* ── Siri-Blase ── */
.orb{{
  position:relative;
  width:74px;height:74px;
  flex-shrink:0;
}}

.orb-glow{{
  position:absolute;
  inset:-20px;
  border-radius:50%;
  background:radial-gradient(circle,
    rgba(232,69,106,0.20) 0%,
    rgba(244,114,182,0.08) 50%,
    transparent 70%
  );
  animation:gpulse 2.8s ease-in-out infinite;
}}
@keyframes gpulse{{
  0%,100%{{transform:scale(1);opacity:0.55;}}
  50%{{transform:scale(1.35);opacity:1;}}
}}

.orb-core{{
  position:absolute;inset:0;
  border-radius:50%;
  overflow:hidden;
  background:#060206;
}}
.blob{{
  position:absolute;
  border-radius:50%;
  will-change:transform;
}}
.b1{{width:62px;height:62px;top:-10px;left:-10px;
     background:#E8456A;filter:blur(14px);
     animation:b1 3.2s ease-in-out infinite;}}
.b2{{width:54px;height:54px;top:8px;right:-10px;
     background:#F472B6;filter:blur(13px);
     animation:b2 4.0s ease-in-out infinite;}}
.b3{{width:50px;height:50px;bottom:-8px;left:8px;
     background:#8B5CF6;filter:blur(14px);
     animation:b3 4.6s ease-in-out infinite;}}
.b4{{width:38px;height:38px;top:16px;left:16px;
     background:#06B6D4;filter:blur(12px);opacity:0.4;
     animation:b4 5.2s ease-in-out infinite;}}

@keyframes b1{{
  0%,100%{{transform:translate(0,0) scale(1);}}
  30%{{transform:translate(16px,10px) scale(1.14);}}
  65%{{transform:translate(-6px,16px) scale(0.88);}}
}}
@keyframes b2{{
  0%,100%{{transform:translate(0,0) scale(1);}}
  35%{{transform:translate(-11px,-6px) scale(1.08);}}
  70%{{transform:translate(10px,-11px) scale(0.93);}}
}}
@keyframes b3{{
  0%,100%{{transform:translate(0,0) scale(1);}}
  40%{{transform:translate(-14px,-5px) scale(1.11);}}
  75%{{transform:translate(6px,10px) scale(0.91);}}
}}
@keyframes b4{{
  0%,100%{{transform:translate(0,0) scale(1);}}
  50%{{transform:translate(8px,-8px) scale(1.22);}}
}}

.orb-shine{{
  position:absolute;top:10px;left:12px;
  width:20px;height:12px;border-radius:50%;
  background:rgba(255,255,255,0.18);filter:blur(3px);
}}

/* Schneller wenn aktiv */
.orb.fast .b1{{animation-duration:1.4s;}}
.orb.fast .b2{{animation-duration:1.8s;}}
.orb.fast .b3{{animation-duration:2.1s;}}
.orb.fast .b4{{animation-duration:2.5s;}}
.orb.fast .orb-glow{{animation-duration:1.1s;}}

/* Denkende Ringe */
.ring{{
  position:absolute;inset:-3px;
  border-radius:50%;
  border:1.5px solid rgba(232,69,106,0.5);
  opacity:0;
}}
.ring.on{{animation:rp 1.6s ease-out infinite;}}
.ring:nth-child(2).on{{animation-delay:0.65s;}}
@keyframes rp{{
  0%{{transform:scale(1);opacity:0.6;}}
  100%{{transform:scale(2.6);opacity:0;}}
}}

/* Waveform */
.wv{{
  position:absolute;top:50%;transform:translateY(-50%);
  display:flex;align-items:center;gap:3px;
  opacity:0;transition:opacity 0.22s;
}}
.wv.L{{right:calc(100% + 12px);}}
.wv.R{{left:calc(100% + 12px);}}
.wv.on{{opacity:1;}}

.wb{{
  width:3px;border-radius:3px;
  background:linear-gradient(to top,#E8456A,#F472B6);
  animation:wba 0.66s ease-in-out infinite alternate;
  transform-origin:bottom;
}}
.wv.L .wb:nth-child(1){{height:5px;animation-delay:0s;}}
.wv.L .wb:nth-child(2){{height:13px;animation-delay:0.09s;}}
.wv.L .wb:nth-child(3){{height:21px;animation-delay:0.17s;}}
.wv.R .wb:nth-child(1){{height:21px;animation-delay:0.24s;}}
.wv.R .wb:nth-child(2){{height:13px;animation-delay:0.32s;}}
.wv.R .wb:nth-child(3){{height:5px;animation-delay:0.40s;}}
@keyframes wba{{
  from{{transform:scaleY(0.25);}}
  to{{transform:scaleY(1.40);}}
}}

/* Label */
.lbl{{
  font-family:-apple-system,'SF Mono','Menlo',monospace;
  font-size:9px;font-weight:700;
  letter-spacing:4.5px;text-transform:uppercase;
  color:rgba(245,237,226,0.32);
  transition:color 0.4s,text-shadow 0.4s;
  position:relative;
}}
.lbl.on{{
  color:rgba(245,237,226,0.72);
  text-shadow:0 0 14px rgba(232,69,106,0.55);
}}
.dot{{
  position:absolute;top:0;right:-13px;
  width:5px;height:5px;border-radius:50%;
  background:#E8456A;box-shadow:0 0 6px #E8456A;
  opacity:0;transition:opacity 0.3s;
}}
.dot.on{{opacity:1;}}
</style></head><body>

<div class="bar" id="bar">
  <div class="orb" id="orb">
    <div class="orb-glow"></div>
    <div class="ring" id="r1"></div>
    <div class="ring" id="r2"></div>
    <div class="wv L" id="wL">
      <div class="wb"></div><div class="wb"></div><div class="wb"></div>
    </div>
    <div class="orb-core">
      <div class="blob b1" id="b1"></div>
      <div class="blob b2" id="b2"></div>
      <div class="blob b3" id="b3"></div>
      <div class="blob b4"></div>
      <div class="orb-shine"></div>
    </div>
    <div class="wv R" id="wR">
      <div class="wb"></div><div class="wb"></div><div class="wb"></div>
    </div>
  </div>
  <div style="position:relative;display:inline-block;">
    <div class="lbl" id="lbl">MEGAN</div>
    <div class="dot" id="dot"></div>
  </div>
</div>

<script>
const LABELS={{idle:'MEGAN',listening:'HÖRT ZU',thinking:'DENKT',speaking:'SPRICHT'}};
const COLS={{
  NEUTRAL:  ['#E8456A','#F472B6','#8B5CF6'],
  HAPPY:    ['#F472B6','#fbbf24','#E8456A'],
  THINKING: ['#8B5CF6','#6366f1','#E8456A'],
  FOCUSED:  ['#06B6D4','#8B5CF6','#E8456A'],
  AMUSED:   ['#34d399','#F472B6','#8B5CF6'],
  ANNOYED:  ['#ef4444','#dc2626','#E8456A'],
}};
function setActive(v){{document.getElementById('bar').classList.toggle('on',v);}}
function setState(s,e){{
  const orb=document.getElementById('orb'),lbl=document.getElementById('lbl'),
        wL=document.getElementById('wL'),wR=document.getElementById('wR'),
        r1=document.getElementById('r1'),r2=document.getElementById('r2');
  lbl.textContent=LABELS[s]||s.toUpperCase();
  orb.className='orb'; wL.className='wv L'; wR.className='wv R';
  r1.className='ring'; r2.className='ring'; lbl.className='lbl';
  if(s==='listening'){{orb.classList.add('fast');wL.classList.add('on');wR.classList.add('on');lbl.classList.add('on');}}
  else if(s==='thinking'){{r1.classList.add('on');r2.classList.add('on');lbl.classList.add('on');}}
  else if(s==='speaking'){{orb.classList.add('fast');wL.classList.add('on');wR.classList.add('on');lbl.classList.add('on');}}
  const c=COLS[e]||COLS.NEUTRAL;
  document.getElementById('b1').style.background=c[0];
  document.getElementById('b2').style.background=c[1];
  document.getElementById('b3').style.background=c[2];
}}
function setContinuous(v){{document.getElementById('dot').classList.toggle('on',v);}}
</script>
</body></html>"""


def main():
    window = webview.create_window(
        title="",
        html=HTML,
        width=SCREEN_W,
        height=OVERLAY_H,
        x=0,
        y=SCREEN_H - OVERLAY_H,
        resizable=False,
        frameless=True,
        on_top=True,
        transparent=True,
        background_color="#000001",
        shadow=False,
    )

    # Maus-Events ignorieren damit der User normal weiterarbeiten kann
    threading.Thread(target=_set_ignore_mouse, daemon=True).start()
    threading.Thread(target=_control_loop, args=(window,), daemon=True).start()
    webview.start(debug=False)


if __name__ == "__main__":
    main()

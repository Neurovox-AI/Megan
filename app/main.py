"""VoiceImpulse — Einstiegspunkt"""
import os, sys, threading, time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UI_DIR   = os.path.join(BASE_DIR, "ui")

import webview
import config as cfg_module
import engine as engine_module
import api    as api_module

_engine  = None
_windows = {}
_api     = None

def _html(name): return f"file://{UI_DIR}/{name}.html"

def create_win(name, title, width, height):
    global _windows, _api
    if name in _windows:
        try: _windows[name].show(); return _windows[name]
        except: del _windows[name]
    win = webview.create_window(title, _html(name), js_api=_api,
        width=width, height=height, resizable=False, on_top=True,
        background_color="#FDF6EE", min_size=(width, height))
    _windows[name] = win
    def _closed():
        _windows.pop(name, None)
        if name == "setup" and cfg_module.is_setup_complete():
            threading.Thread(target=lambda: create_win("dashboard", "VoiceImpulse", 360, 520), daemon=True).start()
    win.events.closed += _closed
    threading.Thread(target=_watch_title, args=(win, name), daemon=True).start()
    return win

def _watch_title(win, name):
    while True:
        time.sleep(0.4)
        if name not in _windows: break
        try:
            t = win.evaluate_js("document.title")
            if t == "__OPEN_SETTINGS__":
                win.evaluate_js("document.title='VoiceImpulse'")
                threading.Thread(target=lambda: create_win("settings","Einstellungen",400,580),daemon=True).start()
        except: break

def on_status_change(status):
    win = _windows.get("dashboard")
    if win:
        try: win.evaluate_js(f"typeof updateStatus!=='undefined'&&updateStatus('{status}')")
        except: pass

def setup_hotkey():
    try:
        from pynput import keyboard
        COMBO = {keyboard.Key.cmd, keyboard.Key.shift, keyboard.KeyCode.from_char('m')}
        pressed = set()
        def on_press(key):
            pressed.add(key)
            if all(k in pressed for k in COMBO):
                if _engine and _engine.is_ready(): _engine.listen_and_respond()
        def on_release(key): pressed.discard(key)
        l = keyboard.Listener(on_press=on_press, on_release=on_release)
        l.daemon = True; l.start()
        print("[Hotkey] ⌘⇧M aktiv")
    except Exception as e: print(f"[Hotkey] Fehler: {e}")

def setup_menubar():
    try:
        import AppKit, objc
        from Foundation import NSObject
        bar  = AppKit.NSStatusBar.systemStatusBar()
        item = bar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)
        item.button().setTitle_("〜")
        menu = AppKit.NSMenu.alloc().init()

        lbl = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("● Megan — bereit",None,"")
        lbl.setEnabled_(False); menu.addItem_(lbl)
        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        class VITarget(NSObject):
            @objc.typedSelector(b"v@:@")
            def openDashboard_(self, sender):
                threading.Thread(target=lambda: create_win("dashboard","VoiceImpulse",360,520),daemon=True).start()
            @objc.typedSelector(b"v@:@")
            def openSettings_(self, sender):
                threading.Thread(target=lambda: create_win("settings","Einstellungen",400,580),daemon=True).start()
            @objc.typedSelector(b"v@:@")
            def quitApp_(self, sender):
                AppKit.NSApp.terminate_(None)

        t = VITarget.alloc().init()
        setup_menubar._t = t

        def add(title, action, key):
            mi = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title,action,key)
            mi.setTarget_(t); menu.addItem_(mi)

        add("VoiceImpulse öffnen","openDashboard:","")
        add("Einstellungen","openSettings:",",")
        menu.addItem_(AppKit.NSMenuItem.separatorItem())
        hint = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Shortcut: ⌘⇧M",None,"")
        hint.setEnabled_(False); menu.addItem_(hint)
        menu.addItem_(AppKit.NSMenuItem.separatorItem())
        add("Beenden","quitApp:","q")
        item.setMenu_(menu)
        setup_menubar._item = item; setup_menubar._lbl = lbl

        LABELS={"idle":"● Megan — bereit","loading":"◌ Lädt...","listening":"◉ Hört zu...",
                "thinking":"◌ Denkt...","speaking":"◎ Spricht...","error":"✕ Fehler"}
        def update_mb(s):
            def _do(): lbl.setTitle_(LABELS.get(s,s))
            AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(_do)
        setup_menubar.update = update_mb
        print("[MenuBar] aktiv")
    except Exception as e:
        print(f"[MenuBar] Fehler: {e}")
        setup_menubar.update = lambda s: None

def main():
    global _engine, _api
    _engine = engine_module.VoiceEngine(status_callback=on_status_change)
    _api    = api_module.Api(engine=_engine)
    threading.Thread(target=_engine.initialize, daemon=True).start()
    setup_hotkey()
    setup_menubar()
    cfg = cfg_module.load()
    if not cfg_module.is_setup_complete():
        create_win("setup", "VoiceImpulse einrichten", 420, 560)
    else:
        create_win("dashboard", "VoiceImpulse", 360, 520)
    webview.start(gui="cocoa", debug=False)
    sys.exit(0)

if __name__ == "__main__":
    main()

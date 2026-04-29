"""VoiceImpulse — Config"""
import json
from pathlib import Path

CONFIG_DIR  = Path.home() / ".voiceimpulse"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "setup_complete": False, "plan": "free", "auth_token": None, "email": None,
    "anthropic_key": "",
    "assistant_name": "Megan", "shortcut": "cmd+shift+m", "autostart": True,
    "requests_this_month": 0, "requests_reset_date": None,
}

def load():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return {**DEFAULTS, **json.load(f)}
        except Exception:
            pass
    return DEFAULTS.copy()

def save(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def update(**kwargs):
    cfg = load(); cfg.update(kwargs); save(cfg); return cfg

def is_setup_complete():
    cfg = load()
    if not cfg.get("setup_complete"): return False
    if cfg.get("plan") == "developer":
        return bool(cfg.get("anthropic_key"))
    return True

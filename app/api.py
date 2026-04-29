"""VoiceImpulse — pywebview JS-Bridge"""
import config as cfg_module

class Api:
    def __init__(self, engine=None, on_setup_complete=None):
        self._engine = engine
        self._on_setup_complete = on_setup_complete or (lambda: None)

    def get_config(self):
        cfg = cfg_module.load()
        safe = {k: v for k, v in cfg.items() if k not in ("anthropic_key", "elevenlabs_key")}
        safe["has_anthropic_key"]  = bool(cfg.get("anthropic_key"))
        safe["has_elevenlabs_key"] = bool(cfg.get("elevenlabs_key"))
        return safe

    def complete_setup(self, plan, anthropic_key="", elevenlabs_key="", voice_id=""):
        updates = {"setup_complete": True, "plan": plan}
        if plan == "developer":
            if not anthropic_key:
                return {"ok": False, "error": "Developer-Plan benötigt einen Anthropic API Key."}
            updates["anthropic_key"] = anthropic_key
        cfg_module.update(**updates)
        if self._engine: self._engine.reload_config()
        return {"ok": True}

    def login(self, email, password):
        if not email or not password: return {"ok": False, "error": "Felder leer."}
        cfg_module.update(email=email, auth_token="demo_token")
        return {"ok": True, "email": email}

    def save_settings(self, data):
        allowed = ["assistant_name","shortcut","autostart","anthropic_key"]
        cfg_module.update(**{k: v for k, v in data.items() if k in allowed})
        if self._engine: self._engine.reload_config()
        return {"ok": True}

    def get_status(self):
        cfg = cfg_module.load()
        return {"ready": self._engine.is_ready() if self._engine else False,
                "plan": cfg.get("plan","free"), "email": cfg.get("email"),
                "requests": cfg.get("requests_this_month", 0)}

    def trigger_listen(self):
        if self._engine and self._engine.is_ready():
            self._engine.listen_and_respond(); return {"ok": True}
        return {"ok": False, "error": "Engine nicht bereit."}

    def get_plan_info(self):
        cfg = cfg_module.load(); plan = cfg.get("plan","free")
        limits = {"free": 10, "basic": 60, "pro": 200, "developer": -1}
        return {"plan": plan, "limit": limits.get(plan,10), "used": cfg.get("requests_this_month",0)}

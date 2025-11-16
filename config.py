import json
import sys
from pathlib import Path
from dataclasses import dataclass

@dataclass
class Config:
    APP_NAME: str = "Git ka Wifi By Ashwin Yadav"
    SCRIPT_DIR: Path = Path(sys.argv[0]).parent
    HOME_DIR: Path = Path.home()
    APP_DIR: Path = HOME_DIR / f".{APP_NAME.lower().replace(' ', '_')}"

    PROFILES_FILE: Path = APP_DIR / "profiles.json"
    KEY_FILE: Path = APP_DIR / "fernet.key"
    SESSION_FILE: Path = APP_DIR / "session.json"
    LOG_FILE: Path = APP_DIR / "history.csv"
    SETTINGS_FILE: Path = APP_DIR / "settings.json"
    ICON_PNG: Path = SCRIPT_DIR / "7.png"

CONFIG = Config()
CONFIG.APP_DIR.mkdir(parents=True, exist_ok=True)

class SettingsManager:
    """Handles loading and saving of user-configurable settings."""
    def __init__(self, path: Path):
        self.path = path
        self.defaults = {
            "probe_urls": [
                "http://detectportal.firefox.com/canonical.html",
                "http://wwwservice.fi/generate_204",
                "http://captive.apple.com/hotspot-detect.html"
            ],
            "target_ssids": ["GIT_WIFI_1", "GIT_WIFI_2", "GIT-Library"], # <-- EDIT THESE
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "keepalive_interval_s": 5,
            "session_probe_interval_s": 10,
            "run_speedtest_on_login": False,
            "scrape_data_usage_regex": r"Upload/Download:\s*([\d\.]+\s*[GMK]?B\s*/\s*[\d\.]+\s*[GMK]?B)",
            "scrape_time_left_regex": r"Time Remaining:\s*(\d+\s*minutes?)"
            ,
            # --- NEW FEATURES ---
            "theme": "darkly",
            "CURRENT_VERSION": "1.2.0" # For future auto-updater
        }
        self.settings = self.defaults.copy()
        self.load()

    def load(self):
        if self.path.exists():
            try:
                with self.path.open("r", encoding="utf-8") as f:
                    loaded_settings = json.load(f)
                    # Ensure all default keys exist
                    for key, default_val in self.defaults.items():
                        self.settings[key] = loaded_settings.get(key, default_val)
            except (IOError, json.JSONDecodeError):
                 self.settings = self.defaults.copy()
        self.save() # Save to ensure any new defaults are written

    def save(self):
        try:
            with self.path.open("w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2)
        except IOError: print(f"Warning: Could not save settings to {self.path}")

    def get(self, key): 
        return self.settings.get(key, self.defaults.get(key))
    
    def set(self, key, value): 
        self.settings[key] = value

SETTINGS = SettingsManager(CONFIG.SETTINGS_FILE)
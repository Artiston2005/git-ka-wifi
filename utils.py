import csv
import json
import socket
import sys
from datetime import datetime
from tkinter import messagebox
from config import CONFIG, SETTINGS # Local import

# --- NEW FEATURE: Run on Startup ---
try:
    import winreg
except ImportError:
    winreg = None # Will disable the feature on non-Windows

# --- End New Feature ---

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None
try:
    from win10toast import ToastNotifier
    _toast = ToastNotifier()
except ImportError:
    _toast = None
    try:
        from plyer import notification as plyer_notify
    except ImportError:
        plyer_notify = None

# Global variable to hold the socket lock reference
_lock_socket = None

def check_for_lock():
    """Attempts to acquire a lock on a dedicated local port."""
    LOCK_PORT = 12345
    global _lock_socket
    _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _lock_socket.bind(("127.0.0.1", LOCK_PORT))
        return True
    except socket.error:
        _lock_socket = None # Ensure it's None if lock fails
        return False

def get_lock_socket():
    """Returns the global lock socket."""
    return _lock_socket

def append_log(action, details=""):
    ts = datetime.now().isoformat(sep=" ", timespec="seconds")
    try:
        with open(CONFIG.LOG_FILE, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([ts, action, details])
    except IOError: pass

def notify(title, msg):
    try:
        if _toast: 
            _toast.show_toast(
                title, 
                msg, 
                threaded=True, 
                duration=5, 
                icon_path=str(CONFIG.ICON_PNG) if CONFIG.ICON_PNG.exists() else None
            )
        elif 'plyer_notify' in globals() and plyer_notify: 
            plyer_notify.notify(
                title=title, 
                message=msg, 
                app_name=CONFIG.APP_NAME
            )
    except Exception: pass

def ensure_fernet():
    if Fernet is None: return None
    try:
        if not CONFIG.KEY_FILE.exists(): 
            CONFIG.KEY_FILE.write_bytes(Fernet.generate_key())
        return Fernet(CONFIG.KEY_FILE.read_bytes())
    except IOError: return None

FERNET = ensure_fernet()

def encrypt_profile(obj: dict) -> str:
    if FERNET: 
        return FERNET.encrypt(json.dumps(obj).encode("utf-8")).decode("utf-8")
    return json.dumps(obj) # Fallback to plaintext if Fernet fails

def decrypt_profile(s: str) -> dict:
    if FERNET:
        try: 
            return json.loads(FERNET.decrypt(s.encode("utf-8")))
        except Exception: 
            return {} # Decryption failed
    # Fallback for plaintext
    try: 
        return json.loads(s)
    except json.JSONDecodeError: 
        return {}

def load_profiles():
    if not CONFIG.PROFILES_FILE.exists(): return {}
    try:
        raw = json.load(CONFIG.PROFILES_FILE.open(encoding="utf-8"))
        profiles = {name: decrypt_profile(token) for name, token in raw.items()}
        return {k: v for k, v in profiles.items() if v} # Filter out empty/failed
    except (IOError, json.JSONDecodeError): return {}

def save_profiles(profiles: dict):
    out = {name: encrypt_profile(creds) for name, creds in profiles.items()}
    try: 
        CONFIG.PROFILES_FILE.write_text(json.dumps(out, indent=2), encoding="utf-8")
    except IOError: 
        messagebox.showerror("Save Error", "Could not save profiles to disk.")

# --- NEW FEATURE: Run on Startup ---
REG_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_VALUE_NAME = CONFIG.APP_NAME

def is_startup_enabled() -> bool:
    """Check if the app is set to run at startup."""
    if not winreg: return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, REG_VALUE_NAME)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False

def set_startup(enable: bool):
    """Enable or disable running the app at startup."""
    if not winreg:
        messagebox.showwarning("Feature Not Available", "This feature is only available on Windows.")
        return
    
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0, winreg.KEY_WRITE) as key:
            if enable:
                # Get the full path to the running .exe
                # In a packaged app (PyInstaller), sys.argv[0] is the .exe path
                exe_path = f'"{sys.argv[0]}" --startup'
                winreg.SetValueEx(key, REG_VALUE_NAME, 0, winreg.REG_SZ, exe_path)
            else:
                winreg.DeleteValue(key, REG_VALUE_NAME)
    except FileNotFoundError:
        if not enable: pass # Trying to delete a key that doesn't exist
    except Exception as e:
        messagebox.showerror("Registry Error", f"Could not modify startup settings. Do you have permissions?\n{e}")
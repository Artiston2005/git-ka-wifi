import csv
import json
import socket
import sys
from datetime import datetime
from tkinter import messagebox
from config import CONFIG, SETTINGS 

# --- NEW FEATURE: Run on Startup ---
try:
    import winreg
except ImportError:
    winreg = None 

# --- End New Feature ---

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None

# --- MODERN NOTIFICATIONS: winotify ---
try:
    from winotify import Notification, audio
    HAS_WINOTIFY = True
except ImportError:
    HAS_WINOTIFY = False

try:
    from plyer import notification as plyer_notify
except ImportError:
    plyer_notify = None

# --- NEW FEATURE: Robust Single Instance (Mutex) ---
try:
    import win32event
    import win32api
    import winerror
except ImportError:
    win32event = None

_mutex_handle = None

def check_for_lock():
    """
    Uses a Windows Named Mutex to ensure only one instance runs.
    """
    global _mutex_handle
    
    if not win32event:
        return _check_for_lock_socket_fallback()

    mutex_name = "Global\\GitKaWifi_Instance_Lock_v1"
    
    try:
        _mutex_handle = win32event.CreateMutex(None, False, mutex_name)
        last_error = win32api.GetLastError()
        if last_error == winerror.ERROR_ALREADY_EXISTS:
            return False 
        return True
    except Exception:
        return False

def _check_for_lock_socket_fallback():
    """Legacy fallback method using sockets."""
    LOCK_PORT = 12345
    global _mutex_handle 
    _mutex_handle = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _mutex_handle.bind(("127.0.0.1", LOCK_PORT))
        return True
    except socket.error:
        _mutex_handle = None
        return False

def get_lock_socket():
    return _mutex_handle

def append_log(action, details=""):
    ts = datetime.now().isoformat(sep=" ", timespec="seconds")
    try:
        # Log Rotation: Keep file size under 1MB
        if CONFIG.LOG_FILE.exists() and CONFIG.LOG_FILE.stat().st_size > 1024 * 1024:
            try:
                content = CONFIG.LOG_FILE.read_text(encoding="utf-8").splitlines()
                if len(content) > 1000:
                    new_content = "\n".join(content[-1000:]) + "\n"
                    CONFIG.LOG_FILE.write_text(new_content, encoding="utf-8")
            except Exception:
                pass 

        with open(CONFIG.LOG_FILE, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([ts, action, details])
    except IOError: pass

def notify(title, msg):
    """
    Sends a notification using winotify (modern Windows API).
    """
    try:
        if HAS_WINOTIFY:
            toast = Notification(
                app_id=CONFIG.APP_NAME,
                title=title,
                msg=msg,
                duration="short",
                icon=str(CONFIG.ICON_PNG.absolute()) if CONFIG.ICON_PNG.exists() else ""
            )
            # Optional: Add a sound
            toast.set_audio(audio.Default, loop=False)
            toast.show()
            return

        # Fallback to plyer if winotify isn't installed (e.g. non-Windows)
        if plyer_notify:
            plyer_notify.notify(title=title, message=msg, app_name=CONFIG.APP_NAME)
            
    except Exception as e:
        print(f"[Notification Failed] {title}: {msg} ({e})")

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
    return json.dumps(obj) 

def decrypt_profile(s: str) -> dict:
    if FERNET:
        try: 
            return json.loads(FERNET.decrypt(s.encode("utf-8")))
        except Exception: 
            return {} 
    try: 
        return json.loads(s)
    except json.JSONDecodeError: 
        return {}

def load_profiles():
    if not CONFIG.PROFILES_FILE.exists(): return {}
    try:
        raw = json.load(CONFIG.PROFILES_FILE.open(encoding="utf-8"))
        profiles = {name: decrypt_profile(token) for name, token in raw.items()}
        return {k: v for k, v in profiles.items() if v} 
    except (IOError, json.JSONDecodeError): return {}

def save_profiles(profiles: dict):
    out = {name: encrypt_profile(creds) for name, creds in profiles.items()}
    try: 
        CONFIG.PROFILES_FILE.write_text(json.dumps(out, indent=2), encoding="utf-8")
    except IOError: 
        messagebox.showerror("Save Error", "Could not save profiles to disk.")

# --- Run on Startup ---
REG_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_VALUE_NAME = CONFIG.APP_NAME

def is_startup_enabled() -> bool:
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
    if not winreg:
        messagebox.showwarning("Feature Not Available", "This feature is only available on Windows.")
        return
    
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0, winreg.KEY_WRITE) as key:
            if enable:
                exe_path = f'"{sys.argv[0]}" --startup'
                winreg.SetValueEx(key, REG_VALUE_NAME, 0, winreg.REG_SZ, exe_path)
            else:
                winreg.DeleteValue(key, REG_VALUE_NAME)
    except FileNotFoundError:
        if not enable: pass 
    except Exception as e:
        messagebox.showerror("Registry Error", f"Could not modify startup settings.\n{e}")
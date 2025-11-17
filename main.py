import argparse
import gc
import platform
import socket # For diagnostics
import subprocess
import sys
import threading
import json
import time
import webbrowser
from datetime import datetime
from tkinter import PhotoImage, filedialog, messagebox, simpledialog

import ttkbootstrap as ttk
from ttkbootstrap.constants import *

# --- Local Imports from our new files ---
from config import CONFIG, SETTINGS
from forti_client import FortiClient
from utils import (append_log, check_for_lock, get_lock_socket, load_profiles,
                   notify, save_profiles, is_startup_enabled, set_startup)

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    pystray = None
try:
    import keyboard
except ImportError:
    keyboard = None
try:
    import speedtest
except ImportError:
    speedtest = None


class FortiApp:
    def __init__(self, root, start_silently=False):
        self.root = root
        self.root.title(CONFIG.APP_NAME)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        try: self.root.state("zoomed")
        except: self.root.geometry("1366x768")

        self.client = FortiClient()
        self.profiles = load_profiles()
        self.tray_icon = None
        self._threads_stop_event = threading.Event()
        
        self._network_pause_event = threading.Event() 
        self._network_pause_event.set() # Start in a "paused" state
        
        self.network_threads_active = False
        
        self.app_initialized = False # Flag to track if UI is built
        self.start_silently = start_silently

        self.log_history = [] 
        self.log_filter_var = ttk.StringVar(value="All")
        
        # --- START FIX ---
        # This is the new "single source of truth".
        # We check if a session file *already* exists on startup.
        self.is_online = CONFIG.SESSION_FILE.exists()
        # This lock protects session state and file access
        self.session_lock = threading.Lock()
        # --- END FIX ---

        threading.Thread(target=self.background_monitor_worker, daemon=True).start()

    def _initialize_app(self):
        """Builds the UI, sets up tray, and starts background threads."""
        if self.app_initialized:
            return
        self.app_initialized = True
        
        self.log("Initializing application UI and services...", level="DEBUG")
        
        self.build_ui()
        self.setup_tray()
        self.setup_hotkey()

        self.start_background_threads()
        
        if self.start_silently:
            self.log("Started silently in the background.")
        
        self.log("Application initialization complete.")
        
        if not self.profiles:
            self.root.after(200, self._show_onboarding_wizard)
        else:
            self.root.after(200, self.start_app_flow)
        
        gc.collect() 

    def _get_current_ssid(self) -> str | None:
        system = platform.system()
        try:
            if system == "Windows":
                proc = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=3, check=True, creationflags=0x08000000)
                for line in proc.stdout.split('\n'):
                    if "SSID" in line and ":" in line:
                        ssid = line.split(":", 1)[1].strip()
                        if ssid: return ssid
            elif system == "Darwin":
                cmd = ["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"]
                proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=3, check=True)
                for line in proc.stdout.split('\n'):
                    if "SSID" in line and ":" in line:
                        ssid = line.split(":", 1)[1].strip()
                        if ssid: return ssid
            elif system == "Linux":
                cmd = ["iwgetid", "-r"]
                proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=3, check=True)
                ssid = proc.stdout.strip()
                if ssid: return ssid
        except Exception:
            return None
        return None

    # --- START: MODIFIED/FIXED BACKGROUND WORKER ---
    def background_monitor_worker(self):
        """
        Monitors Wi-Fi SSID and pauses/resumes network threads.
        This worker NO LONGER probes the connection.
        """
        self.log("Background Monitor started.", level="DEBUG")
        self._threads_stop_event.wait(2) 

        while not self._threads_stop_event.is_set():
            ssid = self._get_current_ssid()
            is_git_network = ssid and "git" in ssid.lower()

            if is_git_network:
                if not self.app_initialized:
                    self.root.after(0, self._initialize_app)
                
                if not self.network_threads_active:
                    self.log(f"Git network '{ssid}' detected. Resuming operations.")
                    self.network_threads_active = True
                    self._network_pause_event.clear() # UN-PAUSE
                    self.root.after(0, self.root.deiconify)
                    notify(CONFIG.APP_NAME, f"Connected to '{ssid}'. Resuming.")
                    
            else:
                if self.network_threads_active:
                    self.log(f"Non-Git network ('{ssid}') detected. Pausing operations.")
                    self.network_threads_active = False
                    self._network_pause_event.set() # PAUSE
                    self.root.after(0, self.root.withdraw)
                    notify(CONFIG.APP_NAME, f"Paused: Not on a Git network.")
            
            # --- BUGGY CODE BLOCK IS NOW REMOVED ---
            # The session probe logic that was here is gone.
            # This fixes the race condition.
            # --- END OF FIX ---
            
            self._threads_stop_event.wait(SETTINGS.get("session_probe_interval_s"))
        
        self.log("Background Monitor stopped.", level="DEBUG")
    # --- END: MODIFIED/FIXED BACKGROUND WORKER ---

    def start_app_flow(self):
        self.root.after(500, self.refresh_status_ui)
        self.root.after(700, self.initiate_startup_login)

    def build_ui(self):
        top_frame = ttk.Frame(self.root, padding=(10, 5))
        top_frame.pack(fill=X, side=TOP)
        ttk.Label(top_frame, text=CONFIG.APP_NAME, font=("Segoe UI", 18, "bold")).pack(side=LEFT, padx=5)
        self.status_progressbar = ttk.Progressbar(top_frame, mode='indeterminate', length=200)
        self.status_label = ttk.Label(top_frame, text="", font=("Segoe UI", 9))
        
        btn_frame_top = ttk.Frame(top_frame)
        btn_frame_top.pack(side=RIGHT)
        
        ttk.Button(btn_frame_top, text="⚙️ Settings", command=self._create_settings_window, bootstyle="outline-secondary").pack(side=RIGHT, padx=(5,10))
        ttk.Separator(btn_frame_top, orient=VERTICAL).pack(side=RIGHT, fill=Y, padx=5, pady=5)
        ttk.Button(btn_frame_top, text="LinkedIn", command=self._open_linkedin_link, bootstyle="outline-info").pack(side=RIGHT, padx=5)
        ttk.Button(btn_frame_top, text="GitHub", command=self._open_github_link, bootstyle="outline-info").pack(side=RIGHT, padx=5)
        ttk.Label(btn_frame_top, text="About Developer: Ashwin Yadav").pack(side=RIGHT, padx=10)
        
        main = ttk.Frame(self.root, padding=(12, 8))
        main.pack(fill=BOTH, expand=True)
        sidebar = self._create_sidebar(main)
        sidebar.pack(side=LEFT, fill=Y, padx=(0, 12))
        dashboard = self._create_dashboard(main)
        dashboard.pack(side=RIGHT, fill=BOTH, expand=True)

    def _create_sidebar(self, parent):
        sidebar = ttk.Frame(parent, width=380)
        profile_frame = ttk.Labelframe(sidebar, text="Profile Management", padding=10); profile_frame.pack(fill=X, pady=(0, 10))
        self.profile_cb = ttk.Combobox(profile_frame, state="readonly", values=list(self.profiles.keys())); self.profile_cb.pack(fill=X, pady=6)
        self.profile_cb.bind("<<ComboboxSelected>>", lambda e: self.on_profile_selected())
        
        btn_frame = ttk.Frame(profile_frame); btn_frame.pack(fill=X, pady=4)
        ttk.Button(btn_frame, text="New", command=self.new_profile, bootstyle="info").pack(side=LEFT, expand=True, fill=X, padx=2)
        ttk.Button(btn_frame, text="Delete", command=self.delete_profile, bootstyle="warning").pack(side=LEFT, expand=True, fill=X, padx=2)
        btn_frame2 = ttk.Frame(profile_frame); btn_frame2.pack(fill=X, pady=4)
        ttk.Button(btn_frame2, text="Import", command=self.import_profiles, bootstyle="outline-secondary").pack(side=LEFT, expand=True, fill=X, padx=2)
        ttk.Button(btn_frame2, text="Export", command=self.export_profiles, bootstyle="outline-secondary").pack(side=LEFT, expand=True, fill=X, padx=2)

        creds_frame = ttk.Labelframe(sidebar, text="Credentials & Actions", padding=10); creds_frame.pack(fill=X, pady=5)
        ttk.Label(creds_frame, text="Username:").pack(anchor=W); self.user_var = ttk.StringVar()
        ttk.Entry(creds_frame, textvariable=self.user_var).pack(fill=X, pady=2)
        ttk.Label(creds_frame, text="Password:").pack(anchor=W); self.pass_var = ttk.StringVar()
        pass_entry = ttk.Entry(creds_frame, textvariable=self.pass_var, show="*"); pass_entry.pack(fill=X, pady=2)
        show_pass_var = ttk.BooleanVar(); ttk.Checkbutton(creds_frame, text="Show", variable=show_pass_var, bootstyle="square-toggle", command=lambda: pass_entry.config(show="" if show_pass_var.get() else "*")).pack(anchor=E, pady=2)

        ttk.Button(creds_frame, text="Save Profile", command=self.save_profile, bootstyle="success").pack(fill=X, pady=8)
        self.login_btn = ttk.Button(creds_frame, text="🔑 Login", command=lambda: self._initiate_login(user=self.user_var.get(), pwd=self.pass_var.get()), bootstyle="primary"); self.login_btn.pack(fill=X, pady=4)
        self.relogin_btn = ttk.Button(creds_frame, text="🔁 Relogin", command=self._initiate_login, bootstyle="outline-info"); self.relogin_btn.pack(fill=X, pady=4)
        self.logout_btn = ttk.Button(creds_frame, text="🚪 Logout", command=self.btn_logout, bootstyle="danger"); self.logout_btn.pack(fill=X, pady=4)
        
        auto_frame = ttk.Labelframe(sidebar, text="Automation", padding=10); auto_frame.pack(fill=X, pady=10)
        self.autologin_var = ttk.BooleanVar(); ttk.Checkbutton(auto_frame, text="Auto-login this profile at startup", variable=self.autologin_var).pack(anchor=W, pady=4)
        self.keepalive_var = ttk.BooleanVar(value=True); ttk.Checkbutton(auto_frame, text="Enable Auto Keepalive", variable=self.keepalive_var).pack(anchor=W)
        self.autorelogin_var = ttk.BooleanVar(value=True); ttk.Checkbutton(auto_frame, text="Enable Auto Relogin on disconnect", variable=self.autorelogin_var).pack(anchor=W, pady=4)
        return sidebar

    def _create_dashboard(self, parent):
        dashboard = ttk.Frame(parent)
        cards = ttk.Frame(dashboard); cards.pack(fill=X, pady=(0, 8))
        card_style = {"padding": 12, "bootstyle": "light"}
        
        self.card_status = ttk.Frame(cards, **card_style); self.card_status.pack(side=LEFT, padx=6, expand=True, fill=X)
        ttk.Label(self.card_status, text="Connection Status", font=("Segoe UI", 10, "bold")).pack(anchor=W)
        self.conn_label = ttk.Label(self.card_status, text="Checking...", font=("Segoe UI", 16)); self.conn_label.pack(anchor=W, pady=(6, 0))
        
        self.card_user = ttk.Frame(cards, **card_style); self.card_user.pack(side=LEFT, padx=6, expand=True, fill=X)
        ttk.Label(self.card_user, text="Active Profile", font=("Segoe UI", 10, "bold")).pack(anchor=W)
        self.active_user_label = ttk.Label(self.card_user, text="—", font=("Segoe UI", 14)); self.active_user_label.pack(anchor=W, pady=(6, 0))
        
        self.card_token = ttk.Frame(cards, **card_style); self.card_token.pack(side=LEFT, padx=6, expand=True, fill=X)
        ttk.Label(self.card_token, text="Session Token", font=("Segoe UI", 10, "bold")).pack(anchor=W)
        self.token_label = ttk.Label(self.card_token, text="—", font=("Segoe UI", 12)); self.token_label.pack(anchor=W, pady=(6, 0))
        
        notebook = ttk.Notebook(dashboard); notebook.pack(fill=BOTH, expand=True, padx=6, pady=6)
        
        log_tab = ttk.Frame(notebook, padding=10)
        
        self.info_text = ttk.Text(log_tab, height=5, font=("Consolas", 9), state=DISABLED); self.info_text.pack(fill=X, padx=8, pady=6)
        
        log_filter_frame = ttk.Frame(log_tab); log_filter_frame.pack(fill=X, padx=8, pady=(0, 5))
        self.log_filter_var.set("All")
        btn_all = ttk.Radiobutton(log_filter_frame, text="All", variable=self.log_filter_var, value="All", command=self._on_log_filter_change, bootstyle="outline-toolbutton")
        btn_all.pack(side=LEFT, padx=2)
        btn_info = ttk.Radiobutton(log_filter_frame, text="Info", variable=self.log_filter_var, value="INFO", command=self._on_log_filter_change, bootstyle="outline-toolbutton")
        btn_info.pack(side=LEFT, padx=2)
        btn_warn = ttk.Radiobutton(log_filter_frame, text="Warning", variable=self.log_filter_var, value="WARNING", command=self._on_log_filter_change, bootstyle="outline-toolbutton-warning")
        btn_warn.pack(side=LEFT, padx=2)
        btn_err = ttk.Radiobutton(log_filter_frame, text="Error", variable=self.log_filter_var, value="ERROR", command=self._on_log_filter_change, bootstyle="outline-toolbutton-danger")
        btn_err.pack(side=LEFT, padx=2)
        
        log_tree_frame = ttk.Frame(log_tab); log_tree_frame.pack(fill=BOTH, expand=True, padx=8, pady=6)
        log_cols = ("time", "level", "message")
        self.log_tree = ttk.Treeview(log_tree_frame, columns=log_cols, show="headings", height=10)
        
        self.log_tree.heading("time", text="Time", anchor=W)
        self.log_tree.heading("level", text="Level", anchor=W)
        self.log_tree.heading("message", text="Message", anchor=W)
        
        self.log_tree.column("time", width=80, stretch=False, anchor=W)
        self.log_tree.column("level", width=80, stretch=False, anchor=W)
        self.log_tree.column("message", width=600, stretch=True, anchor=W)
        
        log_scroll = ttk.Scrollbar(log_tree_frame, orient=VERTICAL, command=self.log_tree.yview)
        self.log_tree.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side=RIGHT, fill=Y)
        self.log_tree.pack(side=LEFT, fill=BOTH, expand=True)
        
        self.log_tree.tag_configure("ERROR", background="#8B0000", foreground="white") # Dark Red
        self.log_tree.tag_configure("WARNING", background="#FF8C00", foreground="black") # Dark Orange
        self.log_tree.tag_configure("DEBUG", foreground="grey")
        
        notebook.add(log_tab, text="Session & Logs")
        
        perf_tab = ttk.Frame(notebook, padding=10)
        scrape_frame = ttk.Labelframe(perf_tab, text="Live Session Stats", padding=10); scrape_frame.pack(fill=X, pady=5)
        self.data_usage_label = ttk.Label(scrape_frame, text="Data Usage: —", font=("Segoe UI", 12)); self.data_usage_label.pack(anchor=W)
        self.time_left_label = ttk.Label(scrape_frame, text="Time Remaining: —", font=("Segoe UI", 12)); self.time_left_label.pack(anchor=W, pady=5)
        
        speed_frame = ttk.Labelframe(perf_tab, text="Network Speed", padding=10); speed_frame.pack(fill=X, pady=10)
        self.speed_dl_label = ttk.Label(speed_frame, text="Download: —", font=("Segoe UI", 12)); self.speed_dl_label.pack(anchor=W)
        self.speed_ul_label = ttk.Label(speed_frame, text="Upload: —", font=("Segoe UI", 12)); self.speed_ul_label.pack(anchor=W, pady=5)
        self.speed_ping_label = ttk.Label(speed_frame, text="Ping: —", font=("Segoe UI", 12)); self.speed_ping_label.pack(anchor=W)
        speed_btn_text = "📶 Run Speed Test" if speedtest else "Speed Test (speedtest-cli not installed)"; speed_btn_state = NORMAL if speedtest else DISABLED
        self.run_speed_btn = ttk.Button(speed_frame, text=speed_btn_text, command=self._run_speed_test_thread, bootstyle="outline-info", state=speed_btn_state); self.run_speed_btn.pack(pady=10)
        notebook.add(perf_tab, text="Performance")
        
        diag_tab = ttk.Frame(notebook, padding=10)
        self.diag_btn = ttk.Button(diag_tab, text="🩺 Run Diagnostics", command=self._run_diagnostics, bootstyle="info")
        self.diag_btn.pack(pady=10)
        self.diag_log = ttk.ScrolledText(diag_tab, height=10, font=("Consolas", 9), state=DISABLED, wrap=WORD)
        self.diag_log.pack(fill=BOTH, expand=True, padx=8, pady=6)
        notebook.add(diag_tab, text="Diagnostics")
        
        return dashboard

    def _show_onboarding_wizard(self):
        dialog = ttk.Toplevel(self.root); dialog.title("Welcome!"); dialog.transient(self.root); dialog.grab_set(); dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=20); frame.pack(fill=BOTH, expand=True)
        ttk.Label(frame, text="Let's create your first profile.", font=("Segoe UI", 14, "bold")).pack(pady=(0, 10))
        
        ttk.Label(frame, text="Profile Name:").pack(anchor=W); name_var = ttk.StringVar()
        ttk.Entry(frame, textvariable=name_var).pack(fill=X, pady=2)
        ttk.Label(frame, text="Username:").pack(anchor=W); user_var = ttk.StringVar()
        ttk.Entry(frame, textvariable=user_var).pack(fill=X, pady=2)
        ttk.Label(frame, text="Password:").pack(anchor=W); pass_var = ttk.StringVar()
        ttk.Entry(frame, textvariable=pass_var, show="*").pack(fill=X, pady=2)
        
        def save_and_start():
            name, user, pwd = name_var.get().strip(), user_var.get().strip(), pass_var.get()
            if not all([name, user, pwd]): return messagebox.showerror("Error", "All fields are required.", parent=dialog)
            self.profiles[name] = {"username": user, "password": pwd, "autologin": True}
            save_profiles(self.profiles); self.update_profile_list_and_select(name); dialog.destroy()
            self.start_app_flow()
            
        ttk.Button(frame, text="Save & Get Started", command=save_and_start, bootstyle="success").pack(pady=20)
        dialog.wait_window()

    def _create_settings_window(self):
        win = ttk.Toplevel(self.root); win.title("Settings"); win.transient(self.root); win.grab_set(); win.resizable(False, False)
        
        notebook = ttk.Notebook(win, padding=10); notebook.pack(fill=BOTH, expand=True)
        net_tab = ttk.Frame(notebook, padding=10)
        auto_tab = ttk.Frame(notebook, padding=10)
        app_tab = ttk.Frame(notebook, padding=10) # New tab for app settings
        notebook.add(net_tab, text="Network"); notebook.add(auto_tab, text="Automation"); notebook.add(app_tab, text="Application")
        
        # --- Network Tab ---
        ttk.Label(net_tab, text="Target SSIDs (comma-separated):").pack(anchor=W)
        ssid_var = ttk.StringVar(value=",".join(SETTINGS.get("target_ssids")))
        ttk.Entry(net_tab, textvariable=ssid_var).pack(fill=X, pady=2, padx=5)

        ttk.Label(net_tab, text="Probe URLs (comma-separated):").pack(anchor=W, pady=(10,0))
        probe_var = ttk.StringVar(value=",".join(SETTINGS.get("probe_urls")))
        ttk.Entry(net_tab, textvariable=probe_var).pack(fill=X, pady=2, padx=5)

        ttk.Label(net_tab, text="User-Agent String:").pack(anchor=W, pady=(10,0))
        ua_var = ttk.StringVar(value=SETTINGS.get("user_agent")); ttk.Entry(net_tab, textvariable=ua_var).pack(fill=X, pady=2, padx=5)
        
        f = ttk.Frame(net_tab); f.pack(fill=X, pady=(10,0))
        ttk.Label(f, text="Keepalive Interval (s):").pack(side=LEFT, anchor=W)
        keep_var = ttk.IntVar(value=SETTINGS.get("keepalive_interval_s")); ttk.Spinbox(f, from_=5, to=300, textvariable=keep_var, width=8).pack(side=LEFT, padx=5)
        ttk.Label(f, text="Session Probe Interval (s):").pack(side=LEFT, anchor=W, padx=(10,0))
        probe_int_var = ttk.IntVar(value=SETTINGS.get("session_probe_interval_s")); ttk.Spinbox(f, from_=10, to=600, textvariable=probe_int_var, width=8).pack(side=LEFT, padx=5)
        
        # --- Automation Tab ---
        speed_var = ttk.BooleanVar(value=SETTINGS.get("run_speedtest_on_login")); ttk.Checkbutton(auto_tab, text="Run speed test automatically after login", variable=speed_var).pack(anchor=W, pady=5, padx=5)
        ttk.Label(auto_tab, text="Regex for Data Usage:").pack(anchor=W, pady=(10,0))
        usage_regex_var = ttk.StringVar(value=SETTINGS.get("scrape_data_usage_regex")); ttk.Entry(auto_tab, textvariable=usage_regex_var).pack(fill=X, pady=2, padx=5)
        ttk.Label(auto_tab, text="Regex for Time Remaining:").pack(anchor=W, pady=(10,0))
        time_regex_var = ttk.StringVar(value=SETTINGS.get("scrape_time_left_regex")); ttk.Entry(auto_tab, textvariable=time_regex_var).pack(fill=X, pady=2, padx=5)

        # --- NEW FEATURE: Application Tab ---
        # Theme Selector
        ttk.Label(app_tab, text="Application Theme:").pack(anchor=W, padx=5)
        theme_var = ttk.StringVar(value=SETTINGS.get("theme"))
        theme_names = self.root.style.theme_names()
        theme_cb = ttk.Combobox(app_tab, textvariable=theme_var, values=theme_names, state="readonly")
        theme_cb.pack(fill=X, pady=(2, 10), padx=5)

        # Run on Startup
        self.startup_var = ttk.BooleanVar(value=is_startup_enabled())
        startup_check = ttk.Checkbutton(app_tab, text="Run on Windows startup", variable=self.startup_var)
        startup_check.pack(anchor=W, pady=5, padx=5)
        if "winreg" not in sys.modules:
            startup_check.config(state=DISABLED)
        # --- End New Feature ---


        def save_settings():
            # Save Network
            SETTINGS.set("target_ssids", [s.strip() for s in ssid_var.get().split(',') if s.strip()])
            SETTINGS.set("probe_urls", [u.strip() for u in probe_var.get().split(',') if u.strip()])
            SETTINGS.set("user_agent", ua_var.get())
            SETTINGS.set("keepalive_interval_s", keep_var.get()); 
            SETTINGS.set("session_probe_interval_s", probe_int_var.get())
            
            # Save Automation
            SETTINGS.set("run_speedtest_on_login", speed_var.get()); 
            SETTINGS.set("scrape_data_usage_regex", usage_regex_var.get())
            SETTINGS.set("scrape_time_left_regex", time_regex_var.get())
            
            # --- NEW FEATURE: Save App Settings ---
            # Save Startup
            set_startup(self.startup_var.get())

            # Save Theme
            old_theme = SETTINGS.get("theme")
            new_theme = theme_var.get()
            SETTINGS.set("theme", new_theme)
            # --- End New Feature ---

            SETTINGS.save()
            self.client.update_headers()
            self.log("Settings saved.")
            win.destroy()
            
            if old_theme != new_theme:
                messagebox.showinfo("Theme Changed", "Please restart the application to apply the new theme.")

            
        btn_frame = ttk.Frame(win, padding=10); btn_frame.pack(fill=X)
        ttk.Button(btn_frame, text="Save & Close", command=save_settings, bootstyle="success").pack(side=RIGHT)
        ttk.Button(btn_frame, text="Cancel", command=win.destroy).pack(side=RIGHT, padx=5)

    def set_ui_busy(self, is_busy, message=""):
        if is_busy:
            self.status_label.config(text=message)
            
            # --- FIX ---
            # We must pack the progressbar *before* the label,
            # otherwise the label has nothing to be 'before'.
            self.status_progressbar.pack(side=LEFT, padx=(0, 5)) 
            self.status_progressbar.start()
            self.status_label.pack(side=LEFT, padx=(10, 0))
            # --- END FIX ---
            
            for btn in [self.login_btn, self.logout_btn, self.relogin_btn]: btn.config(state=DISABLED)
            if self.tray_icon: self.tray_icon.title = f"{CONFIG.APP_NAME} - {message}"
        else:
            self.status_progressbar.stop()
            self.status_progressbar.pack_forget()
            self.status_label.pack_forget()
            for btn in [self.login_btn, self.logout_btn, self.relogin_btn]: btn.config(state=NORMAL)
            self.refresh_status_ui() 
        self.root.update_idletasks()

    def log(self, text, level="INFO"):
        if not self.app_initialized:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [{level.upper()}] {text}")
            return

        ts = datetime.now().strftime("%H:%M:%S")
        level = level.upper()
        log_entry = {"time": ts, "level": level, "message": text}
        
        self.log_history.append(log_entry)
        append_log(level, text)
        
        current_filter = self.log_filter_var.get()
        if current_filter == "All" or log_entry["level"] == current_filter:
            self.root.after(0, self._insert_log_entry, log_entry)

    def _insert_log_entry(self, entry: dict):
        if not self.app_initialized:
            return
            
        try:
            tags = (entry["level"],)
            item_id = self.log_tree.insert("", END, values=(entry["time"], entry["level"], entry["message"]), tags=tags)
            self.log_tree.see(item_id)
        except Exception as e:
            print(f"Failed to insert log entry into Treeview: {e}")

    def _on_log_filter_change(self):
        current_filter = self.log_filter_var.get()
        self.log_tree.delete(*self.log_tree.get_children())
        
        for entry in self.log_history:
            if current_filter == "All" or entry["level"] == current_filter:
                self._insert_log_entry(entry)

    def refresh_status_ui(self):
        if not self.app_initialized: return
        
        tray_title = f"{CONFIG.APP_NAME} - Offline"

        # --- START FIX: Non-blocking Lock ---
        # Check if we are theoretically online
        if self.is_online:
            # Try to acquire the lock WITHOUT blocking.
            # If we can't get it (because keepalive is running), we just SKIP this update.
            # This prevents the UI from freezing.
            if self.session_lock.acquire(blocking=False):
                try:
                    # We have the lock, safe to read the file
                    if CONFIG.SESSION_FILE.exists():
                        s = json.loads(CONFIG.SESSION_FILE.read_text(encoding="utf-8"))
                        ts, token, ka_url = s.get("timestamp"), s.get("token"), s.get("keepalive_url")
                        if not all([ts, token, ka_url]): raise ValueError("Incomplete session file")
                        
                        # --- Success block ---
                        self.conn_label.config(text="Online", bootstyle="success"); self.token_label.config(text=f"{token[:10]}...")
                        info = f"Logged In At: {ts}\nKeepalive URL: {ka_url}\nToken: {token}"
                        self.info_text.config(state=NORMAL); self.info_text.delete("1.0", END); self.info_text.insert("1.0", info); self.info_text.config(state=DISABLED)
                        
                        tray_title = f"{CONFIG.APP_NAME} - Online" 
                        if self.tray_icon: self.tray_icon.title = tray_title
                        return # Done, success
                
                except (IOError, json.JSONDecodeError, ValueError) as e: 
                    self.log(f"Session file corrupt, resetting state. {e}", level="WARNING")
                    self.is_online = False
                    CONFIG.SESSION_FILE.unlink(missing_ok=True)
                
                finally:
                    self.session_lock.release() # Always release!
            else:
                # Lock was busy. We simply return and keep the old UI state.
                # This keeps the window responsive.
                return 

        # --- Fallback / Offline Block ---
        self.conn_label.config(text="Offline", bootstyle="danger"); self.token_label.config(text="—")
        self.info_text.config(state=NORMAL); self.info_text.delete("1.0", END); self.info_text.insert("1.0", "No active session."); self.info_text.config(state=DISABLED)
        if self.tray_icon: self.tray_icon.title = tray_title

    def new_profile(self):
        name = simpledialog.askstring("New Profile", "Enter a name for the new profile:", parent=self.root)
        if not name or not name.strip(): return
        if name in self.profiles: return messagebox.showerror("Error", f"Profile '{name}' already exists.")
        self.profiles[name] = {"username": "", "password": "", "autologin": False}; self.update_profile_list_and_select(name); self.log(f"Created profile '{name}'")
    
    def delete_profile(self):
        name = self.profile_cb.get()
        if not name: return messagebox.showwarning("No Selection", "Please select a profile to delete.")
        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete profile '{name}'?"):
            del self.profiles[name]; save_profiles(self.profiles); self.profile_cb['values'] = list(self.profiles.keys())
            self.profile_cb.set(""); self.user_var.set(""); self.pass_var.set(""); self.autologin_var.set(False); self.active_user_label.config(text="—")
            self.log(f"Deleted profile '{name}'")

    def import_profiles(self):
        path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")]);
        if not path: return
        try:
            with open(path, "r", encoding="utf-8") as f: imported = json.load(f)
            if not isinstance(imported, dict): raise ValueError("Invalid format")
            from utils import decrypt_profile 
            decrypted = {name: decrypt_profile(token) for name, token in imported.items()}
            self.profiles.update({k:v for k,v in decrypted.items() if v}); save_profiles(self.profiles)
            self.profile_cb['values'] = list(self.profiles.keys()); self.log(f"Imported {len(imported)} profiles"); messagebox.showinfo("Success", "Profiles imported.")
        except (IOError, json.JSONDecodeError, ValueError) as e: messagebox.showerror("Import Failed", f"Could not import profiles: {e}")

    def export_profiles(self):
        if not self.profiles: return messagebox.showwarning("No Profiles", "There are no profiles to export.")
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files", "**.json")]);
        if not path: return
        try:
            from utils import encrypt_profile 
            import json 
            encrypted = {name: encrypt_profile(data) for name, data in self.profiles.items()}
            with open(path, "w", encoding="utf-8") as f: json.dump(encrypted, f, indent=2)
            self.log(f"Exported {len(self.profiles)} profiles"); messagebox.showinfo("Success", "Profiles exported.")
        except IOError as e: messagebox.showerror("Export Failed", f"Could not export: {e}")

    def save_profile(self):
        name = self.profile_cb.get()
        if not name: return messagebox.showwarning("No Profile", "Select or create a profile first.")
        if self.autologin_var.get():
            for p_name, p_data in self.profiles.items():
                if p_name != name: p_data['autologin'] = False
        self.profiles[name] = {"username": self.user_var.get(), "password": self.pass_var.get(), "autologin": self.autologin_var.get()}
        save_profiles(self.profiles); self.log(f"Saved profile '{name}'"); messagebox.showinfo("Saved", f"Profile '{name}' has been saved.", parent=self.root)

    def on_profile_selected(self, event=None):
        name = self.profile_cb.get()
        if not name: return
        data = self.profiles.get(name, {}); self.user_var.set(data.get("username", "")); self.pass_var.set(data.get("password", ""))
        self.autologin_var.set(data.get("autologin", False)); self.active_user_label.config(text=data.get("username", "—")); self.log(f"Loaded profile '{name}'")

    def update_profile_list_and_select(self, name):
        if name in self.profiles:
            self.profile_cb['values'] = list(self.profiles.keys()); self.profile_cb.set(name); self.on_profile_selected()
        else:
            self.log(f"Cannot select profile '{name}' because it does not exist.", level="ERROR")

    def _initiate_login(self, user=None, pwd=None):
        if user is None or pwd is None:
            name = self.profile_cb.get()
            if not name: 
                messagebox.showwarning("No Profile", "Please select a profile to log in.")
                return
            creds = self.profiles.get(name, {})
            user, pwd = creds.get("username"), creds.get("password")
            if not user or not pwd: 
                messagebox.showwarning("Incomplete Profile", "Profile is missing credentials.")
                return
            self.log(f"Initiating login for profile: {name}...")
        else:
            if not user.strip() or not pwd: 
                messagebox.showwarning("Missing Credentials", "Username and password required.")
                return
            self.log(f"Initiating login for user: {user}...")
        threading.Thread(target=self._login_thread, args=(user, pwd), daemon=True).start()

    def _login_thread(self, user, pwd):
        self.root.after(0, self.set_ui_busy, True, "Logging in...")
        
        # --- START FIX ---
        # Acquire the lock to prevent keepalive from running
        with self.session_lock:
            ok, msg = self.client.login(user, pwd)
            self.log(f"Login result: {msg}", level="INFO" if ok else "ERROR"); 
            self.is_online = ok # Set our state *while* holding the lock
        # Lock is released here
        # --- END FIX ---
        
        # set_ui_busy(False) will call refresh_status_ui()
        self.root.after(0, self.set_ui_busy, False)
        
        gc.collect() 
        notify(CONFIG.APP_NAME, "Login Successful!" if ok else f"Login Failed: {msg}")
        if ok and SETTINGS.get("run_speedtest_on_login"): self.root.after(500, self._run_speed_test_thread)

    def btn_logout(self):
        self.log("Attempting logout..."); threading.Thread(target=self._logout_thread, daemon=True).start()

    def _logout_thread(self):
        self.root.after(0, self.set_ui_busy, True, "Logging out...")
        
        # --- START FIX ---
        # Acquire the lock to prevent keepalive from running
        with self.session_lock:
            ok, msg = self.client.logout()
            self.log(f"Logout result: {msg}", level="INFO" if ok else "ERROR")
            self.is_online = False # Clear our state
        # Lock is released here
        # --- END FIX ---
        
        self.root.after(0, self.refresh_status_ui); 
        self.root.after(0, self.set_ui_busy, False)
        notify(CONFIG.APP_NAME, "Logout Successful!" if ok else f"Logout Failed: {msg}")

    def start_background_threads(self):
        self._threads_stop_event.clear()
        threading.Thread(target=self.keepalive_worker, daemon=True).start()
        self.log("Background services (Keepalive) started.", level="DEBUG")

    # --- START: MODIFIED KEEPALIVE WORKER ---
    def keepalive_worker(self):
        """
        This worker now also handles disconnects and auto-relogin.
        It uses a non-blocking lock to avoid racing with the login thread.
        """
        while not self._threads_stop_event.is_set():
            if self._network_pause_event.is_set():
                time.sleep(1) 
                continue
            
            # --- START FIX ---
            # We only run keepalive logic if we are supposed to be online.
            if self.keepalive_var.get() and self.is_online:
                
                # Try to acquire the lock *without blocking*.
                # If we can't get it, a login/logout is in progress.
                if self.session_lock.acquire(blocking=False):
                    try:
                        # We have the lock, double-check if we're *still* online
                        if not self.is_online: 
                            continue # State changed while waiting, just skip
                        
                        # Now we can safely run the keepalive
                        ok, msg, scraped_data = self.client.keepalive()
                        
                        if ok:
                            # Keepalive ping was successful
                            self.log(f"Keepalive ping: {msg}", level="DEBUG")
                            if scraped_data: 
                                self.root.after(0, self._update_scraped_data_ui, scraped_data)
                        else: 
                            # Keepalive FAILED. This is the only place we detect a disconnect.
                            self.log(f"Keepalive failed: {msg}", level="WARNING")
                            self.log("Session expired. Invalidating session.", level="WARNING")
                            self.is_online = False
                            
                            self.root.after(0, self.refresh_status_ui)
                            notify(CONFIG.APP_NAME, "Portal session expired.")
                            
                            if self.autorelogin_var.get():
                                self.log("Auto-relogin triggered.", level="WARNING")
                                self.root.after(100, self._initiate_login)
                    finally:
                        self.session_lock.release() # Always release the lock
                else:
                    # Lock is held (login/logout in progress), skip this run.
                    self.log("Login/logout in progress, skipping keepalive cycle.", level="DEBUG")
            # --- END FIX ---
            
            # Wait for the next interval
            self._threads_stop_event.wait(SETTINGS.get("keepalive_interval_s"))

    def initiate_startup_login(self):
        autologin_profile = None
        for name, data in self.profiles.items():
            if data.get("autologin"):
                autologin_profile = name
                break
        if autologin_profile:
            self.log(f"Startup: Found autologin profile '{autologin_profile}'. Attempting login.")
            self.update_profile_list_and_select(autologin_profile)
            self._initiate_login()
        elif self.profiles:
            first_profile = next(iter(self.profiles))
            self.log(f"Startup: No autologin profile found. Selecting '{first_profile}'.")
            self.update_profile_list_and_select(first_profile)

    def _run_speed_test_thread(self):
        if not speedtest: return
        def _worker():
            self.root.after(0, self.run_speed_btn.config, {"state": DISABLED, "text": "Testing..."})
            self.log("Speed test started...", level="DEBUG")
            try:
                st = speedtest.Speedtest(); st.get_best_server(); st.download(); st.upload(); res = st.results.dict()
                dl = f"{res['download'] / 1_000_000:.2f} Mbps"; ul = f"{res['upload'] / 1_000_000:.2f} Mbps"; ping = f"{res['ping']:.2f} ms"
                self.root.after(0, self._update_speed_test_ui, dl, ul, ping)
                self.log(f"Speed test complete: {dl} down, {ul} up, {ping} ping")
            except Exception as e:
                self.root.after(0, self._update_speed_test_ui, "Error", "Error", "Error"); self.log(f"Speed test failed: {e}", level="ERROR")
            finally:
                self.root.after(0, self.run_speed_btn.config, {"state": NORMAL, "text": "📶 Run Speed Test"})
                gc.collect() 
        threading.Thread(target=_worker, daemon=True).start()

    def _update_scraped_data_ui(self, data):
        if "usage" in data: self.data_usage_label.config(text=f"Data Usage: {data['usage']}")
        if "time_left" in data: self.time_left_label.config(text=f"Time Remaining: {data['time_left']}")

    def _update_speed_test_ui(self, dl, ul, ping):
        self.speed_dl_label.config(text=f"Download: {dl}"); self.speed_ul_label.config(text=f"Upload: {ul}"); self.speed_ping_label.config(text=f"Ping: {ping}")

    def _open_github_link(self):
        url = "https://github.com/Artiston2005" 
        self.log(f"Opening GitHub URL: {url}", level="INFO")
        try:
            webbrowser.open(url, new=2)
        except Exception as e:
            self.log(f"Failed to open web browser: {e}", level="ERROR")
            messagebox.showerror("Error", f"Could not open web browser: {e}")

    def _open_linkedin_link(self):
        url = "www.linkedin.com/in/ashwin-yadav-1704a1248" 
        self.log(f"Opening LinkedIn URL: {url}", level="INFO")
        try:
            webbrowser.open(url, new=2)
        except Exception as e:
            self.log(f"Failed to open web browser: {e}", level="ERROR")
            messagebox.showerror("Error", f"Could not open web browser: {e}")

    def _run_diagnostics(self):
        self.diag_log.config(state=NORMAL)
        self.diag_log.delete("1.0", END)
        self.diag_log.config(state=DISABLED)
        self.diag_btn.config(state=DISABLED, text="Running...")
        threading.Thread(target=self._diagnostics_thread, daemon=True).start()

    def _diagnostics_thread(self):
        def log_diag(message):
            def _log():
                self.diag_log.config(state=NORMAL)
                self.diag_log.insert(END, f"{message}\n")
                self.diag_log.see(END)
                self.diag_log.config(state=DISABLED)
            self.root.after(0, _log)

        def run_check(title, func, *args):
            log_diag(f"[TESTING] {title}...")
            try:
                result, ok = func(*args)
                log_diag(f"[ {'PASS' if ok else 'FAIL'} ] {result}")
                return ok
            except Exception as e:
                log_diag(f"[ FAIL ] Error: {e}")
                return False
        
        log_diag(f"Starting diagnostics at {datetime.now().strftime('%H:%M:%S')}...\n")
        self.log("Diagnostics started.", level="DEBUG")
        
        def check_portal():
            status, msg = self.client.probe_connection(timeout=5)
            if status == "error":
                return f"Probe failed: {msg}", False
            elif status == "offline":
                return f"Probe successful: Portal detected. ({msg})", True
            elif status == "online":
                return "Probe successful: No portal detected. (Already online?)", True
        portal_ok = run_check("Captive Portal Detection", check_portal)

        def check_dns():
            try:
                ip = socket.gethostbyname("google.com")
                return f"DNS OK: 'google.com' resolved to {ip}", True
            except socket.gaierror:
                return "DNS FAILED: Could not resolve 'google.com'", False
        dns_ok = run_check("DNS Resolution", check_dns)

        def check_ping(host):
            param = "-n" if platform.system().lower() == "windows" else "-c"
            command = ["ping", param, "1", host]
            try:
                flags = 0x08000000 if platform.system().lower() == "windows" else 0
                subprocess.run(command, check=True, capture_output=True, text=True, timeout=5, creationflags=flags)
                return f"Ping OK: Responded from {host}", True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                return f"Ping FAILED: No response from {host}", False
        
        ping_google_ok = run_check("Ping Google DNS (8.8.8.8)", check_ping, "8.8.8.8")
        
        log_diag("\n--- Summary ---")
        if portal_ok and "offline" in check_portal()[0]:
            log_diag("✅ Portal is reachable. App should be working.")
        if not dns_ok and not ping_google_ok:
            log_diag("❌ Critical Error: No internet connection or DNS. Check your Wi-Fi connection.")
        if dns_ok and ping_google_ok and not portal_ok:
            log_diag("⚠️ Warning: Internet seems to be working, but the login portal is not detectable.")
        
        log_diag("Diagnostics complete.")
        self.log("Diagnostics complete.", level="DEBUG")
        self.root.after(0, self.diag_btn.config, {"state": NORMAL, "text": "🩺 Run Diagnostics"})
        gc.collect() 

    def setup_tray(self):
        if not pystray: return self.log("pystray not found, tray icon disabled.", level="WARNING")
        image = Image.new("RGB", (64, 64), color="blue")
        if CONFIG.ICON_PNG.exists():
            try: image = Image.open(CONFIG.ICON_PNG)
            except Exception: pass
        
        initial_title = f"{CONFIG.APP_NAME} - Initializing..."
        
        menu = pystray.Menu(pystray.MenuItem("Show", self.root.deiconify, default=True), pystray.MenuItem("Login", self._initiate_login),
                            pystray.MenuItem("Logout", self.btn_logout), pystray.MenuItem("Quit", self.quit_app))
        self.tray_icon = pystray.Icon(CONFIG.APP_NAME.lower(), image, initial_title, menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start(); self.log("Tray icon started.", level="DEBUG")
    
    def hide_to_tray(self):
        if self.tray_icon and self.tray_icon.visible: self.root.withdraw(); notify(CONFIG.APP_NAME, "Minimized to tray.")
        else: self.quit_app()

    def quit_app(self):
        self.log("Quit request received. Shutting down...", level="DEBUG")
        self._threads_stop_event.set()
        self._network_pause_event.clear() 
        
        lock_socket = get_lock_socket()
        if lock_socket:
            try: lock_socket.close()
            except Exception: pass
        
        if self.tray_icon: self.tray_icon.stop()
        self.root.quit()

    def setup_hotkey(self):
        if not keyboard: return self.log("keyboard module not found, hotkey disabled.", level="WARNING")
        try: keyboard.add_hotkey("ctrl+alt+p", self._initiate_login); self.log("Hotkey Ctrl+Alt+P registered for relogin.", level="DEBUG")
        except Exception as e: self.log(f"Hotkey registration failed: {e}", level="ERROR")


def cli_mode():
    parser = argparse.ArgumentParser(description=f"{CONFIG.APP_NAME} CLI"); group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--login", action="store_true"); group.add_argument("--logout", action="store_true"); group.add_argument("--status", action="store_true")
    parser.add_argument("-p", "--profile", type=str); parser.add_argument("-u", "--username", type=str); parser.add_argument("-w", "--password", type=str)
    args = parser.parse_args(); client = FortiClient()
    
    if args.status:
        if CONFIG.SESSION_FILE.exists(): print("Status: Online\n", CONFIG.SESSION_FILE.read_text(encoding='utf-8'))
        else: print("Status: Offline")
    elif args.logout: 
        print(client.logout()[1])
    elif args.login:
        user, pwd = args.username, args.password
        if args.profile:
            profiles = load_profiles()
            if args.profile in profiles: 
                user, pwd = profiles[args.profile].get("username"), profiles[args.profile].get("password")
            else: 
                return print(f"Error: Profile '{args.profile}' not found.")
        if not user or not pwd: 
            return print("Error: Username and password required.")
        print(client.login(user, pwd)[1])

def main():
    # --- DEV SWITCH ---
    DEV_MODE = False
    # ---------------------

    is_headless = not hasattr(sys, 'stdout') or sys.stdout is None
    
    if not check_for_lock():
        print(f"Error: Another instance of {CONFIG.APP_NAME} is already running.")
        if not is_headless:
            try:
                root = ttk.Window(themename="darkly") 
                root.withdraw()
                messagebox.showerror(CONFIG.APP_NAME, "Another instance is already running and has been blocked.")
                root.destroy()
            except Exception: pass
        sys.exit(1)
    
    if {"--login", "--logout", "--status"}.intersection(sys.argv) and not is_headless:
        return cli_mode()

    start_silently = "--startup" in sys.argv
    
    current_theme = SETTINGS.get("theme")
    root = ttk.Window(themename=current_theme)
    
    if start_silently and not DEV_MODE:
        root.withdraw()
    
    if CONFIG.ICON_PNG.exists():
        try: root.iconphoto(False, PhotoImage(file=str(CONFIG.ICON_PNG)))
        except Exception as e: print(f"Could not load window icon: {e}")
    
    app = FortiApp(root, start_silently=start_silently) 

    if DEV_MODE:
        root.after(100, app._initialize_app)
    
    root.mainloop()

if __name__ == "__main__":
    main()
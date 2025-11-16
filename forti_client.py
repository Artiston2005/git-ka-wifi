import json
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
# --- NEW FEATURE: Advanced Network Retries ---
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
# --- End New Feature ---

from config import CONFIG, SETTINGS # Local import


class FortiClient:
    def __init__(self):
        self.session = requests.Session()
        self.portal_base_url = None

        # --- NEW FEATURE: Advanced Network Retries ---
        retry_strategy = Retry(
            total=3,  # Total number of retries
            backoff_factor=1,  # Wait 1s, 2s, 4s between retries
            status_forcelist=[429, 500, 502, 503, 504], # Status codes to retry on
            allowed_methods=["HEAD", "GET", "POST"] # Retry on POSTs too
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        # --- End New Feature ---
        
        self.update_headers()

    def update_headers(self):
        self.session.headers.update({"User-Agent": SETTINGS.get("user_agent")})

    def _extract_magic(self, resp: requests.Response) -> str | None:
        if "fgtauth" in resp.url:
            match = re.search(r"[?&]([0-9a-fA-F]{10,})", resp.url)
            if match: return match.group(1)
        match = re.search(r'name="magic"\s+value="([^"]+)"', resp.text)
        return match.group(1) if match else None

    def _get_portal_base_url(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def probe_connection(self, timeout=5):
        probe_urls = SETTINGS.get("probe_urls")
        if not probe_urls:
            return "error", "No probe URLs configured in settings."
        
        last_error = ""
        for url in probe_urls:
            try:
                # Use a shorter timeout for probes, but use session's retry logic
                resp = self.session.get(url, allow_redirects=True, timeout=timeout)
                return ("offline", "Portal redirect detected") if "fgtauth" in resp.url else ("online", "No portal redirect")
            except requests.RequestException as e:
                last_error = f"Probe failed for {url}: {e}"
                continue
        
        return "error", f"All probes failed. Last error: {last_error}"

    def login(self, username, password, timeout=12):
        status, msg = self.probe_connection(timeout=5) # Quick probe first
        if status == "online": return True, "Already online"
        if status == "error": return False, msg
        
        probe_urls = SETTINGS.get("probe_urls")
        if not probe_urls:
            return False, "No probe URLs configured for login."
        
        login_probe_url = probe_urls[0]

        try:
            # Use the longer timeout for the actual login sequence
            resp = self.session.get(login_probe_url, allow_redirects=True, timeout=timeout)
            
            if "fgtauth" not in resp.url:
                 return False, "Failed to trigger portal redirect. Are you on the right network?"

            self.portal_base_url = self._get_portal_base_url(resp.url)
            magic = self._extract_magic(resp)
            if not magic: return False, "Could not find magic token"
            
            payload = {"4Tredir": login_probe_url, "magic": magic, "username": username, "password": password}
            
            r2 = self.session.post(resp.url, data=payload, allow_redirects=False, timeout=timeout)
            
            if r2.status_code in (302, 303) and "Location" in r2.headers:
                loc = r2.headers["Location"]
                keepalive_url = urljoin(self.portal_base_url, loc) if loc.startswith("/") else loc
                session_data = {
                    "token": magic, 
                    "keepalive_url": keepalive_url, 
                    "timestamp": datetime.now().isoformat(sep=" ", timespec="seconds"), 
                    "portal_base": self.portal_base_url
                }
                CONFIG.SESSION_FILE.write_text(json.dumps(session_data), encoding="utf-8")
                return True, "Login successful"
            
            return False, f"Login failed (status: {r2.status_code}). Check credentials."
        
        except requests.RequestException as e:
            # The retry logic failed, so this is a permanent error
            return False, f"Login request failed after retries: {e}"

    def logout(self, timeout=8):
        if not CONFIG.SESSION_FILE.exists(): return False, "No active session"
        try:
            data = json.loads(CONFIG.SESSION_FILE.read_text(encoding="utf-8"))
            token, base_url = data.get("token"), data.get("portal_base")
            if not token or not base_url: return False, "Token/base URL missing"
            self.session.get(f"{base_url}/logout?{token}", timeout=timeout)
            CONFIG.SESSION_FILE.unlink(missing_ok=True)
            return True, "Logout successful"
        except Exception as e:
            CONFIG.SESSION_FILE.unlink(missing_ok=True)
            return False, f"Logout error: {e}"

    def keepalive(self, timeout=8):
        if not CONFIG.SESSION_FILE.exists(): return False, "No active session", {}
        try:
            data = json.loads(CONFIG.SESSION_FILE.read_text(encoding="utf-8"))
            ka_url = data.get("keepalive_url")
            if not ka_url: return False, "Keepalive URL not found", {}
            r = self.session.get(ka_url, timeout=timeout)
            scraped_data = {}
            usage_match = re.search(SETTINGS.get("scrape_data_usage_regex"), r.text, re.IGNORECASE)
            if usage_match: scraped_data["usage"] = usage_match.group(1).strip()
            time_match = re.search(SETTINGS.get("scrape_time_left_regex"), r.text, re.IGNORECASE)
            if time_match: scraped_data["time_left"] = time_match.group(1).strip()
            return True, f"Keepalive status: {r.status_code}", scraped_data
        except requests.RequestException as e:
            return False, f"Keepalive error after retries: {e}", {}
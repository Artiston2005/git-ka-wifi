import json
import re
import concurrent.futures
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import CONFIG, SETTINGS

class FortiClient:
    def __init__(self):
        self.session = requests.Session()
        self.portal_base_url = None

        # Standard retry strategy for login/keepalive
        retry_strategy = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
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

    def _fast_probe(self, timeout=3):
        """
        Checks multiple probe URLs in parallel. Returns the first successful response.
        Disables retries for speed and to prevent log spam on dead URLs.
        """
        probe_urls = SETTINGS.get("probe_urls")
        if not probe_urls:
            return None

        def check_url(url):
            try:
                # Create a temp session with NO retries for probing
                # This prevents the "NameResolutionError" log spam
                with requests.Session() as s:
                    s.mount('http://', HTTPAdapter(max_retries=0))
                    s.mount('https://', HTTPAdapter(max_retries=0))
                    return s.get(url, allow_redirects=True, timeout=timeout)
            except Exception:
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(probe_urls)) as executor:
            future_to_url = {executor.submit(check_url, url): url for url in probe_urls}
            
            for future in concurrent.futures.as_completed(future_to_url):
                resp = future.result()
                if resp:
                    return resp
        return None

    def probe_connection(self, timeout=3):
        resp = self._fast_probe(timeout)
        if not resp:
            return "error", "All probes failed or timed out."
            
        if "fgtauth" in resp.url:
            return "offline", "Portal redirect detected"
        else:
            return "online", "No portal redirect"

    def login(self, username, password, timeout=10):
        # 1. Fast Parallel Probe
        resp = self._fast_probe(timeout=4)

        if not resp:
            return False, "Network unreachable or probes timed out."

        # 2. Check if we are already online
        if "fgtauth" not in resp.url:
             session_data = {
                 "type": "unmanaged",
                 "timestamp": datetime.now().isoformat(sep=" ", timespec="seconds"),
                 "token": "PASSTHROUGH",
                 "keepalive_url": None
             }
             CONFIG.SESSION_FILE.write_text(json.dumps(session_data), encoding="utf-8")
             return True, "Already online (No redirect detected)"

        # 3. Perform Login
        try:
            self.portal_base_url = self._get_portal_base_url(resp.url)
            magic = self._extract_magic(resp)
            if not magic: 
                return False, "Could not find magic token in portal page."
            
            post_url = resp.url
            original_url = SETTINGS.get("probe_urls")[0] 

            payload = {
                "4Tredir": original_url, 
                "magic": magic, 
                "username": username, 
                "password": password
            }
            
            r2 = self.session.post(post_url, data=payload, allow_redirects=False, timeout=timeout)
            
            if r2.status_code in (302, 303) and "Location" in r2.headers:
                loc = r2.headers["Location"]
                keepalive_url = urljoin(self.portal_base_url, loc) if loc.startswith("/") else loc
                
                session_data = {
                    "type": "managed",
                    "token": magic, 
                    "keepalive_url": keepalive_url, 
                    "timestamp": datetime.now().isoformat(sep=" ", timespec="seconds"), 
                    "portal_base": self.portal_base_url
                }
                CONFIG.SESSION_FILE.write_text(json.dumps(session_data), encoding="utf-8")
                return True, "Login successful"
            
            return False, f"Login failed (status: {r2.status_code}). Check credentials."
        
        except requests.RequestException as e:
            return False, f"Login request failed: {e}"

    def logout(self, timeout=5):
        if not CONFIG.SESSION_FILE.exists(): return False, "No active session"
        try:
            data = json.loads(CONFIG.SESSION_FILE.read_text(encoding="utf-8"))
            
            if data.get("type") == "unmanaged":
                CONFIG.SESSION_FILE.unlink(missing_ok=True)
                return True, "Logout successful (Local)"

            token, base_url = data.get("token"), data.get("portal_base")
            if not token or not base_url: return False, "Token/base URL missing"
            
            logout_url = f"{base_url}/logout?{token}"
            self.session.get(logout_url, timeout=timeout)
            
            CONFIG.SESSION_FILE.unlink(missing_ok=True)
            return True, "Logout successful"
        except Exception as e:
            CONFIG.SESSION_FILE.unlink(missing_ok=True)
            return False, f"Logout error: {e}"

    def keepalive(self, timeout=5):
        if not CONFIG.SESSION_FILE.exists(): return False, "No active session", {}
        try:
            data = json.loads(CONFIG.SESSION_FILE.read_text(encoding="utf-8"))
            
            if data.get("type") == "unmanaged":
                status, msg = self.probe_connection(timeout=timeout)
                if status == "online":
                    return True, "Connected (Passthrough)", {}
                else:
                    return False, "Connection lost or portal detected", {}

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
            return False, f"Keepalive error: {e}", {}
"""Session Manager for FastMoss Authentication & Cookies"""
import json
import logging
from pathlib import Path
from typing import Dict, Any, Tuple
from playwright.sync_api import sync_playwright

from src.config import DEFAULT_STORAGE_STATE_PATH, get_selectors

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, storage_state_path: Path = DEFAULT_STORAGE_STATE_PATH):
        self.storage_state_path = storage_state_path
        self.selectors = get_selectors()

    def has_session_file(self) -> bool:
        """Cek apakah file storage_state.json sudah ada dan tidak kosong"""
        if not self.storage_state_path.exists():
            return False
        try:
            with open(self.storage_state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return bool(data.get("cookies") or data.get("origins"))
        except Exception:
            return False

    def validate_session(self, country: str = "id") -> Tuple[bool, str]:
        """
        Buka dashboard FastMoss dengan storage_state.json untuk memvalidasi sesi aktif.
        Return: (is_valid, user_or_message)
        """
        if not self.has_session_file():
            return False, "File sesi (storage_state.json) belum ditemukan. Silakan login terlebih dahulu."

        try:
            import sys
            is_win = (sys.platform == "win32")
            launch_args = ["--disable-blink-features=AutomationControlled"]
            if is_win:
                launch_args.append("--window-position=-2400,-2400")

            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=False,
                    args=launch_args
                )
                context = browser.new_context(
                    storage_state=str(self.storage_state_path),
                    viewport={"width": 1440, "height": 900}
                )
                page = context.new_page()

                dashboard_url = f"https://www.fastmoss.com/{country.lower()}/dashboard"
                page.goto(dashboard_url, timeout=30000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)

                current_url = page.url.lower()

                if "login" in current_url:
                    browser.close()
                    return False, "Sesi kadaluarsa (di-redirect ke halaman login FastMoss)"

                profile_sel = self.selectors.get("session_verification", {}).get("user_profile", ".user-info, .profile-name")
                is_logged_in = False
                account_name = ""

                try:
                    elem = page.locator(profile_sel).first
                    if elem.count() > 0 and elem.is_visible():
                        account_name = elem.text_content() or "Akun FastMoss"
                        is_logged_in = True
                except Exception:
                    pass

                if not is_logged_in and "dashboard" in current_url:
                    is_logged_in = True
                    account_name = "Akun Aktif"

                browser.close()

                if is_logged_in:
                    return True, f"Sesi aktif ({account_name.strip()})"
                else:
                    return False, "Sesi tidak valid / belum login"

        except Exception as e:
            return False, f"Gagal memvalidasi sesi: {str(e)}"

    _active_vnc_context = None
    _active_vnc_browser = None
    _active_vnc_playwright = None
    _save_trigger_event = None
    _save_done_event = None
    _stop_event = None
    _save_error = None

    def start_vnc_session(self, country: str = "id") -> Tuple[bool, str, bool]:
        """
        Meluncurkan Chromium headed.
        - Di Windows: langsung membuka jendela browser di layar desktop.
        - Di Linux VPS: membuka di virtual display (Xvfb :99) untuk streaming noVNC.
        """
        import sys
        import os
        import threading
        import time

        is_local = (sys.platform == "win32")

        # Cek apakah browser sebelumnya masih benar-benar terhubung
        if SessionManager._active_vnc_browser is not None:
            try:
                if not SessionManager._active_vnc_browser.is_connected():
                    SessionManager._active_vnc_browser = None
                    SessionManager._active_vnc_context = None
            except Exception:
                SessionManager._active_vnc_browser = None
                SessionManager._active_vnc_context = None

        if SessionManager._active_vnc_context is not None:
            return True, "Jendela browser login sudah terbuka.", is_local

        SessionManager._save_trigger_event = threading.Event()
        SessionManager._save_done_event = threading.Event()
        SessionManager._stop_event = threading.Event()
        SessionManager._save_error = None

        def _run_browser():
            try:
                p = sync_playwright().start()
                SessionManager._active_vnc_playwright = p

                launch_kwargs = {
                    "headless": False,
                    "args": [
                        "--start-maximized",
                        "--disable-blink-features=AutomationControlled",
                        "--force-device-scale-factor=1"
                    ]
                }

                if is_local:
                    launch_kwargs["channel"] = "chrome"
                else:
                    env = os.environ.copy()
                    if "DISPLAY" not in env:
                        env["DISPLAY"] = ":99"
                    launch_kwargs["env"] = env
                    launch_kwargs["args"].append("--no-sandbox")

                browser = p.chromium.launch(**launch_kwargs)
                SessionManager._active_vnc_browser = browser

                context_kwargs = {
                    "no_viewport": True
                }
                if self.storage_state_path.exists():
                    context_kwargs["storage_state"] = str(self.storage_state_path)

                context = browser.new_context(**context_kwargs)
                SessionManager._active_vnc_context = context

                page = context.new_page()
                login_url = f"https://www.fastmoss.com/{country.lower()}/auth?type=login&redirect=https%3A%2F%2Fwww.fastmoss.com%2F{country.lower()}"
                page.goto(login_url)
                try:
                    page.bring_to_front()
                    if is_local:
                        import subprocess
                        ps_cmd = '$ws = New-Object -ComObject Wscript.Shell; $ws.AppActivate("FastMoss"); $ws.AppActivate("Chromium")'
                        subprocess.run(["powershell", "-Command", ps_cmd], timeout=3, capture_output=True)
                except Exception:
                    pass

                # Tunggu trigger simpan atau stop di thread ini sendiri (mencegah greenlet error)
                while not SessionManager._stop_event.is_set():
                    if SessionManager._save_trigger_event.is_set():
                        try:
                            self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
                            context.storage_state(path=str(self.storage_state_path))
                            SessionManager._save_error = None
                        except Exception as ex:
                            SessionManager._save_error = str(ex)
                        finally:
                            SessionManager._save_done_event.set()
                        break
                    time.sleep(0.3)

            except Exception as e:
                logger.error(f"Error start login browser: {e}")
            finally:
                try:
                    if SessionManager._active_vnc_browser:
                        SessionManager._active_vnc_browser.close()
                except Exception:
                    pass
                try:
                    if SessionManager._active_vnc_playwright:
                        SessionManager._active_vnc_playwright.stop()
                except Exception:
                    pass
                SessionManager._active_vnc_context = None
                SessionManager._active_vnc_browser = None
                SessionManager._active_vnc_playwright = None

        thread = threading.Thread(target=_run_browser, daemon=True)
        thread.start()
        time.sleep(2)
        msg = "Browser login telah terbuka di desktop Anda." if is_local else "Browser login noVNC berhasil dibuka."
        return True, msg, is_local

    def save_vnc_session(self) -> Tuple[bool, str]:
        """Menyimpan storage_state.json dari context headed yang sedang dibuka"""
        if SessionManager._active_vnc_context is None or SessionManager._save_trigger_event is None:
            return False, "Tidak ada browser login yang sedang aktif."

        SessionManager._save_trigger_event.set()
        if SessionManager._save_done_event.wait(timeout=10):
            if SessionManager._save_error:
                return False, f"Gagal menyimpan sesi: {SessionManager._save_error}"
            return True, "Sesi FastMoss berhasil disimpan ke storage_state.json!"
        else:
            return False, "Timeout saat menyimpan sesi browser."

    def close_vnc_session(self):
        """Menutup browser headed login"""
        if SessionManager._stop_event:
            SessionManager._stop_event.set()

    def login_interactive(self, country: str = "id"):
        """
        Buka Chromium headed agar admin/user dapat login manual.
        Menunggu sampai user menekan Enter di konsol atau dashboard terbuka, lalu menyimpan storage_state.json.
        """
        print("\n=======================================================")
        print("MEMBUKA BROWSER CHROMIUM UNTUK LOGIN MANUAL FASTMOSS")
        print("1. Silakan login seperti biasa (Email / Password / OTP).")
        print("2. Setelah dashboard FastMoss terbuka sempurna, kembali ke konsol ini.")
        print("=======================================================\n")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=[
                    "--start-maximized",
                    "--disable-blink-features=AutomationControlled",
                    "--force-device-scale-factor=1"
                ]
            )
            context_kwargs = {
                "no_viewport": True,
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            }
            if self.storage_state_path.exists():
                context_kwargs["storage_state"] = str(self.storage_state_path)

            context = browser.new_context(**context_kwargs)
            page = context.new_page()

            login_url = f"https://www.fastmoss.com/{country.lower()}"
            page.goto(login_url)

            input("Tekan [ENTER] di sini setelah Anda SELESAI login dan dashboard FastMoss sudah terbuka...")

            self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(self.storage_state_path))
            print(f"\n[OK] Sesi FastMoss berhasil disimpan ke: {self.storage_state_path}")
            browser.close()


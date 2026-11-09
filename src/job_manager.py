"""Job Queue and Background Worker Manager for FastMoss Web App"""
import json
import logging
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.config import STORAGE_DIR, LOGS_DIR
from src.models import CreatorInput, JobConfig, CreatorLog, CreatorSummary
from src.utils import parse_revenue_value
from src.input_reader import InputReader
from src.scraper import FastMossScraper, SessionExpiredException
from src.session_manager import SessionManager
from src.notifier import Notifier

logger = logging.getLogger("job_manager")

JOBS_DB_PATH = STORAGE_DIR / "jobs.db"


class JobManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(JobManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, db_path=JOBS_DB_PATH):
        if self._initialized:
            return
        self.db_path = db_path
        self._init_db()
        self.active_job_id = None
        self.is_paused = False
        self.is_cancelled = False
        self.worker_thread = None
        self.subscribers: Dict[str, List[threading.Event]] = {}
        self._start_worker_daemon()
        self._initialized = True

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    filename TEXT,
                    country TEXT,
                    user_email TEXT DEFAULT 'admin@kurmagroup.com',
                    status TEXT, -- pending, running, paused, completed, cancelled, failed
                    total_creators INTEGER DEFAULT 0,
                    completed_creators INTEGER DEFAULT 0,
                    output_path TEXT,
                    config_json TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN user_email TEXT DEFAULT 'admin@kurmagroup.com'")
            except Exception:
                pass
            conn.execute("""
                CREATE TABLE IF NOT EXISTS job_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT,
                    creator_name TEXT,
                    country TEXT,
                    status TEXT, -- menunggu, sedang diproses, selesai, tanpa video, ambigu, tidak ditemukan, gagal
                    video_count INTEGER DEFAULT 0,
                    ad_count INTEGER DEFAULT 0,
                    total_sales INTEGER DEFAULT 0,
                    duration_seconds REAL DEFAULT 0.0,
                    notes TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(job_id) REFERENCES jobs(id)
                )
            """)
            conn.commit()

    def create_job(self, file_path: Path, filename: str, config: JobConfig, user_email: str = "admin@kurmagroup.com") -> str:
        creators, stats = InputReader.read_input(file_path, default_country=config.country)
        if not creators:
            raise ValueError("Tidak ada nama kreator valid dalam file input.")

        job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        config_dict = {
            "country": config.country,
            "period": getattr(config, "period", "7 Hari") or "7 Hari",
            "max_videos": config.max_videos_per_creator,
            "min_revenue": getattr(config, "min_revenue", 0.0) or 0.0,
            "filter_ad": config.filter_ad_only,
            "filter_bawahan": config.filter_bawahan_only,
            "min_delay": config.min_delay,
            "max_delay": config.max_delay
        }

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO jobs (id, filename, country, user_email, status, total_creators, completed_creators, config_json)
                VALUES (?, ?, ?, ?, 'pending', ?, 0, ?)
            """, (job_id, filename, config.country, user_email, len(creators), json.dumps(config_dict)))

            for c in creators:
                conn.execute("""
                    INSERT INTO job_items (job_id, creator_name, country, status, notes)
                    VALUES (?, ?, ?, 'menunggu', ?)
                """, (job_id, c.nama_kreator, c.negara, c.catatan))
            conn.commit()

        logger.info(f"Job {job_id} dibuat dengan {len(creators)} kreator.")
        return job_id

    def get_job(self, job_id: str) -> Optional[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            if not row:
                return None
            job = dict(row)
            try:
                job["config_dict"] = json.loads(job.get("config_json") or "{}")
            except Exception:
                job["config_dict"] = {}
            cursor.execute("SELECT * FROM job_items WHERE job_id = ? ORDER BY id ASC", (job_id,))
            items = [dict(r) for r in cursor.fetchall()]
            job["items"] = items
            job["creator_items"] = items
            return job

    def list_jobs(self, user_email: Optional[str] = None) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if user_email:
                cursor.execute("SELECT * FROM jobs WHERE user_email = ? ORDER BY created_at DESC", (user_email,))
            else:
                cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC")
            return [dict(r) for r in cursor.fetchall()]

    def pause_job(self, job_id: str):
        if self.active_job_id == job_id:
            self.is_paused = True
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("UPDATE jobs SET status = 'paused', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (job_id,))
                conn.commit()
            return True
        return False

    def resume_job(self, job_id: str):
        if self.active_job_id == job_id:
            self.is_paused = False
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("UPDATE jobs SET status = 'running', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (job_id,))
                conn.commit()
            return True
        return False

    def cancel_job(self, job_id: str):
        if self.active_job_id == job_id:
            self.is_cancelled = True
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("UPDATE jobs SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (job_id,))
                conn.commit()
            return True
        else:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("UPDATE jobs SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'pending'", (job_id,))
                conn.commit()
            return True

    def _start_worker_daemon(self):
        if self.worker_thread is None or not self.worker_thread.is_alive():
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()

    def _worker_loop(self):
        while True:
            try:
                # Cari running job yang terputus (misal setelah restart VPS) atau pending job
                next_job_id = None
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute("SELECT id FROM jobs WHERE status = 'running' ORDER BY created_at ASC LIMIT 1")
                    row = cursor.fetchone()
                    if not row:
                        cursor.execute("SELECT id FROM jobs WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1")
                        row = cursor.fetchone()
                    if row:
                        next_job_id = row["id"]

                if next_job_id:
                    self._execute_job(next_job_id)
                else:
                    time.sleep(2)
            except Exception as e:
                logger.error(f"Error pada worker loop: {e}", exc_info=True)
                time.sleep(5)

    def _execute_job(self, job_id: str):
        self.active_job_id = job_id
        self.is_paused = False
        self.is_cancelled = False

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE jobs SET status = 'running', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (job_id,))
            conn.commit()

        job_data = self.get_job(job_id)
        if not job_data:
            return

        config_dict = json.loads(job_data.get("config_json") or "{}")
        config = JobConfig(
            country=config_dict.get("country", "ID"),
            period=config_dict.get("period", "7 Hari"),
            max_videos_per_creator=config_dict.get("max_videos", 50),
            min_revenue=float(config_dict.get("min_revenue", 0.0) or 0.0),
            filter_ad_only=config_dict.get("filter_ad", True),
            filter_bawahan_only=config_dict.get("filter_bawahan", True),
            min_delay=config_dict.get("min_delay", 3.0),
            max_delay=config_dict.get("max_delay", 7.0)
        )

        scraper = FastMossScraper()
        session_mgr = SessionManager()

        # Cek ketersediaan file sesi sebelum mulai
        notifier = Notifier()
        if not session_mgr.has_session_file():
            error_text = "File sesi FastMoss (storage_state.json) belum ditemukan. Silakan login terlebih dahulu via menu Sesi."
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE jobs SET status = 'paused', error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
                """, (error_text, job_id))
                conn.commit()
            notifier.notify_session_expired(error_text)
            self.active_job_id = None
            return

        creators_to_process = []
        for item in job_data.get("items", []):
            if item["status"] in ["menunggu", "sedang diproses"]:
                creators_to_process.append(CreatorInput(
                    nama_kreator=item["creator_name"],
                    negara=item["country"],
                    catatan=item["notes"] or ""
                ))

        try:
            from playwright.sync_api import sync_playwright

            videos_filtered = []
            videos_other = []
            summaries = []
            logs = []

            import sys
            is_win = (sys.platform == "win32")

            launch_kwargs = {
                "headless": False,
                "args": [
                    "--start-maximized",
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox"
                ]
            }
            if is_win:
                launch_kwargs["channel"] = "chrome"

            with sync_playwright() as p:
                browser = p.chromium.launch(**launch_kwargs)
                context_kwargs = {
                    "no_viewport": True
                }
                if scraper.storage_state_path.exists():
                    context_kwargs["storage_state"] = str(scraper.storage_state_path)

                context = browser.new_context(**context_kwargs)
                page = context.new_page()
                try:
                    page.bring_to_front()
                except Exception:
                    pass

                for c_input in creators_to_process:
                    if self.is_cancelled:
                        break

                    # Tunggu jika dijeda
                    while self.is_paused and not self.is_cancelled:
                        time.sleep(2)

                    if self.is_cancelled:
                        break

                    c_name = c_input.nama_kreator
                    start_t = time.time()

                    # Update status sedang diproses
                    with sqlite3.connect(self.db_path) as conn:
                        conn.execute("""
                            UPDATE job_items SET status = 'sedang diproses', updated_at = CURRENT_TIMESTAMP
                            WHERE job_id = ? AND creator_name = ?
                        """, (job_id, c_name))
                        conn.commit()

                    retry_delays = [10, 30, 60]
                    item_status = "gagal"
                    v_count = 0
                    ad_count = 0
                    total_sales = 0
                    notes = ""

                    for attempt in range(1, 4):
                        try:
                            status_search, info = scraper.search_creator(page, c_name, c_input.negara, context=context)
                            item_status = status_search
                            notes = info.get("catatan", "")

                            if status_search == "selesai":
                                v_items, summary = scraper.scrape_creator_videos(page, context, c_input, info, config)
                                summaries.append(summary)
                                item_status = summary.status
                                v_count = summary.jumlah_video_7hari
                                ad_count = summary.jumlah_video_ad
                                total_sales = summary.total_penjualan_video
                                notes = summary.catatan

                                for v in v_items:
                                    pass_ad = True if not config.filter_ad_only else v.is_ad
                                    pass_cat = True if not config.filter_bawahan_only else v.is_bawahan_wanita
                                    rev_val = parse_revenue_value(v.penjualan_video_nilai)
                                    pass_rev = True if config.min_revenue <= 0 else (rev_val >= config.min_revenue)

                                    if pass_ad and pass_cat and pass_rev:
                                        videos_filtered.append(v)
                                    else:
                                        videos_other.append(v)

                            elif status_search == "tanpa video":
                                item_status = "tanpa video"
                            elif status_search == "ambigu":
                                item_status = "ambigu"
                            else:
                                item_status = "tidak ditemukan"

                            break  # Berhasil

                        except SessionExpiredException as se:
                            logger.error(f"Sesi FastMoss putus saat memproses {c_name}: {se}")
                            with sqlite3.connect(self.db_path) as conn:
                                conn.execute("""
                                    UPDATE jobs SET status = 'paused', error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
                                """, (str(se), job_id))
                                conn.commit()
                            notifier.notify_session_expired(str(se))
                            self.is_paused = True
                            break

                        except Exception as ex:
                            if attempt < 3:
                                d = retry_delays[attempt - 1]
                                logger.warning(f"Percobaan {attempt} gagal untuk {c_name}: {ex}. Retry dalam {d} detik...")
                                time.sleep(d)
                            else:
                                logger.error(f"Gagal 3x untuk kreator {c_name}: {ex}")
                                safe_name = re.sub(r"[^\w\-]", "_", c_name)
                                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                                ss_path = LOGS_DIR / f"{safe_name}_fail_{ts}.png"
                                try:
                                    page.screenshot(path=str(ss_path))
                                except Exception:
                                    pass
                                item_status = "gagal"
                                notes = f"Error setelah 3x percobaan: {str(ex)}"

                    if self.is_paused:
                        break

                    dur_s = round(time.time() - start_t, 1)

                    # Simpan summary jika belum ada (misal tidak ditemukan/ambigu)
                    if status_search != "selesai":
                        summaries.append(CreatorSummary(
                            nama_input=c_name,
                            nickname=info.get("nickname", "") if isinstance(info, dict) else "",
                            tiktok_id=info.get("tiktok_id", "") if isinstance(info, dict) else "",
                            url_detail=info.get("detail_url", "") if isinstance(info, dict) else "",
                            status=item_status,
                            jumlah_video_7hari=0,
                            jumlah_video_ad=0,
                            total_penjualan_video=0,
                            durasi_scrape_detik=dur_s,
                            catatan=notes
                        ))
                    elif summaries:
                        summaries[-1].durasi_scrape_detik = dur_s

                    logs.append(CreatorLog(
                        nama_input=c_name,
                        status=item_status,
                        pesan_error=notes or "",
                        waktu_mulai=datetime.fromtimestamp(start_t).strftime("%Y-%m-%d %H:%M:%S"),
                        waktu_selesai=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        durasi_detik=dur_s
                    ))

                    with sqlite3.connect(self.db_path) as conn:
                        conn.execute("""
                            UPDATE job_items 
                            SET status = ?, video_count = ?, ad_count = ?, total_sales = ?, duration_seconds = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE job_id = ? AND creator_name = ?
                        """, (item_status, v_count, ad_count, total_sales, dur_s, notes, job_id, c_name))
                        conn.execute("""
                            UPDATE jobs 
                            SET completed_creators = completed_creators + 1, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                        """, (job_id,))
                        conn.commit()

                    scraper._sleep_random(config.min_delay, config.max_delay)

                try:
                    context.storage_state(path=str(scraper.storage_state_path))
                except Exception:
                    pass
                browser.close()

            # Buat file Excel hasil jika ada data
            final_status = "completed" if not self.is_cancelled else "cancelled"
            excel_path = None
            if summaries or videos_filtered or videos_other:
                excel_path = scraper.excel_handler.generate_report(
                    videos_filtered=videos_filtered,
                    videos_other=videos_other,
                    summaries=summaries,
                    logs=logs,
                    config=config
                )

            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE jobs 
                    SET status = ?, output_path = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (final_status, str(excel_path) if excel_path else "", job_id))
                conn.commit()

            if final_status == "completed":
                notifier.notify_job_completed(job_id, job_data.get("total_creators", 0), len(summaries), str(excel_path) if excel_path else "")

        except Exception as e:
            logger.error(f"Job {job_id} gagal dieksekusi: {e}", exc_info=True)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE jobs SET status = 'failed', error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
                """, (str(e), job_id))
                conn.commit()
        finally:
            self.active_job_id = None


"""Core Scraping Engine for FastMoss Kreator Analitik"""
import logging
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Callable
from playwright.sync_api import sync_playwright, Page, BrowserContext

from src.config import (
    LOGS_DIR,
    DEFAULT_STORAGE_STATE_PATH,
    get_selectors,
    get_category_config
)
from src.models import (
    CreatorInput,
    VideoItem,
    CreatorSummary,
    CreatorLog,
    JobConfig
)
from src.category_checker import CategoryChecker
from src.excel_handler import ExcelHandler
from src.utils import parse_revenue_value

logger = logging.getLogger("fastmoss_scraper")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class SessionExpiredException(Exception):
    """Dilempar bila FastMoss logout, di-redirect ke login, atau memicu captcha/limit paket"""
    pass


class FastMossScraper:
    def __init__(self, storage_state_path: Path = DEFAULT_STORAGE_STATE_PATH):
        self.storage_state_path = storage_state_path
        self.selectors = get_selectors()
        self.cat_config = get_category_config()
        self.category_checker = CategoryChecker()
        self.excel_handler = ExcelHandler()

    def check_page_session(self, page: Page):
        """Deteksi apakah sesi habis, di-redirect ke login, atau terkena captcha/rate limit"""
        url = page.url.lower()
        if "/auth" in url and "login" in url:
            raise SessionExpiredException("Sesi FastMoss telah berakhir (di-redirect ke halaman login).")
        try:
            title = page.title().strip().lower()
            if title == "web security" or "one more check" in (page.locator("body").text_content() or "")[:500].lower():
                raise SessionExpiredException("Terdeteksi verifikasi keamanan / bot challenge FastMoss (Web Security).")
            geetest = page.locator(".geetest_radar, .geetest_popup_wrap")
            if geetest.count() > 0 and geetest.first.is_visible():
                raise SessionExpiredException("Terdeteksi captcha GeeTest FastMoss.")
        except SessionExpiredException:
            raise
        except Exception:
            pass

    def handle_login_modal_if_present(self, page: Page, context: Optional[BrowserContext] = None, timeout_seconds: int = 120) -> bool:
        """
        Deteksi apakah muncul modal popup 'Masuk' FastMoss.
        Jika muncul di noVNC / layar lokal, beri waktu user untuk memasukkan password & captcha.
        Setelah user berhasil login (modal hilang), otomatis simpan context.storage_state()!
        """
        try:
            modal = page.locator(".ant-modal:has-text('Masuk'), .ant-modal:has(input[type='password']), div[class*='modal']:has-text('Masuk')").first
            if modal.count() > 0 and modal.is_visible():
                logger.warning(
                    f"[LOGIN DIPERLUKAN] Muncul modal 'Masuk' FastMoss di browser! "
                    f"Menunggu hingga {timeout_seconds} detik untuk input password & verifikasi di noVNC/layar..."
                )
                start_w = time.time()
                while time.time() - start_w < timeout_seconds:
                    time.sleep(2)
                    if modal.count() == 0 or not modal.is_visible():
                        logger.info("Modal 'Masuk' telah tertutup/selesai! Memverifikasi status login...")
                        self._sleep_random(2.0, 3.0)
                        if context and self.storage_state_path:
                            try:
                                self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
                                context.storage_state(path=str(self.storage_state_path))
                                logger.info(f"Sesi baru berhasil disimpan ke '{self.storage_state_path}'!")
                            except Exception as save_err:
                                logger.warning(f"Gagal auto-save storage_state: {save_err}")
                        return True

                logger.error("[TIMEOUT] Waktu tunggu login habis. Modal login masih terbuka.")
                raise SessionExpiredException("Sesi FastMoss tidak aktif (muncul popup Masuk yang belum diselesaikan).")
        except SessionExpiredException:
            raise
        except Exception as e:
            logger.debug(f"Pengecekan modal login: {e}")
        return False

    def _sleep_random(self, min_s: float = 3.0, max_s: float = 7.0):
        """Jeda santai human-like sesuai prinsip 'asal benar & stabil'"""
        duration = random.uniform(min_s, max_s)
        time.sleep(duration)

    def _normalize_number(self, text: Optional[str]) -> Optional[int]:
        """Konversi angka FastMoss (e.g. '1.240', '12,5 rb', '1.5 jt', '500') ke integer murni"""
        if not text:
            return None
        clean = text.strip().replace(" ", "").lower()
        if not clean or clean == "-" or clean == "--":
            return 0

        if "jt" in clean or "m" in clean:
            num_part = re.sub(r"[^\d,\.]", "", clean).replace(",", ".")
            try:
                return int(float(num_part) * 1_000_000)
            except Exception:
                return 0

        if "rb" in clean or "k" in clean:
            num_part = re.sub(r"[^\d,\.]", "", clean).replace(",", ".")
            try:
                return int(float(num_part) * 1_000)
            except Exception:
                return 0

        digits_only = re.sub(r"[^\d]", "", clean)
        try:
            return int(digits_only) if digits_only else 0
        except Exception:
            return 0

    def _normalize_rate(self, text: Optional[str]) -> Optional[float]:
        """Konversi persentase FastMoss (e.g. '5.42%', '12%') ke decimal float"""
        if not text:
            return None
        clean = text.strip().replace("%", "").replace(",", ".").strip()
        try:
            return float(clean) / 100.0
        except Exception:
            return 0.0

    def _extract_duration_seconds(self, text: Optional[str]) -> Optional[int]:
        """Ekstrak durasi detik (e.g. 'Durasi: 45s', '01:15', '30s')"""
        if not text:
            return None
        match_time = re.search(r"(\d+):(\d+)", text)
        if match_time:
            m, s = match_time.groups()
            return int(m) * 60 + int(s)

        match_sec = re.search(r"(\d+)\s*(?:s|detik)?", text, re.IGNORECASE)
        if match_sec:
            return int(match_sec.group(1))
        return None

    def search_creator(self, page: Page, creator_name: str, country: str = "id", context: Optional[BrowserContext] = None) -> Tuple[str, Dict]:
        """
        Cari kreator di FastMoss:
        Prioritas:
          (a) ID TikTok persis sama
          (b) Nickname persis sama (case-insensitive, abaikan emoji/spasi ganda)
          (c) Satu-satunya hasil
        Return: (status, info_dict)
        Status: 'selesai' (ditemukan), 'tidak ditemukan', 'ambigu'
        """
        target_country = (country or "id").upper()
        target_label = "Malaysia" if target_country == "MY" else "Indonesia"
        search_url = "https://www.fastmoss.com/id/influencer/search"

        try:
            if "influencer/search" not in page.url.lower():
                page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
                self._sleep_random(2.0, 4.0)

            self.check_page_session(page)
            self.handle_login_modal_if_present(page, context=context)

            # Cek & sesuaikan tombol negara (Indonesia / Malaysia)
            try:
                country_btn = page.locator("button:has-text('Malaysia'), button:has-text('Indonesia')").first
                country_btn.wait_for(state="visible", timeout=10000)
                current_btn_txt = country_btn.text_content() or ""
                logger.info(f"Tombol negara saat ini: '{current_btn_txt}', target: '{target_label}'")
                if target_label not in current_btn_txt:
                    country_btn.click()
                    self._sleep_random(1.0, 1.5)
                    clicked_opt = False
                    for opt in page.locator(".ant-popover span, span").filter(has_text=target_label).all():
                        if opt.is_visible() and opt.text_content().strip() == target_label:
                            opt.click()
                            clicked_opt = True
                            break
                    if not clicked_opt:
                        fallback = page.locator(f"span:text-is('{target_label}')").first
                        if fallback.count() > 0 and fallback.is_visible():
                            fallback.click()
                    self._sleep_random(3.0, 4.5)
            except Exception as c_err:
                logger.warning(f"Gagal switch negara via UI: {c_err}")

            input_sel = "input.search-bar-v3_input__B62sP, input[placeholder*='nama pengguna' i], input[placeholder*='nickname' i]"
            input_elem = page.locator(input_sel).first
            input_elem.wait_for(state="visible", timeout=10000)

            clean_c_name = creator_name.replace("@", "").strip()
            logger.info(f"Mencari kreator '{creator_name}' (Negara: {target_country})...")
            input_elem.click()
            input_elem.fill("")
            self._sleep_random(0.3, 0.5)
            input_elem.fill(clean_c_name)
            self._sleep_random(1.0, 1.5)

            # Verifikasi input tidak kosong akibat re-render
            if not input_elem.input_value():
                input_elem.fill(clean_c_name)
                self._sleep_random(0.5, 0.8)

            # Klik tombol submit pencarian resmi (tombol pink tanda panah kanan)
            go_btn = page.locator("button.search-bar-v3_goBtn__34Gqf, button[class*='goBtn']").first
            if go_btn.count() > 0 and go_btn.is_visible():
                logger.info("Klik tombol submit pencarian (go button)...")
                go_btn.click()
            else:
                input_elem.press("Enter")

            # Beri jeda agar request pencarian FastMoss selesai dimuat
            self._sleep_random(3.5, 5.0)

            row_sel = "tbody tr:has(a[href*='/influencer/detail/'])"
            rows = page.locator(row_sel).all()
            row_count = len(rows)
            logger.info(f"Ditemukan {row_count} baris hasil pencarian untuk '{creator_name}'")

            if row_count == 0:
                clean_alt = creator_name.strip()
                if clean_alt != clean_c_name:
                    input_elem.fill("")
                    input_elem.fill(clean_alt)
                    if go_btn.count() > 0 and go_btn.is_visible():
                        go_btn.click()
                    else:
                        input_elem.press("Enter")
                    self._sleep_random(3.5, 4.5)
                    rows = page.locator(row_sel).all()
                    row_count = len(rows)

            if row_count == 0:
                return "tidak ditemukan", {"catatan": "Tidak ada hasil ditemukan di pencarian FastMoss"}

            target_clean = re.sub(r"[^\w]+", "", creator_name.lower())

            candidates = []
            exact_match = None

            for i in range(min(row_count, 15)):
                row = rows[i]
                text_content = row.text_content() or ""
                if not text_content.strip() or "Tidak Ada Data" in text_content:
                    continue
                
                link_elem = row.locator("a[href*='/influencer/detail/']").first
                detail_href = ""
                link_text = ""
                if link_elem.count() > 0:
                    detail_href = link_elem.get_attribute("href") or ""
                    link_text = (link_elem.text_content() or "").strip()
                    if detail_href.startswith("/"):
                        detail_href = f"https://www.fastmoss.com{detail_href}"

                # Ekstrak TikTok ID secara akurat
                id_elem = row.locator("span:has-text('ID:'), div:has-text('ID:')").filter(has_text="ID:").last
                row_tiktok_id = ""
                if id_elem.count() > 0:
                    raw_id_txt = (id_elem.text_content() or "").strip()
                    row_tiktok_id = raw_id_txt.replace("ID:", "").strip()
                
                if not row_tiktok_id:
                    id_match = re.search(r"ID:\s*([a-zA-Z0-9_\.]+)", text_content)
                    row_tiktok_id = id_match.group(1).strip() if id_match else ""

                # Bersihkan row_tiktok_id jika ada teks gender/usia yang menempel
                row_tiktok_id = re.split(r"(?:Laki|Perempuan|Usia|\s)", row_tiktok_id)[0].strip()

                # Ekstrak Nickname
                nick_elem = row.locator(".paragraph-text, a[href*='/influencer/detail/']").first
                row_nickname = (nick_elem.text_content() or "").strip() if nick_elem.count() > 0 else ""
                if "ID:" in row_nickname:
                    row_nickname = row_nickname.split("ID:")[0].strip()
                if not row_nickname:
                    if "ID:" in text_content:
                        row_nickname = text_content.split("ID:")[0].strip()
                    elif link_text:
                        row_nickname = link_text.split("ID:")[0].strip()
                    else:
                        lines = [line.strip() for line in text_content.split("\n") if line.strip()]
                        row_nickname = lines[0] if lines else ""

                cand_info = {
                    "nickname": row_nickname,
                    "tiktok_id": row_tiktok_id,
                    "detail_url": detail_href,
                    "row_element": row
                }
                candidates.append(cand_info)

                clean_row_id = re.sub(r"[^\w]+", "", row_tiktok_id.lower())
                clean_row_nick = re.sub(r"[^\w]+", "", row_nickname.lower())
                logger.debug(f"Candidate #{i}: nick='{row_nickname}' id='{row_tiktok_id}' clean_nick='{clean_row_nick}' clean_id='{clean_row_id}'")

                if clean_row_id and (clean_row_id == target_clean or target_clean in clean_row_id or clean_row_id in target_clean):
                    exact_match = cand_info
                    logger.info(f"Match ditemukan via TikTok ID: {row_tiktok_id}")
                    break
                if clean_row_nick and (clean_row_nick == target_clean or target_clean in clean_row_nick or clean_row_nick in target_clean):
                    exact_match = cand_info
                    logger.info(f"Match ditemukan via Nickname: {row_nickname}")
                    break

            if exact_match:
                return "selesai", exact_match

            if len(candidates) == 1:
                return "selesai", candidates[0]

            if not candidates:
                return "tidak ditemukan", {"catatan": "Tidak ada hasil valid ditemukan di FastMoss"}

            top_3_str = "; ".join([f"{c['nickname']} ({c['tiktok_id']})" for c in candidates[:3]])
            return "ambigu", {
                "catatan": f"Ambigu ({len(candidates)} hasil). 3 teratas: {top_3_str}",
                "detail_url": candidates[0]["detail_url"] if candidates else "",
                "nickname": candidates[0]["nickname"] if candidates else "",
                "tiktok_id": candidates[0]["tiktok_id"] if candidates else ""
            }

        except Exception as e:
            logger.error(f"Error saat mencari kreator '{creator_name}': {e}")
            return "gagal", {"catatan": f"Error search: {str(e)}"}

    def get_product_category(self, context: BrowserContext, product_id: str, product_name: str, country: str = "id") -> Tuple[str, bool]:
        """
        Cek kategori produk (L1 > L2 > L3):
        1. Cek cache SQLite.
        2. Jika belum ada: buka halaman detail produk FastMoss, ekstrak breadcrumb.
        3. Fallback: kata kunci nama produk.
        Return: (kategori_string, is_bawahan_wanita)
        """
        if not product_id and not product_name:
            return "", False

        cached = self.category_checker.get_cached(product_id)
        if cached:
            is_bawahan = bool(cached["is_bawahan_wanita"])
            cat_str = " > ".join(filter(None, [cached["category_l1"], cached["category_l2"], cached["category_l3"]]))
            if not cat_str and cached.get("method") == "keyword_fallback":
                cat_str = f"kategori: perkiraan"
            return cat_str, is_bawahan

        l1, l2, l3 = "", "", ""
        method = "breadcrumb"

        if product_id:
            try:
                prod_page = context.new_page()
                prod_url = f"https://www.fastmoss.com/{country.lower()}/e-commerce/detail/{product_id}"
                prod_page.goto(prod_url, timeout=25000, wait_until="domcontentloaded")
                self._sleep_random(2.0, 3.5)

                bc_sel = self.selectors.get("product_detail", {}).get("breadcrumb", ".breadcrumb, [class*='category-path']")
                bc_elems = prod_page.locator(bc_sel)
                
                if bc_elems.count() > 0:
                    bc_text = bc_elems.first.text_content() or ""
                    parts = [p.strip() for p in re.split(r"[>/»\n]+", bc_text) if p.strip()]
                    if len(parts) >= 1:
                        l1 = parts[0]
                    if len(parts) >= 2:
                        l2 = parts[1]
                    if len(parts) >= 3:
                        l3 = parts[2]

                prod_page.close()
            except Exception as e:
                logger.warning(f"Gagal memuat detail produk {product_id}: {e}")

        is_bawahan = self.category_checker.check_hierarchy(l1, l2, l3)

        if not is_bawahan and product_name:
            keyword_match, kw_label = self.category_checker.check_keyword_fallback(product_name, country)
            if keyword_match:
                is_bawahan = True
                method = "keyword_fallback"
                cat_str = kw_label
                self.category_checker.save_cache(product_id, product_name, "", "", "", True, method)
                return cat_str, True

        cat_str = " > ".join(filter(None, [l1, l2, l3]))
        if not cat_str and method == "breadcrumb":
            cat_str = "Lainnya"

        self.category_checker.save_cache(product_id, product_name, l1, l2, l3, is_bawahan, method)
        return cat_str, is_bawahan

    def scrape_creator_videos(
        self,
        page: Page,
        context: BrowserContext,
        creator_input: CreatorInput,
        creator_info: Dict,
        config: JobConfig
    ) -> Tuple[List[VideoItem], CreatorSummary]:
        detail_url = creator_info.get("detail_url") or ""
        nickname = creator_info.get("nickname") or creator_input.nama_kreator
        tiktok_id = creator_info.get("tiktok_id") or ""
        country = (creator_input.negara or config.country).lower()
        target_period = getattr(config, "period", "7 Hari") or "7 Hari"

        summary = CreatorSummary(
            nama_input=creator_input.nama_kreator,
            nickname=nickname,
            tiktok_id=tiktok_id,
            url_detail=detail_url,
            status="selesai",
            catatan=creator_info.get("catatan", "")
        )

        if not detail_url:
            summary.status = "gagal"
            summary.catatan = "URL detail kreator tidak ditemukan"
            return [], summary

        target_url = detail_url.split("#")[0]
        logger.info(f"Navigasi ke detail analitik video kreator: {target_url}")
        page.goto(target_url, timeout=40000, wait_until="domcontentloaded")
        self._sleep_random(3.0, 4.5)

        self.check_page_session(page)
        self.handle_login_modal_if_present(page, context=context)

        # Klik tab Analisis Video jika ada di header lengket
        try:
            tab_video = page.locator("li.anchor-ceiling-suction-item, a, div").filter(has_text="Analisis Video").first
            if tab_video.count() > 0 and tab_video.is_visible():
                tab_video.click()
                self._sleep_random(1.5, 2.5)
        except Exception:
            pass

        # Scroll ke bagian Daftar Video agar elemen ter-render sempurna
        try:
            dv = page.locator("xpath=//*[text()='Daftar Video']").first
            try:
                dv.wait_for(state="attached", timeout=12000)
            except Exception:
                pass
            if dv.count() > 0:
                dv.scroll_into_view_if_needed()
                self._sleep_random(1.5, 2.5)
            else:
                for _ in range(6):
                    page.mouse.wheel(0, 800)
                    self._sleep_random(0.4, 0.7)
                    if page.locator("xpath=//*[text()='Daftar Video']").count() > 0:
                        page.locator("xpath=//*[text()='Daftar Video']").first.scroll_into_view_if_needed()
                        self._sleep_random(1.5, 2.0)
                        break
        except Exception:
            pass

        # Ambil nickname & tiktok id dari header profil jika belum ada
        try:
            h_nick = page.locator(self.selectors.get("creator_detail", {}).get("header_nickname", "h1, .nickname")).first
            if h_nick.count() > 0:
                summary.nickname = h_nick.text_content().strip()
            h_id = page.locator(self.selectors.get("creator_detail", {}).get("header_tiktok_id", ".tiktok-id, span:has-text('ID:')")).first
            if h_id.count() > 0:
                summary.tiktok_id = h_id.text_content().replace("ID:", "").replace("@", "").strip()
        except Exception:
            pass

        # Pilih filter periode pada Daftar Video (default: 7 Hari, atau 28 Hari, 14 Hari, 90 Hari)
        logger.info(f"Memilih periode analitik video: '{target_period}'")
        try:
            period_locators = [
                page.locator(f"xpath=//*[text()='Daftar Video']/ancestor::div[contains(@class, 'flex')][1]//label[.//span[text()='{target_period}']]").first,
                page.locator(f"xpath=//*[text()='Daftar Video']/following::div[contains(@class, 'ant-radio-group')][1]//label[.//span[text()='{target_period}']]").first,
                page.locator(f"xpath=//*[text()='Daftar Video']/..//label[.//span[text()='{target_period}']]").first,
                page.locator(f"xpath=//*[text()='Daftar Video']/following::*//label[contains(@class, 'ant-radio-button-wrapper')]").filter(has_text=target_period).first
            ]

            target_btn = None
            for loc in period_locators:
                if loc.count() > 0:
                    try:
                        loc.wait_for(state="visible", timeout=4000)
                        if loc.is_visible():
                            target_btn = loc
                            break
                    except Exception:
                        pass

            if target_btn and target_btn.is_visible():
                target_btn.scroll_into_view_if_needed()
                btn_cls = target_btn.get_attribute("class") or ""
                if "ant-radio-button-wrapper-checked" not in btn_cls:
                    logger.info(f"Mengklik tombol filter periode '{target_period}' pada Daftar Video...")
                    target_btn.click()
                    self._sleep_random(2.0, 3.5)
                    # Double-check apakah status sudah checked, jika belum klik ulang
                    btn_cls = target_btn.get_attribute("class") or ""
                    if "ant-radio-button-wrapper-checked" not in btn_cls:
                        target_btn.click()
                        self._sleep_random(2.0, 3.0)
                else:
                    logger.info(f"Tombol periode '{target_period}' pada Daftar Video sudah dalam status aktif.")
            else:
                logger.warning(f"Tombol periode '{target_period}' di area Daftar Video tidak ditemukan/visible.")
        except Exception as p_err:
            logger.warning(f"Gagal memilih tombol periode '{target_period}': {p_err}")

        # Urutkan tabel video berdasarkan 'Penjualan dari Video' (omzet mata uang regional: RM / Rp)
        try:
            th_rev = page.locator("xpath=//*[text()='Daftar Video']/following::table[1]//th[contains(., 'Penjualan dari Video')]").first
            if th_rev.count() > 0 and th_rev.is_visible():
                is_desc = th_rev.locator(".anticon-caret-down.active").count() > 0
                if not is_desc:
                    logger.info("Mengurutkan tabel video berdasarkan 'Penjualan dari Video' (mata uang)...")
                    th_rev.click()
                    self._sleep_random(2.5, 3.5)
        except Exception as sort_err:
            logger.warning(f"Gagal mengurutkan tabel berdasarkan 'Penjualan dari Video': {sort_err}")

        # Selector tabel di bawah Daftar Video
        video_table_rows_sel = "xpath=//*[text()='Daftar Video']/following::table[1]//tbody/tr"
        try:
            page.wait_for_selector(video_table_rows_sel, timeout=8000)
        except Exception:
            pass

        # Periksa apakah ada baris data video valid
        all_trs = page.locator(video_table_rows_sel).all()
        if not all_trs:
            all_trs = page.locator("tbody tr").all()
            
        has_data = False
        for tr in all_trs:
            tr_txt = (tr.text_content() or "").strip()
            tds = tr.locator("td").all()
            if len(tds) >= 7 and "tidak ada data" not in tr_txt.lower():
                if any(c.text_content().strip() for c in tds):
                    has_data = True
                    break

        if not has_data:
            summary.status = "tanpa video"
            summary.catatan = f"Tidak ada video penjualan dalam {target_period}"
            return [], summary

        video_items = []
        max_videos = config.max_videos_per_creator
        page_num = 1
        product_sales_tracker = {}

        while len(video_items) < max_videos:
            rows = page.locator(video_table_rows_sel).all()
            if not rows:
                rows = page.locator("tbody tr").all()
                
            valid_page_rows = []
            for r in rows:
                r_txt = (r.text_content() or "").strip()
                cells = r.locator("td").all()
                if len(cells) >= 7 and "tidak ada data" not in r_txt.lower():
                    if any(c.text_content().strip() for c in cells):
                        valid_page_rows.append((r, cells))

            if not valid_page_rows:
                if len(video_items) == 0:
                    summary.status = "tanpa video"
                    summary.catatan = f"Tidak ada video penjualan dalam {target_period}"
                break

            for row, cells in valid_page_rows:
                if len(video_items) >= max_videos:
                    break

                c0 = cells[0]
                c0_text = (c0.text_content() or "").strip()

                # 1. Cek Badge AD
                ad_elems = c0.locator('text=AD, span:has-text("AD"), [class*="ad"]').all()
                is_ad = (len(ad_elems) > 0) or ("AD" in c0_text.split()) or c0_text.startswith("AD")

                # 2. Link Video
                v_link = row.locator("a[href*='/video/'], a[href*='tiktok.com']").first
                url_video = ""
                if v_link.count() > 0:
                    raw_v = v_link.get_attribute("href") or ""
                    url_video = f"https://www.fastmoss.com{raw_v}" if raw_v.startswith("/") else raw_v

                # 3. Durasi Video
                dur_match = re.search(r"Durasi:?\s*(\d+)s", c0_text, re.IGNORECASE)
                durasi = int(dur_match.group(1)) if dur_match else self._extract_duration_seconds(c0_text)

                # 4. Waktu Rilis (Col 1)
                waktu_rilis = (cells[1].text_content() or "").strip()
                if not re.search(r"\d{4}-\d{2}-\d{2}", waktu_rilis):
                    d_match = re.search(r"(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)", row.text_content() or "")
                    waktu_rilis = d_match.group(1) if d_match else ""

                # 5. Tipe Video (Col 2)
                tipe_video = (cells[2].text_content() or "").strip() or "Reguler"

                # 6. Penjualan Video Unit (Col 3)
                c3_text = (cells[3].text_content() or "").strip()
                sales_unit = self._normalize_number(c3_text) or 0

                # 7. Penjualan Dari Video Nilai (Col 4)
                sales_nilai = (cells[4].text_content() or "").strip()

                # 8. Jumlah Putaran / Views (Col 5)
                c5_text = (cells[5].text_content() or "").strip()
                views = self._normalize_number(c5_text) or 0

                # 9. Tingkat Interaksi (Col 6)
                c6_text = (cells[6].text_content() or "").strip()
                rate = self._normalize_rate(c6_text)

                # 10. Produk (Col 7 / Col Terakhir)
                p_link = row.locator("a[href*='/e-commerce/detail/'], a[href*='/product/']").first
                link_produk = ""
                product_id = ""
                nama_produk = ""
                if p_link.count() > 0:
                    raw_p = p_link.get_attribute("href") or ""
                    link_produk = f"https://www.fastmoss.com{raw_p}" if raw_p.startswith("/") else raw_p
                    id_m = re.search(r"/detail/([^/?]+)", raw_p)
                    if id_m:
                        product_id = id_m.group(1)
                    raw_name = p_link.get_attribute("title") or p_link.text_content() or ""
                    nama_produk = re.sub(r"Penjualan:.*$", "", raw_name).strip()

                if not nama_produk and len(cells) > 7:
                    raw_last = (cells[7].text_content() or "").strip()
                    nama_produk = re.sub(r"Penjualan:.*$", "", raw_last).strip()

                # 11. Cek Kategori Produk (Bawahan Wanita)
                cat_str, is_bawahan = self.get_product_category(context, product_id, nama_produk, country)

                if nama_produk:
                    product_sales_tracker[nama_produk] = product_sales_tracker.get(nama_produk, 0) + (sales_unit or 1)

                item = VideoItem(
                    nama_kreator_input=creator_input.nama_kreator,
                    nickname_fastmoss=summary.nickname,
                    tiktok_id=summary.tiktok_id,
                    url_detail_fastmoss=summary.url_detail,
                    negara=country.upper(),
                    ads="AD" if is_ad else "",
                    durasi_detik=durasi,
                    waktu_rilis=waktu_rilis,
                    tipe_video=tipe_video,
                    penjualan_video_unit=sales_unit,
                    penjualan_video_nilai=sales_nilai,
                    jumlah_putaran=views,
                    tingkat_interaksi=rate,
                    nama_produk=nama_produk,
                    link_produk=link_produk,
                    kategori_produk=cat_str,
                    url_video=url_video,
                    is_bawahan_wanita=is_bawahan,
                    is_ad=is_ad
                )
                video_items.append(item)

            # Pagination
            if len(video_items) < max_videos:
                next_btn = page.locator("xpath=//*[text()='Daftar Video']/following::ul[contains(@class, 'ant-pagination')][1]//li[contains(@class, 'ant-pagination-next') and not(contains(@class, 'ant-pagination-disabled'))]").first
                if next_btn.count() == 0 or not next_btn.is_visible():
                    next_btn = page.locator(".ant-pagination-next:not(.ant-pagination-disabled)").first
                if next_btn.count() > 0 and next_btn.is_visible():
                    logger.info(f"Klik halaman berikutnya ({page_num + 1}) untuk kreator {creator_input.nama_kreator}")
                    next_btn.click()
                    page_num += 1
                    self._sleep_random(3.0, 5.0)
                else:
                    break
            else:
                break

        summary.jumlah_video_7hari = len(video_items)
        summary.jumlah_video_ad = sum(1 for v in video_items if v.is_ad)
        summary.total_penjualan_video = sum(v.penjualan_video_unit or 0 for v in video_items)
        if product_sales_tracker:
            top_prod = max(product_sales_tracker.items(), key=lambda x: x[1])
            summary.produk_terlaris = f"{top_prod[0]} ({top_prod[1]} unit)"

        if len(video_items) == 0 and summary.status == "selesai":
            summary.status = "tanpa video"
            summary.catatan = f"Tidak ada video penjualan dalam {target_period}"

        return video_items, summary

    def run_job(
        self,
        creators: List[CreatorInput],
        config: JobConfig,
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None
    ) -> Path:
        videos_filtered: List[VideoItem] = []
        videos_other: List[VideoItem] = []
        summaries: List[CreatorSummary] = []
        logs: List[CreatorLog] = []

        total_creators = len(creators)
        logger.info(f"Memulai job FastMoss Scraper untuk {total_creators} kreator. Negara default: {config.country}")

        with sync_playwright() as p:
            launch_args = [
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox"
            ]

            import sys
            is_win = (sys.platform == "win32")
            launch_kwargs = {
                "headless": False,
                "args": launch_args
            }
            if is_win:
                launch_kwargs["channel"] = "chrome"

            browser = p.chromium.launch(**launch_kwargs)
            
            context_kwargs = {
                "viewport": {"width": 1440, "height": 900}
            }
            if self.storage_state_path.exists():
                context_kwargs["storage_state"] = str(self.storage_state_path)

            context = browser.new_context(**context_kwargs)
            page = context.new_page()

            for idx, c_input in enumerate(creators, start=1):
                c_name = c_input.nama_kreator.strip()
                c_country = (c_input.negara or config.country).upper()
                start_time = datetime.now()
                start_str = start_time.strftime("%Y-%m-%d %H:%M:%S")

                if progress_callback:
                    progress_callback(idx, total_creators, c_name, "sedang diproses")

                logger.info(f"[{idx}/{total_creators}] Memproses kreator: {c_name} ({c_country})")

                c_log = CreatorLog(
                    nama_input=c_name,
                    waktu_mulai=start_str
                )

                try:
                    status_search, info = self.search_creator(page, c_name, c_country)

                    if status_search == "selesai":
                        v_items, summary = self.scrape_creator_videos(page, context, c_input, info, config)
                        summaries.append(summary)

                        for item in v_items:
                            pass_ad = True if not config.filter_ad_only else item.is_ad
                            pass_cat = True if not config.filter_bawahan_only else item.is_bawahan_wanita
                            rev_val = parse_revenue_value(item.penjualan_video_nilai)
                            pass_rev = True if config.min_revenue <= 0 else (rev_val >= config.min_revenue)

                            if pass_ad and pass_cat and pass_rev:
                                videos_filtered.append(item)
                            else:
                                videos_other.append(item)

                        c_log.status = summary.status
                        c_log.pesan_error = summary.catatan

                    elif status_search == "tanpa video":
                        summary = CreatorSummary(
                            nama_input=c_name,
                            nickname=info.get("nickname", ""),
                            tiktok_id=info.get("tiktok_id", ""),
                            url_detail=info.get("detail_url", ""),
                            status="tanpa video",
                            catatan=info.get("catatan", "")
                        )
                        summaries.append(summary)
                        c_log.status = "tanpa video"
                        c_log.pesan_error = info.get("catatan", "")

                    elif status_search == "ambigu":
                        summary = CreatorSummary(
                            nama_input=c_name,
                            status="ambigu",
                            url_detail=info.get("detail_url", ""),
                            catatan=info.get("catatan", "")
                        )
                        summaries.append(summary)
                        c_log.status = "ambigu"
                        c_log.pesan_error = info.get("catatan", "")

                    else:
                        summary = CreatorSummary(
                            nama_input=c_name,
                            status="tidak ditemukan",
                            catatan=info.get("catatan", "Tidak ditemukan di FastMoss")
                        )
                        summaries.append(summary)
                        c_log.status = "tidak ditemukan"
                        c_log.pesan_error = summary.catatan

                except Exception as ex:
                    logger.error(f"Gagal memproses kreator {c_name}: {ex}", exc_info=True)
                    safe_name = re.sub(r"[^\w\-]", "_", c_name)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    ss_path = LOGS_DIR / f"{safe_name}_{ts}.png"
                    try:
                        page.screenshot(path=str(ss_path))
                        logger.info(f"Screenshot error disimpan ke: {ss_path}")
                    except Exception:
                        pass

                    summary = CreatorSummary(
                        nama_input=c_name,
                        status="gagal",
                        catatan=str(ex)
                    )
                    summaries.append(summary)
                    c_log.status = "gagal"
                    c_log.pesan_error = str(ex)

                end_time = datetime.now()
                c_log.waktu_selesai = end_time.strftime("%Y-%m-%d %H:%M:%S")
                c_log.durasi_detik = (end_time - start_time).total_seconds()
                logs.append(c_log)

                self._sleep_random(config.min_delay, config.max_delay)

            browser.close()

        logger.info("Menyusun file Excel laporan hasil...")
        excel_path = self.excel_handler.generate_report(
            videos_filtered=videos_filtered,
            videos_other=videos_other,
            summaries=summaries,
            logs=logs,
            config=config
        )
        logger.info(f"Laporan Excel berhasil dibuat: {excel_path}")
        return excel_path


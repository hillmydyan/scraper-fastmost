"""Product Category Classifier and SQLite Cache for FastMoss Scraper"""
import sqlite3
import re
from typing import Optional, Tuple, Dict
from src.config import CACHE_DB_PATH, get_category_config


class CategoryChecker:
    def __init__(self, db_path=CACHE_DB_PATH):
        self.db_path = db_path
        self.config = get_category_config()
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS product_categories (
                    product_id TEXT PRIMARY KEY,
                    product_name TEXT,
                    category_l1 TEXT,
                    category_l2 TEXT,
                    category_l3 TEXT,
                    is_bawahan_wanita INTEGER,
                    method TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def get_cached(self, product_id: str) -> Optional[Dict]:
        if not product_id:
            return None
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM product_categories WHERE product_id = ?",
                (product_id,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def save_cache(self, product_id: str, product_name: str, l1: str, l2: str, l3: str, is_bawahan: bool, method: str):
        if not product_id:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO product_categories 
                (product_id, product_name, category_l1, category_l2, category_l3, is_bawahan_wanita, method, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (product_id, product_name, l1, l2, l3, 1 if is_bawahan else 0, method))
            conn.commit()

    def check_hierarchy(self, l1: str, l2: str, l3: str = "") -> bool:
        """Periksa apakah hirarki kategori cocok dengan Pakaian Wanita -> Bawahan Wanita"""
        target = self.config.get("target_hierarchy", {})
        target_l1 = target.get("l1", "Pakaian & Pakaian Dalam Wanita").lower()
        target_l2 = target.get("l2", "Bawahan Wanita").lower()
        allowed_l3 = [x.lower() for x in target.get("l3_allowed", [])]

        l1_clean = (l1 or "").strip().lower()
        l2_clean = (l2 or "").strip().lower()
        l3_clean = (l3 or "").strip().lower()

        # Cocok L1 dan L2
        if target_l1 in l1_clean and target_l2 in l2_clean:
            return True
        
        # Jika L2 langsung menyebut bawahan wanita / rok / celana
        if "bawahan" in l2_clean and "wanita" in l2_clean:
            return True

        # Jika L3 ada dalam daftar L3 yang diizinkan dan L1/L2 pakaian wanita
        if any(allowed in l3_clean for allowed in allowed_l3):
            if "pakaian" in l1_clean or "wanita" in l1_clean or "wanita" in l2_clean:
                return True

        return False

    def check_keyword_fallback(self, product_name: str, country: str = "ID") -> Tuple[bool, str]:
        """Fallback pengecekan cerdas berdasarkan kata kunci nama produk (dengan filter eksklusi atasan & pria)"""
        if not product_name:
            return False, ""

        name_clean = product_name.lower().strip()

        # 1. Eksklusi produk pria / lelaki
        exclude_gender = self.config.get("exclude_gender_keywords", ["pria", "lelaki", "men", "man", "cowok"])
        for g in exclude_gender:
            if re.search(rf"\b{re.escape(g)}\b", name_clean):
                if not any(re.search(rf"\b{w}\b", name_clean) for w in ["wanita", "women", "perempuan", "cewek", "muslimah"]):
                    return False, ""

        # 2. Eksklusi produk atasan, baju, dress, baju kurung, dsb
        exclude_tops = self.config.get("exclude_keywords", [])
        for top in exclude_tops:
            if re.search(rf"\b{re.escape(top)}\b", name_clean):
                # Jika judul diawali dengan atasan (misal "Baju-T...", "Cardigan...", "Sweater...", "Jaket...")
                if re.search(rf"^(?:[\w\s]{{0,15}})?\b{re.escape(top)}\b", name_clean):
                    return False, ""
                # Jika frasa atasan mendahului kata bawahan (misal "jaket jeans", "kemeja jeans")
                if any(f"{top} {bot}" in name_clean for bot in ["jeans", "seluar", "celana"]):
                    return False, ""

        # 3. Pencocokan kata kunci bawahan wanita
        fallback_cfg = self.config.get("fallback_keywords", {})
        country_key = "malaysia" if country.upper() == "MY" else "indonesia"
        keywords = fallback_cfg.get(country_key, [])
        if country_key == "malaysia":
            keywords = list(set(keywords + fallback_cfg.get("indonesia", [])))

        # Urutkan dari keyword terpanjang dulu (e.g. 'seluar jeans' sebelum 'jeans')
        keywords = sorted(keywords, key=len, reverse=True)

        for kw in keywords:
            pattern = rf"(?:\b|_){re.escape(kw.lower())}(?:\b|_)"
            if re.search(pattern, name_clean):
                return True, f"kategori: perkiraan ({kw})"

        return False, ""


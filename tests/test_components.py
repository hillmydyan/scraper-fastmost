"""Unit tests for offline components (InputReader, CategoryChecker, ExcelHandler, AuthManager, Notifier)"""
import os
import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl
import pandas as pd
import pytest

from src.models import CreatorInput, VideoItem, CreatorSummary, CreatorLog, JobConfig
from src.input_reader import InputReader
from src.category_checker import CategoryChecker
from src.excel_handler import ExcelHandler
from src.auth import AuthManager
from src.notifier import Notifier
from src.job_manager import JobManager


def test_input_reader():
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        data = [
            {"nama_kreator": "  sirrah.fashion  ", "negara": "ID", "catatan": "Test 1"},
            {"nama_kreator": "SIRRAH.FASHION", "negara": "ID", "catatan": "Duplikat"},
            {"nama_kreator": "@gadisku", "negara": "MY", "catatan": "Test MY"},
            {"nama_kreator": "", "negara": "ID", "catatan": "Empty"},
        ]
        df = pd.DataFrame(data)
        df.to_excel(tmp_path, index=False)

        creators, stats = InputReader.read_input(tmp_path)
        assert len(creators) == 2
        assert creators[0].nama_kreator == "sirrah.fashion"
        assert creators[1].nama_kreator == "@gadisku"
        assert stats["duplicates_removed"] == 1
        assert stats["empty_rows_removed"] == 1
    finally:
        if tmp_path.exists():
            os.remove(tmp_path)


def test_category_checker():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        checker = CategoryChecker(db_path=db_path)

        # 1. Hierarchy Check
        assert checker.check_hierarchy("Pakaian & Pakaian Dalam Wanita", "Bawahan Wanita", "Rok") is True
        assert checker.check_hierarchy("Pakaian & Pakaian Dalam Wanita", "Atasan Wanita", "Kemeja") is False

        # 2. Keyword Fallback
        is_match, label = checker.check_keyword_fallback("Celana Kulot Linen Highwaist", "ID")
        assert is_match is True
        assert "kulot" in label or "celana" in label

        is_match_my, label_my = checker.check_keyword_fallback("Seluar Jeans Wanita Straight Cut", "MY")
        assert is_match_my is True
        assert "seluar" in label_my or "jeans" in label_my

        is_no_match, _ = checker.check_keyword_fallback("Lipstik Matte Herbal", "ID")
        assert is_no_match is False

        # 3. Cache Test
        checker.save_cache("prod_123", "Rok Mini", "Pakaian & Pakaian Dalam Wanita", "Bawahan Wanita", "Rok", True, "breadcrumb")
        cached = checker.get_cached("prod_123")
        assert cached is not None
        assert cached["is_bawahan_wanita"] == 1
        assert cached["category_l2"] == "Bawahan Wanita"
    finally:
        if db_path.exists():
            os.remove(db_path)


def test_excel_handler():
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        out_path = Path(tmp.name)

    try:
        handler = ExcelHandler()
        v1 = VideoItem(
            nama_kreator_input="sirrah.fashion",
            nickname_fastmoss="Sirrah Official",
            tiktok_id="sirrah.fashion",
            url_detail_fastmoss="https://www.fastmoss.com/id/influencer/detail/123",
            negara="ID",
            ads="AD",
            durasi_detik=45,
            waktu_rilis="2026-11-01 10:00:00",
            tipe_video="Reguler",
            penjualan_video_unit=1500,
            penjualan_video_nilai="Rp 150.000.000",
            jumlah_putaran=250000,
            tingkat_interaksi=0.052,
            nama_produk="Celana Kulot Highwaist",
            link_produk="https://www.fastmoss.com/id/e-commerce/detail/999",
            kategori_produk="Pakaian & Pakaian Dalam Wanita > Bawahan Wanita > Celana Panjang",
            url_video="https://www.tiktok.com/@sirrah/video/789",
            is_bawahan_wanita=True,
            is_ad=True
        )

        v_other = VideoItem(
            nama_kreator_input="sirrah.fashion",
            nickname_fastmoss="Sirrah Official",
            tiktok_id="sirrah.fashion",
            url_detail_fastmoss="https://www.fastmoss.com/id/influencer/detail/123",
            negara="ID",
            ads="",
            nama_produk="Blouse Polos",
            is_bawahan_wanita=False,
            is_ad=False
        )

        summary = CreatorSummary(
            nama_input="sirrah.fashion",
            nickname="Sirrah Official",
            tiktok_id="sirrah.fashion",
            status="selesai",
            jumlah_video_7hari=2,
            jumlah_video_ad=1,
            total_penjualan_video=1500,
            produk_terlaris="Celana Kulot Highwaist (1500 unit)",
            url_detail="https://www.fastmoss.com/id/influencer/detail/123"
        )

        log = CreatorLog(
            nama_input="sirrah.fashion",
            status="selesai",
            waktu_mulai="2026-11-02 09:00:00",
            waktu_selesai="2026-11-02 09:01:00",
            durasi_detik=60.0
        )

        config = JobConfig(country="ID")
        res_file = handler.generate_report(
            videos_filtered=[v1],
            videos_other=[v_other],
            summaries=[summary],
            logs=[log],
            config=config,
            custom_filepath=out_path
        )

        wb = openpyxl.load_workbook(res_file)
        sheet_names = wb.sheetnames
        assert "Video" in sheet_names
        assert "Video Lainnya" in sheet_names
        assert "Ringkasan Kreator" in sheet_names
        assert "Log" in sheet_names

        ws_v = wb["Video"]
        assert ws_v.cell(row=2, column=1).value == "sirrah.fashion"
        assert ws_v.cell(row=2, column=6).value == "AD"
        assert ws_v.cell(row=2, column=10).value == 1500

    finally:
        if out_path.exists():
            os.remove(out_path)


def test_auth_manager():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        auth = AuthManager(db_path=db_path)
        
        # Test default seeded accounts
        admin = auth.authenticate("admin@kurmagroup.com", "admin123")
        assert admin is not None
        assert admin.is_admin is True

        staff = auth.authenticate("staff@kurmagroup.com", "staff123")
        assert staff is not None
        assert staff.is_admin is False

        # Test invalid password
        wrong = auth.authenticate("admin@kurmagroup.com", "wrongpass")
        assert wrong is None
    finally:
        if db_path.exists():
            os.remove(db_path)


def test_notifier():
    notifier = Notifier()
    # Test formatting and dispatch without crashing
    assert notifier.send_message("Test message") is True


if __name__ == "__main__":
    test_input_reader()
    print("[PASS] test_input_reader")
    test_category_checker()
    print("[PASS] test_category_checker")
    test_excel_handler()
    print("[PASS] test_excel_handler")
    test_auth_manager()
    print("[PASS] test_auth_manager")
    test_notifier()
    print("[PASS] test_notifier")
    print("All component & system tests passed successfully!")

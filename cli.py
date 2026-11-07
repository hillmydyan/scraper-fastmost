"""Command Line Interface (CLI) for FastMoss Kreator Analitik Scraper (Fase 1 Engine)"""
import argparse
import sys
from pathlib import Path
import pandas as pd

from src.config import DEFAULT_STORAGE_STATE_PATH
from src.session_manager import SessionManager
from src.scraper import FastMossScraper
from src.input_reader import InputReader
from src.models import JobConfig


def cmd_login(args):
    session_mgr = SessionManager()
    session_mgr.login_interactive(country=args.country)


def cmd_check_session(args):
    session_mgr = SessionManager()
    is_valid, msg = session_mgr.validate_session(country=args.country)
    if is_valid:
        print(f"[BERHASIL] {msg}")
    else:
        print(f"[PERINGATAN] {msg}")
        sys.exit(1)


def cmd_sample_input(args):
    output_path = Path(args.output)
    sample_data = [
        {"nama_kreator": "GADISKU", "negara": "MY", "catatan": "Kreator Fashion Malaysia"},
        {"nama_kreator": "sirrah.fashion", "negara": "ID", "catatan": "Brand Bawahan Wanita"},
        {"nama_kreator": "@jiniso.id", "negara": "ID", "catatan": "Jeans & Bawahan Wanita"},
        {"nama_kreator": "lozyhijab", "negara": "ID", "catatan": "Fashion Muslimah"}
    ]
    df = pd.DataFrame(sample_data)
    df.to_excel(output_path, index=False)
    print(f"[OK] File template sampel berhasil dibuat: {output_path.resolve()}")


def cmd_scrape(args):
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERROR] File input '{args.input}' tidak ditemukan.")
        sys.exit(1)

    session_mgr = SessionManager()
    if not session_mgr.has_session_file():
        print("[PERINGATAN] File storage_state.json belum ada.")
        print("Jalankan: python cli.py login --country ID")
        print("Lalu coba kembali.")
        sys.exit(1)

    print("\n--- Validasi Sesi FastMoss ---")
    is_valid, msg = session_mgr.validate_session(country=args.country)
    print(f"Status sesi: {msg}")
    if not is_valid:
        print("[ERROR] Sesi FastMoss tidak valid atau telah kadaluarsa. Silakan jalankan 'python cli.py login'.")
        sys.exit(1)

    print("\n--- Membaca File Input ---")
    try:
        creators, stats = InputReader.read_input(input_path, default_country=args.country)
        print(f"Total baris awal      : {stats['total_initial']}")
        print(f"Nama kreator valid    : {stats['valid_count']}")
        print(f"Duplikat dibuang      : {stats['duplicates_removed']}")
        print(f"Baris kosong dibuang  : {stats['empty_rows_removed']}")
    except Exception as e:
        print(f"[ERROR] Gagal memproses file input: {e}")
        sys.exit(1)

    if not creators:
        print("[ERROR] Tidak ada nama kreator valid untuk diproses.")
        sys.exit(1)

    config = JobConfig(
        country=args.country.upper(),
        max_videos_per_creator=args.max_videos,
        filter_ad_only=not args.all_ads,
        filter_bawahan_only=not args.all_categories,
        min_delay=args.min_delay,
        max_delay=args.max_delay
    )

    print("\n--- Parameter Scraping (Prinsip: Asal Benar & Stabil) ---")
    print(f"Negara default        : {config.country}")
    print(f"Maksimal video/kreator: {config.max_videos_per_creator}")
    print(f"Filter Label AD       : {'Hanya ber-badge AD' if config.filter_ad_only else 'Semua Video'}")
    print(f"Filter Kategori       : {'Hanya Bawahan Wanita' if config.filter_bawahan_only else 'Semua Kategori'}")
    print(f"Jeda acak antar aksi  : {config.min_delay} - {config.max_delay} detik")
    print("----------------------------------------------------------\n")

    scraper = FastMossScraper()

    def on_progress(idx, total, name, status):
        print(f"[{idx}/{total}] {name} -> {status}...")

    excel_output = scraper.run_job(creators, config, progress_callback=on_progress)
    print(f"\n=======================================================")
    print(f"SCRAPING SELESAI!")
    print(f"File hasil Excel: {excel_output.resolve()}")
    print(f"=======================================================")


def main():
    parser = argparse.ArgumentParser(description="FastMoss Kreator Analitik Scraper CLI")
    subparsers = parser.add_subparsers(dest="command", help="Perintah yang tersedia")

    p_login = subparsers.add_parser("login", help="Buka browser Chromium headed untuk login manual dan simpan sesi")
    p_login.add_argument("--country", default="id", help="Kode negara (id / my)")

    p_check = subparsers.add_parser("check-session", help="Validasi sesi aktif di FastMoss")
    p_check.add_argument("--country", default="id", help="Kode negara (id / my)")

    p_sample = subparsers.add_parser("sample-input", help="Buat template file Excel contoh untuk daftar kreator")
    p_sample.add_argument("--output", default="template_kreator.xlsx", help="Nama file template output")

    p_scrape = subparsers.add_parser("scrape", help="Jalankan scraping FastMoss dari file input Excel/CSV")
    p_scrape.add_argument("--input", "-i", required=True, help="Path ke file input .xlsx atau .csv")
    p_scrape.add_argument("--country", default="ID", help="Negara target (ID atau MY)")
    p_scrape.add_argument("--max-videos", type=int, default=50, help="Maksimal video per kreator (default: 50)")
    p_scrape.add_argument("--all-ads", action="store_true", help="Ambil semua video tanpa menyaring label AD saja")
    p_scrape.add_argument("--all-categories", action="store_true", help="Ambil semua kategori produk tanpa menyaring Bawahan Wanita")
    p_scrape.add_argument("--min-delay", type=float, default=3.0, help="Jeda minimum antar aksi (detik)")
    p_scrape.add_argument("--max-delay", type=float, default=7.0, help="Jeda maksimum antar aksi (detik)")

    args = parser.parse_args()

    if args.command == "login":
        cmd_login(args)
    elif args.command == "check-session":
        cmd_check_session(args)
    elif args.command == "sample-input":
        cmd_sample_input(args)
    elif args.command == "scrape":
        cmd_scrape(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()


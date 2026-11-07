"""Data models for FastMoss Scraper"""
from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime
from src.utils import parse_revenue_value


@dataclass
class CreatorInput:
    nama_kreator: str
    negara: str = "ID"
    catatan: str = ""


@dataclass
class VideoItem:
    nama_kreator_input: str
    nickname_fastmoss: str
    tiktok_id: str
    url_detail_fastmoss: str
    negara: str
    ads: str  # "AD" atau ""
    durasi_detik: Optional[int] = None
    waktu_rilis: Optional[str] = None
    tipe_video: Optional[str] = None
    penjualan_video_unit: Optional[int] = None
    penjualan_video_nilai: Optional[str] = None
    jumlah_putaran: Optional[int] = None
    tingkat_interaksi: Optional[float] = None
    nama_produk: Optional[str] = None
    link_produk: Optional[str] = None
    kategori_produk: Optional[str] = None
    url_video: Optional[str] = None
    diambil_pada: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M WIB"))
    is_bawahan_wanita: bool = False
    is_ad: bool = False


@dataclass
class CreatorSummary:
    nama_input: str
    nickname: str = ""
    tiktok_id: str = ""
    status: str = "menunggu"  # selesai, tanpa video, tidak ditemukan, ambigu, gagal
    jumlah_video_7hari: int = 0
    jumlah_video_ad: int = 0
    total_penjualan_video: int = 0
    produk_terlaris: str = ""
    url_detail: str = ""
    durasi_scrape_detik: float = 0.0
    catatan: str = ""


@dataclass
class CreatorLog:
    nama_input: str
    status: str = "sukses"
    pesan_error: str = ""
    waktu_mulai: str = ""
    waktu_selesai: str = ""
    durasi_detik: float = 0.0


@dataclass
class JobConfig:
    country: str = "ID"  # "ID" atau "MY"
    period: str = "7 Hari"  # "7 Hari", "28 Hari", "14 Hari", "90 Hari"
    max_videos_per_creator: int = 50
    min_revenue: float = 0.0  # Minimal omzet/pendapatan video (dalam mata uang region: RM atau Rp)
    filter_ad_only: bool = True
    filter_bawahan_only: bool = True
    min_delay: float = 3.0
    max_delay: float = 7.0


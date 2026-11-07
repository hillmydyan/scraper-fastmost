# FastMoss Kreator Analitik Scraper (Web App & VPS)

Aplikasi otomasi riset kreator TikTok Shop melalui FastMoss untuk mengekstrak metrik performa video penjualan 7 hari terakhir (fokus kategori **Bawahan Wanita** & label **Ads**), dikembangkan berdasarkan spesifikasi dokumen PRD Kurma Group Indonesia.

---

## 🚀 Prinsip Utama: *"Asal Benar & Stabil, Tidak Perlu Cepat"*
* Scraper mengutamakan **akurasi data 100% dan keamanan akun** di atas kecepatan.
* Menggunakan jeda santai manusiawi (**3–7 detik antar aksi**) dan selalu menunggu elemen tabel / breadcrumb selesai di-render secara utuh sebelum mengekstrak data.
* Mencegah pemblokiran, deteksi bot, rate limit, atau captcha dari FastMoss.

---

## 📁 Struktur Direktori

```text
scraper-fastmoss/
├── config/
│   ├── selectors.yaml           # Selector UI FastMoss (mudah diganti jika UI berubah)
│   ├── kategori_target.yaml     # Hirarki kategori resmi & kata kunci fallback
│   └── notifications.yaml       # Konfigurasi Notifikasi Bot Telegram & WhatsApp
├── src/
│   ├── __init__.py
│   ├── config.py                # Loader konfigurasi & path sistem
│   ├── models.py                # Dataclass untuk Input, Video, Summary, Log
│   ├── input_reader.py          # Validasi & pembersih input Excel/CSV (dedup, trim)
│   ├── category_checker.py      # SQLite cache & pengklasifikasi Bawahan Wanita
│   ├── excel_handler.py         # OpenPyXL styler: 3 sheets, highlight AD, freeze pane
│   ├── session_manager.py       # Pengelola storage_state.json, noVNC & validasi login
│   ├── scraper.py               # Core Playwright scraping engine (Retry 3x & Anti-bot)
│   ├── job_manager.py           # Antrean job SQLite & auto-resume setelah restart
│   ├── auth.py                  # Autentikasi Pengguna & Role (Admin / Staff)
│   └── notifier.py              # Pengirim notifikasi Telegram & WhatsApp
├── templates/
│   ├── base.html                # Layout utama Tailwind CSS & Navigasi
│   ├── login.html               # Halaman Login Akun Kurma
│   ├── index.html               # Halaman 1: Upload Job Baru & Drag & Drop
│   ├── job_progress.html        # Halaman 2: Progres Realtime & Tabel Kreator
│   ├── history.html             # Halaman 3: Riwayat Job & Download Hasil
│   └── session.html             # Halaman Admin: Manajemen Sesi FastMoss & noVNC
├── storage/
│   ├── sessions/                # Lokasi file storage_state.json
│   ├── outputs/                 # Lokasi file hasil export .xlsx (disimpan 30 hari)
│   ├── uploads/                 # File Excel/CSV yang diupload user
│   ├── logs/                    # Screenshot failure debug & structured log
│   ├── cache.db                 # SQLite cache kategori produk FastMoss
│   ├── jobs.db                  # SQLite database riwayat job & antrean
│   └── users.db                 # SQLite database akun pengguna
├── tests/
│   └── test_components.py       # Unit test validasi komponen offline
├── app.py                       # Server Web Flask (API & Frontend)
├── cli.py                       # CLI Runner (Fase 1 Engine)
├── Dockerfile                   # Konfigurasi Docker VPS (Ubuntu 22.04 + noVNC + Playwright)
├── docker-compose.yml           # Orkestrasi Docker container
├── supervisord.conf             # Daemon supervisor (Xvfb, x11vnc, noVNC, Flask)
├── nginx.conf                   # Template konfigurasi reverse proxy Nginx HTTPS
├── requirements.txt             # Dependensi Python
└── README.md
```

---

## 🌐 Menjalankan Web Application (Flask)

### 1. Menjalankan di Komputer Lokal / Server Manual
```bash
python app.py
```
Aplikasi web akan berjalan di: **`http://localhost:5000`**

### 2. Akun Login Bawaan (Default)
Aplikasi diamankan dengan otentikasi role-based sesuai PRD:
* **Admin IT:** `admin@kurmagroup.com` / `admin123` (bisa melihat semua job & mengakses menu Sesi FastMoss / noVNC).
* **Staff Riset:** `staff@kurmagroup.com` / `staff123` (hanya dapat mengupload dan melihat job miliknya sendiri).

---

## 🚀 Fitur Lengkap Sistem (Semua Fase PRD Selesai)

1. **Fase 1 — Engine Scraping CLI & Format Excel (Selesai)**:
   * Playwright Chromium headless.
   * Format Excel sesuai spesifikasi Bagian 5.2 PRD: 3 sheet (`Video`, `Ringkasan Kreator`, `Log`), format angka murni, kolom AD berwarna kuning muda, dan link aktif.
   * Filter L1/L2 Bawahan Wanita dengan cache SQLite (`storage/cache.db`) dan fallback kata kunci.

2. **Fase 2 — API, Antrean Job & Sesi noVNC di VPS (Selesai)**:
   * Antrean job sekuensial (1 worker / 1 sesi aktif) untuk menjaga keamanan akun FastMoss.
   * Virtual Display (**Xvfb**) + **x11vnc** + **noVNC (websockify)**: Admin dapat login ke FastMoss via browser visual asli langsung dari halaman admin web app tanpa install software VNC tambahan.
   * Health-check sesi otomatis sebelum job dimulai.

3. **Fase 3 — Web Application Responsif & Manajemen Role (Selesai)**:
   * Halaman 1: Buat Job Baru dengan validasi instan drag-and-drop file Excel/CSV.
   * Halaman 2: Live monitoring progres realtime per kreator (badge status warna, durasi, tombol jeda/lanjut/batal).
   * Halaman 3: Riwayat job dan download file Excel hasil.
   * Autentikasi Kurma Group dengan pembatasan hak akses Admin vs Staff.

4. **Fase 4 — Hardening & Keandalan Produksi (Selesai)**:
   * **Retry Logic Otomatis**: Jika terjadi timeout / selector tidak muncul, sistem melakukan retry hingga 3x dengan interval backoff (10s, 30s, 60s) dan menyimpan screenshot error ke folder `storage/logs/`.
   * **Auto-Resume Pasca VPS Restart**: Jika VPS ter-restart di tengah proses, worker otomatis melanjutkan job dari kreator terakhir yang belum selesai.
   * **Notifikasi Bot Admin**: Terintegrasi bot Telegram dan WhatsApp webhook untuk peringatan cepat jika sesi FastMoss putus atau job selesai.

---

## 🐳 Deployment di VPS Menggunakan Docker Compose

Deploy aplikasi di VPS Ubuntu 22.04 hanya butuh 1 perintah:

```bash
docker compose up -d --build
```
Semua service (Xvfb virtual display, x11vnc, noVNC websockify port 6080, Flask app port 5000, Chromium browser) akan otomatis berjalan di dalam kontainer terisolasi dengan persistent volume untuk folder `storage/`.

---

## 🧪 Pengujian Komponen (Unit Tests)

Jalankan seluruh rangkaian test unit:
```bash
python tests/test_components.py
```
Semua modul (*InputReader, CategoryChecker, ExcelHandler, AuthManager, Notifier*) telah lulus uji 100%.

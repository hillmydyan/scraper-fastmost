# PRD — FastMoss Kreator Analitik Scraper (Web App di VPS)

Oct 31, 2026 · @Kurma · Kurma Group Indonesia

## 1. Ringkasan produk

Aplikasi web yang berjalan penuh di VPS Kurma Group (dibuka lewat browser, tanpa instalasi) yang mengambil data **video penjualan 7 hari terakhir** dari kreator TikTok Shop lewat FastMoss, tanpa staff harus buka FastMoss satu per satu. User cukup upload Excel berisi daftar nama kreator, klik Mulai, lalu tunggu file Excel hasilnya.

**Masalah yang diselesaikan.** Riset kreator kompetitor (kategori Bawahan Wanita) saat ini dikerjakan manual: buka FastMoss, cari nama, buka tab Analisis Video, set 7 hari, urutkan penjualan, catat produk dan video yang pakai label Ads. Untuk puluhan kreator per hari ini makan waktu berjam-jam dan rawan salah catat.

**Tujuan.**

- Satu kali login FastMoss di VPS, dipakai bersama oleh semua user web app.
- Input puluhan sampai ratusan nama kreator sekaligus dari Excel.
- Output Excel seragam: kreator, video, produk, status Ads, metrik penjualan 7 hari.
- Mengutamakan akurasi dan kebenaran data di atas kecepatan: proses per kreator tidak perlu buru-buru (tanpa target waktu ketat), mengutamakan jeda manusiawi dan pemuatan elemen yang tuntas agar data valid 100% serta akun aman dari deteksi bot/rate-limit.

**Di luar cakupan (v1).** Scraping produk per kategori (sudah dicakup proyek Kalodata), analisis siaran langsung, data pengikut, otomatis follow/kontak kreator, dan scraping selain FastMoss.

**Pengguna.** Tim riset Fashion INA-MLY (Nawa, Alfina) dan Tim Herbal (Silvia) di Kurma Group; admin teknis = tim IT (2 orang) yang memegang VPS dan sesi login FastMoss.

## 2. Alur kerja end-to-end

&#91;embedded content: alur scraping · upload sampai export, 1 loop per kreator\]

User hanya menyentuh dua titik: upload Excel di awal dan download hasil di akhir. Semua langkah di tengah dikerjakan engine di VPS, satu kreator per giliran, dan status tiap kreator tampil realtime di halaman web.

**Detail tiap langkah.**

1. **Upload Excel.** Web app membaca kolom nama kreator, membersihkan spasi/duplikat, lalu mengirim daftar ke VPS sebagai satu *job*.
2. **Ketik nama di pencarian FastMoss.** Engine membuka Lainnya → Kreator → Pencarian Kreator, set negara (Indonesia/Malaysia sesuai pilihan user), ketik nama di kotak pencarian nickname.
3. **Validasi kreator.** Dianggap ketemu bila nickname atau ID TikTok (contoh: `sirrah.fashion`) cocok persis (case-insensitive). Lebih dari satu hasil dan tidak ada yang persis → tandai *ambigu* dan simpan kandidat teratas untuk dicek manual.
4. **Analisis Video, 7 hari.** Buka halaman detail kreator → tab Analisis Video → pilih 7 Hari → urutkan kolom Penjualan Video dari terbanyak.
5. **Ambil data.** Untuk tiap baris video: judul/link video, durasi, waktu rilis, tipe video, produk yang dijual, penjualan video, penjualan dari video (nilai), jumlah putaran, tingkat interaksi, dan label **AD** bila ada pada thumbnail.
6. **Simpan baris hasil.** Satu baris per video per kreator; kreator tanpa video 7 hari tetap muncul satu baris dengan status `tanpa video`.
7. **Ulangi** sampai antrean habis, lalu engine menyusun Excel hasil dan halaman web menampilkan tombol download.

## 3. Arsitektur sistem

&#91;embedded content: arsitektur · desktop app, VPS, FastMoss\]

Tiga zona: staff cukup membuka web app di browser, VPS menjalankan API + antrean + worker scraping dan menyimpan sesi FastMoss, lalu FastMoss diakses hanya dari VPS. Akun FastMoss cukup satu dan tidak pernah dipegang staff.

| Komponen | Tanggung jawab | Catatan |
| --- | --- | --- |
| Web App (browser) | Upload Excel, tampilkan progres per kreator, unduh hasil, pilih negara (ID/MY) | Di-serve dari VPS, dibuka dari PC atau HP; login akun Kurma |
| API Server (VPS) | Terima job, simpan daftar nama, kirim status (WebSocket/polling), serve file hasil | Satu endpoint publik, HTTPS, IP/VPN whitelist opsional |
| Antrean Job | Urutkan job per user, satu job diproses satu worker | Mencegah dua job menekan satu sesi FastMoss bersamaan |
| Scraping Worker | Jalankan Playwright dengan cookies FastMoss, navigasi, ekstrak data | 1 browser context aktif; jeda santai & manusiawi (3–8 detik antar aksi) untuk stabilitas, akurasi data, dan anti-bot |
| Sesi FastMoss | Chromium headed + noVNC untuk login manual admin; simpan storage\_state; deteksi sesi kadaluarsa | storage\_state dimuat ke browser context headless tiap job dimulai |
| Database + penyimpanan | Riwayat job, baris hasil, file .xlsx | SQLite cukup untuk v1; Postgres bila job > 50/hari |

## 4. Spesifikasi scraping FastMoss

Worker meniru persis klik yang dilakukan staff hari ini. Urutan navigasi di bawah mengacu ke UI FastMoss versi Oktober 2026; selector harus disimpan di satu file konfigurasi agar mudah diganti saat UI berubah.

**4.1 Navigasi per kreator**

1. Buka `https://www.fastmoss.com/{negara}/influencer/search` (`id` untuk Indonesia, `my` untuk Malaysia). Pastikan dropdown negara di header sesuai; bila tidak, ganti lewat dropdown.
2. Isi kotak pencarian "Silakan masukkan nama pengguna (nickname)" dengan nama dari Excel, tekan Enter, tunggu tabel hasil termuat (network idle maksimal 15 detik).
3. Cocokkan hasil: prioritas (a) ID TikTok persis sama, (b) nickname persis sama (abaikan huruf besar/kecil, emoji, dan spasi ganda), (c) satu-satunya hasil. Tidak ada yang memenuhi → status `tidak ditemukan` / `ambigu`.
4. Klik kreator → halaman `influencer/detail/{id}`. Catat ID FastMoss ini ke hasil supaya scraping berikutnya bisa langsung ke URL detail tanpa pencarian.
5. Klik tab **Analisis Video** → pilih **7 Hari** → Status Penayangan Iklan biarkan **Semua** → klik header **Penjualan Video** sampai urut menurun (nilai terbesar di atas).
6. Baca semua baris di halaman; bila ada paginasi, lanjut sampai halaman habis atau sampai batas `maks_video_per_kreator` (default 50).
7. Scroll ke kanan tabel untuk kolom produk (thumbnail + nama produk di kolom paling kanan). Bila nama produk terpotong, ambil dari atribut `title`/tooltip atau buka hover.

**4.2 Filter kategori produk: Pakaian & Pakaian Dalam Wanita → Bawahan Wanita.** Filter *Kategori Penjualan* di halaman Pencarian Kreator hanya me-ranking kreator, bukan menyaring videonya. Di tabel Analisis Video, satu kreator menjual banyak produk dari kategori berbeda (contoh GADISKU: shawl hoodie, mini hoodie cotton) dan kolom produk **tidak menampilkan kategori**. Karena itu engine menentukan kategori per produk sendiri, lalu menyaring video:

1. Dari tiap baris video, ambil ID produk dari link thumbnail/nama produk di kolom Penjualan Produk.
2. Cek **cache kategori produk** di database (`product_id → kategori L1/L2/L3 FastMoss`). Bila belum ada, buka halaman detail produk FastMoss (`/id/e-commerce/detail/{product_id}`) dan baca breadcrumb/label kategorinya sekali saja, simpan ke cache. Produk yang sama di kreator lain tidak dibuka ulang.
3. Video **lolos** bila kategori L1 = *Pakaian & Pakaian Dalam Wanita* dan L2 = *Bawahan Wanita* (semua L3: Rok, Celana Pendek, Legging, Jeans, Celana Panjang, Skirt Pants & Skorts). Bila halaman detail produk tidak memuat kategori, fallback ke kata kunci nama produk (rok, celana, legging, jeans, kulot, skort; Melayu: seluar, skirt) dan tandai `kategori: perkiraan`.
4. Default job: **hanya video ber-label AD dan produk Bawahan Wanita** yang ditulis ke sheet Video. Video lain tidak dibuang, tapi masuk sheet `Video Lainnya` supaya tetap bisa dicek. Kedua filter bisa dimatikan user lewat opsi lanjutan (bagian 6).

Kategori yang dipantau disimpan sebagai daftar di konfigurasi admin (`kategori_target.yaml`), jadi nanti bisa ditambah Atasan Wanita, Hijab, dan lainnya tanpa ubah kode. Alternatif yang perlu dicoba developer di Fase 1: tombol **Ekspor Data** di Analisis Video (akun Profesional) — bila file ekspornya memuat ID produk atau kategori, pakai itu untuk mengurangi klik per kreator.

**4.3 Aturan label Ads.** Thumbnail video di FastMoss memakai badge **AD** di pojok kiri atas (lihat contoh kreator GADISKU). Aturan: badge ada → kolom `Ads` = `AD`; badge tidak ada → kolom dikosongkan (bukan `Tidak`). Sebagai pembanding, catat juga nilai kolom *Status Penayangan Iklan* bila FastMoss menampilkannya per baris.

**4.4 Data yang diambil per baris video**

| Kolom output | Sumber di FastMoss | Format |
| --- | --- | --- |
| Nama kreator (input) | Dari Excel user | teks |
| Nickname FastMoss | Header halaman detail | teks |
| ID TikTok | Header detail, "ID:" | teks |
| URL detail FastMoss | URL halaman | link |
| Negara | Dropdown negara | ID / MY |
| Ads | Badge AD pada thumbnail | `AD` atau kosong |
| Durasi video | Teks "Durasi:" | detik, angka |
| Waktu rilis | Kolom Waktu Rilis | `YYYY-MM-DD HH:MM:SS` |
| Tipe video | Kolom Tipe Video | teks |
| Penjualan video (unit) | Kolom Penjualan Video | angka |
| Penjualan dari video (nilai) | Kolom Penjualan dari Video | angka + mata uang (Rp/RM) |
| Jumlah putaran | Kolom Jumlah Putaran | angka |
| Tingkat interaksi | Kolom Tingkat Interaksi | persen, angka desimal |
| Nama produk | Kolom produk paling kanan | teks |
| Link produk / ID produk | Link pada thumbnail produk | link |
| Kategori produk | Kategori L1 > L2 > L3 dari detail produk FastMoss (4.2) | Ya / kosong |
| URL video | Link thumbnail video | link |
| Diambil pada | Jam server VPS | `YYYY-MM-DD HH:MM` WIB |

Angka disimpan sebagai angka murni (bukan teks "799.960"); pemisah ribuan FastMoss (titik) dan koma desimal harus dinormalkan sebelum ditulis ke Excel.

**4.5 Ritme, keandalan, dan batasan akses.**
Prinsip utama: **"Asal Benar & Stabil, Tidak Perlu Cepat"**.
Satu browser context, jeda acak 3–8 detik antar aksi navigasi dan scroll, maksimal 1 kreator aktif per sesi FastMoss. Worker mengutamakan akurasi: selalu menunggu elemen data, request jaringan (network idle), dan render tabel/kategori selesai secara penuh sebelum mengekstrak nilai (menghindari data terlewat atau stale elements). Tidak ada target throughput cepat yang dipaksakan; kecepatan dikompromikan demi akurasi data 100% dan keamanan akun FastMoss dari deteksi bot, rate limit, atau captcha. Bila FastMoss menampilkan captcha, halaman login, atau pesan batas paket → job dijeda otomatis, status `sesi perlu login ulang`, dan admin diberi notifikasi.

## 5. Spesifikasi input dan output Excel

**5.1 Input (.xlsx atau .csv).** Satu sheet, header di baris 1. Hanya kolom `nama_kreator` yang wajib; sisanya opsional dan diteruskan ke output.

| Kolom | Wajib | Isi |
| --- | --- | --- |
| nama\_kreator | Ya | Nickname atau ID TikTok, satu per baris. Boleh diawali `@` |
| negara | Tidak | `ID` atau `MY`; kosong → ikut pilihan negara di app |
| catatan | Tidak | Teks bebas user, ikut tercetak di output |

Validasi saat upload: baris kosong dibuang, duplikat (setelah trim + lowercase) digabung dan dilaporkan, maksimal 500 nama per job (bisa diubah admin). App menampilkan ringkasan "N nama valid, M duplikat dibuang" sebelum tombol Mulai aktif.

**5.2 Output (.xlsx).** Nama file `fastmoss_{negara}_{YYYYMMDD_HHMM}.xlsx`, tiga sheet:

| Sheet | Isi | Satu baris = |
| --- | --- | --- |
| Video | Video yang lolos filter AD + Bawahan Wanita; semua kolom tabel 4.4, urut per kreator lalu Penjualan Video menurun. Video yang tidak lolos masuk sheet tambahan Video Lainnya | satu video |
| Ringkasan Kreator | Nama input, nickname, ID TikTok, status, jumlah video 7 hari, jumlah video AD, total penjualan video, produk terlaris, URL detail | satu kreator |
| Log | Nama input, status, pesan error, waktu mulai/selesai, durasi detik | satu kreator |

Status kreator di sheet Ringkasan dan Log: `selesai`, `tanpa video`, `tidak ditemukan`, `ambigu`, `gagal` (dengan pesan error). Header dibekukan (freeze pane), kolom AD diberi fill kuning muda, angka berformat angka (bukan teks), link berupa hyperlink aktif.

## 6. Spesifikasi UI web app

Satu web app responsif (PC dan HP), tiga halaman. Prinsip: user tidak perlu tahu ada browser atau VPS di belakang; yang terlihat hanya "upload → tunggu → unduh".

**Halaman 1 — Job baru**

- Area drop file Excel/CSV + tombol Pilih File.
- Pilihan negara: Indonesia / Malaysia (default Indonesia, diingat dari job terakhir).
- Opsi lanjutan (terlipat): maks video per kreator (default 50), hanya ambil video ber-label AD (default nyala), hanya produk kategori Bawahan Wanita (default nyala), kategori target bisa dipilih dari daftar.
- Ringkasan validasi: jumlah nama valid, duplikat dibuang, baris kosong.
- Tombol **Mulai Scraping** (aktif bila sesi FastMoss di VPS berstatus `aktif`).

**Halaman 2 — Progres job**

- Progress bar: `23 / 120 kreator`, estimasi sisa waktu, indikator status progres & akurasi.
- Tabel realtime per kreator: nama, status (ikon warna), jumlah video, jumlah AD, durasi proses. Baris yang sedang diproses disorot.
- Tombol Jeda, Lanjutkan, Batalkan. Batal tetap menyimpan hasil parsial dan mengizinkan unduh.
- Banner merah bila sesi FastMoss putus: "Sesi FastMoss perlu login ulang — hubungi Admin IT", job otomatis jeda.

**Halaman 3 — Riwayat & hasil**

- Daftar job: tanggal, negara, jumlah kreator, status, tombol Unduh Excel, tombol Jalankan Ulang (pakai daftar nama yang sama).
- Detail job: tabel Ringkasan Kreator yang bisa difilter (status, ada AD, kategori produk) sebelum diunduh.
- File hasil disimpan di VPS 30 hari; user mengunduh lewat browser.

**Login app.** User login pakai akun Kurma (email + password atau token dari admin); role `staff` hanya melihat job sendiri, role `admin` melihat semua job dan halaman Sesi FastMoss (status sesi, tombol Login FastMoss yang membuka noVNC, tombol Simpan Sesi, log akses).

## 7. Manajemen sesi login FastMoss

Login dilakukan **sekali oleh Admin IT**, hasilnya disimpan di VPS sebagai `storage_state.json` (format Playwright: cookies + localStorage). Semua job memakai state yang sama. Hanya ada satu cara mengisi sesi — login manual lewat browser asli di VPS yang ditampilkan via VNC:

1. Admin buka halaman **Sesi FastMoss** di web app (role admin) → klik **Login FastMoss**.
2. VPS menjalankan Chromium *headed* di display virtual (Xvfb) dan menampilkannya lewat **noVNC** langsung di dalam halaman web app (iframe), jadi admin tidak perlu aplikasi VNC terpisah.
3. Admin login manual seperti manusia biasa: email, password, OTP/captcha bila diminta, sampai dashboard FastMoss terbuka.
4. Admin klik **Simpan Sesi** → worker menyimpan `storage_state.json` (cookies + localStorage) dari browser context tersebut, lalu Chromium headed ditutup.
5. Worker scraping selanjutnya berjalan *headless* memakai `storage_state.json` itu. Tidak ada ekspor/unggah cookies JSON manual sama sekali.

**Validasi sesi.** Setelah disimpan, worker membuka `fastmoss.com/id/dashboard` dan memastikan nama akun (contoh `wisnu@white...`) dan label *Versi Profesional* terbaca. Gagal → status sesi `tidak valid`, file lama tetap dipakai sampai yang baru valid.

**Pemantauan.** Health check tiap 30 menit saat idle dan sebelum tiap job. Sesi kadaluarsa → job aktif dijeda (bukan gagal), status `sesi perlu login ulang`, notifikasi ke admin (WhatsApp/Telegram bot atau email). Admin ulangi langkah 1–4 lewat noVNC; setelah sesi baru valid, job lanjut dari kreator terakhir yang belum selesai.

**Keamanan.** File sesi disimpan terenkripsi di VPS (kunci di environment variable), tidak pernah dikirim ke browser user, hanya role `admin` yang bisa membuka noVNC dan menghapus sesi. Akses noVNC dilindungi password sekali pakai yang dibuat API dan otomatis ditutup 15 menit setelah login selesai. Log akses mencatat siapa login FastMoss dan kapan. Satu akun FastMoss hanya untuk satu worker aktif agar tidak memicu deteksi login ganda.

## 8. Penanganan error, validasi, dan batasan

Setiap kreator berdiri sendiri: satu kreator gagal tidak menghentikan job, dan hasil parsial selalu bisa diunduh.

| Situasi | Perilaku sistem | Status di output |
| --- | --- | --- |
| Nama tidak ada di hasil pencarian | Coba ulang sekali tanpa `@` dan tanpa spasi; tetap tidak ada → lewati | `tidak ditemukan` |
| Lebih dari satu hasil, tak ada yang persis | Simpan 3 kandidat teratas (nickname + ID) di kolom catatan | `ambigu` |
| Kreator ketemu, tab Analisis Video kosong 7 hari | Tulis satu baris ringkasan tanpa video | `tanpa video` |
| Halaman timeout / selector tidak ketemu | Retry maksimal 3x dengan jeda 10, 30, 60 detik; simpan screenshot ke folder log | `gagal` + pesan |
| Captcha / redirect ke login / limit paket | Jeda seluruh job, notifikasi admin, tunggu sesi baru | job `menunggu sesi` |
| Tab browser ditutup / koneksi putus | Job tetap jalan di VPS; app reconnect dan tarik status terbaru | tidak berubah |
| File Excel input rusak / kolom tidak ada | Tolak saat upload, tampilkan baris bermasalah | tidak ada job |
| VPS restart di tengah job | Job dilanjutkan dari kreator terakhir yang belum berstatus akhir | tidak berubah |

**Batasan yang disepakati.** Data mengikuti apa yang ditampilkan FastMoss (bisa beda dengan angka asli TikTok); hanya 7 hari terakhir (rentang lain = fase berikutnya); hanya satu akun FastMoss aktif, jadi job antar user berjalan berurutan, bukan paralel; perubahan UI FastMoss bisa menghentikan scraping sampai selector diperbarui (target perbaikan 1 hari kerja).

**Hal yang harus dicek developer sebelum mulai.** Syarat layanan FastMoss untuk akses otomatis dan risiko akun diblokir — keputusan ritme (4.5) sengaja dibuat sangat santai dan konservatif ("asal benar, tidak perlu cepat") demi keamanan akun dan memastikan seluruh data terekstrak tanpa cacat.

## 9. Tech stack, non-functional, dan fase pengerjaan

**Stack yang direkomendasikan** (developer boleh mengusulkan pengganti setara, dengan alasan tertulis):

| Lapisan | Pilihan | Alasan |
| --- | --- | --- |
| Frontend web | React + Vite (atau Next.js), di-serve Nginx | Tanpa instalasi; dibuka dari PC/HP, satu deploy untuk semua user |
| API | Python FastAPI + Uvicorn | Satu bahasa dengan worker; WebSocket bawaan untuk progres realtime |
| Worker scraping | Python Playwright, Chromium headless | Dukungan `storage_state`, selector tahan perubahan, screenshot untuk debug; mode headed di Xvfb + noVNC (websockify) untuk login manual admin |
| Antrean | Redis + RQ (v1 boleh SQLite-based queue) | Sederhana, satu worker cukup |
| Database | SQLite (v1) → PostgreSQL bila volume naik | Nol konfigurasi awal |
| Excel | openpyxl | Format kolom, freeze pane, hyperlink |
| VPS | Ubuntu 22.04, 2 vCPU / 4 GB RAM, Docker Compose | Chromium headless butuh ±1 GB, Xvfb + noVNC ±200 MB saat login; sisanya API + DB |
| Notifikasi admin | Telegram bot atau WhatsApp API | Sesi putus harus cepat diketahui |

**Non-functional.** Progres kreator tampil di browser maksimal 3 detik setelah selesai di VPS; file hasil tersedia maksimal 10 detik setelah job selesai; log terstruktur (JSON) per kreator dengan screenshot saat gagal; semua selector FastMoss di `selectors.yaml`, bukan hard-coded; konfigurasi (jeda, maks video, kata kunci kategori) dapat diubah admin tanpa deploy ulang; web app di-serve lewat HTTPS (Let's Encrypt) dan hanya bisa dibuka setelah login akun Kurma.

**Fase pengerjaan**

1. **Fase 1 — Engine (minggu 1–2).** Script Playwright yang menerima daftar nama dari CSV lewat CLI, memakai `storage_state.json`, menghasilkan Excel sesuai bagian 5.2. Uji dengan 20 kreator Bawahan Wanita (ID) dan 10 kreator MY termasuk GADISKU. *Gate:* 90% kreator uji berstatus `selesai` dengan data yang cocok saat dicek manual.
2. **Fase 2 — API + antrean di VPS (minggu 3).** Endpoint upload job, status, unduh; worker jalan dari antrean; health check sesi; login manual via Chromium headed + noVNC dari halaman admin. *Gate:* dua job dari dua user berjalan berurutan tanpa saling ganggu.
3. **Fase 3 — Web app (minggu 4–5).** Tiga halaman di bagian 6, login role staff/admin, deploy HTTPS di VPS. *Gate:* staff riset menjalankan satu job penuh tanpa bantuan developer.
4. **Fase 4 — Hardening (minggu 6).** Retry, resume setelah restart, notifikasi admin, dokumentasi admin (cara login ulang, ganti selector). *Gate:* semua acceptance criteria bagian 10 lulus.

## 10. Acceptance criteria dan pertanyaan terbuka

**Acceptance criteria (wajib lulus sebelum serah terima)**

- [ ] Upload Excel 100 nama → job selesai tanpa intervensi, Excel hasil berisi 3 sheet sesuai 5.2.
- [ ] Setiap video di sheet Video sama dengan tampilan FastMoss (7 Hari, urut Penjualan Video menurun) untuk 10 kreator sampel yang dicek manual; selisih angka 0.
- [ ] Video ber-badge AD terdeteksi 100% pada sampel; video tanpa badge kolom Ads kosong. Sheet Video hanya berisi produk Bawahan Wanita saat filter nyala, dicek manual pada 30 produk sampel; produk kategori lain berada di sheet Video Lainnya.
- [ ] Nama yang tidak ada di FastMoss berstatus `tidak ditemukan` dan job tetap lanjut.
- [ ] Sesi FastMoss dicabut di tengah job → job jeda, admin dapat notifikasi, login ulang lewat noVNC → job lanjut dari kreator terakhir tanpa duplikat baris.
- [ ] Tab browser ditutup lalu dibuka lagi saat job berjalan → progres tersambung kembali.
- [ ] Negara Malaysia: nilai penjualan tercatat dalam RM dan angka ribuan/desimal benar.
- [ ] Dua user mengirim job bersamaan → keduanya selesai, berurutan, tanpa error sesi.
- [ ] Selector diubah di `selectors.yaml` tanpa deploy ulang → worker memakai nilai baru di job berikutnya.
- [ ] Prioritas akurasi dan stabilitas data: scraper berjalan dengan ritme santai dan jeda manusiawi (human-like delay), data 100% akurat tanpa baris yang terlewat atau terpotong pada sampel uji, serta tidak memicu pemblokiran/rate limit dari FastMoss.

**Pertanyaan terbuka untuk Mia**

- [ ] Apakah daftar video dibatasi 50 per kreator, atau ambil semua yang ada di 7 hari?
- [ ] Kategori lain selain Bawahan Wanita (misal Hijab, Atasan Wanita) perlu masuk daftar kata kunci sejak v1?
- [ ] Notifikasi admin lewat WhatsApp (nomor kantor 0811-789-436) atau Telegram?
- [ ] Berapa user yang akan memakai app bersamaan, dan perlukah job paralel (artinya butuh lebih dari satu akun FastMoss)?
- [ ] Hasil disimpan di VPS 30 hari cukup, atau perlu sinkron ke Google Drive tim?

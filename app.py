"""FastMoss Kreator Analitik - Flask Web Application with Auth & Role Management"""
import csv
import os
import re
import tempfile
import time
from datetime import datetime
from functools import wraps
from pathlib import Path
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    send_file,
    flash
)
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user
)

from src.config import BASE_DIR, STORAGE_DIR, OUTPUTS_DIR
from src.models import JobConfig
from src.utils import parse_revenue_value
from src.input_reader import InputReader
from src.session_manager import SessionManager
from src.job_manager import JobManager
from src.auth import AuthManager, User

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "kurma-group-fastmoss-secret-key-2026")

# Inisialisasi Auth, JobManager, & SessionManager
auth_manager = AuthManager()
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

job_manager = JobManager()
session_manager = SessionManager()


@login_manager.user_loader
def load_user(user_id):
    return auth_manager.get_by_id(int(user_id))


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Akses ditolak: Menu ini hanya untuk Admin IT.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated_function


# ===================== AUTH ROUTES =====================

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        user = auth_manager.authenticate(email, password)
        if user:
            login_user(user)
            return redirect(url_for("index"))
        flash("Email atau password akun Kurma salah.", "error")

    return render_template("login.html", active_page="login")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Anda telah berhasil logout.", "info")
    return redirect(url_for("login"))


# ===================== MAIN PAGES =====================

@app.route("/")
@login_required
def index():
    """Halaman 1: Buat Job Baru"""
    return render_template("index.html", active_page="new_job")


@app.route("/job/<job_id>")
@login_required
def job_progress(job_id):
    """Halaman 2: Progres Job Realtime"""
    job = job_manager.get_job(job_id)
    if not job:
        flash("Job tidak ditemukan", "error")
        return redirect(url_for("index"))
    
    # Cek kepemilikan job jika bukan admin
    if not current_user.is_admin and job.get("user_email") != current_user.email:
        flash("Akses ditolak: Anda hanya dapat melihat job milik Anda sendiri.", "error")
        return redirect(url_for("history"))

    return render_template("job_progress.html", job=job, active_page="new_job")


@app.route("/history")
@login_required
def history():
    """Halaman 3: Riwayat & Hasil Job (Admin: Semua, Staff: Milik Sendiri)"""
    filter_email = None if current_user.is_admin else current_user.email
    jobs = job_manager.list_jobs(user_email=filter_email)
    return render_template("history.html", jobs=jobs, active_page="history")


@app.route("/session")
@login_required
@admin_required
def session_page():
    """Halaman Admin: Manajemen Sesi FastMoss"""
    return render_template("session.html", active_page="session")


# ===================== API ENDPOINTS =====================

@app.route("/api/validate-file", methods=["POST"])
@login_required
def api_validate_file():
    """Validasi file Excel/CSV sebelum disubmit"""
    if "file" not in request.files:
        return jsonify({"success": False, "error": "Tidak ada file yang diunggah"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"success": False, "error": "Nama file kosong"}), 400

    suffix = Path(file.filename).suffix.lower()
    if suffix not in [".xlsx", ".xls", ".csv"]:
        return jsonify({"success": False, "error": "Format file harus .xlsx atau .csv"}), 400

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        file.save(tmp.name)
        tmp_path = Path(tmp.name)

    try:
        creators, stats = InputReader.read_input(tmp_path)
        return jsonify({"success": True, "stats": stats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400
    finally:
        if tmp_path.exists():
            os.remove(tmp_path)


@app.route("/api/jobs", methods=["POST"])
@login_required
def api_create_job():
    """Buat dan masukkan job baru ke antrean (Upload Excel/CSV atau Input Satuan/Manual)"""
    input_mode = request.form.get("input_mode", "file")
    creator_text = request.form.get("creator_text", "").strip()

    country = request.form.get("country", "ID").upper()
    period = request.form.get("period", "7 Hari")
    max_videos = int(request.form.get("max_videos", 50))
    min_revenue_raw = request.form.get("min_revenue", "0")
    min_revenue = parse_revenue_value(min_revenue_raw)
    filter_ad = bool(request.form.get("filter_ad"))
    filter_bawahan = bool(request.form.get("filter_bawahan"))
    min_delay = float(request.form.get("min_delay", 3.0))
    max_delay = float(request.form.get("max_delay", 7.0))

    config = JobConfig(
        country=country,
        period=period,
        max_videos_per_creator=max_videos,
        min_revenue=min_revenue,
        filter_ad_only=filter_ad,
        filter_bawahan_only=filter_bawahan,
        min_delay=min_delay,
        max_delay=max_delay
    )

    upload_dir = STORAGE_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())

    # Cek apakah user menggunakan input satuan / manual teks
    has_file = "file" in request.files and bool(request.files["file"].filename)
    if input_mode == "manual" or (not has_file and creator_text):
        raw_items = [re.sub(r"^@", "", x).strip() for x in re.split(r"[\r\n,]+", creator_text) if x.strip()]
        unique_creators = []
        seen = set()
        for c in raw_items:
            c_clean = " ".join(c.split())
            if c_clean and c_clean.lower() not in seen:
                seen.add(c_clean.lower())
                unique_creators.append(c_clean)

        if not unique_creators:
            flash("Silakan masukkan minimal 1 nama atau ID TikTok kreator.", "error")
            return redirect(url_for("index"))

        if len(unique_creators) == 1:
            safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", unique_creators[0])
            display_filename = f"{unique_creators[0]} (Manual)"
            saved_file_path = upload_dir / f"manual_{safe_name}_{ts}.csv"
        else:
            display_filename = f"Input Manual ({len(unique_creators)} Kreator)"
            saved_file_path = upload_dir / f"manual_batch_{len(unique_creators)}_{ts}.csv"

        with open(saved_file_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["nama_kreator", "negara", "catatan"])
            for c_name in unique_creators:
                writer.writerow([c_name, country, "input_satuan"])

    else:
        if not has_file:
            flash("Silakan pilih file Excel/CSV atau gunakan tab 'Cari Satuan' untuk input langsung.", "error")
            return redirect(url_for("index"))

        file = request.files["file"]
        suffix = Path(file.filename).suffix.lower()
        if suffix not in [".xlsx", ".xls", ".csv"]:
            flash("Format file harus .xlsx, .xls, atau .csv", "error")
            return redirect(url_for("index"))

        display_filename = file.filename
        saved_file_path = upload_dir / f"{Path(file.filename).stem}_{ts}{suffix}"
        file.save(str(saved_file_path))

    try:
        job_id = job_manager.create_job(
            saved_file_path,
            display_filename,
            config,
            user_email=current_user.email
        )
        return redirect(url_for("job_progress", job_id=job_id))
    except Exception as e:
        flash(f"Gagal membuat job: {str(e)}", "error")
        return redirect(url_for("index"))


@app.route("/api/jobs/<job_id>", methods=["GET"])
@login_required
def api_get_job(job_id):
    """Mendapatkan data status job terkini untuk polling/update realtime"""
    job = job_manager.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    
    if not current_user.is_admin and job.get("user_email") != current_user.email:
        return jsonify({"error": "Unauthorized"}), 403

    return jsonify({"job": job})


@app.route("/api/jobs/<job_id>/pause", methods=["POST"])
@login_required
def api_pause_job(job_id):
    job = job_manager.get_job(job_id)
    if not job or (not current_user.is_admin and job.get("user_email") != current_user.email):
        return jsonify({"error": "Unauthorized"}), 403
    success = job_manager.pause_job(job_id)
    return jsonify({"success": success})


@app.route("/api/jobs/<job_id>/resume", methods=["POST"])
@login_required
def api_resume_job(job_id):
    job = job_manager.get_job(job_id)
    if not job or (not current_user.is_admin and job.get("user_email") != current_user.email):
        return jsonify({"error": "Unauthorized"}), 403
    success = job_manager.resume_job(job_id)
    return jsonify({"success": success})


@app.route("/api/jobs/<job_id>/cancel", methods=["POST"])
@login_required
def api_cancel_job(job_id):
    job = job_manager.get_job(job_id)
    if not job or (not current_user.is_admin and job.get("user_email") != current_user.email):
        return jsonify({"error": "Unauthorized"}), 403
    success = job_manager.cancel_job(job_id)
    return jsonify({"success": success})


@app.route("/download/<job_id>")
@login_required
def download_result(job_id):
    """Download file Excel hasil scraping"""
    job = job_manager.get_job(job_id)
    if not job or not job.get("output_path"):
        flash("File hasil belum tersedia atau job gagal", "error")
        return redirect(url_for("job_progress", job_id=job_id))

    if not current_user.is_admin and job.get("user_email") != current_user.email:
        flash("Akses ditolak: Anda tidak memiliki izin mengunduh file ini.", "error")
        return redirect(url_for("history"))

    file_path = Path(job["output_path"])
    if not file_path.exists():
        flash("File hasil tidak ditemukan di penyimpanan server", "error")
        return redirect(url_for("job_progress", job_id=job_id))

    return send_file(
        str(file_path),
        as_attachment=True,
        download_name=file_path.name
    )


@app.route("/api/sample-template")
def download_sample_template():
    """Download template file Excel kosong yang valid"""
    template_path = BASE_DIR / "template_kreator.xlsx"
    if not template_path.exists():
        from cli import cmd_sample_input
        import argparse
        cmd_sample_input(argparse.Namespace(output=str(template_path)))
    return send_file(str(template_path), as_attachment=True, download_name="template_kreator.xlsx")


@app.route("/api/session/status")
@login_required
def api_session_status():
    """Pemeriksaan status sesi lokal sederhana"""
    has_file = session_manager.has_session_file()
    if not has_file:
        return jsonify({
            "is_valid": False,
            "message": "File cookies FastMoss (storage_state.json) belum ditemukan. Silakan login terlebih dahulu."
        })
    return jsonify({
        "is_valid": True,
        "message": "File sesi FastMoss terdeteksi."
    })


@app.route("/api/session/check", methods=["POST"])
@login_required
@admin_required
def api_session_check():
    """Pemeriksaan validasi penuh dengan membuka dashboard FastMoss"""
    is_valid, msg = session_manager.validate_session(country="id")
    return jsonify({"is_valid": is_valid, "message": msg})


@app.route("/api/session/vnc-start", methods=["POST"])
@login_required
@admin_required
def api_session_vnc_start():
    country = request.json.get("country", "id") if request.is_json else "id"
    success, msg, is_local = session_manager.start_vnc_session(country=country)
    return jsonify({"success": success, "message": msg, "is_local": is_local})


@app.route("/api/session/vnc-save", methods=["POST"])
@login_required
@admin_required
def api_session_vnc_save():
    success, msg = session_manager.save_vnc_session()
    return jsonify({"success": success, "message": msg})


@app.route("/api/session/vnc-close", methods=["POST"])
@login_required
@admin_required
def api_session_vnc_close():
    session_manager.close_vnc_session()
    return jsonify({"success": True, "message": "Browser login noVNC ditutup."})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n=======================================================")
    print(f"FASTMOSS SCRAPER WEB APP (FLASK)")
    print(f"Server berjalan di: http://localhost:{port}")
    print(f"Default Admin Login : admin@kurmagroup.com / admin123")
    print(f"Default Staff Login : staff@kurmagroup.com / staff123")
    print(f"=======================================================\n")
    app.run(host="0.0.0.0", port=port, debug=False)

"""Notification service for FastMoss Scraper (Telegram & WhatsApp)"""
import logging
import os
from pathlib import Path
import requests
import yaml

from src.config import CONFIG_DIR

logger = logging.getLogger("notifier")


class Notifier:
    def __init__(self, config_path: Path = CONFIG_DIR / "notifications.yaml"):
        self.config = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    self.config = yaml.safe_load(f) or {}
            except Exception as e:
                logger.error(f"Gagal membaca config notifications: {e}")

    def send_message(self, text: str) -> bool:
        """Kirim pesan notifikasi ke semua channel yang aktif"""
        success = True
        logger.info(f"[NOTIFIKASI] {text}")

        # 1. Telegram
        tg_cfg = self.config.get("telegram", {})
        tg_token = os.environ.get("TELEGRAM_BOT_TOKEN") or tg_cfg.get("bot_token")
        tg_chat_id = os.environ.get("TELEGRAM_CHAT_ID") or tg_cfg.get("chat_id")
        tg_enabled = tg_cfg.get("enabled", False) or bool(os.environ.get("TELEGRAM_BOT_TOKEN"))

        if tg_enabled and tg_token and tg_chat_id:
            try:
                url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
                payload = {
                    "chat_id": tg_chat_id,
                    "text": text,
                    "parse_mode": "HTML"
                }
                res = requests.post(url, json=payload, timeout=10)
                if not res.ok:
                    logger.warning(f"Gagal kirim notifikasi Telegram: {res.text}")
                    success = False
            except Exception as e:
                logger.error(f"Error kirim Telegram: {e}")
                success = False

        # 2. WhatsApp
        wa_cfg = self.config.get("whatsapp", {})
        wa_webhook = os.environ.get("WHATSAPP_WEBHOOK_URL") or wa_cfg.get("webhook_url")
        wa_enabled = wa_cfg.get("enabled", False) or bool(os.environ.get("WHATSAPP_WEBHOOK_URL"))

        if wa_enabled and wa_webhook:
            try:
                payload = {
                    "message": text,
                    "phone": wa_cfg.get("phone_number", "")
                }
                res = requests.post(wa_webhook, json=payload, timeout=10)
                if not res.ok:
                    logger.warning(f"Gagal kirim notifikasi WhatsApp: {res.text}")
                    success = False
            except Exception as e:
                logger.error(f"Error kirim WhatsApp: {e}")
                success = False

        return success

    def notify_session_expired(self, reason: str = ""):
        msg = (
            "🚨 <b>[FastMoss Scraper] PERINGATAN: Sesi FastMoss Putus!</b>\n\n"
            f"Detail: <code>{reason}</code>\n"
            "Job aktif otomatis dijeda demi keamanan akun. Silakan Admin login ulang via web app di menu <b>Sesi FastMoss</b>."
        )
        self.send_message(msg)

    def notify_job_completed(self, job_id: str, total: int, completed: int, excel_path: str):
        msg = (
            f"✅ <b>[FastMoss Scraper] Job Selesai: {job_id}</b>\n\n"
            f"• Total Kreator: {total}\n"
            f"• Sukses Diproses: {completed}\n"
            f"• File Excel: <code>{Path(excel_path).name if excel_path else '-'}</code>\n\n"
            "File hasil dapat diunduh di dashboard web app."
        )
        self.send_message(msg)

    def notify_job_paused(self, job_id: str, reason: str):
        msg = (
            f"⏸️ <b>[FastMoss Scraper] Job Dijeda: {job_id}</b>\n\n"
            f"Alasan: {reason}\n"
            "Lakukan verifikasi sesi atau lanjutkan job lewat menu progres."
        )
        self.send_message(msg)


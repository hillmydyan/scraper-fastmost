"""User Authentication & Role Management for FastMoss Web App"""
import sqlite3
from typing import Optional
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

from src.config import STORAGE_DIR

USERS_DB_PATH = STORAGE_DIR / "users.db"


class User(UserMixin):
    def __init__(self, id: int, email: str, name: str, role: str):
        self.id = id
        self.email = email
        self.name = name
        self.role = role

    @property
    def is_admin(self) -> bool:
        return self.role.lower() == "admin"


class AuthManager:
    def __init__(self, db_path=USERS_DB_PATH):
        self.db_path = db_path
        self._init_db()
        self._seed_default_users()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'staff',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def _seed_default_users(self):
        """Buat akun default Kurma Group bila belum ada"""
        if not self.get_by_email("admin@kurmagroup.com"):
            self.create_user("admin@kurmagroup.com", "admin123", "Admin IT Kurma", "admin")
        if not self.get_by_email("staff@kurmagroup.com"):
            self.create_user("staff@kurmagroup.com", "staff123", "Tim Riset Fashion", "staff")

    def create_user(self, email: str, password: str, name: str, role: str = "staff") -> Optional[User]:
        pwd_hash = generate_password_hash(password)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO users (email, password_hash, name, role)
                    VALUES (?, ?, ?, ?)
                """, (email.strip().lower(), pwd_hash, name, role))
                conn.commit()
                user_id = cursor.lastrowid
                return User(user_id, email, name, role)
        except Exception:
            return None

    def get_by_id(self, user_id: int) -> Optional[User]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT id, email, name, role FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                return User(row["id"], row["email"], row["name"], row["role"])
        return None

    def get_by_email(self, email: str) -> Optional[User]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT id, email, name, role FROM users WHERE email = ?", (email.strip().lower(),))
            row = cursor.fetchone()
            if row:
                return User(row["id"], row["email"], row["name"], row["role"])
        return None

    def authenticate(self, email: str, password: str) -> Optional[User]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT id, email, password_hash, name, role FROM users WHERE email = ?", (email.strip().lower(),))
            row = cursor.fetchone()
            if row and check_password_hash(row["password_hash"], password):
                return User(row["id"], row["email"], row["name"], row["role"])
        return None


import os
import psycopg2  # было pyscopg2 — исправлено
from psycopg2.extras import RealDictCursor  # было pyscopg2 — исправлено
import random
import string
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")

class Database:
    def __init__(self):
        self.conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

    def generate_customer_code(self):
        while True:
            letters = ''.join(random.choices(string.ascii_uppercase, k=2))
            numbers = ''.join(random.choices(string.digits, k=5))
            code = f"GD-{letters}{numbers}"
            with self.conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as cnt FROM users WHERE customer_code = %s", (code,))
                result = cur.fetchone()
                if result['cnt'] == 0:
                    return code

    def get_or_create_user(self, telegram_id, username=None, first_name=None):
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
            user = cur.fetchone()
            if user:
                return user

            customer_code = self.generate_customer_code()
            cur.execute("""
                INSERT INTO users (telegram_id, username, first_name, customer_code, balance)
                VALUES (%s, %s, %s, %s, %s) RETURNING *
            """, (telegram_id, username or '', first_name or '', customer_code, 0.0))
            self.conn.commit()
            return cur.fetchone()

    def get_user(self, telegram_id):
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
            return cur.fetchone()

    def get_user_track_codes(self, telegram_id):
        user = self.get_user(telegram_id)
        if not user:
            return []
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT track_code, description, status, created_date
                FROM track_codes
                WHERE user_id = %s
                ORDER BY created_date DESC
            """, (user['id'],))
            return cur.fetchall()

    def add_track_code(self, telegram_id, track_code, description=""):
        user = self.get_user(telegram_id)
        if not user:
            return False
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO track_codes (user_id, track_code, description)
                    VALUES (%s, %s, %s)
                """, (user['id'], track_code.upper(), description))
                self.conn.commit()
            return True
        except Exception:
            return False

    def get_exchange_rates(self):
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM exchange_rates ORDER BY currency_code")
            return cur.fetchall()

    def is_admin(self, telegram_id):
        user = self.get_user(telegram_id)
        return user and user.get('is_admin', False)

db = Database()
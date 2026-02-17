import os
import random
import string
from datetime import datetime

# Определяем тип базы
DATABASE_URL = os.getenv('DATABASE_URL')

if DATABASE_URL:
    # PostgreSQL
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def get_connection():
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

    def execute_query(query, params=None, fetchone=False, fetchall=False):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params or ())
                if fetchone:
                    return cur.fetchone()
                if fetchall:
                    return cur.fetchall()
                conn.commit()
                return None
else:
    # SQLite (локальная разработка)
    import sqlite3
    DB_PATH = 'golden_dragon.db'

    def get_connection():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def execute_query(query, params=None, fetchone=False, fetchall=False):
        with get_connection() as conn:
            cur = conn.cursor()
            # Заменяем %s на ? для SQLite
            if '%s' in query:
                query = query.replace('%s', '?')
            cur.execute(query, params or ())
            if fetchone:
                return cur.fetchone()
            if fetchall:
                return cur.fetchall()
            conn.commit()
            return None

class Database:
    def generate_customer_code(self):
        while True:
            letters = ''.join(random.choices(string.ascii_uppercase, k=2))
            numbers = ''.join(random.choices(string.digits, k=5))
            code = f"GD-{letters}{numbers}"
            result = execute_query(
                "SELECT COUNT(*) as cnt FROM users WHERE customer_code = %s",
                (code,),
                fetchone=True
            )
            if result['cnt'] == 0:
                return code

    def register_user(self, user_id, username, first_name, last_name, phone_number, is_admin=False):
        # Проверяем, существует ли пользователь
        user = execute_query(
            "SELECT * FROM users WHERE user_id = %s",
            (user_id,),
            fetchone=True
        )
        if user:
            if is_admin:
                execute_query(
                    "UPDATE users SET is_admin = 1 WHERE user_id = %s",
                    (user_id,)
                )
            return user['customer_code']

        customer_code = self.generate_customer_code()
        execute_query(
            """INSERT INTO users 
               (user_id, username, first_name, last_name, phone_number, customer_code, is_admin, balance)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (user_id, username, first_name, last_name, phone_number, customer_code,
             1 if is_admin else 0, 0.0)
        )
        return customer_code

    def get_user(self, user_id):
        return execute_query(
            "SELECT * FROM users WHERE user_id = %s",
            (user_id,),
            fetchone=True
        )

    def is_admin(self, user_id):
        result = execute_query(
            "SELECT is_admin FROM users WHERE user_id = %s",
            (user_id,),
            fetchone=True
        )
        return result and result['is_admin'] == 1

    def get_exchange_rates(self):
        return execute_query(
            "SELECT * FROM exchange_rates ORDER BY currency_code",
            fetchall=True
        )

    def update_exchange_rate(self, currency_code, rate):
        execute_query(
            "UPDATE exchange_rates SET rate = %s, last_updated = NOW() WHERE currency_code = %s",
            (rate, currency_code)
        )

    def get_delivery_methods(self):
        return execute_query(
            "SELECT * FROM delivery_methods ORDER BY method_code",
            fetchall=True
        )

    def update_delivery_price(self, method_code, price_per_kg):
        execute_query(
            "UPDATE delivery_methods SET price_per_kg = %s, last_updated = NOW() WHERE method_code = %s",
            (price_per_kg, method_code)
        )

    def update_delivery_days(self, method_code, min_days, max_days):
        execute_query(
            "UPDATE delivery_methods SET min_days = %s, max_days = %s, last_updated = NOW() WHERE method_code = %s",
            (min_days, max_days, method_code)
        )

    def add_track_code(self, user_id, track_code, description=""):
        try:
            execute_query(
                """INSERT INTO track_codes (user_id, track_code, description)
                   VALUES (%s, %s, %s)""",
                (user_id, track_code.upper(), description)
            )
            return True
        except Exception:
            return False

    def get_user_track_codes(self, user_id):
        return execute_query(
            """SELECT track_code, description, status, created_date
               FROM track_codes
               WHERE user_id = %s
               ORDER BY created_date DESC""",
            (user_id,),
            fetchall=True
        )

    def update_track_code_status(self, track_code_id, new_status):
        execute_query(
            "UPDATE track_codes SET status = %s, last_updated = NOW() WHERE id = %s",
            (new_status, track_code_id)
        )

    def get_recent_orders(self, limit=20):
        return execute_query(
            """SELECT tc.id, tc.track_code, tc.status, tc.created_date, u.customer_code
               FROM track_codes tc
               LEFT JOIN users u ON tc.user_id = u.user_id
               ORDER BY tc.created_date DESC
               LIMIT %s""",
            (limit,),
            fetchall=True
        )

    def get_statistics(self):
        total_users = execute_query("SELECT COUNT(*) as cnt FROM users", fetchone=True)['cnt']
        admin_users = execute_query("SELECT COUNT(*) as cnt FROM users WHERE is_admin = 1", fetchone=True)['cnt']
        total_track_codes = execute_query("SELECT COUNT(*) as cnt FROM track_codes", fetchone=True)['cnt']
        delivered = execute_query("SELECT COUNT(*) as cnt FROM track_codes WHERE status = 'Доставлен'", fetchone=True)['cnt']
        return {
            'total_users': total_users,
            'admin_users': admin_users,
            'total_track_codes': total_track_codes,
            'delivered_track_codes': delivered
        }

    def get_all_users(self, include_admins=False):
        if include_admins:
            return execute_query("SELECT * FROM users ORDER BY registration_date DESC", fetchall=True)
        else:
            return execute_query("SELECT * FROM users WHERE is_admin = 0 ORDER BY registration_date DESC", fetchall=True)

db = Database()
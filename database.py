import os
import psycopg2
from psycopg2.extras import RealDictCursor
import random
import string
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")

class Database:
    def __init__(self):
        self.conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

    def generate_customer_code(self):
        """Генерирует уникальный код клиента"""
        while True:
            letters = ''.join(random.choices(string.ascii_uppercase, k=2))
            numbers = ''.join(random.choices(string.digits, k=5))
            code = f"GD-{letters}{numbers}"
            with self.conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as cnt FROM users WHERE customer_code = %s", (code,))
                result = cur.fetchone()
                if result['cnt'] == 0:
                    return code

    def register_user(self, user_id, username, first_name, last_name, phone_number, is_admin=False):
        """Регистрирует нового пользователя или обновляет существующего"""
        # Проверяем, существует ли пользователь
        user = self.get_user(user_id)
        if user:
            # Пользователь существует, обновляем данные и возвращаем код
            with self.conn.cursor() as cur:
                cur.execute("""
                    UPDATE users 
                    SET username = %s, first_name = %s, last_name = %s, phone_number = %s, is_admin = %s
                    WHERE telegram_id = %s
                """, (username, first_name, last_name, phone_number, is_admin, user_id))
                self.conn.commit()
            return user['customer_code']

        # Создаём нового пользователя
        customer_code = self.generate_customer_code()
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (telegram_id, username, first_name, last_name, phone_number, customer_code, is_admin)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING customer_code
            """, (user_id, username, first_name, last_name, phone_number, customer_code, is_admin))
            self.conn.commit()
            result = cur.fetchone()
            return result['customer_code']

    def get_user(self, telegram_id):
        """Возвращает пользователя по telegram_id"""
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
            return cur.fetchone()

    def get_user_track_codes(self, telegram_id):
        """Возвращает трек-коды пользователя"""
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
        """Добавляет трек-код для пользователя"""
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
        except psycopg2.IntegrityError:
            # Трек-код уже существует
            return False
        except Exception as e:
            print(f"Error adding track code: {e}")
            return False

    def update_track_code_status(self, track_code_id, new_status):
        """Обновляет статус трек-кода"""
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE track_codes
                SET status = %s, updated_at = NOW()
                WHERE id = %s
            """, (new_status, track_code_id))
            self.conn.commit()

    def get_exchange_rates(self):
        """Возвращает все курсы валют"""
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM exchange_rates ORDER BY currency_code")
            return cur.fetchall()

    def update_exchange_rate(self, currency_code, rate):
        """Обновляет курс валюты"""
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE exchange_rates
                SET rate = %s, updated_at = NOW()
                WHERE currency_code = %s
            """, (rate, currency_code))
            self.conn.commit()

    def get_delivery_methods(self):
        """Возвращает все способы доставки"""
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM delivery_methods ORDER BY method_code")
            return cur.fetchall()

    def update_delivery_price(self, method_code, price_per_kg):
        """Обновляет цену доставки"""
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE delivery_methods
                SET price_per_kg = %s, updated_at = NOW()
                WHERE method_code = %s
            """, (price_per_kg, method_code))
            self.conn.commit()

    def update_delivery_days(self, method_code, min_days, max_days):
        """Обновляет сроки доставки"""
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE delivery_methods
                SET min_days = %s, max_days = %s, updated_at = NOW()
                WHERE method_code = %s
            """, (min_days, max_days, method_code))
            self.conn.commit()

    def get_recent_orders(self, limit=20):
        """Возвращает последние заказы (для админки)"""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT tc.id, tc.track_code, tc.status, tc.created_date, u.customer_code
                FROM track_codes tc
                LEFT JOIN users u ON tc.user_id = u.id
                ORDER BY tc.created_date DESC
                LIMIT %s
            """, (limit,))
            return cur.fetchall()

    def get_statistics(self):
        """Возвращает статистику (для админки)"""
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM users")
            total_users = cur.fetchone()['cnt']
            
            cur.execute("SELECT COUNT(*) as cnt FROM users WHERE is_admin = TRUE")
            admin_users = cur.fetchone()['cnt']
            
            cur.execute("SELECT COUNT(*) as cnt FROM track_codes")
            total_track_codes = cur.fetchone()['cnt']
            
            cur.execute("SELECT COUNT(*) as cnt FROM track_codes WHERE status = 'Доставлен'")
            delivered = cur.fetchone()['cnt']
            
            return {
                'total_users': total_users,
                'admin_users': admin_users,
                'total_track_codes': total_track_codes,
                'delivered_track_codes': delivered
            }

    def get_all_users(self, include_admins=False):
        """Возвращает всех пользователей (для админки)"""
        with self.conn.cursor() as cur:
            if include_admins:
                cur.execute("SELECT * FROM users ORDER BY registration_date DESC")
            else:
                cur.execute("SELECT * FROM users WHERE is_admin = FALSE ORDER BY registration_date DESC")
            return cur.fetchall()

    def is_admin(self, telegram_id):
        """Проверяет, является ли пользователь администратором"""
        user = self.get_user(telegram_id)
        return user and user.get('is_admin', False)

# Глобальный экземпляр базы данных
db = Database()
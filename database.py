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

    def _execute_query(self, query, params=None, fetchone=False, fetchall=False):
        """Вспомогательный метод для выполнения запросов с обработкой ошибок"""
        try:
            with self.conn.cursor() as cur:
                cur.execute(query, params or ())
                if fetchone:
                    return cur.fetchone()
                if fetchall:
                    return cur.fetchall()
                self.conn.commit()
                return None
        except Exception as e:
            self.conn.rollback()
            print(f"Database error: {e}")
            raise e

    # ------------------------- ГЕНЕРАЦИЯ КОДА -------------------------
    def generate_customer_code(self, first_name, phone_number):
        """Генерирует код клиента: GD + первые 2 буквы имени + последние 4 цифры телефона"""
        letters = (first_name[:2] if first_name and len(first_name) >= 2 else "GD").upper()
        digits = ''.join(filter(str.isdigit, phone_number))
        last_digits = digits[-4:] if len(digits) >= 4 else digits.zfill(4)
        code = f"GD-{letters}{last_digits}"
        
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM users WHERE customer_code = %s", (code,))
            if cur.fetchone()['cnt'] == 0:
                return code
            else:
                return f"GD-{letters}{last_digits}{random.choice(string.digits)}"

    # ------------------------- ПОЛЬЗОВАТЕЛИ -------------------------
    def register_user(self, user_id, username, first_name, last_name, phone_number, is_admin=False):
        """Регистрирует нового пользователя или обновляет существующего"""
        try:
            user = self.get_user(user_id)
            if user:
                with self.conn.cursor() as cur:
                    cur.execute("""
                        UPDATE users 
                        SET username = %s, first_name = %s, last_name = %s, phone_number = %s, is_admin = %s
                        WHERE telegram_id = %s
                    """, (username, first_name, last_name, phone_number, is_admin, user_id))
                    self.conn.commit()
                return user['customer_code']
            
            customer_code = self.generate_customer_code(first_name, phone_number)
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO users (telegram_id, username, first_name, last_name, phone_number, customer_code, is_admin)
                    VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING customer_code
                """, (user_id, username, first_name, last_name, phone_number, customer_code, is_admin))
                self.conn.commit()
                result = cur.fetchone()
                return result['customer_code']
        except Exception as e:
            self.conn.rollback()
            print(f"Error in register_user: {e}")
            raise e

    def get_user(self, telegram_id):
        """Возвращает пользователя по telegram_id"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
                return cur.fetchone()
        except Exception as e:
            self.conn.rollback()
            print(f"Error in get_user: {e}")
            return None

    def get_user_by_customer_code(self, customer_code):
        """Возвращает пользователя по коду клиента"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE customer_code = %s", (customer_code,))
                return cur.fetchone()
        except Exception as e:
            self.conn.rollback()
            print(f"Error in get_user_by_customer_code: {e}")
            return None

    def is_admin(self, telegram_id):
        """Проверяет, является ли пользователь администратором"""
        try:
            user = self.get_user(telegram_id)
            return user and user.get('is_admin', False)
        except Exception as e:
            self.conn.rollback()
            print(f"Error in is_admin: {e}")
            return False

    def update_balance(self, telegram_id, amount):
        """Обновляет баланс пользователя (положительное или отрицательное значение)"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("UPDATE users SET balance = balance + %s WHERE telegram_id = %s", (amount, telegram_id))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            print(f"Error in update_balance: {e}")
            raise e

    # ------------------------- ТРЕК-КОДЫ -------------------------
    def add_track_code(self, telegram_id, track_code, description="", price=0):
        """Добавляет трек-код для пользователя (для админов)"""
        try:
            user = self.get_user(telegram_id)
            if not user:
                return False, "Пользователь не найден"
            
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO track_codes (user_id, track_code, description, price)
                    VALUES (%s, %s, %s, %s)
                """, (user['id'], track_code.upper(), description, price))
                self.conn.commit()
            return True, "Трек-код добавлен"
        except psycopg2.IntegrityError:
            self.conn.rollback()
            return False, "Трек-код уже существует"
        except Exception as e:
            self.conn.rollback()
            print(f"Error in add_track_code: {e}")
            return False, str(e)

    def get_user_track_codes(self, telegram_id):
        """Возвращает все трек-коды пользователя"""
        try:
            user = self.get_user(telegram_id)
            if not user:
                return []
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT id, track_code, description, status, created_date, price
                    FROM track_codes
                    WHERE user_id = %s
                    ORDER BY created_date DESC
                """, (user['id'],))
                return cur.fetchall()
        except Exception as e:
            self.conn.rollback()
            print(f"Error in get_user_track_codes: {e}")
            return []

    def update_track_code_status(self, track_code_id, new_status):
        """Обновляет статус трек-кода"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    UPDATE track_codes
                    SET status = %s, updated_at = NOW()
                    WHERE id = %s
                """, (new_status, track_code_id))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            print(f"Error in update_track_code_status: {e}")
            raise e

    def get_recent_orders(self, limit=20):
        """Возвращает последние заказы (для админки)"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT tc.id, tc.track_code, tc.status, tc.created_date, u.customer_code, tc.price
                    FROM track_codes tc
                    LEFT JOIN users u ON tc.user_id = u.id
                    ORDER BY tc.created_date DESC
                    LIMIT %s
                """, (limit,))
                return cur.fetchall()
        except Exception as e:
            self.conn.rollback()
            print(f"Error in get_recent_orders: {e}")
            return []

    # ------------------------- КУРСЫ ВАЛЮТ -------------------------
    def get_exchange_rates(self):
        """Возвращает все курсы валют"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT * FROM exchange_rates ORDER BY currency_code")
                return cur.fetchall()
        except Exception as e:
            self.conn.rollback()
            print(f"Error in get_exchange_rates: {e}")
            return []

    def update_exchange_rate(self, currency_code, rate):
        """Обновляет курс валюты"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    UPDATE exchange_rates
                    SET rate = %s, updated_at = NOW()
                    WHERE currency_code = %s
                """, (rate, currency_code))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            print(f"Error in update_exchange_rate: {e}")
            raise e

    # ------------------------- МЕТОДЫ ДОСТАВКИ -------------------------
    def get_delivery_methods(self, delivery_type=None):
        """Возвращает способы доставки (можно фильтровать по типу)"""
        try:
            with self.conn.cursor() as cur:
                if delivery_type:
                    cur.execute("""
                        SELECT * FROM delivery_methods 
                        WHERE type = %s 
                        ORDER BY method_code
                    """, (delivery_type,))
                else:
                    cur.execute("SELECT * FROM delivery_methods ORDER BY method_code")
                return cur.fetchall()
        except Exception as e:
            self.conn.rollback()
            print(f"Error in get_delivery_methods: {e}")
            return []

    def update_delivery_price(self, method_code, price_per_kg):
        """Обновляет цену доставки"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    UPDATE delivery_methods
                    SET price_per_kg = %s, updated_at = NOW()
                    WHERE method_code = %s
                """, (price_per_kg, method_code))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            print(f"Error in update_delivery_price: {e}")
            raise e

    def update_delivery_days(self, method_code, min_days, max_days):
        """Обновляет сроки доставки"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    UPDATE delivery_methods
                    SET min_days = %s, max_days = %s, updated_at = NOW()
                    WHERE method_code = %s
                """, (min_days, max_days, method_code))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            print(f"Error in update_delivery_days: {e}")
            raise e

    # ------------------------- СТАТИСТИКА -------------------------
    def get_statistics(self):
        """Возвращает статистику (для админки)"""
        try:
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
        except Exception as e:
            self.conn.rollback()
            print(f"Error in get_statistics: {e}")
            return {
                'total_users': 0,
                'admin_users': 0,
                'total_track_codes': 0,
                'delivered_track_codes': 0
            }

    def get_all_users(self, include_admins=False):
        """Возвращает всех пользователей (для админки)"""
        try:
            with self.conn.cursor() as cur:
                if include_admins:
                    cur.execute("SELECT * FROM users ORDER BY registration_date DESC")
                else:
                    cur.execute("SELECT * FROM users WHERE is_admin = FALSE ORDER BY registration_date DESC")
                return cur.fetchall()
        except Exception as e:
            self.conn.rollback()
            print(f"Error in get_all_users: {e}")
            return []

db = Database()
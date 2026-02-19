import sqlite3
import random
import string
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple

class Database:
    """Класс для работы с базой данных SQLite"""
    
    def __init__(self, db_name: str = "bot_database.db"):
        """Инициализация подключения к базе данных"""
        self.db_name = db_name
        self.conn = None
        self.connect()
        self.create_tables()
        self.init_default_data()
    
    def connect(self):
        """Установка соединения с базой данных"""
        self.conn = sqlite3.connect(self.db_name)
        self.conn.row_factory = sqlite3.Row  # Возвращать строки как словари
    
    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """Выполнить SQL-запрос"""
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            self.conn.commit()
            return cursor
        except sqlite3.Error as e:
            print(f"Ошибка базы данных: {e}")
            self.conn.rollback()
            raise
    
    def executemany(self, query: str, params: list) -> sqlite3.Cursor:
        """Выполнить множественный SQL-запрос"""
        try:
            cursor = self.conn.cursor()
            cursor.executemany(query, params)
            self.conn.commit()
            return cursor
        except sqlite3.Error as e:
            print(f"Ошибка базы данных: {e}")
            self.conn.rollback()
            raise
    
    def fetch_one(self, query: str, params: tuple = ()) -> Optional[Dict]:
        """Получить одну запись"""
        cursor = self.execute(query, params)
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def fetch_all(self, query: str, params: tuple = ()) -> List[Dict]:
        """Получить все записи"""
        cursor = self.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    
    # ------------------------- СОЗДАНИЕ ТАБЛИЦ -------------------------
    
    def create_tables(self):
        """Создание всех необходимых таблиц"""
        
        # Таблица пользователей
        self.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                phone_number TEXT,
                customer_code TEXT UNIQUE NOT NULL,
                balance REAL DEFAULT 0,
                is_admin BOOLEAN DEFAULT 0,
                registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Таблица курсов валют
        self.execute("""
            CREATE TABLE IF NOT EXISTS exchange_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                currency_code TEXT UNIQUE NOT NULL,
                currency_name TEXT NOT NULL,
                flag TEXT NOT NULL,
                rate REAL NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Таблица способов доставки
        self.execute("""
            CREATE TABLE IF NOT EXISTS delivery_methods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                method_code TEXT UNIQUE NOT NULL,
                method_name TEXT NOT NULL,
                icon TEXT NOT NULL,
                price_per_kg REAL NOT NULL,
                min_days INTEGER NOT NULL,
                max_days INTEGER NOT NULL,
                description TEXT,
                delivery_type TEXT NOT NULL
            )
        """)
        
        # Таблица трек-кодов (заказов)
        self.execute("""
            CREATE TABLE IF NOT EXISTS track_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_code TEXT UNIQUE NOT NULL,
                user_id INTEGER,
                description TEXT,
                status TEXT DEFAULT 'В обработке',
                price REAL,
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
            )
        """)
        
        # Таблица истории операций
        self.execute("""
            CREATE TABLE IF NOT EXISTS transaction_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                transaction_type TEXT NOT NULL,
                description TEXT,
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)
        
        print("✅ Таблицы созданы или уже существуют")
    
    # ------------------------- ИНИЦИАЛИЗАЦИЯ ДАННЫХ -------------------------
    
    def init_default_data(self):
        """Инициализация данных по умолчанию"""
        
        # Проверяем, есть ли уже данные в таблице курсов валют
        count = self.fetch_one("SELECT COUNT(*) as count FROM exchange_rates")
        if count and count['count'] == 0:
            default_rates = [
                ('USD', 'USD', '🇺🇸', 95.0),
                ('EUR', 'EUR', '🇪🇺', 105.0),
                ('CNY', 'CNY', '🇨🇳', 13.5),
                ('KZT', 'KZT', '🇰🇿', 0.21),
                ('UZS', 'UZS', '🇺🇿', 0.0075),
                ('TJS', 'TJS', '🇹🇯', 8.5)
            ]
            self.executemany(
                "INSERT INTO exchange_rates (currency_code, currency_name, flag, rate) VALUES (?, ?, ?, ?)",
                default_rates
            )
            print("✅ Курсы валют по умолчанию добавлены")
        
        # Проверяем, есть ли уже данные в таблице способов доставки
        count = self.fetch_one("SELECT COUNT(*) as count FROM delivery_methods")
        if count and count['count'] == 0:
            default_methods = [
                # cargo - карго доставка
                ('avia_cargo', 'Авиа доставка', '✈️', 10.0, 3, 7, 'Быстрая доставка самолётом', 'cargo'),
                ('auto_cargo', 'Авто карго', '🚚', 5.0, 14, 21, 'Экономичная доставка автотранспортом', 'cargo'),
                ('rail_cargo', 'Ж/Д доставка', '🚆', 7.0, 10, 15, 'Доставка поездом', 'cargo'),
                
                # white - белая доставка
                ('avia_white', 'Авиа доставка', '✈️', 15.0, 5, 10, 'Белая доставка самолётом с документами', 'white'),
                ('auto_white', 'Авто карго', '🚚', 8.0, 15, 25, 'Белая доставка автотранспортом', 'white'),
                ('rail_white', 'Ж/Д доставка', '🚆', 10.0, 12, 20, 'Белая доставка поездом', 'white')
            ]
            self.executemany(
                """INSERT INTO delivery_methods 
                   (method_code, method_name, icon, price_per_kg, min_days, max_days, description, delivery_type) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                default_methods
            )
            print("✅ Способы доставки по умолчанию добавлены")
    
    # ------------------------- РАБОТА С ПОЛЬЗОВАТЕЛЯМИ -------------------------
    
    def generate_customer_code(self) -> str:
        """Генерация уникального кода клиента"""
        while True:
            # Формат: GD + 6 случайных цифр
            code = 'GD' + ''.join(random.choices(string.digits, k=6))
            # Проверяем, не существует ли уже такой код
            existing = self.fetch_one("SELECT id FROM users WHERE customer_code = ?", (code,))
            if not existing:
                return code
    
    def register_user(self, user_id: int, username: str = None, first_name: str = None,
                     last_name: str = None, phone_number: str = None, is_admin: bool = False) -> str:
        """Регистрация нового пользователя"""
        
        # Проверяем, не зарегистрирован ли уже пользователь
        existing = self.fetch_one("SELECT customer_code FROM users WHERE user_id = ?", (user_id,))
        if existing:
            return existing['customer_code']
        
        # Генерируем уникальный код клиента
        customer_code = self.generate_customer_code()
        
        self.execute("""
            INSERT INTO users (user_id, username, first_name, last_name, phone_number, customer_code, is_admin)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, username, first_name, last_name, phone_number, customer_code, is_admin))
        
        return customer_code
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        """Получить данные пользователя по Telegram ID"""
        return self.fetch_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
    
    def get_user_by_customer_code(self, customer_code: str) -> Optional[Dict]:
        """Получить данные пользователя по коду клиента"""
        return self.fetch_one("SELECT * FROM users WHERE customer_code = ?", (customer_code,))
    
    def get_all_users(self, include_admins: bool = True) -> List[Dict]:
        """Получить всех пользователей"""
        if include_admins:
            return self.fetch_all("SELECT * FROM users ORDER BY registration_date DESC")
        else:
            return self.fetch_all("SELECT * FROM users WHERE is_admin = 0 ORDER BY registration_date DESC")
    
    def is_admin(self, user_id: int) -> bool:
        """Проверить, является ли пользователь администратором"""
        user = self.get_user(user_id)
        return user and user['is_admin'] == 1
    
    def update_balance(self, user_id: int, amount: float) -> bool:
        """Обновить баланс пользователя"""
        user = self.get_user(user_id)
        if not user:
            return False
        
        new_balance = user['balance'] + amount
        self.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
        
        # Добавляем запись в историю транзакций
        self.add_transaction(
            user_id=user_id,
            amount=amount,
            transaction_type='пополнение' if amount > 0 else 'списание',
            description=f"Изменение баланса на {amount} руб."
        )
        
        return True
    
    def update_user_info(self, user_id: int, **kwargs) -> bool:
        """Обновить информацию о пользователе"""
        user = self.get_user(user_id)
        if not user:
            return False
        
        allowed_fields = ['username', 'first_name', 'last_name', 'phone_number']
        updates = []
        values = []
        
        for field, value in kwargs.items():
            if field in allowed_fields and value is not None:
                updates.append(f"{field} = ?")
                values.append(value)
        
        if not updates:
            return False
        
        values.append(user_id)
        query = f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?"
        self.execute(query, tuple(values))
        return True
    
    # ------------------------- РАБОТА С КУРСАМИ ВАЛЮТ -------------------------
    
    def get_exchange_rates(self) -> List[Dict]:
        """Получить все курсы валют"""
        return self.fetch_all("SELECT * FROM exchange_rates ORDER BY currency_code")
    
    def get_exchange_rate(self, currency_code: str) -> Optional[Dict]:
        """Получить курс конкретной валюты"""
        return self.fetch_one("SELECT * FROM exchange_rates WHERE currency_code = ?", (currency_code,))
    
    def update_exchange_rate(self, currency_code: str, new_rate: float) -> bool:
        """Обновить курс валюты"""
        result = self.execute(
            "UPDATE exchange_rates SET rate = ?, updated_at = CURRENT_TIMESTAMP WHERE currency_code = ?",
            (new_rate, currency_code)
        )
        return result.rowcount > 0
    
    def add_exchange_rate(self, currency_code: str, currency_name: str, flag: str, rate: float) -> bool:
        """Добавить новую валюту"""
        try:
            self.execute(
                "INSERT INTO exchange_rates (currency_code, currency_name, flag, rate) VALUES (?, ?, ?, ?)",
                (currency_code, currency_name, flag, rate)
            )
            return True
        except sqlite3.IntegrityError:
            return False
    
    # ------------------------- РАБОТА СО СПОСОБАМИ ДОСТАВКИ -------------------------
    
    def get_delivery_methods(self, delivery_type: str = None) -> List[Dict]:
        """Получить способы доставки"""
        if delivery_type:
            return self.fetch_all(
                "SELECT * FROM delivery_methods WHERE delivery_type = ? ORDER BY price_per_kg",
                (delivery_type,)
            )
        else:
            return self.fetch_all("SELECT * FROM delivery_methods ORDER BY delivery_type, price_per_kg")
    
    def get_delivery_method(self, method_code: str) -> Optional[Dict]:
        """Получить конкретный способ доставки"""
        return self.fetch_one("SELECT * FROM delivery_methods WHERE method_code = ?", (method_code,))
    
    def update_delivery_price(self, method_code: str, new_price: float) -> bool:
        """Обновить цену доставки"""
        result = self.execute(
            "UPDATE delivery_methods SET price_per_kg = ? WHERE method_code = ?",
            (new_price, method_code)
        )
        return result.rowcount > 0
    
    def update_delivery_days(self, method_code: str, min_days: int, max_days: int) -> bool:
        """Обновить сроки доставки"""
        result = self.execute(
            "UPDATE delivery_methods SET min_days = ?, max_days = ? WHERE method_code = ?",
            (min_days, max_days, method_code)
        )
        return result.rowcount > 0
    
    def add_delivery_method(self, method_code: str, method_name: str, icon: str,
                           price_per_kg: float, min_days: int, max_days: int,
                           description: str, delivery_type: str) -> bool:
        """Добавить новый способ доставки"""
        try:
            self.execute(
                """INSERT INTO delivery_methods 
                   (method_code, method_name, icon, price_per_kg, min_days, max_days, description, delivery_type) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (method_code, method_name, icon, price_per_kg, min_days, max_days, description, delivery_type)
            )
            return True
        except sqlite3.IntegrityError:
            return False
    
    # ------------------------- РАБОТА С ТРЕК-КОДАМИ (ЗАКАЗАМИ) -------------------------
    
    def generate_track_code(self) -> str:
        """Генерация уникального трек-кода"""
        while True:
            # Формат: GD + 8 случайных символов (буквы и цифры)
            code = 'GD' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            existing = self.fetch_one("SELECT id FROM track_codes WHERE track_code = ?", (code,))
            if not existing:
                return code
    
    def add_track_code(self, user_id: int = None, description: str = None,
                      price: float = None, status: str = 'В обработке') -> str:
        """Добавить новый трек-код"""
        track_code = self.generate_track_code()
        
        # Получаем внутренний ID пользователя если передан Telegram ID
        db_user_id = None
        if user_id:
            user = self.get_user(user_id)
            if user:
                db_user_id = user['id']
        
        self.execute("""
            INSERT INTO track_codes (track_code, user_id, description, price, status)
            VALUES (?, ?, ?, ?, ?)
        """, (track_code, db_user_id, description, price, status))
        
        return track_code
    
    def get_track_code(self, track_code: str) -> Optional[Dict]:
        """Получить информацию о трек-коде"""
        return self.fetch_one("""
            SELECT tc.*, u.customer_code, u.user_id as telegram_id
            FROM track_codes tc
            LEFT JOIN users u ON tc.user_id = u.id
            WHERE tc.track_code = ?
        """, (track_code,))
    
    def get_user_track_codes(self, user_id: int) -> List[Dict]:
        """Получить все трек-коды пользователя"""
        user = self.get_user(user_id)
        if not user:
            return []
        
        return self.fetch_all("""
            SELECT * FROM track_codes 
            WHERE user_id = ? 
            ORDER BY created_date DESC
        """, (user['id'],))
    
    def update_track_code_status(self, track_code_id: int, new_status: str) -> bool:
        """Обновить статус трек-кода"""
        result = self.execute(
            "UPDATE track_codes SET status = ? WHERE id = ?",
            (new_status, track_code_id)
        )
        return result.rowcount > 0
    
    def get_recent_orders(self, limit: int = 10) -> List[Dict]:
        """Получить последние заказы"""
        return self.fetch_all("""
            SELECT tc.*, u.customer_code 
            FROM track_codes tc
            LEFT JOIN users u ON tc.user_id = u.id
            ORDER BY tc.created_date DESC
            LIMIT ?
        """, (limit,))
    
    # ------------------------- ИСТОРИЯ ТРАНЗАКЦИЙ -------------------------
    
    def add_transaction(self, user_id: int, amount: float,
                       transaction_type: str, description: str = None) -> bool:
        """Добавить запись в историю транзакций"""
        user = self.get_user(user_id)
        if not user:
            return False
        
        self.execute("""
            INSERT INTO transaction_history (user_id, amount, transaction_type, description)
            VALUES (?, ?, ?, ?)
        """, (user['id'], amount, transaction_type, description))
        
        return True
    
    def get_user_transactions(self, user_id: int, limit: int = 20) -> List[Dict]:
        """Получить историю транзакций пользователя"""
        user = self.get_user(user_id)
        if not user:
            return []
        
        return self.fetch_all("""
            SELECT * FROM transaction_history 
            WHERE user_id = ? 
            ORDER BY created_date DESC
            LIMIT ?
        """, (user['id'], limit))
    
    # ------------------------- СТАТИСТИКА -------------------------
    
    def get_statistics(self) -> Dict[str, int]:
        """Получить общую статистику"""
        stats = {}
        
        # Количество пользователей
        result = self.fetch_one("SELECT COUNT(*) as count FROM users")
        stats['total_users'] = result['count'] if result else 0
        
        # Количество администраторов
        result = self.fetch_one("SELECT COUNT(*) as count FROM users WHERE is_admin = 1")
        stats['admin_users'] = result['count'] if result else 0
        
        # Количество трек-кодов
        result = self.fetch_one("SELECT COUNT(*) as count FROM track_codes")
        stats['total_track_codes'] = result['count'] if result else 0
        
        # Количество доставленных
        result = self.fetch_one("SELECT COUNT(*) as count FROM track_codes WHERE status = 'Доставлен'")
        stats['delivered_track_codes'] = result['count'] if result else 0
        
        # Общая сумма всех заказов
        result = self.fetch_one("SELECT SUM(price) as total FROM track_codes")
        stats['total_orders_sum'] = result['total'] if result and result['total'] else 0
        
        return stats
    
    # ------------------------- ЗАКРЫТИЕ СОЕДИНЕНИЯ -------------------------
    
    def close(self):
        """Закрыть соединение с базой данных"""
        if self.conn:
            self.conn.close()
            print("🔒 Соединение с БД закрыто")


# Создаем глобальный экземпляр базы данных
db = Database()

# Функция для закрытия соединения при завершении работы
def close_db():
    db.close()
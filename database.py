from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY
import random
import string

class Database:
    def __init__(self):
        self.supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    def generate_customer_code(self):
        """Генерирует уникальный код клиента"""
        while True:
            letters = ''.join(random.choices(string.ascii_uppercase, k=2))
            numbers = ''.join(random.choices(string.digits, k=5))
            code = f"GD-{letters}{numbers}"
            # Проверяем уникальность
            result = self.supabase.table("users").select("customer_code").eq("customer_code", code).execute()
            if not result.data:
                return code

    def get_or_create_user(self, telegram_id, username=None, first_name=None):
        """Возвращает пользователя или создаёт нового"""
        result = self.supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
        
        if result.data:
            return result.data[0]
        
        # Создаём нового пользователя
        customer_code = self.generate_customer_code()
        new_user = self.supabase.table("users").insert({
            "telegram_id": telegram_id,
            "username": username or "",
            "first_name": first_name or "",
            "customer_code": customer_code,
            "balance": 0.0
        }).execute()
        
        return new_user.data[0]

    def get_user(self, telegram_id):
        """Получить пользователя по telegram_id"""
        result = self.supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
        return result.data[0] if result.data else None

    def update_balance(self, telegram_id, amount):
        """Обновить баланс пользователя"""
        user = self.get_user(telegram_id)
        if not user:
            return None
        new_balance = user["balance"] + amount
        result = self.supabase.table("users").update({"balance": new_balance}).eq("telegram_id", telegram_id).execute()
        return result.data[0] if result.data else None

    def add_track_code(self, telegram_id, track_code, description=""):
        """Добавить трек-код"""
        user = self.get_user(telegram_id)
        if not user:
            return None
        
        result = self.supabase.table("orders").insert({
            "user_id": user["id"],
            "track_code": track_code.upper(),
            "status": "В обработке",
            "description": description
        }).execute()
        
        return result.data[0] if result.data else None

    def get_user_orders(self, telegram_id):
        """Получить все заказы пользователя"""
        user = self.get_user(telegram_id)
        if not user:
            return []
        
        result = self.supabase.table("orders").select("track_code, status, description, created_at").eq("user_id", user["id"]).order("created_at", desc=True).execute()
        return result.data

    def get_exchange_rates(self):
        """Получить курсы валют"""
        result = self.supabase.table("exchange_rates").select("*").order("currency_code").execute()
        return result.data

# Глобальный экземпляр
db = Database()
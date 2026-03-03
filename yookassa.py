import uuid
import base64
import json
from typing import Dict, Any, Optional

try:
    import requests
except ImportError:
    print("⚠️ Библиотека requests не установлена. Платежи через ЮKassa не будут работать.")
    requests = None

from config import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY

class YooKassaClient:
    def __init__(self, shop_id=None, secret_key=None):
        """
        Инициализация клиента ЮKassa
        
        Args:
            shop_id: ID магазина (если None, берется из config)
            secret_key: Секретный ключ (если None, берется из config)
        """
        self.shop_id = shop_id or YOOKASSA_SHOP_ID
        self.secret_key = secret_key or YOOKASSA_SECRET_KEY
        self.api_url = "https://api.yookassa.ru/v3"
        
        # Проверяем наличие requests
        if requests is None:
            print("⚠️ ЮKassa: библиотека requests не установлена")
            self.auth_header = None
            return
        
        # Создаем базовую аутентификацию
        if self.shop_id and self.secret_key:
            auth_string = f"{self.shop_id}:{self.secret_key}"
            self.auth_header = base64.b64encode(auth_string.encode()).decode()
            print(f"✅ ЮKassa инициализирована с shop_id: {self.shop_id[:5]}...")
        else:
            self.auth_header = None
            print("⚠️ ЮKassa не настроена: отсутствуют SHOP_ID или SECRET_KEY")
    
    def create_payment(self, amount: float, description: str, telegram_id: int, 
                      return_url: str = None, metadata: Dict = None) -> Optional[Dict]:
        """
        Создание платежа в ЮKassa
        """
        if requests is None:
            print("❌ ЮKassa: библиотека requests не установлена")
            return None
            
        if not self.shop_id or not self.secret_key or not self.auth_header:
            print("⚠️ ЮKassa не настроена")
            return None
            
        if metadata is None:
            metadata = {}
        
        metadata['telegram_id'] = telegram_id
        
        payment_data = {
            "amount": {
                "value": f"{amount:.2f}",
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": return_url or "https://t.me/GoldenDragonCargoBot"
            },
            "capture": True,
            "description": description[:50],
            "metadata": metadata
        }
        
        headers = {
            "Content-Type": "application/json",
            "Idempotence-Key": str(uuid.uuid4()),
            "Authorization": f"Basic {self.auth_header}"
        }
        
        try:
            response = requests.post(
                f"{self.api_url}/payments",
                json=payment_data,
                headers=headers
            )
            
            if response.status_code in (200, 201):
                result = response.json()
                print(f"✅ Платеж создан: {result.get('id')}")
                return result
            else:
                print(f"❌ Ошибка создания платежа: {response.status_code}")
                print(f"Ответ: {response.text[:200]}")
                return None
                
        except Exception as e:
            print(f"❌ Исключение при создании платежа: {e}")
            return None
    
    def get_payment(self, payment_id: str) -> Optional[Dict]:
        """
        Получение информации о платеже
        """
        if requests is None:
            return None
            
        if not self.auth_header:
            return None
            
        headers = {
            "Authorization": f"Basic {self.auth_header}"
        }
        
        try:
            response = requests.get(
                f"{self.api_url}/payments/{payment_id}",
                headers=headers
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"❌ Ошибка получения платежа: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ Исключение при получении платежа: {e}")
            return None

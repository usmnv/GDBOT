import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ACCESS_CODE = os.getenv("ADMIN_ACCESS_CODE", "GD-A4333")

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# ЮKassa
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "")
PROVIDER_TOKEN = os.getenv("PROVIDER_TOKEN", "")  # Токен от BotFather

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://common-adara-goldendragon-845bca68.koyeb.app/api/yookassa/webhook")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в переменных окружения")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL и SUPABASE_KEY должны быть заданы в переменных окружения")
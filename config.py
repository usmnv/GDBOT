import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ACCESS_CODE = os.getenv("ADMIN_ACCESS_CODE", "GD-A4333")  # Значение по умолчанию, если не задано

# Добавляем переменные для Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")  # или os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в переменных окружения")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL и SUPABASE_KEY должны быть заданы в переменных окружения")
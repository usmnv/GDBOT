import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    print("⚠️ Внимание: BOT_TOKEN не найден в переменных окружения")
    BOT_TOKEN = os.getenv('BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TOKEN')
    if not BOT_TOKEN:
        print("❌ ОШИБКА: BOT_TOKEN не найден!")
        sys.exit(1)

# Имя файла базы данных (можете оставить golden_dragon.db или изменить)
DATABASE_NAME = 'golden_dragon.db'

ADMIN_ACCESS_CODE = 'GD-A4333'

print(f"✅ Конфигурация загружена")
print(f"🔧 Режим: {'Amvera' if 'AMVERA' in os.environ else 'Локальный'}")
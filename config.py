import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ACCESS_CODE = "GD-A4333"

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан")
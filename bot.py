import logging
import os
import json
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
import uvicorn

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, filters, ContextTypes
)

# Импортируем конфигурацию и базу данных
from config import BOT_TOKEN, ADMIN_ACCESS_CODE
from database import db

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ------------------------- Состояния ConversationHandler -------------------------
PHONE, ADMIN_CODE, TRACK_CODE = range(3)
SELECT_CURRENCY, ENTER_NEW_RATE = range(3, 5)
SELECT_DELIVERY_METHOD, ENTER_NEW_PRICE, ENTER_NEW_DAYS = range(5, 8)
SELECT_ORDER_STATUS, BROADCAST_MESSAGE = range(8, 10)
EXCHANGE_SELECT_FROM, EXCHANGE_SELECT_TO, EXCHANGE_ENTER_AMOUNT = range(10, 13)

# ------------------------- Глобальные переменные -------------------------
telegram_app = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация и завершение работы бота"""
    global telegram_app
    
    # Создаём приложение бота
    telegram_app = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрируем все обработчики
    register_handlers(telegram_app)
    
    # Инициализируем и запускаем бота
    await telegram_app.initialize()
    await telegram_app.start()
    
    logger.info("✅ Telegram бот запущен")
    
    yield
    
    # Остановка бота
    await telegram_app.stop()
    await telegram_app.shutdown()
    logger.info("🛑 Telegram бот остановлен")

# Создаём FastAPI приложение
app = FastAPI(lifespan=lifespan, title="Golden Dragon Bot + API")

# Разрешаем CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ -------------------------
def get_main_keyboard(is_admin=False):
    """Главная клавиатура"""
    keyboard = [
        ["👤 Личный кабинет"],
        ["💰 Курсы валют", "💱 Обмен валют"],
        ["🚚 Доставка"],
        ["🏭 Склады в Китае"],
        ["🔎 Поиск по трек-коду"],
        ["🆘 Поддержка"]
    ]
    if is_admin:
        keyboard.append(["⚙️ Админ-панель"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ------------------------- ОБРАБОТЧИКИ БОТА -------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /start"""
    user = update.effective_user
    user_data = db.get_user(user.id)
    
    if user_data:
        customer_code = user_data['customer_code']
        is_admin = user_data['is_admin']
        await update.message.reply_text(
            f"🏮 Добро пожаловать в Golden Dragon!\n\nВаш код клиента: {customer_code}\n\nИспользуйте меню.",
            reply_markup=get_main_keyboard(is_admin)
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "👋 Привет! Для регистрации отправьте ваш контакт:",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("📱 Отправить контакт", request_contact=True)]],
                resize_keyboard=True, one_time_keyboard=True
            )
        )
        return PHONE

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка полученного контакта"""
    contact = update.message.contact
    user = update.effective_user
    
    if contact.user_id != user.id:
        await update.message.reply_text("Пожалуйста, отправьте свой контакт.")
        return PHONE
    
    customer_code = db.register_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        phone_number=contact.phone_number
    )
    
    await update.message.reply_text(
        f"✅ Регистрация успешна!\n📋 Ваш код: {customer_code}",
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END

async def personal_cabinet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Личный кабинет с кнопкой WebApp"""
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data:
        await update.message.reply_text("Пожалуйста, сначала зарегистрируйтесь через /start")
        return
    
    track_codes = db.get_user_track_codes(user_id)
    track_count = len(track_codes)
    
    # URL мини-приложения (GitHub Pages)
    # ⚠️ ЗАМЕНИТЕ НА ВАШ РЕАЛЬНЫЙ URL
    webapp_url = f"https://usmnv.github.io/Gd-cargo/?code={user_data['customer_code']}"
    
    keyboard = [[
        InlineKeyboardButton(
            "📱 Открыть мини-приложение",
            web_app=WebAppInfo(url=webapp_url)
        )
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    info_text = (
        f"👤 Личный кабинет\n\n"
        f"📋 Код клиента: {user_data['customer_code']}\n"
        f"💳 Баланс: {user_data['balance']} руб\n"
        f"📦 Заказов: {track_count}\n"
        f"📅 Регистрация: {user_data['registration_date']}\n"
        f"👑 Статус: {'Администратор' if user_data['is_admin'] else 'Клиент'}\n\n"
        f"Нажмите кнопку ниже для доступа к полному функционалу:"
    )
    await update.message.reply_text(info_text, reply_markup=reply_markup)

async def exchange_rates_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ курсов валют"""
    rates = db.get_exchange_rates()
    if not rates:
        await update.message.reply_text("Курсы валют временно недоступны.")
        return
    
    text = "💱 Текущие курсы валют:\n\n"
    for rate in rates:
        text += f"{rate[2]} {rate[3]}: {rate[1]} RUB\n"
    await update.message.reply_text(text)

async def delivery_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню доставки"""
    methods = db.get_delivery_methods()
    if not methods:
        await update.message.reply_text("Информация о доставке временно недоступна.")
        return
    
    keyboard = [[f"{m[5]} {m[1]}"] for m in methods] + [["🔙 Назад"]]
    await update.message.reply_text(
        "🚚 Выберите способ доставки:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

async def handle_delivery_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детали выбранного способа доставки"""
    text = update.message.text
    
    if text == "🔙 Назад":
        user_id = update.effective_user.id
        is_admin = db.is_admin(user_id)
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard(is_admin))
        return
    
    method_text = text[2:].strip() if len(text) > 2 else text
    methods = db.get_delivery_methods()
    
    for m in methods:
        if m[1] == method_text:
            await update.message.reply_text(
                f"{m[5]} {m[1]}\n\n"
                f"💰 Цена: ${m[2]} за кг\n"
                f"📅 Срок: {m[3]}-{m[4]} дней\n"
                f"📝 {m[6]}\n\n"
                f"Пример: 5 кг = ${m[2] * 5}"
            )
            return
    
    await update.message.reply_text("Способ доставки не найден.")

async def search_track_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск трек-кода"""
    await update.message.reply_text("Введите трек-код для добавления:")
    return TRACK_CODE

async def handle_track_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка трек-кода"""
    user_id = update.effective_user.id
    track_code = update.message.text.strip().upper()
    
    success = db.add_track_code(user_id, track_code)
    
    if success:
        await update.message.reply_text(f"✅ Трек-код {track_code} добавлен!\nСтатус: В обработке")
    else:
        await update.message.reply_text(f"❌ Трек-код {track_code} уже существует.")
    
    return ConversationHandler.END

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поддержка"""
    await update.message.reply_text(
        "🆘 Поддержка\n\n"
        "📞 Телефон: +7 (800) 123-45-67\n"
        "📧 Email: support@goldendragon.com\n"
        "⏰ Время работы: 9:00 - 21:00 (МСК)"
    )

# ------------------------- СКЛАДЫ В КИТАЕ -------------------------
async def warehouses_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню складов"""
    keyboard = [
        ["🏭 Склад Иу"],
        ["🏭 Склад Гуанчжоу"],
        ["🏭 Склад Урумчи"],
        ["🔙 Назад"]
    ]
    await update.message.reply_text(
        "Выберите склад для получения информации:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

async def handle_warehouse_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о складе"""
    text = update.message.text
    
    if text == "🔙 Назад":
        await warehouses_menu(update, context)
        return
    
    warehouses = {
        "🏭 Склад Иу": {
            "address": "浙江省义乌市国际商贸城, 义乌, 322000, Китай",
            "conditions": "✅ Минимальный вес: 5 кг\n✅ Приёмка: 0.5$/кг\n✅ Хранение: 3 дня бесплатно",
            "contact": "📞 Менеджер: +86 123 4567 8901"
        },
        "🏭 Склад Гуанчжоу": {
            "address": "广州市白云区机场路, 广州, 510000, Китай",
            "conditions": "✅ Минимальный вес: 10 кг\n✅ Приёмка: 0.3$/кг\n✅ Хранение: 5 дней бесплатно",
            "contact": "📞 Менеджер: +86 123 4567 8902"
        },
        "🏭 Склад Урумчи": {
            "address": "新疆乌鲁木齐市经济开发区, 乌鲁木齐, 830000, Китай",
            "conditions": "✅ Минимальный вес: 3 кг\n✅ Приёмка: 0.4$/кг\n✅ Хранение: 7 дней бесплатно",
            "contact": "📞 Менеджер: +86 123 4567 8903"
        }
    }
    
    info = warehouses.get(text)
    if info:
        await update.message.reply_text(
            f"{text}\n\n📍 Адрес: {info['address']}\n📦 Условия: {info['conditions']}\n{info['contact']}\n\n"
            "Для возврата нажмите '🔙 Назад'"
        )
    else:
        await update.message.reply_text("Склад не найден.")

# ------------------------- ОБМЕН ВАЛЮТ -------------------------
async def exchange_currency_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало обмена валют"""
    user_id = update.effective_user.id
    if not db.get_user(user_id):
        await update.message.reply_text("Пожалуйста, сначала зарегистрируйтесь через /start")
        return ConversationHandler.END

    rates = db.get_exchange_rates()
    if not rates:
        await update.message.reply_text("Курсы валют временно недоступны.")
        return ConversationHandler.END

    context.user_data['exchange_rates'] = rates

    all_currencies = [f"{r[2]} {r[3]}" for r in rates] + ["🇷🇺 RUB (Российский рубль)"]
    keyboard = []
    for i in range(0, len(all_currencies), 2):
        keyboard.append(all_currencies[i:i+2])
    keyboard.append(["🔙 Назад"])

    await update.message.reply_text(
        "💱 Выберите ВАЛЮТУ, КОТОРУЮ ХОТИТЕ ОБМЕНЯТЬ (отдаёте):",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return EXCHANGE_SELECT_FROM

async def exchange_select_from(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор исходной валюты"""
    text = update.message.text.strip()
    
    if text == "🔙 Назад":
        user_id = update.effective_user.id
        is_admin = db.is_admin(user_id)
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard(is_admin))
        return ConversationHandler.END

    rates = context.user_data['exchange_rates']
    selected_from = None

    for r in rates:
        if f"{r[2]} {r[3]}" in text:
            selected_from = ('currency', r[0], r[1], r[2], r[3])
            break
    if "🇷🇺 RUB" in text:
        selected_from = ('rub', 'RUB', 1.0, '🇷🇺', 'Российский рубль')

    if not selected_from:
        await update.message.reply_text("Валюта не найдена. Попробуйте снова.")
        return EXCHANGE_SELECT_FROM

    context.user_data['exchange_from'] = selected_from

    all_currencies = []
    for r in rates:
        if r[0] != selected_from[1]:
            all_currencies.append(f"{r[2]} {r[3]}")
    if selected_from[1] != 'RUB':
        all_currencies.append("🇷🇺 RUB (Российский рубль)")

    keyboard = []
    for i in range(0, len(all_currencies), 2):
        keyboard.append(all_currencies[i:i+2])
    keyboard.append(["🔙 Назад"])

    await update.message.reply_text(
        f"Выбрано: {selected_from[3]} {selected_from[4]}\n\n"
        "Теперь выберите ВАЛЮТУ, КОТОРУЮ ХОТИТЕ ПОЛУЧИТЬ:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return EXCHANGE_SELECT_TO

async def exchange_select_to(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор целевой валюты"""
    text = update.message.text.strip()
    
    if text == "🔙 Назад":
        return await exchange_currency_start(update, context)

    rates = context.user_data['exchange_rates']
    from_data = context.user_data['exchange_from']
    selected_to = None

    for r in rates:
        if f"{r[2]} {r[3]}" in text and r[0] != from_data[1]:
            selected_to = ('currency', r[0], r[1], r[2], r[3])
            break
    if "🇷🇺 RUB" in text and from_data[1] != 'RUB':
        selected_to = ('rub', 'RUB', 1.0, '🇷🇺', 'Российский рубль')

    if not selected_to:
        await update.message.reply_text("Валюта не найдена или совпадает с исходной. Попробуйте снова.")
        return EXCHANGE_SELECT_TO

    context.user_data['exchange_to'] = selected_to

    await update.message.reply_text(
        f"💱 Конвертация:\n"
        f"Исходная: {from_data[3]} {from_data[4]} ({from_data[1]})\n"
        f"Целевая: {selected_to[3]} {selected_to[4]} ({selected_to[1]})\n\n"
        f"Введите сумму в {from_data[1]}:"
    )
    return EXCHANGE_ENTER_AMOUNT

async def exchange_enter_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ввод суммы и расчёт"""
    text = update.message.text.strip()
    
    if text == "🔙 Назад":
        return await exchange_select_from(update, context)

    try:
        amount = float(text.replace(',', '.'))
        if amount <= 0:
            await update.message.reply_text("Сумма должна быть положительным числом.")
            return EXCHANGE_ENTER_AMOUNT

        from_data = context.user_data['exchange_from']
        to_data = context.user_data['exchange_to']
        rates = context.user_data['exchange_rates']

        if from_data[0] == 'rub':
            rate_from_rub = 1.0
        else:
            rate_from_rub = next((r[1] for r in rates if r[0] == from_data[1]), None)
            if rate_from_rub is None:
                await update.message.reply_text("Курс исходной валюты не найден.")
                return ConversationHandler.END

        if to_data[0] == 'rub':
            rate_to_rub = 1.0
        else:
            rate_to_rub = next((r[1] for r in rates if r[0] == to_data[1]), None)
            if rate_to_rub is None:
                await update.message.reply_text("Курс целевой валюты не найден.")
                return ConversationHandler.END

        amount_in_rub = amount * rate_from_rub if from_data[0] != 'rub' else amount
        result = amount_in_rub / rate_to_rub if to_data[0] != 'rub' else amount_in_rub

        from_flag = from_data[3] if from_data[0] != 'rub' else '🇷🇺'
        to_flag = to_data[3] if to_data[0] != 'rub' else '🇷🇺'
        from_code = from_data[1]
        to_code = to_data[1]

        await update.message.reply_text(
            f"✅ Результат конвертации:\n\n"
            f"{from_flag} {from_code}: {amount:.2f}\n"
            f"{to_flag} {to_code}: {result:.2f}\n\n"
            f"Курс: 1 {from_code} = {result/amount:.4f} {to_code}"
        )

        user_id = update.effective_user.id
        is_admin = db.is_admin(user_id)
        await update.message.reply_text(
            "Главное меню:",
            reply_markup=get_main_keyboard(is_admin)
        )
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число (например 100.50).")
        return EXCHANGE_ENTER_AMOUNT

# ------------------------- АДМИН-ФУНКЦИИ -------------------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Панель администратора"""
    user_id = update.effective_user.id
    if not db.is_admin(user_id):
        await update.message.reply_text("У вас нет доступа к админ-панели.")
        return
    
    keyboard = [
        ["📊 Статистика"],
        ["💱 Изменить курс валют"],
        ["🚚 Изменить цены доставки"],
        ["📦 Управление заказами"],
        ["📢 Сделать рассылку"],
        ["👥 Пользователи"],
        ["🔙 Назад"]
    ]
    await update.message.reply_text(
        "⚙️ Админ-панель:\n\nВыберите действие:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

async def admin_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Регистрация администратора"""
    await update.message.reply_text("Введите код доступа для регистрации администратора:")
    return ADMIN_CODE

async def handle_admin_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка кода администратора"""
    user = update.effective_user
    code = update.message.text.strip()
    
    if code == ADMIN_ACCESS_CODE:
        customer_code = db.register_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            phone_number="admin",
            is_admin=True
        )
        await update.message.reply_text(
            f"✅ Вы зарегистрированы как администратор!\n📋 Ваш код: {customer_code}",
            reply_markup=get_main_keyboard(True)
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ Неверный код доступа. Попробуйте снова.")
        return ADMIN_CODE

async def change_exchange_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Изменение курса валюты"""
    user_id = update.effective_user.id
    if not db.is_admin(user_id):
        await update.message.reply_text("У вас нет доступа.")
        return
    
    rates = db.get_exchange_rates()
    keyboard = [[f"{r[2]} {r[3]} (текущий: {r[1]} RUB)"] for r in rates] + [["🔙 Назад"]]
    context.user_data['rates'] = rates
    
    await update.message.reply_text(
        "💱 Выберите валюту для изменения курса:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return SELECT_CURRENCY

async def select_currency_for_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор валюты для изменения"""
    text = update.message.text
    
    if text == "🔙 Назад":
        await update.message.reply_text("Отменено.", reply_markup=get_main_keyboard(True))
        return ConversationHandler.END
    
    for r in context.user_data.get('rates', []):
        if f"{r[2]} {r[3]}" in text:
            context.user_data['selected_currency'] = r[0]
            context.user_data['currency_name'] = r[3]
            context.user_data['flag'] = r[2]
            context.user_data['current_rate'] = r[1]
            await update.message.reply_text(
                f"Выбрана валюта: {r[2]} {r[3]}\nТекущий курс: {r[1]} RUB\n\nВведите новый курс:"
            )
            return ENTER_NEW_RATE
    
    await update.message.reply_text("Валюта не найдена.")
    return ConversationHandler.END

async def enter_new_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ввод нового курса"""
    text = update.message.text.strip()
    
    if text == "🔙 Назад":
        await update.message.reply_text("Отменено.", reply_markup=get_main_keyboard(True))
        return ConversationHandler.END
    
    try:
        new_rate = float(text.replace(',', '.'))
        currency_code = context.user_data['selected_currency']
        old_rate = context.user_data['current_rate']
        
        db.update_exchange_rate(currency_code, new_rate)
        
        await update.message.reply_text(
            f"✅ Курс обновлен!\n\n"
            f"{context.user_data['flag']} {context.user_data['currency_name']}\n"
            f"📉 Было: {old_rate} RUB\n📈 Стало: {new_rate} RUB",
            reply_markup=get_main_keyboard(True)
        )
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число (например 95.50).")
        return ENTER_NEW_RATE

async def change_delivery_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Изменение цены доставки"""
    user_id = update.effective_user.id
    if not db.is_admin(user_id):
        await update.message.reply_text("У вас нет доступа.")
        return
    
    methods = db.get_delivery_methods()
    keyboard = [[f"{m[5]} {m[1]} (${m[2]}/кг)"] for m in methods] + [["🔙 Назад"]]
    context.user_data['delivery_methods'] = methods
    
    await update.message.reply_text(
        "🚚 Выберите способ доставки для изменения:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return SELECT_DELIVERY_METHOD

async def select_delivery_for_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор способа доставки для изменения"""
    text = update.message.text.strip()
    
    if text == "🔙 Назад":
        await update.message.reply_text("Отменено.", reply_markup=get_main_keyboard(True))
        return ConversationHandler.END
    
    if text in ["💰 Изменить цену за кг", "📅 Изменить сроки доставки"]:
        if text == "💰 Изменить цену за кг":
            await update.message.reply_text(
                f"Введите новую цену за кг для {context.user_data['method_name']}:\n"
                f"Текущая цена: ${context.user_data['current_price']}"
            )
            return ENTER_NEW_PRICE
        else:
            await update.message.reply_text(
                f"Введите новые сроки для {context.user_data['method_name']}:\n"
                f"Текущие сроки: {context.user_data['min_days']}-{context.user_data['max_days']} дней\n"
                f"Формат: минимальные-максимальные дни (например 5-10)"
            )
            return ENTER_NEW_DAYS
    else:
        for m in context.user_data.get('delivery_methods', []):
            if f"{m[5]} {m[1]}" in text:
                context.user_data['selected_method'] = m[0]
                context.user_data['method_name'] = m[1]
                context.user_data['current_price'] = m[2]
                context.user_data['min_days'] = m[3]
                context.user_data['max_days'] = m[4]
                context.user_data['icon'] = m[5]
                
                keyboard = [
                    ["💰 Изменить цену за кг"],
                    ["📅 Изменить сроки доставки"],
                    ["🔙 Назад"]
                ]
                await update.message.reply_text(
                    f"📝 Выбран способ: {m[5]} {m[1]}\n\n"
                    f"💰 Текущая цена: ${m[2]}/кг\n"
                    f"📅 Текущие сроки: {m[3]}-{m[4]} дней\n\n"
                    f"Что хотите изменить?",
                    reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                )
                return SELECT_DELIVERY_METHOD
    
    await update.message.reply_text("Способ доставки не найден.")
    return ConversationHandler.END

async def enter_new_delivery_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ввод новой цены доставки"""
    text = update.message.text.strip()
    
    if text == "🔙 Назад":
        await update.message.reply_text("Отменено.", reply_markup=get_main_keyboard(True))
        return ConversationHandler.END
    
    try:
        new_price = float(text.replace(',', '.'))
        method_code = context.user_data['selected_method']
        old_price = context.user_data['current_price']
        
        db.update_delivery_price(method_code, new_price)
        
        await update.message.reply_text(
            f"✅ Цена обновлена!\n\n"
            f"{context.user_data['icon']} {context.user_data['method_name']}\n"
            f"💰 Было: ${old_price}/кг\n💰 Стало: ${new_price}/кг",
            reply_markup=get_main_keyboard(True)
        )
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число (например 15.50).")
        return ENTER_NEW_PRICE

async def enter_new_delivery_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ввод новых сроков доставки"""
    text = update.message.text.strip()
    
    if text == "🔙 Назад":
        await update.message.reply_text("Отменено.", reply_markup=get_main_keyboard(True))
        return ConversationHandler.END
    
    try:
        if '-' in text:
            parts = text.split('-')
            min_days = int(parts[0].strip())
            max_days = int(parts[1].strip())
        else:
            min_days = max_days = int(text.strip())
        
        method_code = context.user_data['selected_method']
        db.update_delivery_days(method_code, min_days, max_days)
        
        await update.message.reply_text(
            f"✅ Сроки обновлены!\n\n"
            f"{context.user_data['icon']} {context.user_data['method_name']}\n"
            f"📅 Было: {context.user_data['min_days']}-{context.user_data['max_days']} дней\n"
            f"📅 Стало: {min_days}-{max_days} дней",
            reply_markup=get_main_keyboard(True)
        )
        return ConversationHandler.END
    except (ValueError, IndexError):
        await update.message.reply_text("Пожалуйста, введите корректные сроки (например 5-10).")
        return ENTER_NEW_DAYS

async def manage_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление заказами"""
    user_id = update.effective_user.id
    if not db.is_admin(user_id):
        await update.message.reply_text("У вас нет доступа.")
        return
    
    orders = db.get_recent_orders()
    if not orders:
        await update.message.reply_text("Нет заказов для отображения.")
        return
    
    text = "📦 Последние заказы:\n\n"
    keyboard = []
    
    for o in orders:
        status_icon = "🟡" if o[2] == "В обработке" else "🟢" if o[2] == "Доставлен" else "🔴"
        text += f"{status_icon} {o[1]}\nКлиент: {o[4] or 'Неизвестен'}\nСтатус: {o[2]}\n\n"
        keyboard.append([f"{o[1]} - {o[2]}"])
    
    keyboard.append(["🔙 Назад"])
    context.user_data['recent_orders'] = orders
    
    await update.message.reply_text(
        text + "Выберите заказ для изменения статуса:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return SELECT_ORDER_STATUS

async def select_order_for_status_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор заказа для изменения статуса"""
    text = update.message.text
    
    if text == "🔙 Назад":
        await update.message.reply_text("Отменено.", reply_markup=get_main_keyboard(True))
        return ConversationHandler.END
    
    track_code = text.split(' - ')[0] if ' - ' in text else text
    orders = context.user_data.get('recent_orders', [])
    
    for o in orders:
        if o[1] == track_code:
            context.user_data['selected_order_id'] = o[0]
            context.user_data['selected_track_code'] = o[1]
            context.user_data['current_status'] = o[2]
            context.user_data['customer_code'] = o[4]
            
            keyboard = [
                ["🟡 В обработке"], ["🟢 Доставлен"], ["🔴 Отменен"],
                ["🚚 В пути"], ["📦 На складе"], ["🔙 Назад"]
            ]
            await update.message.reply_text(
                f"📦 Заказ: {o[1]}\n👤 Клиент: {o[4] or 'Неизвестен'}\n📅 Дата: {o[3]}\n📊 Текущий статус: {o[2]}\n\n"
                f"Выберите новый статус:",
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            )
            return ConversationHandler.END
    
    await update.message.reply_text("Заказ не найден.")
    return ConversationHandler.END

async def update_order_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обновление статуса заказа"""
    user_id = update.effective_user.id
    if not db.is_admin(user_id):
        return
    
    text = update.message.text
    
    if text == "🔙 Назад":
        await update.message.reply_text("Отменено.", reply_markup=get_main_keyboard(True))
        return
    
    status_map = {
        "🟡 В обработке": "В обработке",
        "🟢 Доставлен": "Доставлен",
        "🔴 Отменен": "Отменен",
        "🚚 В пути": "В пути",
        "📦 На складе": "На складе"
    }
    
    new_status = status_map.get(text)
    if not new_status:
        return
    
    order_id = context.user_data.get('selected_order_id')
    if order_id:
        db.update_track_code_status(order_id, new_status)
        await update.message.reply_text(
            f"✅ Статус обновлен!\n\n📦 Заказ: {context.user_data['selected_track_code']}\n📈 Новый статус: {new_status}",
            reply_markup=get_main_keyboard(True)
        )

async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Рассылка сообщений"""
    user_id = update.effective_user.id
    if not db.is_admin(user_id):
        await update.message.reply_text("У вас нет доступа.")
        return
    
    keyboard = [
        ["📢 Всем пользователям"],
        ["👥 Только клиентам с заказами"],
        ["👑 Только администраторам"],
        ["🔙 Назад"]
    ]
    await update.message.reply_text(
        "📢 Рассылка сообщений\n\nВыберите аудиторию:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return BROADCAST_MESSAGE

async def select_broadcast_audience(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор аудитории рассылки"""
    text = update.message.text
    
    if text == "🔙 Назад":
        await update.message.reply_text("Отменено.", reply_markup=get_main_keyboard(True))
        return ConversationHandler.END
    
    cursor = db.conn.cursor()
    
    if text == "📢 Всем пользователям":
        cursor.execute("SELECT COUNT(*) FROM users")
        count = cursor.fetchone()[0]
        context.user_data['broadcast_type'] = 'all'
        context.user_data['recipient_count'] = count
    elif text == "👥 Только клиентам с заказами":
        cursor.execute("SELECT COUNT(DISTINCT user_id) FROM track_codes")
        count = cursor.fetchone()[0]
        context.user_data['broadcast_type'] = 'with_orders'
        context.user_data['recipient_count'] = count
    elif text == "👑 Только администраторам":
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1")
        count = cursor.fetchone()[0]
        context.user_data['broadcast_type'] = 'admins'
        context.user_data['recipient_count'] = count
    else:
        return ConversationHandler.END
    
    await update.message.reply_text(
        f"Выбрана аудитория: {text}\nПолучателей: {context.user_data['recipient_count']}\n\nВведите сообщение для рассылки:"
    )
    return BROADCAST_MESSAGE

async def send_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправка рассылки"""
    msg = update.message.text
    
    if msg == "🔙 Назад":
        await update.message.reply_text("Отменено.", reply_markup=get_main_keyboard(True))
        return ConversationHandler.END
    
    broadcast_type = context.user_data.get('broadcast_type')
    cursor = db.conn.cursor()
    
    if broadcast_type == 'all':
        cursor.execute("SELECT user_id FROM users")
    elif broadcast_type == 'with_orders':
        cursor.execute("SELECT DISTINCT user_id FROM track_codes")
    elif broadcast_type == 'admins':
        cursor.execute("SELECT user_id FROM users WHERE is_admin = 1")
    else:
        await update.message.reply_text("Тип рассылки не выбран.")
        return ConversationHandler.END
    
    recipients = cursor.fetchall()
    sent = 0
    failed = 0
    
    for r in recipients:
        try:
            await context.bot.send_message(
                chat_id=r[0],
                text=f"📢 Сообщение от Golden Dragon:\n\n{msg}"
            )
            sent += 1
        except:
            failed += 1
    
    await update.message.reply_text(
        f"📊 Результаты рассылки:\n\n✅ Успешно: {sent}\n❌ Не удалось: {failed}",
        reply_markup=get_main_keyboard(True)
    )
    return ConversationHandler.END

async def fix_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Назначить администратором (отладка)"""
    user = update.effective_user
    code = db.register_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        phone_number="debug",
        is_admin=True
    )
    await update.message.reply_text(
        f"✅ Вы назначены администратором!\n📋 Код: {code}",
        reply_markup=get_main_keyboard(True)
    )

async def check_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка базы данных"""
    cursor = db.conn.cursor()
    tables = ['users', 'exchange_rates', 'delivery_methods', 'track_codes']
    res = []
    
    for t in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {t}")
            cnt = cursor.fetchone()[0]
            res.append(f"✅ {t}: {cnt} записей")
        except:
            res.append(f"❌ {t}: ошибка")
    
    await update.message.reply_text("📊 Проверка БД:\n\n" + "\n".join(res))

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена действия"""
    user_id = update.effective_user.id
    is_admin = db.is_admin(user_id)
    await update.message.reply_text("❌ Отменено.", reply_markup=get_main_keyboard(is_admin))
    return ConversationHandler.END

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    text = update.message.text.strip()
    user_id = update.effective_user.id
    is_admin = db.is_admin(user_id)

    if text == "👤 Личный кабинет":
        await personal_cabinet(update, context)
    elif text == "💰 Курсы валют":
        await exchange_rates_menu(update, context)
    elif text == "💱 Обмен валют":
        pass  # Обрабатывается ConversationHandler
    elif text == "🚚 Доставка":
        await delivery_menu(update, context)
    elif text == "🏭 Склады в Китае":
        await warehouses_menu(update, context)
    elif text.startswith("🏭 Склад"):
        await handle_warehouse_selection(update, context)
    elif text == "🔎 Поиск по трек-коду":
        await search_track_code(update, context)
    elif text == "🆘 Поддержка":
        await support(update, context)
    elif text == "⚙️ Админ-панель" and is_admin:
        await admin_panel(update, context)
    elif text == "📊 Статистика" and is_admin:
        stats = db.get_statistics()
        await update.message.reply_text(
            f"📊 Статистика:\n\n👥 Пользователей: {stats['total_users']}\n"
            f"👑 Админов: {stats['admin_users']}\n📦 Трек-кодов: {stats['total_track_codes']}\n"
            f"✅ Доставлено: {stats['delivered_track_codes']}"
        )
    elif text == "💱 Изменить курс валют" and is_admin:
        await change_exchange_rate(update, context)
    elif text == "🚚 Изменить цены доставки" and is_admin:
        await change_delivery_price(update, context)
    elif text == "📦 Управление заказами" and is_admin:
        await manage_orders(update, context)
    elif text == "📢 Сделать рассылку" and is_admin:
        await broadcast_message(update, context)
    elif text == "👥 Пользователи" and is_admin:
        users = db.get_all_users(include_admins=True)
        admins = sum(1 for u in users if u[7] == 1)
        await update.message.reply_text(
            f"👥 Пользователи:\n\nВсего: {len(users)}\nАдминов: {admins}\nОбычных: {len(users)-admins}"
        )
    elif any(icon in text for icon in ["🚚", "✈️", "🚆"]):
        await handle_delivery_method(update, context)
    elif " - " in text and is_admin:
        await select_order_for_status_change(update, context)
    elif text in ["🟡 В обработке", "🟢 Доставлен", "🔴 Отменен", "🚚 В пути", "📦 На складе"] and is_admin:
        await update_order_status(update, context)
    elif text == "🔙 Назад":
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard(is_admin))
    elif text and len(text) > 8 and any(c.isdigit() for c in text) and any(c.isalpha() for c in text):
        success = db.add_track_code(user_id, text)
        if success:
            await update.message.reply_text(f"📦 Трек-код добавлен: {text}")
        else:
            await update.message.reply_text(f"❌ Трек-код {text} уже существует.")
    else:
        await update.message.reply_text(
            "Используйте кнопки меню для навигации.",
            reply_markup=get_main_keyboard(is_admin)
        )

# ------------------------- РЕГИСТРАЦИЯ ВСЕХ ОБРАБОТЧИКОВ -------------------------
def register_handlers(application: Application):
    """Регистрирует все обработчики в приложении бота"""
    
    # ConversationHandler для регистрации
    conv_registration = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={PHONE: [MessageHandler(filters.CONTACT, handle_contact)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # ConversationHandler для регистрации админа
    conv_admin_reg = ConversationHandler(
        entry_points=[CommandHandler('admin', admin_register)],
        states={ADMIN_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_code)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # ConversationHandler для трек-кода
    conv_track = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^🔎 Поиск по трек-коду$'), search_track_code)],
        states={TRACK_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_track_code)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # ConversationHandler для обмена валют
    conv_exchange = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^💱 Обмен валют$'), exchange_currency_start)],
        states={
            EXCHANGE_SELECT_FROM: [MessageHandler(filters.TEXT & ~filters.COMMAND, exchange_select_from)],
            EXCHANGE_SELECT_TO: [MessageHandler(filters.TEXT & ~filters.COMMAND, exchange_select_to)],
            EXCHANGE_ENTER_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, exchange_enter_amount)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # ConversationHandler для изменения курса
    conv_change_rate = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^💱 Изменить курс валют$'), change_exchange_rate)],
        states={
            SELECT_CURRENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_currency_for_change)],
            ENTER_NEW_RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_new_rate)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # ConversationHandler для изменения доставки
    conv_change_delivery = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^🚚 Изменить цены доставки$'), change_delivery_price)],
        states={
            SELECT_DELIVERY_METHOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_delivery_for_change)],
            ENTER_NEW_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_new_delivery_price)],
            ENTER_NEW_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_new_delivery_days)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # ConversationHandler для управления заказами
    conv_manage_orders = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^📦 Управление заказами$'), manage_orders)],
        states={SELECT_ORDER_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_order_for_status_change)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # ConversationHandler для рассылки
    conv_broadcast = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^📢 Сделать рассылку$'), broadcast_message)],
        states={
            BROADCAST_MESSAGE: [
                MessageHandler(filters.Regex('^(📢 Всем пользователям|👥 Только клиентам с заказами|👑 Только администраторам)$'), select_broadcast_audience),
                MessageHandler(filters.TEXT & ~filters.COMMAND, send_broadcast_message),
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Добавляем все обработчики
    application.add_handler(CommandHandler('fixadmin', fix_admin))
    application.add_handler(CommandHandler('checkdb', check_db))
    application.add_handler(conv_registration)
    application.add_handler(conv_admin_reg)
    application.add_handler(conv_track)
    application.add_handler(conv_exchange)
    application.add_handler(conv_change_rate)
    application.add_handler(conv_change_delivery)
    application.add_handler(conv_manage_orders)
    application.add_handler(conv_broadcast)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("✅ Все обработчики бота зарегистрированы")

# ------------------------- API ЭНДПОИНТЫ ДЛЯ МИНИ-ПРИЛОЖЕНИЯ -------------------------

@app.get("/api/user/{telegram_id}")
async def api_get_user(telegram_id: int):
    """Возвращает данные пользователя для мини-приложения"""
    user = db.get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    orders = db.get_user_track_codes(telegram_id)
    
    return {
        "customer_code": user["customer_code"],
        "balance": user["balance"],
        "orders_count": len(orders),
        "delivered_count": sum(1 for o in orders if o[2] == "Доставлен"),
        "first_name": user["first_name"],
        "phone_number": user["phone_number"]
    }

@app.get("/api/orders/{telegram_id}")
async def api_get_orders(telegram_id: int):
    """Возвращает заказы пользователя"""
    orders = db.get_user_track_codes(telegram_id)
    
    result = []
    for o in orders:
        result.append({
            "track_code": o[0],
            "description": o[1],
            "status": o[2],
            "date": str(o[3]) if o[3] else ""
        })
    
    return {"orders": result}

@app.get("/api/exchange_rates")
async def api_get_exchange_rates():
    """Возвращает все курсы валют"""
    rates = db.get_exchange_rates()
    
    result = []
    for r in rates:
        result.append({
            "code": r[0],
            "rate": r[1],
            "flag": r[2],
            "name": r[3]
        })
    
    return {"rates": result}

@app.get("/api/track/{track_code}")
async def api_track_order(track_code: str):
    """Поиск трек-кода"""
    cursor = db.conn.cursor()
    cursor.execute("""
        SELECT track_code, status, description, created_date, u.customer_code
        FROM track_codes tc
        LEFT JOIN users u ON tc.user_id = u.user_id
        WHERE track_code = ?
    """, (track_code.upper(),))
    row = cursor.fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Track code not found")
    
    return {
        "track_code": row[0],
        "status": row[1],
        "description": row[2],
        "date": str(row[3]) if row[3] else "",
        "customer_code": row[4]
    }

@app.get("/health")
async def health():
    """Проверка здоровья сервиса"""
    return {"status": "ok", "service": "Golden Dragon Bot + API"}

@app.get("/")
async def root():
    """Корневой эндпоинт"""
    return {
        "message": "Golden Dragon Bot API",
        "endpoints": [
            "/health",
            "/api/user/{telegram_id}",
            "/api/orders/{telegram_id}",
            "/api/exchange_rates",
            "/api/track/{track_code}"
        ]
    }

# ------------------------- ЗАПУСК -------------------------
def main():
    """Запуск FastAPI сервера"""
    port = int(os.getenv("PORT", 8000))
    logger.info(f"🚀 Запуск FastAPI на порту {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
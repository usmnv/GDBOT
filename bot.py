import logging
import os
import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, LabeledPrice
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, filters, ContextTypes, CallbackQueryHandler,
    PreCheckoutQueryHandler
)

# Импортируем конфигурацию и базу данных
from config import BOT_TOKEN, ADMIN_ACCESS_CODE, YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, PROVIDER_TOKEN, WEBHOOK_URL
from database import db

# Импортируем ЮKassa клиент
from yookassa import YooKassaClient

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ------------------------- Состояния ConversationHandler -------------------------
PHONE, ADMIN_CODE = range(2)
SELECT_CURRENCY, ENTER_NEW_RATE = range(2, 4)
SELECT_DELIVERY_METHOD, ENTER_NEW_PRICE, ENTER_NEW_DAYS = range(4, 7)
SELECT_ORDER_STATUS, BROADCAST_MESSAGE = range(7, 9)
EXCHANGE_SELECT_FROM, EXCHANGE_SELECT_TO, EXCHANGE_ENTER_AMOUNT = range(9, 12)
PAYMENT_AMOUNT = 12

# ------------------------- Глобальные переменные -------------------------
telegram_app = None
yookassa = YooKassaClient(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)

# ------------------------- ОБРАБОТЧИК ОШИБОК -------------------------
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling an update:", exc_info=context.error)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация и завершение работы бота"""
    global telegram_app
    
    telegram_app = Application.builder().token(BOT_TOKEN).build()
    telegram_app.add_error_handler(error_handler)
    register_handlers(telegram_app)
    await telegram_app.bot.delete_webhook(drop_pending_updates=True)
    await telegram_app.initialize()
    await telegram_app.start()
    asyncio.create_task(telegram_app.updater.start_polling())
    
    logger.info("✅ Telegram бот запущен и получает обновления")
    
    yield
    
    await telegram_app.updater.stop()
    await telegram_app.stop()
    await telegram_app.shutdown()
    logger.info("🛑 Telegram бот остановлен")

# ------------------------- FastAPI приложение -------------------------
app = FastAPI(lifespan=lifespan, title="Golden Dragon Bot + API")
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
        ["📦 Фулфилмент"],
        ["💰 Курсы валют", "💱 Обмен валют"],
        ["🚚 Доставка", "📄 Белая доставка"],
        ["🏭 Склады в Китае"],
        ["💳 Пополнить баланс", "📊 История платежей"],
        ["🆘 Поддержка"]
    ]
    if is_admin:
        keyboard.append(["⚙️ Админ-панель"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_delivery_keyboard():
    """Клавиатура выбора доставки"""
    keyboard = [
        ["🚚 Авто карго"],
        ["✈️ Авиа доставка"],
        ["🚆 Ж/Д доставка"],
        ["🔙 Назад"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ------------------------- ОСНОВНЫЕ ОБРАБОТЧИКИ -------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /start"""
    user = update.effective_user
    user_data = db.get_user(user.id)
    
    # Проверяем, не пришли ли мы с оплаты
    if context.args and context.args[0].startswith('pay_'):
        try:
            amount = float(context.args[0].replace('pay_', ''))
            context.user_data['payment_amount'] = amount
            await pay_menu(update, context)
            return
        except:
            pass
    
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

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр баланса"""
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    if not user_data:
        await update.message.reply_text("Сначала зарегистрируйтесь через /start")
        return
    await update.message.reply_text(f"💳 Ваш баланс: {user_data['balance']} руб")

# ------------------------- ЮKassa ПЛАТЕЖИ -------------------------

async def pay_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню выбора суммы для пополнения"""
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data:
        await update.message.reply_text("Сначала зарегистрируйтесь через /start")
        return ConversationHandler.END
    
    # Проверяем наличие provider_token
    if not PROVIDER_TOKEN:
        await update.message.reply_text(
            "❌ Платежная система временно недоступна. Пожалуйста, обратитесь к поддержке."
        )
        return ConversationHandler.END
    
    keyboard = [
        ["100 ₽", "500 ₽", "1000 ₽"],
        ["5000 ₽", "10000 ₽", "Другая сумма"],
        ["🔙 Назад"]
    ]
    
    await update.message.reply_text(
        "💰 Пополнение баланса через ЮKassa\n\n"
        "Выберите сумму пополнения или введите свою:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return PAYMENT_AMOUNT

async def handle_payment_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбранной суммы"""
    text = update.message.text.replace(" ₽", "").strip()
    
    if text == "🔙 Назад":
        user_id = update.effective_user.id
        is_admin = db.is_admin(user_id)
        await update.message.reply_text("Отменено", reply_markup=get_main_keyboard(is_admin))
        return ConversationHandler.END
    
    if text == "Другая сумма":
        await update.message.reply_text(
            "Введите сумму пополнения в рублях (от 10 до 100000):",
            reply_markup=ReplyKeyboardMarkup([["🔙 Назад"]], resize_keyboard=True)
        )
        return PAYMENT_AMOUNT
    
    try:
        amount = float(text.replace(',', '.'))
        if amount < 10:
            await update.message.reply_text("Минимальная сумма пополнения - 10 рублей. Введите сумму еще раз:")
            return PAYMENT_AMOUNT
        if amount > 100000:
            await update.message.reply_text("Максимальная сумма пополнения - 100000 рублей. Введите сумму еще раз:")
            return PAYMENT_AMOUNT
        
        # Создаем инвойс через Telegram Payments API
        await send_payment_invoice(update, context, amount)
        
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число")
        return PAYMENT_AMOUNT
    
    return ConversationHandler.END

async def send_payment_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: float):
    """Отправка инвойса пользователю"""
    user_id = update.effective_user.id
    
    # Создаем уникальный payload для идентификации платежа
    payload = f"payment_{user_id}_{int(datetime.now().timestamp())}"
    
    # Подготавливаем данные для чека (54-ФЗ)
    provider_data = json.dumps({
        "receipt": {
            "items": [
                {
                    "description": "Пополнение баланса Golden Dragon",
                    "quantity": "1.00",
                    "amount": {
                        "value": f"{amount:.2f}",
                        "currency": "RUB"
                    },
                    "vat_code": 1
                }
            ]
        }
    })
    
    # Цена в копейках (минимальные единицы валюты)
    price_in_kopecks = int(amount * 100)
    
    prices = [LabeledPrice(label="Пополнение баланса", amount=price_in_kopecks)]
    
    try:
        # Отправляем инвойс
        await context.bot.send_invoice(
            chat_id=user_id,
            title="Пополнение баланса Golden Dragon",
            description=f"Пополнение баланса на {amount} рублей",
            payload=payload,
            provider_token=PROVIDER_TOKEN,
            currency="RUB",
            prices=prices,
            start_parameter="balance_replenishment",
            provider_data=provider_data,
            need_phone_number=True,
            send_phone_number_to_provider=True
        )
        
        # Сохраняем информацию о платеже в БД
        db.create_payment_record(
            payment_id=payload,
            user_id=user_id,
            amount=amount,
            status='pending'
        )
        
    except Exception as e:
        logger.error(f"Ошибка при отправке инвойса: {e}")
        await update.message.reply_text("❌ Произошла ошибка при создании платежа")

async def pre_checkout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка pre-checkout запроса"""
    query = update.pre_checkout_query
    
    # Всегда отвечаем Ok, так как мы проверили все заранее
    await query.answer(ok=True)
    logger.info(f"Pre-checkout запрос одобрен: {query.id}")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка успешного платежа"""
    payment = update.message.successful_payment
    user_id = update.effective_user.id
    
    # Получаем сумму в рублях из копеек
    amount_rub = payment.total_amount // 100
    
    # Обновляем статус платежа в БД
    db.update_payment_status(payment.invoice_payload, 'succeeded')
    
    # Пополняем баланс пользователя
    db.update_balance(user_id, amount_rub)
    
    # Получаем обновленный баланс
    user = db.get_user(user_id)
    
    await update.message.reply_text(
        f"✅ Оплата прошла успешно!\n\n"
        f"💰 Сумма: {amount_rub} руб.\n"
        f"💳 Новый баланс: {user['balance']} руб.\n\n"
        f"Спасибо за использование Golden Dragon!"
    )
    
    logger.info(f"Успешный платеж от пользователя {user_id}: {amount_rub} руб.")

async def payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на inline кнопки для проверки оплаты"""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith('check_payment_'):
        payment_id = query.data.replace('check_payment_', '')
        
        # Получаем информацию о платеже из ЮKassa
        payment_info = yookassa.get_payment(payment_id)
        
        if payment_info:
            status = payment_info.get('status')
            
            if status == 'succeeded':
                # Обновляем статус в БД
                user_id = db.update_payment_status(payment_id, 'succeeded')
                
                if user_id:
                    # Получаем сумму из метаданных или из ответа
                    amount = float(payment_info['amount']['value'])
                    
                    # Пополняем баланс пользователя
                    db.update_balance(user_id, amount)
                    
                    # Получаем обновленные данные пользователя
                    user = db.get_user(user_id)
                    
                    await query.edit_message_text(
                        f"✅ Оплата прошла успешно!\n\n"
                        f"💰 Сумма: {amount} руб.\n"
                        f"💳 Новый баланс: {user['balance']} руб.\n\n"
                        f"Спасибо за использование Golden Dragon!"
                    )
                else:
                    await query.edit_message_text(
                        "❌ Не удалось обновить статус платежа. Обратитесь в поддержку."
                    )
            elif status == 'pending':
                await query.edit_message_text(
                    "⏳ Платеж еще обрабатывается. Обычно это занимает несколько минут.\n\n"
                    "Попробуйте проверить позже или нажмите кнопку оплаты, если еще не оплатили."
                )
            else:
                await query.edit_message_text(
                    f"❌ Статус платежа: {status}\n\n"
                    f"Если вы оплатили, но статус не обновился, свяжитесь с поддержкой."
                )
        else:
            await query.edit_message_text("❌ Не удалось получить информацию о платеже.")

async def payment_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает историю платежей пользователя"""
    user_id = update.effective_user.id
    payments = db.get_user_payments(user_id)
    
    if not payments:
        await update.message.reply_text("📊 У вас пока нет истории платежей.")
        return
    
    text = "📊 История пополнений:\n\n"
    for p in payments[:10]:
        status_icon = "✅" if p['status'] == 'succeeded' else "⏳" if p['status'] == 'pending' else "❌"
        date_str = p['created_at'].strftime("%d.%m.%Y %H:%M") if p['created_at'] else ""
        text += f"{status_icon} {p['amount']} руб. - {date_str}\n"
    
    await update.message.reply_text(text)

# ------------------------- ДОСТАВКА -------------------------

async def delivery_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню выбора доставки"""
    await update.message.reply_text(
        "🚚 Выберите вид доставки:",
        reply_markup=get_delivery_keyboard()
    )

async def delivery_avia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация об авиа доставке"""
    text = (
        "✈️ Авиа доставка\n\n"
        "✅ Срок доставки: 3-7 дней\n"
        "✅ Отслеживание по трек-номеру\n"
        "✅ Страховка включена\n"
        "✅ Отправка от 1 кг\n\n"
        "💰 Стоимость: от 10$/кг\n\n"
        "👤 Менеджер: @avia_manager\n"
        "📱 WhatsApp: +7 999 123 45 67\n\n"
        "⏰ Время работы: 9:00 - 18:00 (МСК)"
    )
    await update.message.reply_text(text)

async def delivery_cargo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация об авто карго доставке"""
    text = (
        "🚚 Авто карго\n\n"
        "✅ Срок доставки: 14-21 день\n"
        "✅ Экономичный вариант\n"
        "✅ Подходит для крупных партий\n"
        "✅ Доставка 'от двери до двери'\n\n"
        "💰 Стоимость: от 5$/кг\n\n"
        "👤 Менеджер: @auto_manager\n"
        "📱 WhatsApp: +7 999 234 56 78\n\n"
        "⏰ Время работы: 9:00 - 18:00 (МСК)"
    )
    await update.message.reply_text(text)

async def delivery_rail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о Ж/Д доставке"""
    text = (
        "🚆 Ж/Д доставка\n\n"
        "✅ Срок доставки: 10-15 дней\n"
        "✅ Фиксированная стоимость\n"
        "✅ Для больших объёмов\n"
        "✅ Стабильные сроки\n\n"
        "💰 Стоимость: от 7$/кг\n\n"
        "👤 Менеджер: @rail_manager\n"
        "📱 WhatsApp: +7 999 345 67 89\n\n"
        "⏰ Время работы: 9:00 - 18:00 (МСК)"
    )
    await update.message.reply_text(text)

async def delivery_white(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о белой доставке"""
    text = (
        "📄 Белая доставка (с таможенным оформлением)\n\n"
        "✅ Полное таможенное оформление груза\n"
        "✅ Все необходимые документы предоставляются\n"
        "✅ Работа с юридическими лицами\n"
        "✅ НДС и пошлины включены в стоимость\n"
        "✅ Сертификация и декларирование товаров\n\n"
        "💰 Стоимость: от 15$/кг\n\n"
        "📋 Что входит:\n"
        "• Подготовка таможенной декларации\n"
        "• Расчёт таможенных платежей\n"
        "• Сопровождение на таможне\n"
        "• Доставка под ключ\n\n"
        "👤 Менеджер: @white_delivery_manager\n"
        "📱 WhatsApp: +7 999 456 78 90\n\n"
        "⏰ Время работы: 9:00 - 18:00 (МСК)"
    )
    await update.message.reply_text(text)

async def warehouses_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню складов в Китае"""
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
    """Информация о выбранном складе"""
    text = update.message.text
    
    if text == "🔙 Назад":
        user_id = update.effective_user.id
        is_admin = db.is_admin(user_id)
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard(is_admin))
        return
    
    warehouses = {
        "🏭 Склад Иу": {
            "address": "浙江省义乌市国际商贸城, 义乌, 322000, Китай",
            "conditions": "✅ Минимальный вес: 5 кг\n✅ Приёмка: 0.5$/кг\n✅ Хранение: 3 дня бесплатно",
            "contact": "📞 Менеджер: +86 123 4567 8901\n⏰ Время работы: 9:00 - 18:00 (МСК)"
        },
        "🏭 Склад Гуанчжоу": {
            "address": "广州市白云区机场路, 广州, 510000, Китай",
            "conditions": "✅ Минимальный вес: 10 кг\n✅ Приёмка: 0.3$/кг\n✅ Хранение: 5 дней бесплатно",
            "contact": "📞 Менеджер: +86 123 4567 8902\n⏰ Время работы: 9:00 - 18:00 (МСК)"
        },
        "🏭 Склад Урумчи": {
            "address": "新疆乌鲁木齐市经济开发区, 乌鲁木齐, 830000, Китай",
            "conditions": "✅ Минимальный вес: 3 кг\n✅ Приёмка: 0.4$/кг\n✅ Хранение: 7 дней бесплатно",
            "contact": "📞 Менеджер: +86 123 4567 8903\n⏰ Время работы: 9:00 - 18:00 (МСК)"
        }
    }
    
    info = warehouses.get(text)
    if info:
        await update.message.reply_text(
            f"{text}\n\n📍 Адрес: {info['address']}\n📦 Условия: {info['conditions']}\n{info['contact']}"
        )
    else:
        await update.message.reply_text("Склад не найден.")

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поддержка с контактами менеджеров"""
    text = (
        "🆘 Поддержка\n\n"
        "👤 Основной менеджер: @goldendragon_manager\n"
        "📱 WhatsApp: +7 999 123 45 67\n\n"
        "👤 Менеджер по доставке: @delivery_manager\n"
        "📱 WhatsApp: +7 999 234 56 78\n\n"
        "👤 Менеджер по фулфилменту: @fulfillment_support\n"
        "📱 WhatsApp: +7 999 345 67 89\n\n"
        "👤 Менеджер по белой доставке: @white_delivery_manager\n"
        "📱 WhatsApp: +7 999 456 78 90\n\n"
        "⏰ Время работы: 9:00 - 18:00 (МСК)"
    )
    await update.message.reply_text(text)

async def fullfilment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о фулфилменте"""
    text = (
        "📦 Фулфилмент\n\n"
        "Мы берём на себя всё: приём, хранение, упаковку и отправку ваших заказов.\n"
        "✅ Бесплатное хранение до 7 дней\n"
        "✅ Фото‑ и видеоотчёт\n"
        "✅ Интеграция с вашими магазинами\n\n"
        "👤 Менеджер: @fulfilment_manager\n"
        "📱 WhatsApp: +7 999 111 22 33\n\n"
        "⏰ Время работы: 9:00 - 18:00 (МСК)"
    )
    await update.message.reply_text(text)

async def exchange_rates_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ курсов валют"""
    rates = db.get_exchange_rates()
    if not rates:
        await update.message.reply_text("Курсы валют временно недоступны.")
        return
    
    text = "💱 Текущие курсы валют:\n\n"
    for rate in rates:
        text += f"{rate['flag']} {rate['name']}: {rate['rate']} RUB\n"
    await update.message.reply_text(text)

# --- ОБМЕН ВАЛЮТ ---

async def exchange_currency_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not db.get_user(user_id):
        await update.message.reply_text("Пожалуйста, сначала зарегистрируйтесь через /start")
        return ConversationHandler.END

    rates = db.get_exchange_rates()
    if not rates:
        await update.message.reply_text("Курсы валют временно недоступны.")
        return ConversationHandler.END

    context.user_data['exchange_rates'] = rates

    all_currencies = [f"{r['flag']} {r['name']}" for r in rates] + ["🇷🇺 RUB (Российский рубль)"]
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
    text = update.message.text.strip()
    
    if text == "🔙 Назад":
        user_id = update.effective_user.id
        is_admin = db.is_admin(user_id)
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard(is_admin))
        return ConversationHandler.END

    rates = context.user_data['exchange_rates']
    selected_from = None

    for r in rates:
        if f"{r['flag']} {r['name']}" in text:
            selected_from = ('currency', r['currency_code'], r['rate'], r['flag'], r['name'])
            break
    if "🇷🇺 RUB" in text:
        selected_from = ('rub', 'RUB', 1.0, '🇷🇺', 'Российский рубль')

    if not selected_from:
        await update.message.reply_text("Валюта не найдена. Попробуйте снова.")
        return EXCHANGE_SELECT_FROM

    context.user_data['exchange_from'] = selected_from

    all_currencies = []
    for r in rates:
        if r['currency_code'] != selected_from[1]:
            all_currencies.append(f"{r['flag']} {r['name']}")
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
    text = update.message.text.strip()
    
    if text == "🔙 Назад":
        return await exchange_currency_start(update, context)

    rates = context.user_data['exchange_rates']
    from_data = context.user_data['exchange_from']
    selected_to = None

    for r in rates:
        if f"{r['flag']} {r['name']}" in text and r['currency_code'] != from_data[1]:
            selected_to = ('currency', r['currency_code'], r['rate'], r['flag'], r['name'])
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
            rate_from_rub = next((r['rate'] for r in rates if r['currency_code'] == from_data[1]), None)
            if rate_from_rub is None:
                await update.message.reply_text("Курс исходной валюты не найден.")
                return ConversationHandler.END

        if to_data[0] == 'rub':
            rate_to_rub = 1.0
        else:
            rate_to_rub = next((r['rate'] for r in rates if r['currency_code'] == to_data[1]), None)
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
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard(is_admin))
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число (например 100.50).")
        return EXCHANGE_ENTER_AMOUNT

# --- АДМИН-ФУНКЦИИ ---

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        ["💳 Платежи (админ)"],
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
    """Обработка кода администратора"""
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
    """Изменение курса валют"""
    user_id = update.effective_user.id
    if not db.is_admin(user_id):
        await update.message.reply_text("У вас нет доступа.")
        return ConversationHandler.END
    
    rates = db.get_exchange_rates()
    keyboard = [[f"{r['flag']} {r['name']} (текущий: {r['rate']} RUB)"] for r in rates] + [["🔙 Назад"]]
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
        user_id = update.effective_user.id
        is_admin = db.is_admin(user_id)
        await update.message.reply_text("Отменено.", reply_markup=get_main_keyboard(is_admin))
        return ConversationHandler.END
    
    for r in context.user_data.get('rates', []):
        if f"{r['flag']} {r['name']}" in text:
            context.user_data['selected_currency'] = r['currency_code']
            context.user_data['currency_name'] = r['name']
            context.user_data['flag'] = r['flag']
            context.user_data['current_rate'] = r['rate']
            await update.message.reply_text(
                f"Выбрана валюта: {r['flag']} {r['name']}\nТекущий курс: {r['rate']} RUB\n\nВведите новый курс:"
            )
            return ENTER_NEW_RATE
    
    await update.message.reply_text("Валюта не найдена.")
    return ConversationHandler.END

async def enter_new_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ввод нового курса"""
    text = update.message.text.strip()
    if text == "🔙 Назад":
        user_id = update.effective_user.id
        is_admin = db.is_admin(user_id)
        await update.message.reply_text("Отменено.", reply_markup=get_main_keyboard(is_admin))
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
        return ConversationHandler.END
    
    methods = db.get_delivery_methods()
    keyboard = [[f"{m['icon']} {m['method_name']} (${m['price_per_kg']}/кг)"] for m in methods] + [["🔙 Назад"]]
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
        user_id = update.effective_user.id
        is_admin = db.is_admin(user_id)
        await update.message.reply_text("Отменено.", reply_markup=get_main_keyboard(is_admin))
        return ConversationHandler.END
    
    for m in context.user_data.get('delivery_methods', []):
        if f"{m['icon']} {m['method_name']}" in text:
            context.user_data['selected_method'] = m['method_code']
            context.user_data['method_name'] = m['method_name']
            context.user_data['current_price'] = m['price_per_kg']
            context.user_data['min_days'] = m['min_days']
            context.user_data['max_days'] = m['max_days']
            context.user_data['icon'] = m['icon']
            
            keyboard = [
                ["💰 Изменить цену за кг"],
                ["📅 Изменить сроки доставки"],
                ["🔙 Назад"]
            ]
            await update.message.reply_text(
                f"📝 Выбран способ: {m['icon']} {m['method_name']}\n\n"
                f"💰 Текущая цена: ${m['price_per_kg']}/кг\n"
                f"📅 Текущие сроки: {m['min_days']}-{m['max_days']} дней\n\n"
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
        user_id = update.effective_user.id
        is_admin = db.is_admin(user_id)
        await update.message.reply_text("Отменено.", reply_markup=get_main_keyboard(is_admin))
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
        user_id = update.effective_user.id
        is_admin = db.is_admin(user_id)
        await update.message.reply_text("Отменено.", reply_markup=get_main_keyboard(is_admin))
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
        return ConversationHandler.END
    
    orders = db.get_recent_orders()
    if not orders:
        await update.message.reply_text("Нет заказов для отображения.")
        return ConversationHandler.END
    
    text = "📦 Последние заказы:\n\n"
    keyboard = []
    for o in orders:
        status_icon = "🟡" if o['status'] == "В обработке" else "🟢" if o['status'] == "Доставлен" else "🔴"
        text += f"{status_icon} {o['track_code']}\nКлиент: {o['customer_code'] or 'Неизвестен'}\nСтатус: {o['status']}\nЦена: ${o['price'] or 0}\n\n"
        keyboard.append([f"{o['track_code']} - {o['status']}"])
    
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
        user_id = update.effective_user.id
        is_admin = db.is_admin(user_id)
        await update.message.reply_text("Отменено.", reply_markup=get_main_keyboard(is_admin))
        return ConversationHandler.END
    
    track_code = text.split(' - ')[0] if ' - ' in text else text
    orders = context.user_data.get('recent_orders', [])
    
    for o in orders:
        if o['track_code'] == track_code:
            context.user_data['selected_order_id'] = o['id']
            context.user_data['selected_track_code'] = o['track_code']
            context.user_data['current_status'] = o['status']
            context.user_data['customer_code'] = o['customer_code']
            
            keyboard = [
                ["🟡 В обработке"], ["🟢 Доставлен"], ["🔴 Отменен"],
                ["🚚 В пути"], ["📦 На складе"], ["🔙 Назад"]
            ]
            await update.message.reply_text(
                f"📦 Заказ: {o['track_code']}\n👤 Клиент: {o['customer_code'] or 'Неизвестен'}\n📅 Дата: {o['created_date']}\n💰 Цена: ${o['price'] or 0}\n📊 Текущий статус: {o['status']}\n\n"
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
        user_id = update.effective_user.id
        is_admin = db.is_admin(user_id)
        await update.message.reply_text("Отменено.", reply_markup=get_main_keyboard(is_admin))
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
        return ConversationHandler.END
    
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
    """Выбор аудитории для рассылки"""
    text = update.message.text
    if text == "🔙 Назад":
        user_id = update.effective_user.id
        is_admin = db.is_admin(user_id)
        await update.message.reply_text("Отменено.", reply_markup=get_main_keyboard(is_admin))
        return ConversationHandler.END
    
    cursor = db.conn.cursor()
    if text == "📢 Всем пользователям":
        cursor.execute("SELECT COUNT(*) as cnt FROM users")
        count = cursor.fetchone()['cnt']
        context.user_data['broadcast_type'] = 'all'
        context.user_data['recipient_count'] = count
    elif text == "👥 Только клиентам с заказами":
        cursor.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM track_codes")
        count = cursor.fetchone()['cnt']
        context.user_data['broadcast_type'] = 'with_orders'
        context.user_data['recipient_count'] = count
    elif text == "👑 Только администраторам":
        cursor.execute("SELECT COUNT(*) as cnt FROM users WHERE is_admin = TRUE")
        count = cursor.fetchone()['cnt']
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
        user_id = update.effective_user.id
        is_admin = db.is_admin(user_id)
        await update.message.reply_text("Отменено.", reply_markup=get_main_keyboard(is_admin))
        return ConversationHandler.END
    
    broadcast_type = context.user_data.get('broadcast_type')
    cursor = db.conn.cursor()
    
    if broadcast_type == 'all':
        cursor.execute("SELECT telegram_id FROM users")
    elif broadcast_type == 'with_orders':
        cursor.execute("SELECT DISTINCT u.telegram_id FROM users u JOIN track_codes t ON u.id = t.user_id")
    elif broadcast_type == 'admins':
        cursor.execute("SELECT telegram_id FROM users WHERE is_admin = TRUE")
    else:
        await update.message.reply_text("Тип рассылки не выбран.")
        return ConversationHandler.END
    
    recipients = cursor.fetchall()
    sent = 0
    failed = 0
    
    for r in recipients:
        try:
            await context.bot.send_message(
                chat_id=r['telegram_id'],
                text=f"📢 Сообщение от Golden Dragon:\n\n{msg}"
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            print(f"Ошибка отправки пользователю {r['telegram_id']}: {e}")
            failed += 1
    
    await update.message.reply_text(
        f"📊 Результаты рассылки:\n\n✅ Успешно: {sent}\n❌ Не удалось: {failed}",
        reply_markup=get_main_keyboard(True)
    )
    return ConversationHandler.END

async def admin_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр всех платежей для админа"""
    user_id = update.effective_user.id
    if not db.is_admin(user_id):
        return
    
    cursor = db.conn.cursor()
    cursor.execute("""
        SELECT p.*, u.customer_code, u.telegram_id 
        FROM payments p
        JOIN users u ON p.user_id = u.id
        ORDER BY p.created_at DESC
        LIMIT 20
    """)
    payments = cursor.fetchall()
    
    if not payments:
        await update.message.reply_text("Платежей пока нет.")
        return
    
    text = "💳 Последние платежи:\n\n"
    for p in payments:
        status_icon = "✅" if p['status'] == 'succeeded' else "⏳" if p['status'] == 'pending' else "❌"
        date_str = p['created_at'].strftime("%d.%m.%Y %H:%M") if p['created_at'] else ""
        text += f"{status_icon} {p['amount']} руб. - {p['customer_code']} - {date_str}\n"
    
    await update.message.reply_text(text)

async def fix_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрое назначение администратором (для разработки)"""
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
    """Проверка состояния базы данных"""
    cursor = db.conn.cursor()
    tables = ['users', 'exchange_rates', 'delivery_methods', 'track_codes', 'payments']
    res = []
    for t in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) as cnt FROM {t}")
            cnt = cursor.fetchone()['cnt']
            res.append(f"✅ {t}: {cnt} записей")
        except Exception as e:
            res.append(f"❌ {t}: ошибка - {str(e)}")
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
    elif text == "📦 Фулфилмент":
        await fullfilment(update, context)
    elif text == "💰 Курсы валют":
        await exchange_rates_menu(update, context)
    elif text == "💱 Обмен валют":
        pass
    elif text == "🚚 Доставка":
        await delivery_menu(update, context)
    elif text == "🚚 Авто карго":
        await delivery_cargo(update, context)
    elif text == "✈️ Авиа доставка":
        await delivery_avia(update, context)
    elif text == "🚆 Ж/Д доставка":
        await delivery_rail(update, context)
    elif text == "📄 Белая доставка":
        await delivery_white(update, context)
    elif text == "🏭 Склады в Китае":
        await warehouses_menu(update, context)
    elif text.startswith("🏭 Склад"):
        await handle_warehouse_selection(update, context)
    elif text == "💳 Пополнить баланс":
        await pay_menu(update, context)
    elif text == "📊 История платежей":
        await payment_history(update, context)
    elif text == "🆘 Поддержка":
        await support(update, context)
    elif text == "⚙️ Админ-панель" and is_admin:
        await admin_panel(update, context)
    elif text == "💳 Платежи (админ)" and is_admin:
        await admin_payments(update, context)
    elif text == "📊 Статистика" and is_admin:
        stats = db.get_statistics()
        await update.message.reply_text(
            f"📊 Статистика:\n\n👥 Пользователей: {stats['total_users']}\n"
            f"👑 Админов: {stats['admin_users']}\n📦 Трек-кодов: {stats['total_track_codes']}\n"
            f"✅ Доставлено: {stats['delivered_track_codes']}"
        )
    elif text == "💱 Изменить курс валют" and is_admin:
        pass
    elif text == "🚚 Изменить цены доставки" and is_admin:
        pass
    elif text == "📦 Управление заказами" and is_admin:
        pass
    elif text == "📢 Сделать рассылку" and is_admin:
        pass
    elif text == "👥 Пользователи" and is_admin:
        users = db.get_all_users(include_admins=True)
        admins = sum(1 for u in users if u['is_admin'])
        await update.message.reply_text(
            f"👥 Пользователи:\n\nВсего: {len(users)}\nАдминов: {admins}\nОбычных: {len(users)-admins}"
        )
    elif text == "🔙 Назад":
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard(is_admin))
    else:
        await update.message.reply_text(
            "Используйте кнопки меню для навигации.",
            reply_markup=get_main_keyboard(is_admin)
        )

# ------------------------- РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ -------------------------
def register_handlers(application: Application):
    """Регистрирует все обработчики"""
    
    conv_registration = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={PHONE: [MessageHandler(filters.CONTACT, handle_contact)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    conv_admin_reg = ConversationHandler(
        entry_points=[CommandHandler('admin', admin_register)],
        states={ADMIN_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_code)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    conv_exchange = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^💱 Обмен валют$'), exchange_currency_start)],
        states={
            EXCHANGE_SELECT_FROM: [MessageHandler(filters.TEXT & ~filters.COMMAND, exchange_select_from)],
            EXCHANGE_SELECT_TO: [MessageHandler(filters.TEXT & ~filters.COMMAND, exchange_select_to)],
            EXCHANGE_ENTER_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, exchange_enter_amount)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    conv_change_rate = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^💱 Изменить курс валют$'), change_exchange_rate)],
        states={
            SELECT_CURRENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_currency_for_change)],
            ENTER_NEW_RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_new_rate)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    conv_change_delivery = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^🚚 Изменить цены доставки$'), change_delivery_price)],
        states={
            SELECT_DELIVERY_METHOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_delivery_for_change)],
            ENTER_NEW_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_new_delivery_price)],
            ENTER_NEW_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_new_delivery_days)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    conv_manage_orders = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^📦 Управление заказами$'), manage_orders)],
        states={SELECT_ORDER_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_order_for_status_change)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
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
    
    conv_payment = ConversationHandler(
        entry_points=[
            CommandHandler('pay', pay_menu),
            MessageHandler(filters.Regex('^💳 Пополнить баланс$'), pay_menu)
        ],
        states={
            PAYMENT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_payment_amount)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    application.add_handler(CommandHandler('balance', balance))
    application.add_handler(CommandHandler('fixadmin', fix_admin))
    application.add_handler(CommandHandler('checkdb', check_db))
    
    application.add_handler(conv_payment)
    application.add_handler(PreCheckoutQueryHandler(pre_checkout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    application.add_handler(conv_registration)
    application.add_handler(conv_admin_reg)
    application.add_handler(conv_exchange)
    application.add_handler(conv_change_rate)
    application.add_handler(conv_change_delivery)
    application.add_handler(conv_manage_orders)
    application.add_handler(conv_broadcast)
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(payment_callback, pattern='^check_payment_'))
    
    logger.info("✅ Все обработчики бота зарегистрированы")

# ------------------------- API ЭНДПОИНТЫ -------------------------

@app.get("/api/user/{telegram_id}")
async def api_get_user(telegram_id: int):
    user = db.get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    orders = db.get_user_track_codes(telegram_id)
    return {
        "customer_code": user["customer_code"],
        "balance": user["balance"],
        "orders_count": len(orders),
        "delivered_count": sum(1 for o in orders if o["status"] == "Доставлен"),
        "first_name": user["first_name"],
        "phone_number": user["phone_number"]
    }

@app.get("/api/orders/{telegram_id}")
async def api_get_orders(telegram_id: int):
    orders = db.get_user_track_codes(telegram_id)
    result = []
    for o in orders:
        result.append({
            "track_code": o["track_code"],
            "description": o["description"],
            "status": o["status"],
            "date": str(o["created_date"]) if o["created_date"] else "",
            "price": float(o["price"]) if o["price"] else 0
        })
    return {"orders": result}

@app.get("/api/exchange_rates")
async def api_get_exchange_rates():
    rates = db.get_exchange_rates()
    result = []
    for r in rates:
        result.append({
            "code": r["currency_code"],
            "rate": r["rate"],
            "flag": r["flag"],
            "name": r["name"]
        })
    return {"rates": result}

@app.get("/api/track/{track_code}")
async def api_track_order(track_code: str):
    cursor = db.conn.cursor()
    cursor.execute("""
        SELECT track_code, status, description, created_date, u.customer_code, price
        FROM track_codes tc
        LEFT JOIN users u ON tc.user_id = u.id
        WHERE track_code = %s
    """, (track_code.upper(),))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Track code not found")
    return {
        "track_code": row["track_code"],
        "status": row["status"],
        "description": row["description"],
        "date": str(row["created_date"]) if row["created_date"] else "",
        "customer_code": row["customer_code"],
        "price": float(row["price"]) if row["price"] else 0
    }

@app.post("/api/balance/update")
async def api_update_balance(request: Request):
    data = await request.json()
    telegram_id = data.get("telegram_id")
    amount = data.get("amount")
    if not telegram_id or not amount:
        raise HTTPException(status_code=400, detail="Missing telegram_id or amount")
    db.update_balance(telegram_id, amount)
    user = db.get_user(telegram_id)
    return {"new_balance": user["balance"]}

@app.get("/api/payments/{telegram_id}")
async def api_get_payments(telegram_id: int):
    payments = db.get_user_payments(telegram_id)
    result = []
    for p in payments:
        result.append({
            "amount": float(p["amount"]),
            "status": p["status"],
            "date": str(p["created_at"]) if p["created_at"] else "",
            "payment_id": p["payment_id"]
        })
    return {"payments": result}

@app.post("/api/yookassa/webhook")
async def yookassa_webhook(request: Request):
    """
    Webhook для уведомлений от ЮKassa
    """
    try:
        data = await request.json()
        
        if data.get('event') == 'payment.succeeded':
            payment = data.get('object', {})
            payment_id = payment.get('id')
            metadata = payment.get('metadata', {})
            user_id = metadata.get('telegram_id')
            amount = float(payment.get('amount', {}).get('value', 0))
            
            if user_id and payment_id:
                db.update_payment_status(payment_id, 'succeeded')
                db.update_balance(int(user_id), amount)
                
                try:
                    await telegram_app.bot.send_message(
                        chat_id=int(user_id),
                        text=f"✅ Баланс успешно пополнен!\n\n💰 Сумма: {amount} руб.\n💳 Новый баланс: {db.get_user(int(user_id))['balance']} руб."
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление пользователю {user_id}: {e}")
                
                return {"status": "ok"}
        
        return {"status": "received"}
    
    except Exception as e:
        logger.error(f"Ошибка обработки webhook от ЮKassa: {e}")
        return {"status": "error", "message": str(e)}, 500

@app.get("/health")
async def health():
    return {"status": "ok", "service": "Golden Dragon Bot + API"}

@app.get("/")
async def root():
    return {
        "message": "Golden Dragon Bot API",
        "endpoints": [
            "/health",
            "/api/user/{telegram_id}",
            "/api/orders/{telegram_id}",
            "/api/exchange_rates",
            "/api/track/{track_code}",
            "/api/balance/update (POST)",
            "/api/payments/{telegram_id}",
            "/api/yookassa/webhook (POST)"
        ]
    }

# ------------------------- ЗАПУСК -------------------------
def main():
    port = int(os.getenv("PORT", 8000))
    logger.info(f"🚀 Запуск FastAPI на порту {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()

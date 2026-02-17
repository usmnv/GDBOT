FROM python:3.11-slim

WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Проверяем переменные окружения и запускаем бота
CMD python -c "import os; assert os.getenv('BOT_TOKEN'), 'BOT_TOKEN must be set'" && python bot.py
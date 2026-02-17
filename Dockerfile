FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Просто выводим наличие переменной и запускаем бота
CMD python -c "import os; print('BOT_TOKEN exists:', bool(os.getenv('BOT_TOKEN')))" && python bot.py
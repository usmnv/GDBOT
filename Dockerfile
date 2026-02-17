FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Проверяем переменные перед запуском (более надежно)
RUN python -c "import os; assert os.getenv('BOT_TOKEN'), 'BOT_TOKEN must be set during build'"

CMD ["python", "bot.py"]
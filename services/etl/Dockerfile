FROM python:3.11-slim

# Отключаем буферизацию вывода Python (чтобы логи сразу появлялись в docker compose logs)
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY . .

CMD ["python", "scheduler.py"]

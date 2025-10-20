FROM python:3.11-slim

WORKDIR /app

# Устанавливаем uv
RUN pip install --no-cache-dir uv

# Копируем requirements.txt
COPY requirements.txt .

# Устанавливаем зависимости через uv
RUN uv pip install --system -r requirements.txt

# Копируем остальные файлы
COPY . .

# Создаем папку для логов
RUN mkdir -p /app/logs && chmod 777 /app/logs

# Создаем пользователя
RUN useradd -m -u 1000 collector
USER collector

CMD ["python", "collector.py"]
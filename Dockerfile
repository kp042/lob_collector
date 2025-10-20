FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir uv
COPY requirements.txt .
RUN uv pip install --system -r requirements.txt

COPY . .

RUN mkdir -p /app/logs && chmod 755 /app/logs
RUN useradd -m -u 1000 collector && chown -R collector:collector /app/logs
USER collector

CMD ["python", "collector.py"]
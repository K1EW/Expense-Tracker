FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    EXPENSE_DATA_DIR=/app/data

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home expense \
    && mkdir -p /app/data \
    && chown expense:expense /app/data

COPY server.py ./server.py
COPY web/ ./web/

EXPOSE 8000
USER expense

CMD ["python", "server.py"]

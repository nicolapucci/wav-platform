FROM python:3.12-slim

WORKDIR /app

COPY services/common /app/common
COPY services/ws-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -e /app/common

COPY services/ws-gateway/app /app/app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

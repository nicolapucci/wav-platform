FROM python:3.12-slim

WORKDIR /app

COPY services/common /app/common
COPY services/worker-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -e /app/common

COPY services/worker-service/app /app/app

CMD ["python", "-u", "app/main.py"]

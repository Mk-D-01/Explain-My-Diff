FROM python:3.12.4-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.lock ./
RUN python -m pip install --no-cache-dir --requirement requirements.lock
COPY app ./app
COPY tests ./tests

CMD ["python", "-m", "app"]

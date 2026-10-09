FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Migrations run once at container start (single instance) before uvicorn
# serves traffic. Render injects PORT and expects the app to bind to it;
# local runs default to 8000. If you scale to multiple instances, remove
# `alembic upgrade head` here and run migrations as a single separate step.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

FROM python:3.12-slim

# System dependencies for PDF parsing + OCR
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-ita \
    poppler-utils \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY apps/api/ ./apps/api/
COPY packages/ ./packages/

WORKDIR /app/apps/api

# Make both `app` and `packages` importable
ENV PYTHONPATH=/app/apps/api:/app

# Run migrations then start server
# PORT is injected by Railway automatically
CMD sh -c 'echo "=== ALEMBIC START ===" && alembic upgrade head && echo "=== ALEMBIC OK ===" && echo "=== UVICORN START ===" && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --log-level info'

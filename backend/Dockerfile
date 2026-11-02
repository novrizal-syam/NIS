FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Jakarta

WORKDIR /app

COPY pyproject.toml ./
# Install deps first (layer cache); the source is bind-mounted in dev.
RUN mkdir -p app && touch app/__init__.py \
    && pip install -e ".[dev]" \
    && rm -rf app

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

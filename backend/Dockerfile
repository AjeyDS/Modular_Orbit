FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/backend

COPY backend/pyproject.toml ./pyproject.toml
RUN pip install --upgrade pip && pip install -e .

COPY backend/app ./app
COPY user_model /app/user_model

EXPOSE 8000

CMD ["sh", "-c", "python -m app.db.bootstrap && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"]

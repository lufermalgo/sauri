FROM python:3.11-slim

WORKDIR /app

# Copiar pyproject.toml primero para aprovechar cache de capas Docker
COPY pyproject.toml .

# Instalar dependencias (sin dev extras en producción)
RUN pip install --no-cache-dir .

# Copiar el código fuente
COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

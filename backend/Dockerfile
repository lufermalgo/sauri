FROM python:3.11-slim

WORKDIR /app

# Copy pyproject.toml first to take advantage of Docker layer caching
COPY pyproject.toml .

# Install dependencies (without dev extras in production)
RUN pip install --no-cache-dir .

# Copy the source code
COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

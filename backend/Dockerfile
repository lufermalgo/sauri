FROM python:3.11-slim

WORKDIR /app

# Static ffmpeg/ffprobe (multi-arch, pinned by digest): the worker cuts one preview frame per recording.
COPY --from=mwader/static-ffmpeg:7.1.1@sha256:11a44711684c0b9f754c047dcd64235b8b52deab251bd0e0a86f22faa160749c \
    /ffmpeg /ffprobe /usr/local/bin/

# Copy pyproject.toml first to take advantage of Docker layer caching
COPY pyproject.toml .

# Install dependencies (without dev extras in production)
RUN pip install --no-cache-dir .

# Copy the source code
COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

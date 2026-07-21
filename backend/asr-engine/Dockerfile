FROM python:3.11-slim

WORKDIR /app

# Install system dependencies required by faster-whisper (ctranslate2)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgomp1 && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    fastapi==0.115.0 \
    uvicorn[standard]==0.30.6 \
    pydantic==2.9.2 \
    faster-whisper==1.1.0 \
    boto3==1.35.0 \
    requests==2.32.3

COPY main.py .

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]

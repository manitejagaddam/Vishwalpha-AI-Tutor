# Production Dockerfile for VishwAlpha AI Tutor Backend on Railway
FROM python:3.11-slim

# Prevent Python from writing bytecode and enable unbuffered output
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# Install essential system dependencies (OpenCV, PDF layout, Paddle/Torch, Tesseract)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency installation
COPY --from=ghcr.io/astral-sh/uv:0.6.14 /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy dependency specifications first to leverage Docker layer caching
# requirements-prod.txt is the slim runtime-only file (no PaddleOCR/torch/streamlit)
# requirements.txt is the full dev/ingestion file — NOT copied into the image
COPY requirements-prod.txt ./

# Install Python dependencies into system environment
RUN uv pip install --system --no-cache -r requirements.txt

# Copy backend application source code
COPY app/ ./app/
COPY alembic.ini ./
COPY scripts/ ./scripts/

# Create runtime directory for file uploads
RUN mkdir -p /app/uploads

# Expose default port (Railway overrides $PORT at runtime)
EXPOSE 8000

# Start Uvicorn bound to 0.0.0.0 and dynamic Railway $PORT
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]


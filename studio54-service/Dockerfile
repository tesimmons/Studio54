FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    # Build dependencies
    gcc \
    g++ \
    postgresql-client \
    curl \
    # Audio fingerprinting (fpcalc for AcoustID lookups)
    libchromaprint-tools \
    # Network utilities
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI (for worker autoscaling via docker compose)
RUN curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-27.4.1.tgz | \
    tar xz --strip-components=1 -C /usr/local/bin docker/docker

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Create data directories
RUN mkdir -p /app/covers /app/cache

# Expose API port
EXPOSE 8010

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8010/health', timeout=5.0)" || exit 1

# Run uvicorn server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "2"]

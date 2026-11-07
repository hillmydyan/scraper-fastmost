# Dockerfile for FastMoss Scraper on Ubuntu 22.04 VPS
FROM python:3.10-slim-bullseye

# Environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99

# Install system dependencies, Xvfb, x11vnc, noVNC, websockify, and supervisor
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    x11vnc \
    novnc \
    websockify \
    supervisor \
    curl \
    git \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Symlink noVNC vnc.html to index.html for convenient access
RUN ln -s /usr/share/novnc/vnc.html /usr/share/novnc/index.html || true

# Set working directory
WORKDIR /app

# Copy dependencies and install Python packages
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install Playwright browser
RUN playwright install chromium

# Copy application source code
COPY . /app/

# Setup storage directories
RUN mkdir -p /app/storage/sessions /app/storage/outputs /app/storage/logs /app/storage/uploads

# Expose Web App port (5000) and noVNC port (6080)
EXPOSE 5000 6080

# Start services via supervisor
CMD ["/usr/bin/supervisord", "-c", "/app/supervisord.conf"]


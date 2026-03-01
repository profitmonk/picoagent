FROM python:3.11-slim

# System utilities useful for shell tool
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget jq git && \
    rm -rf /var/lib/apt/lists/*

# Non-root user + persistent data directory
RUN useradd -m -s /bin/bash agent && mkdir -p /data && chown agent:agent /data
WORKDIR /home/agent/app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY picoagent/ picoagent/

# Switch to non-root
USER agent

# Default command
CMD ["python", "-m", "picoagent.main"]

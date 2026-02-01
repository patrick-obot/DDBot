FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create data and logs directories
RUN mkdir -p data logs

# Create non-root user and set ownership
RUN groupadd --system ddbot && \
    useradd --system --gid ddbot --no-create-home ddbot && \
    chown -R ddbot:ddbot /app/data /app/logs

USER ddbot

STOPSIGNAL SIGTERM

# Touch a heartbeat file each poll cycle; check it's been updated recently
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD test -f /app/data/heartbeat && \
    find /app/data/heartbeat -mmin -10 | grep -q . || exit 1

CMD ["python", "-m", "ddbot.main"]

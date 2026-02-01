# DDBot - DownDetector WhatsApp Alert Bot

Monitors [DownDetector.co.za](https://downdetector.co.za) for service outage reports and sends WhatsApp alerts when the report count exceeds a configurable threshold.

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure environment

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

**Required settings:**
- `OPENCLAW_GATEWAY_URL` / `OPENCLAW_GATEWAY_TOKEN` - OpenClaw gateway endpoint and Bearer token
- `WHATSAPP_RECIPIENTS` - Comma-separated phone numbers with country code (e.g. `27821234567`) or group JIDs (e.g. `120363044xxxxx@g.us`)

### 3. Run

```bash
# Continuous monitoring (polls every DD_POLL_INTERVAL seconds)
python -m ddbot.main

# Single check and exit
python -m ddbot.main --once

# Check a specific service
python -m ddbot.main --once --service mtn

# Dry run (scrape only, no WhatsApp messages)
python -m ddbot.main --once --dry-run
```

## Configuration

All settings are configured via environment variables (`.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `DD_SERVICES` | `mtn` | Comma-separated services to monitor |
| `DD_THRESHOLD` | `10` | Report count to trigger an alert |
| `DD_POLL_INTERVAL` | `300` | Seconds between checks |
| `DD_ALERT_COOLDOWN` | `1800` | Seconds before re-alerting for same service |
| `OPENCLAW_GATEWAY_URL` | `http://127.0.0.1:18789` | OpenClaw gateway endpoint |
| `OPENCLAW_GATEWAY_TOKEN` | - | OpenClaw Bearer token for auth |
| `WHATSAPP_RECIPIENTS` | - | Phone numbers or group JIDs to alert |
| `LOG_LEVEL` | `INFO` | Logging level |

## Docker

```bash
docker build -t ddbot .
docker run --env-file .env ddbot
```

## Testing

```bash
pip install -r requirements-dev.txt
pytest tests/
```

## Architecture

- **scraper.py** - Playwright-based DownDetector scraper with fallback strategies
- **notifier.py** - WhatsApp message sending via OpenClaw gateway
- **history.py** - JSON-based alert history with cooldown enforcement
- **config.py** - Environment-based configuration with validation
- **main.py** - Async polling loop with CLI interface

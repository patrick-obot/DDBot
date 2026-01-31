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
- `GREENAPI_INSTANCE_ID` / `GREENAPI_API_TOKEN` - Get these from [GREEN-API](https://green-api.com/) (free developer tier)
- `WHATSAPP_RECIPIENTS` - Comma-separated phone numbers with country code (e.g. `27821234567`)

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
| `GREENAPI_INSTANCE_ID` | - | GREEN-API instance ID |
| `GREENAPI_API_TOKEN` | - | GREEN-API API token |
| `WHATSAPP_RECIPIENTS` | - | Phone numbers to alert |
| `LOG_LEVEL` | `INFO` | Logging level |

## Docker

```bash
docker build -t ddbot .
docker run --env-file .env ddbot
```

## Testing

```bash
pytest tests/
```

## Architecture

- **scraper.py** - Playwright-based DownDetector scraper with retry logic
- **notifier.py** - WhatsApp message sending via GREEN-API
- **history.py** - JSON-based alert history with cooldown enforcement
- **config.py** - Environment-based configuration
- **main.py** - Async polling loop with CLI interface

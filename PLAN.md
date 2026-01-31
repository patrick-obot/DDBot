# DDBot - DownDetector WhatsApp Alert Bot

## Overview
A standalone Python bot that monitors DownDetector.co.za for service outage reports and sends WhatsApp alerts when the report count exceeds a configurable threshold (default: 10).

## Project Location
New standalone repo: `D:\Study\Stiff_Back_Projects\DDBot\`

---

## Architecture

```
DDBot/
├── ddbot/
│   ├── __init__.py
│   ├── main.py              # Entry point, scheduler loop
│   ├── scraper.py           # DownDetector scraping via Playwright
│   ├── notifier.py          # WhatsApp message sending
│   ├── config.py            # Configuration management
│   └── history.py           # Alert history tracking (JSON log)
├── data/
│   └── alert_history.json   # Persistent alert history
├── logs/
│   └── ddbot.log            # Application logs
├── tests/
│   ├── test_scraper.py
│   ├── test_notifier.py
│   └── test_config.py
├── .env                     # Environment variables (gitignored)
├── .env.example             # Template for env vars
├── .gitignore
├── requirements.txt
├── Dockerfile
└── README.md
```

---

## Key Components

### 1. Scraper (`scraper.py`)
- Uses **Playwright** (headless Chromium) to load DownDetector pages
- Handles Cloudflare protection and JS-rendered content
- Targets: `https://downdetector.co.za/status/<service>`
- Extracts current report count from the page
- Configurable list of services to monitor (default: MTN)
- Returns structured data: `{ service, report_count, timestamp, status }`

### 2. Notifier (`notifier.py`)
- Sends WhatsApp messages when threshold is exceeded
- **Primary option: GREEN-API** (free developer tier, good Python SDK)
  - Package: `whatsapp-api-client-python`
  - Requires: instance ID + API token (free registration)
- **Fallback option: Twilio** (if user prefers, ~$0.005/msg)
- Message format: `"⚠️ DDBot Alert: {service} has {count} reports on DownDetector (threshold: {threshold}). Check https://downdetector.co.za/status/{service}"`
- Cooldown period to avoid spam (default: 30 min between alerts for same service)

### 3. Config (`config.py`)
- Loads from `.env` via `python-dotenv`
- Key settings:
  ```
  # Services to monitor (comma-separated)
  DD_SERVICES=mtn,vodacom,telkom

  # Alert threshold
  DD_THRESHOLD=10

  # Polling interval (seconds)
  DD_POLL_INTERVAL=300  # 5 minutes

  # Alert cooldown (seconds) - avoid repeat alerts
  DD_ALERT_COOLDOWN=1800  # 30 minutes

  # WhatsApp config (GREEN-API)
  GREENAPI_INSTANCE_ID=your_instance_id
  GREENAPI_API_TOKEN=your_api_token
  WHATSAPP_RECIPIENTS=27XXXXXXXXX  # comma-separated phone numbers

  # Logging
  LOG_LEVEL=INFO
  ```

### 4. History (`history.py`)
- Persists alert history to `data/alert_history.json`
- Tracks: which alerts were sent, when, for which service, report count
- Enforces cooldown logic (no duplicate alerts within cooldown window)
- Provides summary/query capability (e.g., "last 24h alerts")

### 5. Main Loop (`main.py`)
- Async polling loop using `asyncio`
- Flow per cycle:
  1. For each configured service, scrape DownDetector
  2. If report_count >= threshold AND not in cooldown → send WhatsApp alert
  3. Log result (alert sent or skipped)
  4. Sleep for poll interval
- Graceful shutdown on SIGINT/SIGTERM
- CLI args: `--once` (single check), `--service mtn` (check specific service)

---

## Dependencies (`requirements.txt`)
```
playwright>=1.40.0
python-dotenv>=1.0.0
whatsapp-api-client-python>=0.0.40
aiohttp>=3.9.0
colorlog>=6.7.0
pytest>=7.4.0
pytest-asyncio>=0.21.0
```

---

## Implementation Steps

1. **Scaffold project** — Create directory structure, git init, .gitignore, requirements.txt, .env.example
2. **Config module** — Environment loading, validation, dataclass
3. **Scraper module** — Playwright-based DownDetector scraper with retry logic
4. **History module** — JSON-based alert history with cooldown enforcement
5. **Notifier module** — GREEN-API WhatsApp integration
6. **Main loop** — Async scheduler tying everything together
7. **Tests** — Unit tests for scraper parsing, notifier formatting, history logic
8. **Dockerfile** — Container setup using Playwright base image

---

## Verification / Testing Plan

1. **Unit tests**: `pytest tests/` — test parsing, config validation, history cooldown logic
2. **Manual scraper test**: `python -m ddbot.main --once --service mtn` — verify scraping works and report count is extracted
3. **WhatsApp test**: Send a test message via GREEN-API to verify credentials and delivery
4. **Full integration**: Run the bot for a few polling cycles and confirm alerts fire when threshold is met
5. **History check**: Verify `data/alert_history.json` is populated and cooldown prevents duplicate alerts

---

## Open Decisions (configurable, not blocking)
- **WhatsApp provider**: Plan defaults to GREEN-API (free). Can swap to Twilio/Ultramsg by changing `notifier.py`
- **Additional services**: Start with MTN, add more via `DD_SERVICES` env var
- **Deployment**: Can deploy to Railway (like fpl_agent) or run locally. Dockerfile included either way

# DDBot - Project Context

## Overview
DownDetector Alert Bot. Scrapes downdetector.co.za for service outage reports and sends alerts via WhatsApp (OpenClaw gateway) and/or Telegram when report counts exceed a threshold.

## Architecture
- **ddbot/scraper.py** — Two-tier scraper: `curl_cffi` primary (browser TLS fingerprint impersonation via `impersonate="chrome"`) with lazy Playwright fallback. Detects Cloudflare challenges and Next.js client-rendered pages (no `window.DD`), falling back to Playwright automatically. Playwright fallback uses **connect-over-CDP**: launches Chrome subprocess with minimal flags, connects via `connect_over_cdp()`. Persistent profile at `data/chrome_profile/` preserves `cf_clearance` cookies. Headed mode required (headless blocked by Cloudflare). Data extraction: legacy `window.DD` object → Recharts SVG parsing (`.recharts-area-curve` path coordinates) → text fallback. Clicks "skip" button to reveal chart data. Cookie consent auto-dismissed. `ScrapeResult.source` tracks engine used
- **ddbot/notifier.py** — Multi-channel notifications: WhatsApp via OpenClaw `/tools/invoke` endpoint (supports phone numbers and group JIDs `@g.us`), Telegram via Bot API. Both channels can be enabled simultaneously; at least one required
- **ddbot/history.py** — JSON-based alert history persistence with cooldown logic. Atomic file writes (temp + `os.replace`). Corrupt files backed up to `.bak`
- **ddbot/config.py** — Environment variable config with validation, logging setup. Safe int parsing with fallback defaults. Service name validation (`^[a-z0-9-]+$`)
- **ddbot/main.py** — Async polling loop with crash protection, exponential backoff on all-service-fail (doubles wait up to 1h cap), random inter-service delay, CLI interface (`--once`, `--service`, `--dry-run`, `--env`), heartbeat file for Docker HEALTHCHECK
- **tests/** — Unit tests for all modules (pytest + pytest-asyncio). Dev deps in `requirements-dev.txt`

## Key Decisions
- Switched from GREEN-API to OpenClaw gateway (commit f0677ad)
- Switched from OpenClaw `/hooks/agent` (required LLM processing via gpt-4o-mini) to `/tools/invoke` with the `message` tool for direct WhatsApp delivery. Bearer token auth, expects HTTP 200 with `{"ok": true}`
- Scraper uses `curl_cffi` as primary engine (lightweight HTTP with Chrome TLS fingerprint) and falls back to Playwright only when Cloudflare challenges are detected. Playwright fallback uses connect-over-CDP with minimal Chrome flags and a persistent profile dir (`data/chrome_profile/`) to preserve `cf_clearance` cookies. Anti-detection flags and stealth patches are intentionally omitted — they trigger Cloudflare detection. First run after fresh profile requires manual Turnstile solve in headed mode; subsequent runs reuse the cookie. Headless mode does not work with Cloudflare (different fingerprint). Cookie consent popups auto-dismissed
- Alert cooldown default: 15 min per service. Polling interval default: 30 min. Threshold default: 10 reports.
- Active hours: only polls between 07:00-20:00 SAST by default to reduce bot-detection risk. `--once` bypasses active hours.
- Runtime deps pinned to exact versions in `requirements.txt`; dev/test deps split to `requirements-dev.txt`
- Dockerfile runs as non-root `ddbot` user with `STOPSIGNAL SIGTERM` and heartbeat-based `HEALTHCHECK`
- `.dockerignore` excludes `.git`, `.env`, `tests/`, `__pycache__/`, etc. from image

## Config (env vars)
- `DD_SERVICES` — comma-separated service slugs (default: mtn)
- `DD_THRESHOLD` — report count to trigger alert (default: 10)
- `DD_POLL_INTERVAL` — seconds between polls (default: 1800 / 30 min)
- `DD_ALERT_COOLDOWN` — seconds between alerts per service (default: 900 / 15 min)
- `DD_ACTIVE_HOURS_START` — hour to start polling, 24h format (default: 7)
- `DD_ACTIVE_HOURS_END` — hour to stop polling, 24h format (default: 20)
- `DD_TIMEZONE` — timezone for active hours (default: Africa/Johannesburg)
- `DD_SCRAPE_DELAY_MIN` — minimum seconds between service scrapes (default: 5)
- `DD_SCRAPE_DELAY_MAX` — maximum seconds between service scrapes (default: 15)
- `DD_CHROME_PATH` — explicit path to Chrome/Chromium binary for Playwright CDP fallback (default: auto-detect)
- `OPENCLAW_GATEWAY_URL` — OpenClaw endpoint (default: http://127.0.0.1:18789)
- `OPENCLAW_GATEWAY_TOKEN` — Bearer token for WhatsApp auth
- `WHATSAPP_RECIPIENTS` — comma-separated phone numbers or group JIDs
- `TELEGRAM_BOT_TOKEN` — Telegram bot token (from @BotFather)
- `TELEGRAM_CHAT_IDS` — comma-separated Telegram chat IDs to notify

## Deployment
- **Production server**: 77.37.125.213 (Ubuntu 24.04, same host as OpenClaw gateway)
- **Install path**: `/opt/ddbot` with Python venv at `/opt/ddbot/venv`
- **Systemd service**: `ddbot.service` — runs via `xvfb-run` for headed Chrome support, enabled on boot, auto-restarts on failure
- **Gateway**: `http://127.0.0.1:50548` (localhost since co-located with OpenClaw)
- **Chrome**: Google Chrome stable installed system-wide; `curl_cffi` works directly on the server IP without needing Playwright fallback
- **Management**: `systemctl {start|stop|restart|status} ddbot`, `journalctl -u ddbot -f`

## Raspberry Pi Deployment (Residential IP Bypass)

Cloudflare blocks datacenter IPs aggressively. A Raspberry Pi on a home network provides a residential IP that bypasses these blocks.

### Quick Install
```bash
curl -sSL https://raw.githubusercontent.com/patrick-obot/DDBot/master/setup-pi.sh | sudo bash
```

### Post-Install Setup
1. **Configure credentials**: `sudo nano /opt/ddbot/.env`
2. **Set Chrome path**: `DD_CHROME_PATH=/usr/bin/chromium-browser`
3. **Fix profile permissions**: `sudo chown -R $USER:$USER /opt/ddbot/data/`

### First Run (Cloudflare Cookie)
First run requires manually solving Cloudflare Turnstile via VNC:

1. **Enable VNC**: `sudo raspi-config` → Interface Options → VNC → Enable
2. **Connect via VNC** (RealVNC Viewer to `<pi-ip>:5900`)
3. **Run DDBot**: `cd /opt/ddbot && source venv/bin/activate && python -m ddbot.main --once --service mtn`
4. **Solve Turnstile** checkbox when prompted — cookie saves to `data/chrome_profile/`
5. **Start service**: `sudo systemctl enable ddbot && sudo systemctl start ddbot`

### Pi-Specific Chrome Flags
The scraper uses these flags for Raspberry Pi compatibility:
- `--no-sandbox` — Chrome sandbox fails on Pi due to kernel namespace restrictions
- `--password-store=basic` — Disables GNOME keyring prompt that blocks Chrome startup
- `start_new_session=True` — Detaches Chrome from Python's process group

### Troubleshooting
- **Zombie Chrome processes**: `sudo pkill -9 -f chromium` then `rm -f /opt/ddbot/data/chrome_profile/Singleton*`
- **Profile permission errors**: `sudo chown -R $USER:$USER /opt/ddbot/data/`
- **CDP timeout**: Reboot Pi to clear stale processes
- **0 reports extracted**: The scraper forces a screenshot to trigger chart rendering; if still failing, run with `--debug-dump` to inspect

### Management
```bash
sudo systemctl status ddbot      # Check status
sudo systemctl restart ddbot     # Restart
sudo journalctl -u ddbot -f      # Live logs
sudo journalctl -u ddbot -n 50   # Last 50 lines
```

## Current State
- All core features implemented and tested (139 tests)
- Dual notification channels: WhatsApp (OpenClaw) + Telegram (@DwnDetectorBot)
- Scraper updated for DownDetector Next.js migration (Recharts SVG extraction)
- Deployed and running on production server as systemd service
- Production hardened: safe config parsing, atomic history writes, poll loop crash protection
- Monitoring MTN, polling every 30 min during 7:00-20:00 SAST, 15 min alert cooldown
- No outstanding TODOs or known bugs

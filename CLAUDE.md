# DDBot - Project Context

## Overview
DownDetector WhatsApp Alert Bot. Scrapes downdetector.co.za for service outage reports and sends WhatsApp alerts via OpenClaw gateway when report counts exceed a threshold.

## Architecture
- **ddbot/scraper.py** — Two-tier scraper: `curl_cffi` primary (browser TLS fingerprint impersonation via `impersonate="chrome"`) with lazy Playwright fallback. curl_cffi path uses regex HTML parsing → text-based fallback for data extraction. Detects Cloudflare challenges via markers ("just a moment", "verify you are human", "checking your browser", "cf-challenge") and falls back to Playwright automatically. Playwright fallback uses **connect-over-CDP**: launches a standalone Chrome subprocess with minimal flags (`--remote-debugging-port`, `--user-data-dir`), then connects Playwright via `connect_over_cdp()`. Minimal flags are critical — anti-detection flags like `--disable-blink-features=AutomationControlled` are themselves detected by Cloudflare. Chrome binary auto-detected or set via `DD_CHROME_PATH`. Persistent profile dir at `data/chrome_profile/` preserves `cf_clearance` cookies between runs (first run requires manual Turnstile solve in headed mode). Defaults to headed mode (`headless=False`) since headless Chrome has a different fingerprint that Cloudflare blocks. Playwright fallback adds JS object extraction (window.DD) as Strategy 1. Randomizes page wait times (2-5s). Cloudflare Turnstile checkbox click with up to 15s auto-resolve wait. Cookie consent popups auto-dismissed before data extraction. `ScrapeResult.source` field tracks which engine produced the result ("curl", "playwright", or "error")
- **ddbot/notifier.py** — WhatsApp messaging via OpenClaw `/tools/invoke` endpoint using the `message` tool for direct delivery (no LLM processing). Supports phone numbers and group JIDs (`@g.us`)
- **ddbot/history.py** — JSON-based alert history persistence with cooldown logic. Atomic file writes (temp + `os.replace`). Corrupt files backed up to `.bak`
- **ddbot/config.py** — Environment variable config with validation, logging setup. Safe int parsing with fallback defaults. Service name validation (`^[a-z0-9-]+$`)
- **ddbot/main.py** — Async polling loop with crash protection, exponential backoff on all-service-fail (doubles wait up to 1h cap), random inter-service delay, CLI interface (`--once`, `--service`, `--dry-run`, `--env`), heartbeat file for Docker HEALTHCHECK
- **tests/** — Unit tests for all modules (pytest + pytest-asyncio). Dev deps in `requirements-dev.txt`

## Key Decisions
- Switched from GREEN-API to OpenClaw gateway (commit f0677ad)
- Switched from OpenClaw `/hooks/agent` (required LLM processing via gpt-4o-mini) to `/tools/invoke` with the `message` tool for direct WhatsApp delivery. Bearer token auth, expects HTTP 200 with `{"ok": true}`
- Scraper uses `curl_cffi` as primary engine (lightweight HTTP with Chrome TLS fingerprint) and falls back to Playwright only when Cloudflare challenges are detected. Playwright fallback uses connect-over-CDP with minimal Chrome flags and a persistent profile dir (`data/chrome_profile/`) to preserve `cf_clearance` cookies. Anti-detection flags and stealth patches are intentionally omitted — they trigger Cloudflare detection. First run after fresh profile requires manual Turnstile solve in headed mode; subsequent runs reuse the cookie. Headless mode does not work with Cloudflare (different fingerprint). Cookie consent popups auto-dismissed
- Alert cooldown default: 30 min per service. Polling interval default: 30 min. Threshold default: 10 reports.
- Active hours: only polls between 07:00-20:00 SAST by default to reduce bot-detection risk. `--once` bypasses active hours.
- Runtime deps pinned to exact versions in `requirements.txt`; dev/test deps split to `requirements-dev.txt`
- Dockerfile runs as non-root `ddbot` user with `STOPSIGNAL SIGTERM` and heartbeat-based `HEALTHCHECK`
- `.dockerignore` excludes `.git`, `.env`, `tests/`, `__pycache__/`, etc. from image

## Config (env vars)
- `DD_SERVICES` — comma-separated service slugs (default: mtn)
- `DD_THRESHOLD` — report count to trigger alert (default: 10)
- `DD_POLL_INTERVAL` — seconds between polls (default: 1800 / 30 min)
- `DD_ALERT_COOLDOWN` — seconds between alerts per service (default: 1800)
- `DD_ACTIVE_HOURS_START` — hour to start polling, 24h format (default: 7)
- `DD_ACTIVE_HOURS_END` — hour to stop polling, 24h format (default: 20)
- `DD_TIMEZONE` — timezone for active hours (default: Africa/Johannesburg)
- `DD_SCRAPE_DELAY_MIN` — minimum seconds between service scrapes (default: 5)
- `DD_SCRAPE_DELAY_MAX` — maximum seconds between service scrapes (default: 15)
- `DD_CHROME_PATH` — explicit path to Chrome/Chromium binary for Playwright CDP fallback (default: auto-detect)
- `OPENCLAW_GATEWAY_URL` — OpenClaw endpoint (default: http://127.0.0.1:18789)
- `OPENCLAW_GATEWAY_TOKEN` — Bearer token for auth
- `WHATSAPP_RECIPIENTS` — comma-separated phone numbers or group JIDs

## Current State
- All core features implemented and tested (139 tests)
- OpenClaw integration complete
- Docker deployment ready (hardened with non-root user, healthcheck)
- Production hardened: safe config parsing, atomic history writes, poll loop crash protection
- No outstanding TODOs or known bugs

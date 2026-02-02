# DDBot - Project Context

## Overview
DownDetector WhatsApp Alert Bot. Scrapes downdetector.co.za for service outage reports and sends WhatsApp alerts via OpenClaw gateway when report counts exceed a threshold.

## Architecture
- **ddbot/scraper.py** — Two-tier scraper: `curl_cffi` primary (browser TLS fingerprint impersonation via `impersonate="chrome"`) with lazy Playwright fallback. curl_cffi path uses regex HTML parsing → text-based fallback for data extraction. Detects Cloudflare challenges via markers ("just a moment", "verify you are human", "checking your browser", "cf-challenge") and falls back to Playwright automatically. Playwright fallback uses **connect-over-CDP**: launches a standalone Chrome subprocess with `--remote-debugging-port`, then connects Playwright via `connect_over_cdp()` — this bypasses Cloudflare's fingerprinting of Playwright-launched browsers. Chrome binary auto-detected or set via `DD_CHROME_PATH`. Temp user-data-dir created per session and cleaned up on stop. Playwright fallback adds JS object extraction (window.DD) as Strategy 1. Anti-detection: `playwright-stealth` patches, rotates user-agents from a pool of 6, randomizes page wait times (2-5s). Cloudflare Turnstile checkbox click with up to 15s auto-resolve wait. Cookie consent popups auto-dismissed before data extraction. `ScrapeResult.source` field tracks which engine produced the result ("curl", "playwright", or "error")
- **ddbot/notifier.py** — WhatsApp messaging via OpenClaw `/hooks/agent` endpoint. Supports phone numbers and group JIDs (`@g.us`)
- **ddbot/history.py** — JSON-based alert history persistence with cooldown logic. Atomic file writes (temp + `os.replace`). Corrupt files backed up to `.bak`
- **ddbot/config.py** — Environment variable config with validation, logging setup. Safe int parsing with fallback defaults. Service name validation (`^[a-z0-9-]+$`)
- **ddbot/main.py** — Async polling loop with crash protection, exponential backoff on all-service-fail (doubles wait up to 1h cap), random inter-service delay, CLI interface (`--once`, `--service`, `--dry-run`, `--env`), heartbeat file for Docker HEALTHCHECK
- **tests/** — Unit tests for all modules (pytest + pytest-asyncio). Dev deps in `requirements-dev.txt`

## Key Decisions
- Switched from GREEN-API to OpenClaw gateway (commit f0677ad)
- Using OpenClaw `/hooks/agent` endpoint with Bearer token auth, expects HTTP 202 (commit db6730d)
- Message format wraps content in "Reply with exactly this text..." instruction for OpenClaw agent
- Scraper uses `curl_cffi` as primary engine (lightweight HTTP with Chrome TLS fingerprint) and falls back to Playwright only when Cloudflare challenges are detected. Playwright fallback uses connect-over-CDP (standalone Chrome subprocess + `connect_over_cdp()`) to avoid Cloudflare fingerprinting of Playwright-launched browsers. Cookie consent popups auto-dismissed. Detects challenge pages via markers ("just a moment", "verify you are human", "checking your browser", "cf-challenge")
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
- All core features implemented and tested (101 tests)
- OpenClaw integration complete
- Docker deployment ready (hardened with non-root user, healthcheck)
- Production hardened: safe config parsing, atomic history writes, poll loop crash protection
- No outstanding TODOs or known bugs

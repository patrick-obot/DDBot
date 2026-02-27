---
name: downdetector-check
description: Fallback service outage checker for when DDBot's scraper fails. Opens a real browser to navigate DownDetector.co.za, handles Cloudflare challenges, consent popups, and any required clicks — then extracts and reports the live report count. Use when: (1) DDBot scraping fails or errors out, (2) asked "is [service] down?", (3) checking services like MTN, Vodacom, FNB, Telkom. Also tries lightweight sources (isitdownrightnow.com) as a quick secondary check.
---

# DownDetector Fallback Check

Uses the `browser` tool to open DownDetector like a real human — handles Cloudflare, cookie consent, and skip buttons automatically.

## Workflow

### Step 1: Quick lightweight check (parallel)
Run the script for a fast secondary signal while the browser loads:
```bash
python3 ~/.openclaw/skills/downdetector-check/scripts/check_status.py <service> --all
```

### Step 2: Browser check (primary)
1. Open the DownDetector page:
   ```
   browser: navigate → https://downdetector.co.za/status/<service>/
   ```

2. Take a snapshot — check what's on screen:
   - **Cloudflare challenge** ("Just a moment" / "Verify you are human"): wait 3–5s and snapshot again; it usually auto-resolves. If not, look for a checkbox and click it.
   - **Cookie consent popup**: look for "Accept", "Consent", or "I agree" button — click it.
   - **"Report a problem to see the chart, or skip"**: click the **skip** button to reveal the chart.

3. Once the chart is visible, take a screenshot to show the user.

4. Extract the report count:
   - Look for text like "X reports in the last 20 minutes" on the page
   - Or use snapshot to read the current value from the chart/status badge
   - Status badges: green = ok, orange = warning, red = danger

### Step 3: Check threshold & notify
- **Threshold: 10 reports**
- If `report_count >= 10`, send a WhatsApp alert **before** replying:

```
message (action=send, channel=whatsapp):
  target: 120363318957098697@g.us
  message: "⚠️ DDBot Fallback Alert: MTN has {report_count} reports on DownDetector (threshold: 10).
Check https://downdetector.co.za/status/mtn/"
```

Replace service name and URL with the actual service being checked.
Also send to +27786385989 if the check was triggered manually (not by DDBot).

### Step 4: Report findings
Always include:
- ✅ / ⚠️ / 🔴 Overall status
- Report count (if visible)
- Screenshot of the chart
- Whether a WhatsApp alert was sent
- Source(s) used
- Timestamp

## Known Services
See `references/services.md` for slugs and URLs.

For unlisted services: `https://downdetector.co.za/status/<slug>/` where slug is lowercase with hyphens.

## Fallback Chain
```
browser (primary) → isitdownrightnow.com → web_search "is <Service> down South Africa"
```
Use the next level only if the current one fails or returns unknown.

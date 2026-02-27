#!/usr/bin/env python3
"""
Fallback DownDetector status checker.
Uses lightweight HTTP (no browser) to fetch status from multiple sources.

Usage:
    python3 check_status.py <service>           # e.g. mtn, vodacom, fnb
    python3 check_status.py <service> --all     # include all sources

Output: JSON with status, report_count, sources
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

def fetch(url: str, timeout: int = 15) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    try:
        with urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        return f"HTTP_ERROR:{e.code}"
    except URLError as e:
        return f"URL_ERROR:{e.reason}"
    except Exception as e:
        return f"ERROR:{e}"


def check_downdetector_za(service: str) -> dict:
    """Check downdetector.co.za (primary DDBot source)."""
    url = f"https://downdetector.co.za/status/{service}/"
    html = fetch(url)

    if html.startswith(("HTTP_ERROR", "URL_ERROR", "ERROR")):
        return {"source": "downdetector.co.za", "status": "fetch_error", "error": html}

    html_lower = html.lower()

    # Cloudflare block check
    if any(m in html_lower for m in ["just a moment", "verify you are human", "cf-challenge"]):
        return {"source": "downdetector.co.za", "status": "blocked", "error": "Cloudflare challenge"}

    # Try to extract report count from JS properties
    y_values = re.findall(r"\{\s*x:\s*'[^']+',\s*y:\s*(\d+)\s*\}", html)
    if y_values:
        count = int(y_values[-1])
        status_match = re.search(r"currentServiceProperties\s*=\s*\{[^}]*status:\s*'(\w+)'", html)
        page_status = {"success": "ok", "warning": "warning", "danger": "danger"}.get(
            status_match.group(1) if status_match else "", None
        )
        return {
            "source": "downdetector.co.za",
            "status": page_status or _classify(count),
            "report_count": count,
        }

    # Text fallback
    text = re.sub(r"<[^>]+>", " ", html)
    if "no current problems" in text.lower():
        return {"source": "downdetector.co.za", "status": "ok", "report_count": 0}

    # Check for report patterns
    match = re.search(r"(\d[\d,]*)\s*(?:user\s*)?reports?", text, re.IGNORECASE)
    if match:
        count = int(match.group(1).replace(",", ""))
        return {"source": "downdetector.co.za", "status": _classify(count), "report_count": count}

    return {"source": "downdetector.co.za", "status": "unknown", "error": "Could not parse page"}


def check_isitdown(service: str) -> dict:
    """Check isitdownrightnow.com as a secondary source."""
    url = f"https://www.isitdownrightnow.com/{service}.com.html"
    html = fetch(url)

    if html.startswith(("HTTP_ERROR", "URL_ERROR", "ERROR")):
        return {"source": "isitdownrightnow.com", "status": "fetch_error", "error": html}

    text = re.sub(r"<[^>]+>", " ", html).lower()

    if "is up" in text or "seems to be working fine" in text:
        return {"source": "isitdownrightnow.com", "status": "ok"}
    elif "is down" in text or "seems to be down" in text:
        return {"source": "isitdownrightnow.com", "status": "danger"}

    return {"source": "isitdownrightnow.com", "status": "unknown"}


def _classify(count: int) -> str:
    if count < 10:
        return "ok"
    elif count < 50:
        return "warning"
    return "danger"


def main():
    parser = argparse.ArgumentParser(description="Fallback DownDetector status checker")
    parser.add_argument("service", help="Service slug (e.g. mtn, vodacom)")
    parser.add_argument("--all", action="store_true", help="Check all sources")
    args = parser.parse_args()

    service = args.service.lower().strip()
    results = []

    dd_result = check_downdetector_za(service)
    results.append(dd_result)

    if args.all or dd_result["status"] in ("blocked", "fetch_error", "unknown"):
        results.append(check_isitdown(service))

    # Aggregate
    statuses = [r["status"] for r in results if r["status"] not in ("fetch_error", "unknown", "blocked")]
    severity = {"danger": 3, "warning": 2, "ok": 1}
    final_status = max(statuses, key=lambda s: severity.get(s, 0)) if statuses else "unknown"

    output = {
        "service": service,
        "overall_status": final_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sources": results,
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()

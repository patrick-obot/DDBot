"""DownDetector scraper using Playwright."""

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from playwright_stealth import Stealth

from ddbot.config import DATA_DIR

logger = logging.getLogger("ddbot.scraper")

BASE_URL = "https://downdetector.co.za/status"

_USER_AGENTS = [
    # Chrome 122 – Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Chrome 122 – macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Edge 122 – Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    # Firefox 123 – Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    # Firefox 123 – macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
    # Chrome 122 – Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


@dataclass
class ScrapeResult:
    """Result from scraping a DownDetector service page."""

    service: str
    report_count: int
    timestamp: str
    status: str  # "ok", "warning", "danger", "error"
    error: Optional[str] = None


class DownDetectorScraper:
    """Scrapes DownDetector.co.za for service outage report counts."""

    def __init__(self, headless: bool = True, debug_dump: bool = False):
        self._headless = headless
        self._debug_dump = debug_dump
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def start(self) -> None:
        """Launch the browser and create a persistent context with a random user-agent."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-extensions",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        ua = random.choice(_USER_AGENTS)
        self._context = await self._browser.new_context(
            user_agent=ua,
            viewport={"width": 1280, "height": 720},
        )
        stealth = Stealth()
        await stealth.apply_stealth_async(self._context)
        self._page = await self._context.new_page()
        logger.info("Browser launched (headless=%s, ua=%s, stealth=on)", self._headless, ua[:50])

    async def stop(self) -> None:
        """Close the page, context, browser and playwright."""
        if self._context:
            await self._context.close()
            self._context = None
            self._page = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("Browser closed")

    async def scrape_service(
        self, service: str, retries: int = 2
    ) -> ScrapeResult:
        """Scrape the report count for a single service with retry logic."""
        url = f"{BASE_URL}/{service.lower()}"
        last_error = None

        for attempt in range(1, retries + 1):
            try:
                result = await self._do_scrape(service, url)
                logger.info(
                    "Scraped %s: %d reports (status=%s)",
                    service,
                    result.report_count,
                    result.status,
                )
                return result
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "Scrape attempt %d/%d for %s failed: %s",
                    attempt,
                    retries,
                    service,
                    last_error,
                )
                if attempt < retries:
                    await asyncio.sleep(3 * attempt)

        return ScrapeResult(
            service=service,
            report_count=0,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status="error",
            error=last_error,
        )

    async def _do_scrape(self, service: str, url: str) -> ScrapeResult:
        """Perform the actual page scrape using the persistent page."""
        if not self._page:
            raise RuntimeError("Browser not started. Call start() first.")

        await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        wait_ms = random.randint(2000, 5000)
        await self._page.wait_for_timeout(wait_ms)

        # Detect and wait through Cloudflare challenge pages
        if await self._is_cloudflare_challenge():
            logger.info("Cloudflare challenge detected for %s, waiting for auto-resolve...", service)
            resolved = False
            for _ in range(15):
                await self._page.wait_for_timeout(1000)
                if not await self._is_cloudflare_challenge():
                    logger.info("Cloudflare challenge resolved for %s", service)
                    resolved = True
                    break
            if not resolved:
                logger.warning("Cloudflare challenge did not resolve for %s after 15s", service)

        if self._debug_dump:
            await self._dump_page(service)

        report_count, page_status = await self._extract_from_page(self._page)
        status = page_status or self._classify_status(report_count)

        return ScrapeResult(
            service=service,
            report_count=report_count,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status=status,
        )

    async def _is_cloudflare_challenge(self) -> bool:
        """Check if the current page is a Cloudflare challenge/interstitial."""
        try:
            title = await self._page.title()
            if "just a moment" in title.lower():
                return True
            body_text = await self._page.inner_text("body")
            if "verify you are human" in body_text.lower():
                return True
        except Exception:
            pass
        return False

    async def _dump_page(self, service: str) -> None:
        """Save page artifacts for debugging extraction failures."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        prefix = DATA_DIR / f"debug_{service}"

        try:
            html = await self._page.content()
            Path(f"{prefix}.html").write_text(html, encoding="utf-8")
            logger.info("Debug dump: saved %s.html (%d bytes)", prefix, len(html))
        except Exception as exc:
            logger.warning("Debug dump HTML failed: %s", exc)

        try:
            await self._page.screenshot(path=f"{prefix}.png", full_page=True)
            logger.info("Debug dump: saved %s.png", prefix)
        except Exception as exc:
            logger.warning("Debug dump screenshot failed: %s", exc)

        try:
            body_text = await self._page.inner_text("body")
            Path(f"{prefix}.txt").write_text(body_text, encoding="utf-8")
            logger.info("Debug dump: saved %s.txt (%d chars)", prefix, len(body_text))
        except Exception as exc:
            logger.warning("Debug dump body text failed: %s", exc)

        try:
            dd_obj = await self._page.evaluate(
                "() => { try { return JSON.parse(JSON.stringify(window.DD)); } catch(e) { return {error: e.toString()}; } }"
            )
            Path(f"{prefix}_dd.json").write_text(
                json.dumps(dd_obj, indent=2, default=str), encoding="utf-8"
            )
            logger.info("Debug dump: saved %s_dd.json", prefix)
        except Exception as exc:
            logger.warning("Debug dump window.DD failed: %s", exc)

    async def _extract_from_page(self, page: Page) -> tuple[int, Optional[str]]:
        """Extract report count and status from the page.

        Returns (report_count, status_string_or_None).
        """
        # Strategy 1: Extract from window.DD.currentServiceProperties JS object
        # This is the most reliable source — embedded chart data with status.
        try:
            props = await page.evaluate(
                "() => window.DD && window.DD.currentServiceProperties"
            )
            if props:
                return self._parse_service_properties(props)
        except Exception as exc:
            logger.debug("JS evaluation failed: %s", exc)

        # Strategy 2: Parse the JS from page source as regex fallback
        html = await page.content()
        result = self._parse_properties_from_html(html)
        if result is not None:
            return result

        # Strategy 3: Text-based fallback
        body_text = await page.inner_text("body")

        # Check for explicit "no current problems" message
        if "no current problems" in body_text.lower():
            return 0, "ok"

        count = self._parse_report_text(body_text)
        if count is not None:
            return count, None

        logger.warning("Could not extract report count, defaulting to 0")
        return 0, None

    @staticmethod
    def _parse_service_properties(props: dict) -> tuple[int, Optional[str]]:
        """Parse the window.DD.currentServiceProperties object."""
        # Map DD status strings to our status values
        status_map = {
            "success": "ok",
            "warning": "warning",
            "danger": "danger",
        }
        page_status = status_map.get(props.get("status", ""), None)

        # Get the most recent report count from the series data
        report_count = 0
        try:
            data_points = props["series"]["reports"]["data"]
            if data_points:
                # Last entry is the most recent 15-min interval
                report_count = int(data_points[-1].get("y", 0))
        except (KeyError, TypeError, IndexError):
            pass

        return report_count, page_status

    @staticmethod
    def _parse_properties_from_html(html: str) -> Optional[tuple[int, Optional[str]]]:
        """Regex fallback: extract currentServiceProperties from raw HTML."""
        # Extract status
        status_match = re.search(
            r"currentServiceProperties\s*=\s*\{[^}]*status:\s*'(\w+)'",
            html,
        )
        status_map = {"success": "ok", "warning": "warning", "danger": "danger"}
        page_status = status_map.get(
            status_match.group(1), None
        ) if status_match else None

        # Extract the last y value from series data
        y_values = re.findall(
            r"\{\s*x:\s*'[^']+',\s*y:\s*(\d+)\s*\}",
            html,
        )
        if y_values:
            report_count = int(y_values[-1])
            return report_count, page_status

        # If we found status but no series data, still use it
        if page_status == "ok":
            return 0, page_status

        return None

    @staticmethod
    def _parse_count(text: str) -> Optional[int]:
        """Extract a number from text."""
        if not text:
            return None
        numbers = re.findall(r"\d[\d,]*", text)
        for num_str in numbers:
            try:
                return int(num_str.replace(",", ""))
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_report_text(text: str) -> Optional[int]:
        """Look for patterns like '123 reports' or 'Problem reports: 45'."""
        patterns = [
            r"(\d[\d,]*)\s*(?:user\s*)?reports?",
            r"reports?\s*[:=]\s*(\d[\d,]*)",
            r"(\d[\d,]*)\s*problem",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1).replace(",", ""))
                except ValueError:
                    continue
        return None

    @staticmethod
    def _classify_status(report_count: int) -> str:
        """Classify the severity based on report count."""
        if report_count < 10:
            return "ok"
        elif report_count < 50:
            return "warning"
        else:
            return "danger"

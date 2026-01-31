"""DownDetector scraper using Playwright."""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from playwright.async_api import async_playwright, Browser, Page

logger = logging.getLogger("ddbot.scraper")

BASE_URL = "https://downdetector.co.za/status"


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

    def __init__(self, headless: bool = True):
        self._headless = headless
        self._playwright = None
        self._browser: Optional[Browser] = None

    async def start(self) -> None:
        """Launch the browser instance."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        logger.info("Browser launched (headless=%s)", self._headless)

    async def stop(self) -> None:
        """Close the browser and playwright."""
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
        """Perform the actual page scrape."""
        if not self._browser:
            raise RuntimeError("Browser not started. Call start() first.")

        context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
        )
        page: Page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Wait for the main content to render
            await page.wait_for_timeout(3000)

            report_count = await self._extract_report_count(page)
            status = self._classify_status(report_count)

            return ScrapeResult(
                service=service,
                report_count=report_count,
                timestamp=datetime.now(timezone.utc).isoformat(),
                status=status,
            )
        finally:
            await context.close()

    async def _extract_report_count(self, page: Page) -> int:
        """Extract the report count number from the page content."""
        # Strategy 1: Look for the report count in common DownDetector selectors
        selectors = [
            # Main report count display
            "h2.entry-title",
            ".entry-title",
            # Chart area text
            ".chart-count",
            # Generic large number displays
            "div.text-2xl",
            "span.text-2xl",
        ]

        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    count = self._parse_count(text)
                    if count is not None:
                        return count
            except Exception:
                continue

        # Strategy 2: Search the full page text for report patterns
        body_text = await page.inner_text("body")
        count = self._parse_report_text(body_text)
        if count is not None:
            return count

        # Strategy 3: Check the page title or meta
        title = await page.title()
        count = self._parse_count(title)
        if count is not None:
            return count

        logger.warning("Could not extract report count, defaulting to 0")
        return 0

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
        if report_count == 0:
            return "ok"
        elif report_count < 10:
            return "ok"
        elif report_count < 50:
            return "warning"
        else:
            return "danger"

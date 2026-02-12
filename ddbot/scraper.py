"""DownDetector scraper using curl_cffi (primary) with Playwright fallback."""

import asyncio
import json
import logging
import os
import platform
import random
import re
import socket
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.request import urlopen
from urllib.error import URLError

from curl_cffi.requests import AsyncSession

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

_CF_CHALLENGE_MARKERS = [
    "just a moment",
    "verify you are human",
    "checking your browser",
    "cf-challenge",
]


class CurlBlockedError(Exception):
    """Raised when curl_cffi request is blocked (Cloudflare challenge or non-200)."""

    def __init__(self, status_code: int, reason: str):
        self.status_code = status_code
        self.reason = reason
        super().__init__(f"Blocked (status={status_code}): {reason}")


@dataclass
class ScrapeResult:
    """Result from scraping a DownDetector service page."""

    service: str
    report_count: int
    timestamp: str
    status: str  # "ok", "warning", "danger", "error"
    error: Optional[str] = None
    source: str = "curl"


class DownDetectorScraper:
    """Scrapes DownDetector.co.za for service outage report counts.

    Uses curl_cffi as the primary scraper (lightweight HTTP with browser TLS
    fingerprint impersonation). Falls back to Playwright only when curl_cffi
    encounters a Cloudflare challenge that requires a real browser.
    """

    def __init__(self, headless: bool = False, debug_dump: bool = False, chrome_path: str = ""):
        self._headless = headless
        self._debug_dump = debug_dump
        self._chrome_path = chrome_path
        # curl_cffi session
        self._curl_session: Optional[AsyncSession] = None
        self._curl_ua: Optional[str] = None
        # Playwright (lazy-initialized via CDP)
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._playwright_started = False
        # Chrome subprocess for CDP connection
        self._chrome_process: Optional[subprocess.Popen] = None
        self._profile_dir: Optional[str] = None
        self._cdp_port: Optional[int] = None

    async def start(self) -> None:
        """Initialize the curl_cffi session. Playwright is lazy-started on demand."""
        self._curl_ua = random.choice(_USER_AGENTS)
        self._curl_session = AsyncSession(
            impersonate="chrome",
            headers={
                "User-Agent": self._curl_ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Referer": "https://downdetector.co.za/",
            },
        )
        logger.info("curl_cffi session started (ua=%s)", self._curl_ua[:50])

    @staticmethod
    def _find_chrome_executable(configured_path: str = "") -> str:
        """Locate Chrome binary. Check configured path, then common locations."""
        if configured_path and Path(configured_path).is_file():
            return configured_path

        candidates: list[str] = []
        if platform.system() == "Windows":
            for env_var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
                base = os.environ.get(env_var, "")
                if base:
                    candidates.append(
                        str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
                    )
        else:
            candidates.extend([
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/chromium-browser",
                "/usr/bin/chromium",
                "/snap/bin/chromium",
            ])
            # macOS
            candidates.append(
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            )

        for path in candidates:
            if Path(path).is_file():
                return path

        raise FileNotFoundError(
            "Chrome executable not found. Install Google Chrome or set DD_CHROME_PATH."
        )

    @staticmethod
    def _find_free_port() -> int:
        """Find an available port using OS assignment."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    async def _wait_for_cdp_ready(self, port: int, timeout: float = 15) -> None:
        """Poll Chrome's CDP /json/version endpoint until ready."""
        url = f"http://127.0.0.1:{port}/json/version"
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                resp = urlopen(url, timeout=2)
                if resp.status == 200:
                    return
            except (URLError, OSError):
                pass
            await asyncio.sleep(0.5)
        raise TimeoutError(f"Chrome CDP endpoint not ready after {timeout}s on port {port}")

    async def _ensure_playwright(self) -> None:
        """Lazy-initialize: launch Chrome subprocess + connect via CDP."""
        if self._playwright_started:
            return

        from playwright.async_api import async_playwright

        # 1. Find Chrome and a free port
        chrome_exe = self._find_chrome_executable(self._chrome_path)
        port = self._find_free_port()
        self._cdp_port = port

        # 2. Use persistent profile dir (cookies survive between runs)
        profile_dir = DATA_DIR / "chrome_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        self._profile_dir = str(profile_dir)

        # 3. Launch Chrome subprocess with minimal flags
        #    Anti-detection flags like --disable-blink-features=AutomationControlled
        #    are themselves detected by Cloudflare. Keep flags minimal.
        chrome_args = [
            chrome_exe,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={self._profile_dir}",
            "--password-store=basic",  # Disable keyring prompt on Linux
        ]
        # Chrome sandbox often fails on Linux (especially Raspberry Pi) due to
        # kernel namespace restrictions. Always disable on Linux for reliability.
        if hasattr(os, "geteuid"):  # Linux/macOS
            chrome_args.append("--no-sandbox")
        if self._headless:
            chrome_args.append("--headless=new")

        self._chrome_process = subprocess.Popen(
            chrome_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info(
            "Chrome subprocess launched (pid=%d, port=%d, headless=%s)",
            self._chrome_process.pid, port, self._headless,
        )

        # 4. Wait for CDP to be ready
        await self._wait_for_cdp_ready(port)

        # 5. Connect Playwright via CDP
        self._playwright = await async_playwright().start()
        cdp_url = f"http://127.0.0.1:{port}"
        self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
        logger.info("Playwright connected via CDP to %s", cdp_url)

        # 6. Get or create context and page
        contexts = self._browser.contexts
        if contexts:
            self._context = contexts[0]
        else:
            self._context = await self._browser.new_context()

        pages = self._context.pages
        if pages:
            self._page = pages[0]
        else:
            self._page = await self._context.new_page()

        self._playwright_started = True
        logger.info(
            "Playwright fallback ready via CDP (headless=%s)",
            self._headless,
        )

    async def stop(self) -> None:
        """Close curl_cffi session, Playwright, Chrome subprocess, and temp dir."""
        if self._curl_session:
            await self._curl_session.close()
            self._curl_session = None
            logger.info("curl_cffi session closed")

        if self._playwright_started:
            if self._context:
                try:
                    await self._context.close()
                except Exception:
                    pass
                self._context = None
                self._page = None
            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
            self._playwright_started = False
            logger.info("Playwright browser closed")

        # Terminate Chrome subprocess
        if self._chrome_process is not None:
            try:
                self._chrome_process.terminate()
                self._chrome_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._chrome_process.kill()
                self._chrome_process.wait(timeout=5)
            except OSError:
                pass
            logger.info("Chrome subprocess terminated (pid=%d)", self._chrome_process.pid)
            self._chrome_process = None

        self._profile_dir = None

    async def scrape_service(
        self, service: str, retries: int = 2
    ) -> ScrapeResult:
        """Scrape the report count for a single service with retry logic.

        Two-tier approach per attempt:
        1. Try curl_cffi (fast, lightweight)
        2. If blocked by Cloudflare, fall back to Playwright
        """
        url = f"{BASE_URL}/{service.lower()}"
        last_error = None

        for attempt in range(1, retries + 1):
            # Tier 1: curl_cffi
            try:
                result = await self._do_scrape_curl(service, url)
                logger.info(
                    "Scraped %s via curl_cffi: %d reports (status=%s)",
                    service,
                    result.report_count,
                    result.status,
                )
                return result
            except CurlBlockedError as exc:
                logger.info(
                    "curl_cffi blocked for %s (%s), falling back to Playwright",
                    service,
                    exc.reason,
                )
                # Tier 2: Playwright fallback
                try:
                    await self._ensure_playwright()
                    result = await self._do_scrape_playwright(service, url)
                    logger.info(
                        "Scraped %s via Playwright: %d reports (status=%s)",
                        service,
                        result.report_count,
                        result.status,
                    )
                    return result
                except Exception as pw_exc:
                    last_error = f"Playwright fallback failed: {pw_exc}"
                    logger.warning(
                        "Scrape attempt %d/%d for %s failed (Playwright): %s",
                        attempt,
                        retries,
                        service,
                        last_error,
                    )
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "Scrape attempt %d/%d for %s failed (curl): %s",
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
            source="error",
        )

    async def _do_scrape_curl(self, service: str, url: str) -> ScrapeResult:
        """Scrape using curl_cffi HTTP request."""
        if not self._curl_session:
            raise RuntimeError("curl_cffi session not started. Call start() first.")

        response = await self._curl_session.get(url, timeout=30)

        if response.status_code != 200:
            raise CurlBlockedError(response.status_code, f"HTTP {response.status_code}")

        html = response.text

        # Check for Cloudflare challenge markers
        html_lower = html.lower()
        for marker in _CF_CHALLENGE_MARKERS:
            if marker in html_lower:
                if self._debug_dump:
                    self._dump_html(service, html, suffix="_curl_blocked")
                raise CurlBlockedError(200, f"Cloudflare challenge detected: '{marker}'")

        if self._debug_dump:
            self._dump_html(service, html, suffix="_curl")

        # Strategy 2: Parse JS properties from HTML (regex)
        result = self._parse_properties_from_html(html)
        if result is not None:
            report_count, page_status = result
            status = page_status or self._classify_status(report_count)
            return ScrapeResult(
                service=service,
                report_count=report_count,
                timestamp=datetime.now(timezone.utc).isoformat(),
                status=status,
                source="curl",
            )

        # Detect Next.js client-rendered page (no embedded data, needs JS execution)
        if "_next/static" in html and "window.DD" not in html:
            if self._debug_dump:
                self._dump_html(service, html, suffix="_curl_nextjs")
            raise CurlBlockedError(200, "Next.js client-rendered page, needs Playwright")

        # Strategy 3: Text-based fallback (strip HTML tags)
        body_text = re.sub(r"<[^>]+>", " ", html)

        if "no current problems" in body_text.lower():
            return ScrapeResult(
                service=service,
                report_count=0,
                timestamp=datetime.now(timezone.utc).isoformat(),
                status="ok",
                source="curl",
            )

        count = self._parse_report_text(body_text)
        if count is not None:
            return ScrapeResult(
                service=service,
                report_count=count,
                timestamp=datetime.now(timezone.utc).isoformat(),
                status=self._classify_status(count),
                source="curl",
            )

        logger.warning("curl_cffi: could not extract report count for %s, defaulting to 0", service)
        return ScrapeResult(
            service=service,
            report_count=0,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status="ok",
            source="curl",
        )

    async def _dismiss_consent_popup(self) -> None:
        """Dismiss cookie consent popups if present."""
        consent_selectors = [
            'button:has-text("Consent")',
            'button:has-text("Accept")',
            'button:has-text("I agree")',
            '.fc-cta-consent',
        ]
        for sel in consent_selectors:
            try:
                btn = self._page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    logger.info("Dismissed consent popup via: %s", sel)
                    await self._page.wait_for_timeout(1000)
                    return
            except Exception:
                continue

    async def _click_skip_link(self) -> None:
        """Click the 'skip' button to reveal chart data on DownDetector."""
        try:
            # The skip button appears as "Report a problem to see the chart, or skip"
            skip_btn = self._page.locator('button:has-text("skip")').first
            if await skip_btn.is_visible(timeout=3000):
                await skip_btn.click()
                logger.info("Clicked 'skip' button to reveal chart")
                await self._page.wait_for_timeout(2000)  # Wait for chart to load
        except Exception:
            # Skip button may not be present if chart is already visible
            pass

    async def _do_scrape_playwright(self, service: str, url: str) -> ScrapeResult:
        """Perform the actual page scrape using Playwright (fallback)."""
        if not self._page:
            raise RuntimeError("Playwright not started.")

        await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        wait_ms = random.randint(2000, 5000)
        await self._page.wait_for_timeout(wait_ms)

        # Detect and wait through Cloudflare challenge pages
        if await self._is_cloudflare_challenge():
            logger.info("Cloudflare challenge detected for %s, waiting for auto-resolve...", service)
            resolved = False
            for _ in range(5):
                await self._page.wait_for_timeout(1000)
                if not await self._is_cloudflare_challenge():
                    logger.info("Cloudflare challenge auto-resolved for %s", service)
                    resolved = True
                    break
            if not resolved:
                logger.info("Attempting to click Cloudflare Turnstile checkbox for %s", service)
                if await self._click_cloudflare_checkbox():
                    for _ in range(15):
                        await self._page.wait_for_timeout(1000)
                        if not await self._is_cloudflare_challenge():
                            logger.info("Cloudflare challenge resolved after click for %s", service)
                            resolved = True
                            break
            if not resolved:
                logger.warning("Cloudflare challenge did not resolve for %s", service)

        # Dismiss cookie consent popups before data extraction
        await self._dismiss_consent_popup()

        # Click "skip" link to reveal chart data (required on DownDetector)
        await self._click_skip_link()

        if self._debug_dump:
            await self._dump_page(service)

        report_count, page_status = await self._extract_from_page(self._page)
        status = page_status or self._classify_status(report_count)

        return ScrapeResult(
            service=service,
            report_count=report_count,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status=status,
            source="playwright",
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

    async def _click_cloudflare_checkbox(self) -> bool:
        """Attempt to click the Cloudflare Turnstile checkbox."""
        await self._page.wait_for_timeout(2000)

        # Strategy 1: Find the widget container and click at checkbox coords
        try:
            box = await self._page.evaluate("""() => {
                const input = document.querySelector('[name="cf-turnstile-response"]');
                if (!input) return null;
                let container = input.closest('div[style*="grid"]');
                if (!container) container = input.parentElement?.parentElement?.parentElement;
                if (!container) return null;
                const rect = container.getBoundingClientRect();
                return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
            }""")
            if box and box["width"] > 0 and box["height"] > 0:
                click_x = box["x"] + 30
                click_y = box["y"] + box["height"] / 2
                await self._page.mouse.move(click_x + 100, click_y + 50)
                await self._page.wait_for_timeout(random.randint(200, 500))
                await self._page.mouse.move(click_x, click_y)
                await self._page.wait_for_timeout(random.randint(100, 300))
                await self._page.mouse.click(click_x, click_y)
                logger.info(
                    "Clicked Turnstile widget at (%.0f, %.0f) container=%.0fx%.0f",
                    click_x, click_y, box["width"], box["height"],
                )
                return True
        except Exception as exc:
            logger.debug("Strategy 1 (container coords) failed: %s", exc)

        # Strategy 2: Find and click inside the Turnstile frame directly
        cf_frame = None
        for frame in self._page.frames:
            if "challenges.cloudflare.com" in frame.url:
                cf_frame = frame
                break

        if cf_frame:
            logger.info("Found Turnstile frame: %s", cf_frame.url[:80])
            for selector in ["input[type='checkbox']", ".ctp-checkbox-label", "body"]:
                try:
                    await cf_frame.locator(selector).first.click(timeout=3000)
                    logger.info("Clicked inside Turnstile frame via '%s'", selector)
                    return True
                except Exception:
                    continue

        logger.debug(
            "Could not click Turnstile checkbox (frames=%s)",
            [f.url[:60] for f in self._page.frames],
        )
        return False

    def _dump_html(self, service: str, html: str, suffix: str = "") -> None:
        """Save HTML content for debugging."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / f"debug_{service}{suffix}.html"
        try:
            path.write_text(html, encoding="utf-8")
            logger.info("Debug dump: saved %s (%d bytes)", path, len(html))
        except Exception as exc:
            logger.warning("Debug dump HTML failed: %s", exc)

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

    async def _extract_from_page(self, page) -> tuple[int, Optional[str]]:
        """Extract report count and status from the page.

        Returns (report_count, status_string_or_None).
        """
        # Strategy 1: Extract from window.DD.currentServiceProperties JS object (legacy)
        try:
            props = await page.evaluate(
                "() => window.DD && window.DD.currentServiceProperties"
            )
            if props:
                return self._parse_service_properties(props)
        except Exception as exc:
            logger.debug("window.DD extraction failed: %s", exc)

        # Strategy 2: Parse the JS from page source as regex fallback (legacy)
        html = await page.content()
        result = self._parse_properties_from_html(html)
        if result is not None:
            return result

        # Strategy 3: Extract from Recharts SVG (Next.js pages)
        try:
            recharts_result = await self._extract_from_recharts(page)
            if recharts_result is not None:
                return recharts_result
        except Exception as exc:
            logger.debug("Recharts extraction failed: %s", exc)

        # Strategy 4: Text-based fallback (check for "no current problems" only)
        body_text = await page.inner_text("body")

        if "no current problems" in body_text.lower():
            return 0, "ok"

        # Note: We don't use _parse_report_text here as it incorrectly matches
        # Y-axis labels like "100" followed by "Report a problem" text.

        logger.warning("Could not extract report count, defaulting to 0")
        return 0, None

    async def _extract_from_recharts(self, page) -> Optional[tuple[int, Optional[str]]]:
        """Extract report count from Recharts SVG chart (Next.js pages).

        Parses the SVG path coordinates to calculate the current report count.
        Returns (report_count, status) or None if extraction fails.
        """
        js_code = """() => {
            const wrapper = document.querySelector('.recharts-wrapper');
            if (!wrapper) return null;

            // Get Y-axis scale (max value)
            const yTicks = wrapper.querySelectorAll('.recharts-yAxis .recharts-cartesian-axis-tick-value');
            const yValues = Array.from(yTicks).map(t => parseFloat(t.textContent) || 0);
            const yMax = Math.max(...yValues);
            if (yMax <= 0) return null;

            // Use .recharts-area-curve (actual data line) not .recharts-area-area (fill path)
            // The fill path returns to baseline, giving incorrect Y values
            const areaCurve = wrapper.querySelector('.recharts-area-curve');
            const areaArea = wrapper.querySelector('.recharts-area-area');
            const pathEl = areaCurve || areaArea;
            if (!pathEl) return null;

            const pathD = pathEl.getAttribute('d');
            if (!pathD) return null;

            // Parse Y coordinates from SVG path (format: M49,212L61.66,212...)
            const yCoords = [];
            const regex = /[ML]([\\d.]+),([\\d.]+)/g;
            let match;
            while ((match = regex.exec(pathD)) !== null) {
                yCoords.push(parseFloat(match[2]));
            }

            if (!yCoords.length) return null;

            // Baseline is the max Y coordinate (bottom of chart = 0 reports)
            // SVG Y-axis is inverted: higher Y = lower value
            const baseline = Math.max(...yCoords);
            if (baseline <= 0) return null;

            // Calculate report count for the last data point (most recent)
            const lastY = yCoords[yCoords.length - 1];
            const lastReports = Math.round(yMax * (baseline - lastY) / baseline);

            return { reports: lastReports, yMax: yMax };
        }"""

        result = await page.evaluate(js_code)
        if not result:
            return None

        report_count = result.get("reports", 0)
        status = self._classify_status(report_count)
        logger.debug("Recharts extraction: %d reports (yMax=%s)", report_count, result.get("yMax"))
        return report_count, status

    @staticmethod
    def _parse_service_properties(props: dict) -> tuple[int, Optional[str]]:
        """Parse the window.DD.currentServiceProperties object."""
        status_map = {
            "success": "ok",
            "warning": "warning",
            "danger": "danger",
        }
        page_status = status_map.get(props.get("status", ""), None)

        report_count = 0
        try:
            data_points = props["series"]["reports"]["data"]
            if data_points:
                report_count = int(data_points[-1].get("y", 0))
        except (KeyError, TypeError, IndexError):
            pass

        return report_count, page_status

    @staticmethod
    def _parse_properties_from_html(html: str) -> Optional[tuple[int, Optional[str]]]:
        """Regex fallback: extract currentServiceProperties from raw HTML."""
        status_match = re.search(
            r"currentServiceProperties\s*=\s*\{[^}]*status:\s*'(\w+)'",
            html,
        )
        status_map = {"success": "ok", "warning": "warning", "danger": "danger"}
        page_status = status_map.get(
            status_match.group(1), None
        ) if status_match else None

        y_values = re.findall(
            r"\{\s*x:\s*'[^']+',\s*y:\s*(\d+)\s*\}",
            html,
        )
        if y_values:
            report_count = int(y_values[-1])
            return report_count, page_status

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

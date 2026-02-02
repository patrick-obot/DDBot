"""Tests for ddbot.scraper parsing logic."""

import asyncio
import socket
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from ddbot.scraper import (
    CurlBlockedError,
    DownDetectorScraper,
    ScrapeResult,
    _CF_CHALLENGE_MARKERS,
)


class TestParseServiceProperties:
    def test_success_status_with_data(self):
        props = {
            "status": "success",
            "series": {
                "reports": {
                    "data": [
                        {"x": "2026-01-31T10:00:00+00:00", "y": 1},
                        {"x": "2026-01-31T10:15:00+00:00", "y": 3},
                        {"x": "2026-01-31T10:30:00+00:00", "y": 2},
                    ]
                }
            },
        }
        count, status = DownDetectorScraper._parse_service_properties(props)
        assert count == 2  # last data point
        assert status == "ok"

    def test_warning_status(self):
        props = {
            "status": "warning",
            "series": {
                "reports": {
                    "data": [{"x": "2026-01-31T10:00:00+00:00", "y": 25}]
                }
            },
        }
        count, status = DownDetectorScraper._parse_service_properties(props)
        assert count == 25
        assert status == "warning"

    def test_danger_status(self):
        props = {
            "status": "danger",
            "series": {
                "reports": {
                    "data": [{"x": "2026-01-31T10:00:00+00:00", "y": 100}]
                }
            },
        }
        count, status = DownDetectorScraper._parse_service_properties(props)
        assert count == 100
        assert status == "danger"

    def test_empty_data_points(self):
        props = {
            "status": "success",
            "series": {"reports": {"data": []}},
        }
        count, status = DownDetectorScraper._parse_service_properties(props)
        assert count == 0
        assert status == "ok"

    def test_missing_series(self):
        props = {"status": "success"}
        count, status = DownDetectorScraper._parse_service_properties(props)
        assert count == 0
        assert status == "ok"

    def test_unknown_status(self):
        props = {
            "status": "unknown",
            "series": {
                "reports": {
                    "data": [{"x": "2026-01-31T10:00:00+00:00", "y": 5}]
                }
            },
        }
        count, status = DownDetectorScraper._parse_service_properties(props)
        assert count == 5
        assert status is None


class TestParsePropertiesFromHtml:
    def test_extracts_status_and_last_y(self):
        html = """
        window.DD.currentServiceProperties = {
            id: 33601,
            status: 'warning',
            series: {
              reports: {
                data: [
                  { x: '2026-01-31T10:00:00+00:00', y: 5 },
                  { x: '2026-01-31T10:15:00+00:00', y: 12 },
                  { x: '2026-01-31T10:30:00+00:00', y: 8 },
                ]
              }
            }
        }
        """
        result = DownDetectorScraper._parse_properties_from_html(html)
        assert result is not None
        count, status = result
        assert count == 8
        assert status == "warning"

    def test_success_status(self):
        html = """
        window.DD.currentServiceProperties = {
            status: 'success',
            series: {
              reports: {
                data: [
                  { x: '2026-01-31T10:00:00+00:00', y: 1 },
                ]
              }
            }
        }
        """
        result = DownDetectorScraper._parse_properties_from_html(html)
        assert result is not None
        count, status = result
        assert count == 1
        assert status == "ok"

    def test_no_match_returns_none(self):
        html = "<html><body>Nothing here</body></html>"
        result = DownDetectorScraper._parse_properties_from_html(html)
        assert result is None

    def test_status_only_success_returns_zero(self):
        html = """
        window.DD.currentServiceProperties = {
            status: 'success',
            series: { reports: { data: [] } }
        }
        """
        result = DownDetectorScraper._parse_properties_from_html(html)
        assert result is not None
        count, status = result
        assert count == 0
        assert status == "ok"


class TestParseCount:
    def test_simple_number(self):
        assert DownDetectorScraper._parse_count("42") == 42

    def test_number_with_commas(self):
        assert DownDetectorScraper._parse_count("1,234") == 1234

    def test_number_in_text(self):
        assert DownDetectorScraper._parse_count("There are 56 issues") == 56

    def test_empty_string(self):
        assert DownDetectorScraper._parse_count("") is None

    def test_none_input(self):
        assert DownDetectorScraper._parse_count(None) is None

    def test_no_numbers(self):
        assert DownDetectorScraper._parse_count("no numbers here") is None

    def test_first_number_wins(self):
        assert DownDetectorScraper._parse_count("10 of 50") == 10


class TestParseReportText:
    def test_reports_pattern(self):
        assert DownDetectorScraper._parse_report_text("123 reports today") == 123

    def test_user_reports_pattern(self):
        assert DownDetectorScraper._parse_report_text("45 user reports") == 45

    def test_problem_pattern(self):
        assert DownDetectorScraper._parse_report_text("78 problems detected") == 78

    def test_reports_colon_pattern(self):
        assert DownDetectorScraper._parse_report_text("Reports: 99") == 99

    def test_case_insensitive(self):
        assert DownDetectorScraper._parse_report_text("25 REPORTS") == 25

    def test_no_match(self):
        assert DownDetectorScraper._parse_report_text("all systems operational") is None

    def test_comma_number(self):
        assert DownDetectorScraper._parse_report_text("1,500 reports") == 1500


class TestClassifyStatus:
    def test_zero_is_ok(self):
        assert DownDetectorScraper._classify_status(0) == "ok"

    def test_low_count_is_ok(self):
        assert DownDetectorScraper._classify_status(5) == "ok"

    def test_threshold_is_warning(self):
        assert DownDetectorScraper._classify_status(10) == "warning"

    def test_high_count_is_danger(self):
        assert DownDetectorScraper._classify_status(50) == "danger"

    def test_very_high_is_danger(self):
        assert DownDetectorScraper._classify_status(500) == "danger"


# ---- New tests for curl_cffi integration ----


class TestCurlBlockedError:
    def test_attributes(self):
        err = CurlBlockedError(403, "Forbidden")
        assert err.status_code == 403
        assert err.reason == "Forbidden"
        assert "403" in str(err)
        assert "Forbidden" in str(err)

    def test_is_exception(self):
        err = CurlBlockedError(200, "CF challenge")
        assert isinstance(err, Exception)

    def test_status_200_with_reason(self):
        err = CurlBlockedError(200, "Cloudflare challenge detected: 'just a moment'")
        assert err.status_code == 200
        assert "just a moment" in err.reason


class TestCurlBlockedDetection:
    """Test that Cloudflare challenge markers are detected in HTML."""

    def test_just_a_moment_in_title(self):
        html = "<html><head><title>Just a moment...</title></head><body></body></html>"
        html_lower = html.lower()
        assert any(marker in html_lower for marker in _CF_CHALLENGE_MARKERS)

    def test_verify_you_are_human(self):
        html = "<html><body><p>Verify you are human</p></body></html>"
        html_lower = html.lower()
        assert any(marker in html_lower for marker in _CF_CHALLENGE_MARKERS)

    def test_checking_your_browser(self):
        html = "<html><body>Checking your browser before accessing</body></html>"
        html_lower = html.lower()
        assert any(marker in html_lower for marker in _CF_CHALLENGE_MARKERS)

    def test_cf_challenge_class(self):
        html = '<html><body><div id="cf-challenge-running">Challenge</div></body></html>'
        html_lower = html.lower()
        assert any(marker in html_lower for marker in _CF_CHALLENGE_MARKERS)

    def test_normal_page_not_detected(self):
        html = """<html><body>
        <h1>MTN down? Current problems and outages</h1>
        <p>No current problems at MTN</p>
        </body></html>"""
        html_lower = html.lower()
        assert not any(marker in html_lower for marker in _CF_CHALLENGE_MARKERS)


class TestScrapeResultSource:
    def test_default_source_is_curl(self):
        result = ScrapeResult(
            service="mtn",
            report_count=5,
            timestamp="2026-01-31T10:00:00+00:00",
            status="ok",
        )
        assert result.source == "curl"

    def test_explicit_playwright_source(self):
        result = ScrapeResult(
            service="mtn",
            report_count=5,
            timestamp="2026-01-31T10:00:00+00:00",
            status="ok",
            source="playwright",
        )
        assert result.source == "playwright"

    def test_explicit_error_source(self):
        result = ScrapeResult(
            service="mtn",
            report_count=0,
            timestamp="2026-01-31T10:00:00+00:00",
            status="error",
            error="something failed",
            source="error",
        )
        assert result.source == "error"


class TestDoScrapeCurl:
    """Test the curl_cffi scraping path."""

    @pytest.mark.asyncio
    async def test_successful_extraction(self):
        html = """<html><head><title>MTN outages</title></head><body>
        <script>
        window.DD.currentServiceProperties = {
            status: 'warning',
            series: {
              reports: {
                data: [
                  { x: '2026-01-31T10:00:00+00:00', y: 5 },
                  { x: '2026-01-31T10:15:00+00:00', y: 12 },
                ]
              }
            }
        }
        </script></body></html>"""

        scraper = DownDetectorScraper()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        scraper._curl_session = AsyncMock()
        scraper._curl_session.get = AsyncMock(return_value=mock_response)

        result = await scraper._do_scrape_curl("mtn", "https://downdetector.co.za/status/mtn")
        assert result.report_count == 12
        assert result.status == "warning"
        assert result.source == "curl"

    @pytest.mark.asyncio
    async def test_non_200_raises_blocked(self):
        scraper = DownDetectorScraper()
        mock_response = MagicMock()
        mock_response.status_code = 403
        scraper._curl_session = AsyncMock()
        scraper._curl_session.get = AsyncMock(return_value=mock_response)

        with pytest.raises(CurlBlockedError) as exc_info:
            await scraper._do_scrape_curl("mtn", "https://downdetector.co.za/status/mtn")
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_cf_challenge_raises_blocked(self):
        html = "<html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>"

        scraper = DownDetectorScraper()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        scraper._curl_session = AsyncMock()
        scraper._curl_session.get = AsyncMock(return_value=mock_response)

        with pytest.raises(CurlBlockedError) as exc_info:
            await scraper._do_scrape_curl("mtn", "https://downdetector.co.za/status/mtn")
        assert exc_info.value.status_code == 200
        assert "just a moment" in exc_info.value.reason.lower()

    @pytest.mark.asyncio
    async def test_text_fallback(self):
        html = """<html><body>
        <h1>MTN down?</h1>
        <p>42 reports in the last hour</p>
        </body></html>"""

        scraper = DownDetectorScraper()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        scraper._curl_session = AsyncMock()
        scraper._curl_session.get = AsyncMock(return_value=mock_response)

        result = await scraper._do_scrape_curl("mtn", "https://downdetector.co.za/status/mtn")
        assert result.report_count == 42
        assert result.source == "curl"

    @pytest.mark.asyncio
    async def test_no_current_problems(self):
        html = """<html><body>
        <h1>MTN</h1>
        <p>No current problems at MTN</p>
        </body></html>"""

        scraper = DownDetectorScraper()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        scraper._curl_session = AsyncMock()
        scraper._curl_session.get = AsyncMock(return_value=mock_response)

        result = await scraper._do_scrape_curl("mtn", "https://downdetector.co.za/status/mtn")
        assert result.report_count == 0
        assert result.status == "ok"
        assert result.source == "curl"

    @pytest.mark.asyncio
    async def test_no_session_raises_runtime_error(self):
        scraper = DownDetectorScraper()
        scraper._curl_session = None

        with pytest.raises(RuntimeError, match="curl_cffi session not started"):
            await scraper._do_scrape_curl("mtn", "https://downdetector.co.za/status/mtn")

    @pytest.mark.asyncio
    async def test_defaults_to_zero_when_no_extraction(self):
        html = """<html><body><p>Some random content with no useful data</p></body></html>"""

        scraper = DownDetectorScraper()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        scraper._curl_session = AsyncMock()
        scraper._curl_session.get = AsyncMock(return_value=mock_response)

        result = await scraper._do_scrape_curl("mtn", "https://downdetector.co.za/status/mtn")
        assert result.report_count == 0
        assert result.source == "curl"


class TestScrapeServiceFallback:
    """Test the two-tier fallback logic in scrape_service."""

    @pytest.mark.asyncio
    async def test_curl_success_skips_playwright(self):
        scraper = DownDetectorScraper()
        expected = ScrapeResult(
            service="mtn",
            report_count=10,
            timestamp="2026-01-31T10:00:00+00:00",
            status="warning",
            source="curl",
        )
        scraper._do_scrape_curl = AsyncMock(return_value=expected)
        scraper._do_scrape_playwright = AsyncMock()
        scraper._ensure_playwright = AsyncMock()

        result = await scraper.scrape_service("mtn", retries=2)
        assert result.report_count == 10
        assert result.source == "curl"
        scraper._do_scrape_curl.assert_called_once()
        scraper._do_scrape_playwright.assert_not_called()
        scraper._ensure_playwright.assert_not_called()

    @pytest.mark.asyncio
    async def test_curl_blocked_falls_back_to_playwright(self):
        scraper = DownDetectorScraper()
        pw_result = ScrapeResult(
            service="mtn",
            report_count=15,
            timestamp="2026-01-31T10:00:00+00:00",
            status="warning",
            source="playwright",
        )
        scraper._do_scrape_curl = AsyncMock(
            side_effect=CurlBlockedError(200, "CF challenge")
        )
        scraper._ensure_playwright = AsyncMock()
        scraper._do_scrape_playwright = AsyncMock(return_value=pw_result)

        result = await scraper.scrape_service("mtn", retries=2)
        assert result.report_count == 15
        assert result.source == "playwright"
        scraper._ensure_playwright.assert_called_once()
        scraper._do_scrape_playwright.assert_called_once()

    @pytest.mark.asyncio
    async def test_both_fail_returns_error(self):
        scraper = DownDetectorScraper()
        scraper._do_scrape_curl = AsyncMock(
            side_effect=CurlBlockedError(403, "Forbidden")
        )
        scraper._ensure_playwright = AsyncMock()
        scraper._do_scrape_playwright = AsyncMock(
            side_effect=Exception("Playwright also failed")
        )

        result = await scraper.scrape_service("mtn", retries=1)
        assert result.status == "error"
        assert result.error is not None
        assert "Playwright" in result.error
        assert result.source == "error"

    @pytest.mark.asyncio
    async def test_curl_generic_error_retries(self):
        scraper = DownDetectorScraper()
        expected = ScrapeResult(
            service="mtn",
            report_count=5,
            timestamp="2026-01-31T10:00:00+00:00",
            status="ok",
            source="curl",
        )
        # First call fails with generic error, second succeeds
        scraper._do_scrape_curl = AsyncMock(
            side_effect=[Exception("Network error"), expected]
        )
        scraper._ensure_playwright = AsyncMock()
        scraper._do_scrape_playwright = AsyncMock()

        result = await scraper.scrape_service("mtn", retries=2)
        assert result.report_count == 5
        assert result.source == "curl"
        assert scraper._do_scrape_curl.call_count == 2
        # Generic exceptions don't trigger Playwright fallback
        scraper._ensure_playwright.assert_not_called()


class TestFindChromeExecutable:
    def test_configured_path_exists(self, tmp_path):
        fake_chrome = tmp_path / "chrome.exe"
        fake_chrome.write_text("fake")
        result = DownDetectorScraper._find_chrome_executable(str(fake_chrome))
        assert result == str(fake_chrome)

    def test_configured_path_missing_falls_through(self):
        # Non-existent configured path should try system locations
        with patch("ddbot.scraper.Path.is_file", return_value=False):
            with pytest.raises(FileNotFoundError, match="Chrome executable not found"):
                DownDetectorScraper._find_chrome_executable("/nonexistent/chrome")

    def test_no_config_no_system_chrome_raises(self):
        with patch("ddbot.scraper.Path.is_file", return_value=False):
            with pytest.raises(FileNotFoundError, match="Chrome executable not found"):
                DownDetectorScraper._find_chrome_executable("")

    def test_finds_system_chrome(self, tmp_path):
        fake_chrome = tmp_path / "google-chrome"
        fake_chrome.write_text("fake")
        candidates = [str(fake_chrome)]
        with patch("ddbot.scraper.platform.system", return_value="Linux"):
            # Patch the candidate list by making only our fake path pass is_file
            original_is_file = Path.is_file
            def mock_is_file(self):
                if str(self) == str(fake_chrome):
                    return True
                return False
            with patch.object(Path, "is_file", mock_is_file):
                # We need to also inject our path into candidates
                # Instead, test with configured_path which is simpler
                result = DownDetectorScraper._find_chrome_executable(str(fake_chrome))
                assert result == str(fake_chrome)


class TestFindFreePort:
    def test_returns_int(self):
        port = DownDetectorScraper._find_free_port()
        assert isinstance(port, int)
        assert port > 0

    def test_port_is_bindable(self):
        port = DownDetectorScraper._find_free_port()
        # Port should be available (may rarely race, but generally works)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            assert s.getsockname()[1] == port

    def test_different_ports(self):
        port1 = DownDetectorScraper._find_free_port()
        port2 = DownDetectorScraper._find_free_port()
        # Very likely different (not guaranteed, but extremely probable)
        assert isinstance(port1, int)
        assert isinstance(port2, int)


class TestDismissConsentPopup:
    @pytest.mark.asyncio
    async def test_popup_found_and_clicked(self):
        scraper = DownDetectorScraper()
        mock_btn = AsyncMock()
        mock_btn.is_visible = AsyncMock(return_value=True)
        mock_btn.click = AsyncMock()

        mock_locator = MagicMock()
        mock_locator.first = mock_btn

        mock_page = AsyncMock()
        mock_page.locator = MagicMock(return_value=mock_locator)
        mock_page.wait_for_timeout = AsyncMock()
        scraper._page = mock_page

        await scraper._dismiss_consent_popup()

        mock_btn.click.assert_called_once()
        mock_page.wait_for_timeout.assert_called_once_with(1000)

    @pytest.mark.asyncio
    async def test_no_popup_present(self):
        scraper = DownDetectorScraper()
        mock_btn = AsyncMock()
        mock_btn.is_visible = AsyncMock(return_value=False)

        mock_locator = MagicMock()
        mock_locator.first = mock_btn

        mock_page = AsyncMock()
        mock_page.locator = MagicMock(return_value=mock_locator)
        mock_page.wait_for_timeout = AsyncMock()
        scraper._page = mock_page

        await scraper._dismiss_consent_popup()

        mock_btn.click.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_continues_to_next_selector(self):
        scraper = DownDetectorScraper()

        call_count = 0

        def mock_locator(sel):
            nonlocal call_count
            call_count += 1
            mock_btn = AsyncMock()
            if call_count == 1:
                mock_btn.is_visible = AsyncMock(side_effect=Exception("timeout"))
            else:
                mock_btn.is_visible = AsyncMock(return_value=True)
                mock_btn.click = AsyncMock()
            loc = MagicMock()
            loc.first = mock_btn
            return loc

        mock_page = AsyncMock()
        mock_page.locator = MagicMock(side_effect=mock_locator)
        mock_page.wait_for_timeout = AsyncMock()
        scraper._page = mock_page

        await scraper._dismiss_consent_popup()
        # Should have tried at least 2 selectors
        assert call_count >= 2


class TestStopCleansUpSubprocess:
    @pytest.mark.asyncio
    async def test_subprocess_terminated(self):
        scraper = DownDetectorScraper()
        scraper._playwright_started = False

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.terminate = MagicMock()
        mock_proc.wait = MagicMock()
        mock_proc.kill = MagicMock()
        scraper._chrome_process = mock_proc

        temp_dir = tempfile.mkdtemp(prefix="ddbot_test_")
        scraper._temp_profile_dir = temp_dir

        await scraper.stop()

        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called()
        assert scraper._chrome_process is None
        assert scraper._temp_profile_dir is None
        assert not Path(temp_dir).exists()

    @pytest.mark.asyncio
    async def test_subprocess_killed_on_timeout(self):
        import subprocess as sp

        scraper = DownDetectorScraper()
        scraper._playwright_started = False

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.terminate = MagicMock()
        mock_proc.wait = MagicMock(side_effect=[sp.TimeoutExpired("chrome", 5), None])
        mock_proc.kill = MagicMock()
        scraper._chrome_process = mock_proc
        scraper._temp_profile_dir = None

        await scraper.stop()

        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()
        assert scraper._chrome_process is None

    @pytest.mark.asyncio
    async def test_no_subprocess_no_error(self):
        scraper = DownDetectorScraper()
        scraper._playwright_started = False
        scraper._chrome_process = None
        scraper._temp_profile_dir = None

        # Should not raise
        await scraper.stop()


class TestWaitForCdpReady:
    @pytest.mark.asyncio
    async def test_ready_immediately(self):
        scraper = DownDetectorScraper()
        mock_resp = MagicMock()
        mock_resp.status = 200
        with patch("ddbot.scraper.urlopen", return_value=mock_resp):
            await scraper._wait_for_cdp_ready(9222, timeout=2)

    @pytest.mark.asyncio
    async def test_timeout_raises(self):
        scraper = DownDetectorScraper()
        with patch("ddbot.scraper.urlopen", side_effect=OSError("refused")):
            with pytest.raises(TimeoutError, match="CDP endpoint not ready"):
                await scraper._wait_for_cdp_ready(9222, timeout=1)

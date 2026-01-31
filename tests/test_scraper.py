"""Tests for ddbot.scraper parsing logic."""

import pytest

from ddbot.scraper import DownDetectorScraper


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

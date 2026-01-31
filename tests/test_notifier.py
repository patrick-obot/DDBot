"""Tests for ddbot.notifier."""

import pytest

from ddbot.notifier import format_alert_message, format_phone_for_greenapi


class TestFormatAlertMessage:
    def test_contains_service_name(self):
        msg = format_alert_message("mtn", 25, 10)
        assert "MTN" in msg

    def test_contains_report_count(self):
        msg = format_alert_message("mtn", 25, 10)
        assert "25" in msg

    def test_contains_threshold(self):
        msg = format_alert_message("mtn", 25, 10)
        assert "10" in msg

    def test_contains_url(self):
        msg = format_alert_message("vodacom", 15, 10)
        assert "https://downdetector.co.za/status/vodacom" in msg

    def test_service_lowercased_in_url(self):
        msg = format_alert_message("MTN", 15, 10)
        assert "https://downdetector.co.za/status/mtn" in msg

    def test_contains_warning_emoji(self):
        msg = format_alert_message("mtn", 15, 10)
        assert "\u26a0" in msg


class TestFormatPhone:
    def test_plain_number(self):
        assert format_phone_for_greenapi("27821234567") == "27821234567@c.us"

    def test_plus_prefix(self):
        assert format_phone_for_greenapi("+27821234567") == "27821234567@c.us"

    def test_already_formatted(self):
        assert format_phone_for_greenapi("27821234567@c.us") == "27821234567@c.us"

    def test_strips_spaces(self):
        assert format_phone_for_greenapi("  27 82 123 4567 ") == "27821234567@c.us"

    def test_strips_dashes(self):
        assert format_phone_for_greenapi("27-82-123-4567") == "27821234567@c.us"

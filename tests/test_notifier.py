"""Tests for ddbot.notifier."""

import pytest

from ddbot.notifier import (
    format_alert_message,
    format_recipient_for_openclaw,
    is_group_jid,
    normalize_recipient,
)


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


class TestIsGroupJid:
    def test_group_jid(self):
        assert is_group_jid("120363044xxxxx@g.us") is True

    def test_group_jid_with_whitespace(self):
        assert is_group_jid("  120363044xxxxx@g.us ") is True

    def test_phone_number(self):
        assert is_group_jid("27821234567") is False

    def test_phone_with_plus(self):
        assert is_group_jid("+27821234567") is False


class TestNormalizeRecipient:
    def test_phone_strips_plus(self):
        assert normalize_recipient("+27821234567") == "27821234567"

    def test_phone_strips_spaces(self):
        assert normalize_recipient("  27 82 123 4567 ") == "27821234567"

    def test_phone_strips_dashes(self):
        assert normalize_recipient("27-82-123-4567") == "27821234567"

    def test_group_jid_unchanged(self):
        assert normalize_recipient("120363044xxxxx@g.us") == "120363044xxxxx@g.us"

    def test_group_jid_strips_whitespace(self):
        assert normalize_recipient("  120363044xxxxx@g.us  ") == "120363044xxxxx@g.us"


class TestFormatRecipientForOpenclaw:
    def test_phone_gets_plus_prefix(self):
        assert format_recipient_for_openclaw("27821234567") == "+27821234567"

    def test_phone_with_plus_no_double(self):
        assert format_recipient_for_openclaw("+27821234567") == "+27821234567"

    def test_group_jid_no_plus(self):
        assert format_recipient_for_openclaw("120363044xxxxx@g.us") == "120363044xxxxx@g.us"

    def test_phone_cleans_and_prefixes(self):
        assert format_recipient_for_openclaw("  27-82-123-4567 ") == "+27821234567"

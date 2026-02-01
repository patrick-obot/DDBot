"""Tests for ddbot.main active hours logic."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from ddbot.config import Config
from ddbot.main import is_within_active_hours


class TestIsWithinActiveHours:
    def _make_config(self, start=7, end=20, tz="Africa/Johannesburg"):
        return Config(
            active_hours_start=start,
            active_hours_end=end,
            timezone=tz,
            openclaw_gateway_token="t",
            whatsapp_recipients=["27000"],
        )

    def test_within_hours(self):
        config = self._make_config(start=7, end=20, tz="UTC")
        with patch("ddbot.main.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 15, 12, 0, tzinfo=ZoneInfo("UTC"))
            assert is_within_active_hours(config) is True

    def test_before_start(self):
        config = self._make_config(start=7, end=20, tz="UTC")
        with patch("ddbot.main.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 15, 5, 0, tzinfo=ZoneInfo("UTC"))
            assert is_within_active_hours(config) is False

    def test_after_end(self):
        config = self._make_config(start=7, end=20, tz="UTC")
        with patch("ddbot.main.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 15, 21, 0, tzinfo=ZoneInfo("UTC"))
            assert is_within_active_hours(config) is False

    def test_at_start_boundary(self):
        config = self._make_config(start=7, end=20, tz="UTC")
        with patch("ddbot.main.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 15, 7, 0, tzinfo=ZoneInfo("UTC"))
            assert is_within_active_hours(config) is True

    def test_at_end_boundary(self):
        config = self._make_config(start=7, end=20, tz="UTC")
        with patch("ddbot.main.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 15, 20, 0, tzinfo=ZoneInfo("UTC"))
            assert is_within_active_hours(config) is False

    def test_respects_timezone(self):
        # 21:00 UTC = 23:00 SAST — outside 7-20
        config = self._make_config(start=7, end=20, tz="Africa/Johannesburg")
        with patch("ddbot.main.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(
                2026, 1, 15, 23, 0, tzinfo=ZoneInfo("Africa/Johannesburg")
            )
            assert is_within_active_hours(config) is False

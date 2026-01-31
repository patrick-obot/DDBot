"""Tests for ddbot.history."""

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from ddbot.history import AlertHistory, AlertRecord


@pytest.fixture
def tmp_history(tmp_path):
    """Create an AlertHistory backed by a temp file."""
    return AlertHistory(history_file=tmp_path / "test_history.json")


class TestAlertRecord:
    def test_round_trip(self):
        record = AlertRecord(
            service="mtn",
            report_count=25,
            timestamp="2025-01-01T00:00:00+00:00",
            recipients=["27111"],
        )
        data = record.to_dict()
        restored = AlertRecord.from_dict(data)
        assert restored.service == "mtn"
        assert restored.report_count == 25
        assert restored.recipients == ["27111"]


class TestAlertHistory:
    def test_record_and_retrieve(self, tmp_history):
        tmp_history.record_alert("mtn", 15, ["27111"])
        records = tmp_history.get_all()
        assert len(records) == 1
        assert records[0].service == "mtn"
        assert records[0].report_count == 15

    def test_persistence(self, tmp_path):
        path = tmp_path / "history.json"
        h1 = AlertHistory(history_file=path)
        h1.record_alert("mtn", 20, ["27111"])

        # New instance should load from file
        h2 = AlertHistory(history_file=path)
        assert len(h2.get_all()) == 1
        assert h2.get_all()[0].service == "mtn"

    def test_cooldown_active(self, tmp_history):
        tmp_history.record_alert("mtn", 20, ["27111"])
        assert tmp_history.is_in_cooldown("mtn", cooldown_seconds=3600) is True

    def test_cooldown_different_service(self, tmp_history):
        tmp_history.record_alert("mtn", 20, ["27111"])
        assert tmp_history.is_in_cooldown("vodacom", cooldown_seconds=3600) is False

    def test_cooldown_expired(self, tmp_path):
        path = tmp_path / "history.json"
        # Write a record with an old timestamp
        old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        data = [
            {
                "service": "mtn",
                "report_count": 20,
                "timestamp": old_time,
                "recipients": ["27111"],
            }
        ]
        path.write_text(json.dumps(data))

        history = AlertHistory(history_file=path)
        # 1 hour cooldown should be expired (record is 2 hours old)
        assert history.is_in_cooldown("mtn", cooldown_seconds=3600) is False

    def test_get_recent_filters(self, tmp_path):
        path = tmp_path / "history.json"
        now = datetime.now(timezone.utc)
        data = [
            {
                "service": "mtn",
                "report_count": 10,
                "timestamp": (now - timedelta(hours=48)).isoformat(),
                "recipients": ["27111"],
            },
            {
                "service": "mtn",
                "report_count": 20,
                "timestamp": (now - timedelta(hours=2)).isoformat(),
                "recipients": ["27111"],
            },
        ]
        path.write_text(json.dumps(data))

        history = AlertHistory(history_file=path)
        recent = history.get_recent(hours=24)
        assert len(recent) == 1
        assert recent[0].report_count == 20

    def test_corrupted_file_handled(self, tmp_path):
        path = tmp_path / "history.json"
        path.write_text("not valid json {{{")
        history = AlertHistory(history_file=path)
        assert len(history.get_all()) == 0

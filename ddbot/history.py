"""Alert history tracking with cooldown enforcement."""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from ddbot.config import DATA_DIR

logger = logging.getLogger("ddbot.history")

HISTORY_FILE = DATA_DIR / "alert_history.json"


class AlertRecord:
    """A single alert record."""

    def __init__(
        self,
        service: str,
        report_count: int,
        timestamp: str,
        recipients: List[str],
    ):
        self.service = service
        self.report_count = report_count
        self.timestamp = timestamp
        self.recipients = recipients

    def to_dict(self) -> dict:
        return {
            "service": self.service,
            "report_count": self.report_count,
            "timestamp": self.timestamp,
            "recipients": self.recipients,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AlertRecord":
        return cls(
            service=data["service"],
            report_count=data["report_count"],
            timestamp=data["timestamp"],
            recipients=data.get("recipients", []),
        )


class AlertHistory:
    """Manages alert history with JSON persistence and cooldown enforcement."""

    def __init__(self, history_file: Optional[Path] = None):
        self._file = history_file or HISTORY_FILE
        self._records: List[AlertRecord] = []
        self._load()

    def _load(self) -> None:
        """Load history from disk."""
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text(encoding="utf-8"))
                self._records = [AlertRecord.from_dict(r) for r in data]
                logger.debug("Loaded %d history records", len(self._records))
            except (json.JSONDecodeError, KeyError) as exc:
                bak = self._file.with_suffix(".json.bak")
                logger.warning(
                    "Corrupted history file, backing up to %s and starting fresh: %s",
                    bak,
                    exc,
                )
                try:
                    os.replace(str(self._file), str(bak))
                except OSError as rename_err:
                    logger.warning("Failed to rename corrupt file: %s", rename_err)
                self._records = []
        else:
            self._records = []

    def _save(self) -> None:
        """Persist history to disk atomically."""
        self._file.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(
            [r.to_dict() for r in self._records],
            indent=2,
        )
        # Write to temp file then atomically replace to prevent corruption
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._file.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, str(self._file))
        except BaseException:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def is_in_cooldown(self, service: str, cooldown_seconds: int) -> bool:
        """Check if an alert for this service was sent within the cooldown window."""
        now = datetime.now(timezone.utc)
        for record in reversed(self._records):
            if record.service.lower() != service.lower():
                continue
            try:
                sent_at = datetime.fromisoformat(record.timestamp)
                if sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=timezone.utc)
                elapsed = (now - sent_at).total_seconds()
                if elapsed < cooldown_seconds:
                    logger.debug(
                        "Service %s in cooldown (%.0fs remaining)",
                        service,
                        cooldown_seconds - elapsed,
                    )
                    return True
            except ValueError:
                continue
        return False

    def record_alert(
        self,
        service: str,
        report_count: int,
        recipients: List[str],
    ) -> AlertRecord:
        """Record that an alert was sent."""
        record = AlertRecord(
            service=service,
            report_count=report_count,
            timestamp=datetime.now(timezone.utc).isoformat(),
            recipients=recipients,
        )
        self._records.append(record)
        self._save()
        logger.info(
            "Alert recorded: %s with %d reports -> %d recipients",
            service,
            report_count,
            len(recipients),
        )
        return record

    def get_recent(self, hours: int = 24) -> List[AlertRecord]:
        """Get alerts from the last N hours."""
        now = datetime.now(timezone.utc)
        recent = []
        for record in self._records:
            try:
                sent_at = datetime.fromisoformat(record.timestamp)
                if sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=timezone.utc)
                elapsed_hours = (now - sent_at).total_seconds() / 3600
                if elapsed_hours <= hours:
                    recent.append(record)
            except ValueError:
                continue
        return recent

    def get_all(self) -> List[AlertRecord]:
        """Return all history records."""
        return list(self._records)

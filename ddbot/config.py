"""Configuration management for DDBot."""

import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from dotenv import load_dotenv

_logger = logging.getLogger("ddbot.config")
_SERVICE_PATTERN = re.compile(r"^[a-z0-9-]+$")

# Project root is one level up from this file's directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"


@dataclass
class Config:
    """DDBot configuration loaded from environment variables."""

    services: List[str] = field(default_factory=lambda: ["mtn"])
    threshold: int = 10
    poll_interval: int = 1800
    alert_cooldown: int = 1800
    active_hours_start: int = 7
    active_hours_end: int = 20
    timezone: str = "Africa/Johannesburg"
    scrape_delay_min: int = 5
    scrape_delay_max: int = 15
    openclaw_gateway_url: str = "http://127.0.0.1:18789"
    openclaw_gateway_token: str = ""
    whatsapp_recipients: List[str] = field(default_factory=list)
    log_level: str = "INFO"

    @staticmethod
    def _safe_int(env_var: str, default: int) -> int:
        """Parse an env var as int, falling back to default with a warning."""
        raw = os.getenv(env_var)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            _logger.warning(
                "%s=%r is not a valid integer, using default %d", env_var, raw, default
            )
            return default

    @classmethod
    def from_env(cls, env_path: str | None = None) -> "Config":
        """Load configuration from .env file and environment variables."""
        if env_path:
            load_dotenv(env_path)
        else:
            load_dotenv(PROJECT_ROOT / ".env")

        services_raw = os.getenv("DD_SERVICES", "mtn")
        services = [s.strip().lower() for s in services_raw.split(",") if s.strip()]

        # Validate service names (must be URL-safe slugs)
        for svc in services:
            if not _SERVICE_PATTERN.match(svc):
                _logger.warning(
                    "Service name %r does not match [a-z0-9-]+ pattern, skipping", svc
                )
        services = [s for s in services if _SERVICE_PATTERN.match(s)]

        recipients_raw = os.getenv("WHATSAPP_RECIPIENTS", "")
        recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

        return cls(
            services=services,
            threshold=cls._safe_int("DD_THRESHOLD", 10),
            poll_interval=cls._safe_int("DD_POLL_INTERVAL", 1800),
            alert_cooldown=cls._safe_int("DD_ALERT_COOLDOWN", 1800),
            active_hours_start=cls._safe_int("DD_ACTIVE_HOURS_START", 7),
            active_hours_end=cls._safe_int("DD_ACTIVE_HOURS_END", 20),
            timezone=os.getenv("DD_TIMEZONE", "Africa/Johannesburg"),
            scrape_delay_min=cls._safe_int("DD_SCRAPE_DELAY_MIN", 5),
            scrape_delay_max=cls._safe_int("DD_SCRAPE_DELAY_MAX", 15),
            openclaw_gateway_url=os.getenv(
                "OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789"
            ),
            openclaw_gateway_token=os.getenv("OPENCLAW_GATEWAY_TOKEN", ""),
            whatsapp_recipients=recipients,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )

    def validate(self) -> List[str]:
        """Validate config and return list of error messages (empty = valid)."""
        errors = []
        if not self.services:
            errors.append("DD_SERVICES must contain at least one service")
        if self.threshold < 1:
            errors.append("DD_THRESHOLD must be >= 1")
        if self.poll_interval < 10:
            errors.append("DD_POLL_INTERVAL must be >= 10 seconds")
        if self.alert_cooldown < 0:
            errors.append("DD_ALERT_COOLDOWN must be >= 0")
        if not 0 <= self.active_hours_start <= 23:
            errors.append("DD_ACTIVE_HOURS_START must be 0-23")
        if not 0 <= self.active_hours_end <= 23:
            errors.append("DD_ACTIVE_HOURS_END must be 0-23")
        if self.active_hours_start >= self.active_hours_end:
            errors.append("DD_ACTIVE_HOURS_START must be less than DD_ACTIVE_HOURS_END")
        if self.scrape_delay_min < 0:
            errors.append("DD_SCRAPE_DELAY_MIN must be >= 0")
        if self.scrape_delay_max < self.scrape_delay_min:
            errors.append("DD_SCRAPE_DELAY_MAX must be >= DD_SCRAPE_DELAY_MIN")
        if not self.openclaw_gateway_token:
            errors.append("OPENCLAW_GATEWAY_TOKEN is required")
        if not self.whatsapp_recipients:
            errors.append("WHATSAPP_RECIPIENTS must contain at least one number")
        if self.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            errors.append(f"LOG_LEVEL '{self.log_level}' is not valid")
        return errors


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure application logging with file and console handlers."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("ddbot")
    logger.setLevel(getattr(logging, level, logging.INFO))

    # Avoid adding duplicate handlers on repeated calls
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler
    file_handler = logging.FileHandler(LOGS_DIR / "ddbot.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

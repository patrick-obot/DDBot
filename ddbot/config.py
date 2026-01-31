"""Configuration management for DDBot."""

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# Project root is one level up from this file's directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"


@dataclass
class Config:
    """DDBot configuration loaded from environment variables."""

    services: List[str] = field(default_factory=lambda: ["mtn"])
    threshold: int = 10
    poll_interval: int = 300
    alert_cooldown: int = 1800
    greenapi_instance_id: str = ""
    greenapi_api_token: str = ""
    whatsapp_recipients: List[str] = field(default_factory=list)
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env_path: str | None = None) -> "Config":
        """Load configuration from .env file and environment variables."""
        if env_path:
            load_dotenv(env_path)
        else:
            load_dotenv(PROJECT_ROOT / ".env")

        services_raw = os.getenv("DD_SERVICES", "mtn")
        services = [s.strip().lower() for s in services_raw.split(",") if s.strip()]

        recipients_raw = os.getenv("WHATSAPP_RECIPIENTS", "")
        recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

        return cls(
            services=services,
            threshold=int(os.getenv("DD_THRESHOLD", "10")),
            poll_interval=int(os.getenv("DD_POLL_INTERVAL", "300")),
            alert_cooldown=int(os.getenv("DD_ALERT_COOLDOWN", "1800")),
            greenapi_instance_id=os.getenv("GREENAPI_INSTANCE_ID", ""),
            greenapi_api_token=os.getenv("GREENAPI_API_TOKEN", ""),
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
        if not self.greenapi_instance_id or not self.greenapi_api_token:
            errors.append(
                "GREENAPI_INSTANCE_ID and GREENAPI_API_TOKEN are required"
            )
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

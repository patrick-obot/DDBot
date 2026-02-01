"""WhatsApp notification sending via OpenClaw gateway."""

import logging
from typing import List

import requests

logger = logging.getLogger("ddbot.notifier")


def format_alert_message(
    service: str, report_count: int, threshold: int
) -> str:
    """Format the alert message for WhatsApp."""
    service_display = service.upper()
    url = f"https://downdetector.co.za/status/{service.lower()}"
    return (
        f"\u26a0\ufe0f DDBot Alert: {service_display} has {report_count} reports "
        f"on DownDetector (threshold: {threshold}).\n"
        f"Check {url}"
    )


def normalize_phone(phone: str) -> str:
    """Normalize phone number: strip whitespace, +, dashes."""
    return phone.strip().replace("+", "").replace(" ", "").replace("-", "")


class WhatsAppNotifier:
    """Sends WhatsApp messages via OpenClaw's /tools/invoke endpoint."""

    def __init__(self, gateway_url: str, gateway_token: str):
        self._gateway_url = gateway_url.rstrip("/")
        self._gateway_token = gateway_token

    def send_message(self, phone: str, message: str) -> bool:
        """Send a single WhatsApp message via OpenClaw. Returns True on success."""
        phone = normalize_phone(phone)
        endpoint = f"{self._gateway_url}/tools/invoke"
        try:
            resp = requests.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {self._gateway_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "tool": "messaging",
                    "action": "send",
                    "args": {
                        "channel": "whatsapp",
                        "to": phone,
                        "text": message,
                    },
                },
                timeout=30,
            )
            if resp.status_code == 200:
                logger.info("Message sent to %s via OpenClaw", phone)
                return True
            else:
                logger.error(
                    "OpenClaw returned %d for %s: %s",
                    resp.status_code,
                    phone,
                    resp.text[:200],
                )
                return False
        except Exception as exc:
            logger.error("Failed to send message to %s: %s", phone, exc)
            return False

    def send_alert(
        self,
        recipients: List[str],
        service: str,
        report_count: int,
        threshold: int,
    ) -> List[str]:
        """Send alert to all recipients. Returns list of successfully notified numbers."""
        message = format_alert_message(service, report_count, threshold)
        logger.info(
            "Sending alert for %s (%d reports) to %d recipients",
            service,
            report_count,
            len(recipients),
        )

        sent_to = []
        for phone in recipients:
            if self.send_message(phone, message):
                sent_to.append(phone)

        logger.info(
            "Alert delivered to %d/%d recipients",
            len(sent_to),
            len(recipients),
        )
        return sent_to

    def send_test_message(self, phone: str) -> bool:
        """Send a test message to verify OpenClaw WhatsApp delivery."""
        return self.send_message(
            phone,
            "\u2705 DDBot test message - WhatsApp integration is working!",
        )

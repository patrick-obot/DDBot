"""WhatsApp notification sending via GREEN-API."""

import logging
from typing import List, Optional

from whatsapp_api_client_python import API as GreenAPI

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


def format_phone_for_greenapi(phone: str) -> str:
    """Ensure phone number is in GREEN-API format: <number>@c.us."""
    phone = phone.strip().replace("+", "").replace(" ", "").replace("-", "")
    if not phone.endswith("@c.us"):
        phone = f"{phone}@c.us"
    return phone


class WhatsAppNotifier:
    """Sends WhatsApp messages via GREEN-API."""

    def __init__(self, instance_id: str, api_token: str):
        self._instance_id = instance_id
        self._api_token = api_token
        self._api: Optional[GreenAPI] = None

    def _get_api(self) -> GreenAPI:
        """Lazily initialise the GREEN-API client."""
        if self._api is None:
            self._api = GreenAPI.GreenApi(self._instance_id, self._api_token)
        return self._api

    def send_message(self, phone: str, message: str) -> bool:
        """Send a single WhatsApp message. Returns True on success."""
        chat_id = format_phone_for_greenapi(phone)
        try:
            api = self._get_api()
            response = api.sending.sendMessage(chat_id, message)
            response_data = response.data
            if isinstance(response_data, dict) and response_data.get("idMessage"):
                logger.info("Message sent to %s (id=%s)", chat_id, response_data["idMessage"])
                return True
            else:
                logger.error("Unexpected response sending to %s: %s", chat_id, response_data)
                return False
        except Exception as exc:
            logger.error("Failed to send message to %s: %s", chat_id, exc)
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
        logger.info("Sending alert for %s (%d reports) to %d recipients", service, report_count, len(recipients))

        sent_to = []
        for phone in recipients:
            if self.send_message(phone, message):
                sent_to.append(phone)

        logger.info("Alert delivered to %d/%d recipients", len(sent_to), len(recipients))
        return sent_to

    def send_test_message(self, phone: str) -> bool:
        """Send a test message to verify credentials and delivery."""
        return self.send_message(
            phone,
            "\u2705 DDBot test message - WhatsApp integration is working!",
        )

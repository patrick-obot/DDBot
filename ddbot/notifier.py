"""Notification sending via WhatsApp (OpenClaw) and Telegram."""

import logging
from typing import List, Optional

import requests

logger = logging.getLogger("ddbot.notifier")

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


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


def is_group_jid(recipient: str) -> bool:
    """Check if recipient is a WhatsApp group JID (ends with @g.us)."""
    return recipient.strip().endswith("@g.us")


def normalize_recipient(recipient: str) -> str:
    """Normalize a recipient: group JIDs are kept as-is, phone numbers get cleaned."""
    recipient = recipient.strip()
    if is_group_jid(recipient):
        return recipient
    return recipient.replace("+", "").replace(" ", "").replace("-", "")


def format_recipient_for_openclaw(recipient: str) -> str:
    """Format recipient for the OpenClaw 'to' field.

    Group JIDs are passed as-is; phone numbers get a + prefix.
    """
    normalized = normalize_recipient(recipient)
    if is_group_jid(normalized):
        return normalized
    return f"+{normalized}"


class WhatsAppNotifier:
    """Sends WhatsApp messages via OpenClaw's /tools/invoke endpoint."""

    def __init__(self, gateway_url: str, gateway_token: str):
        self._gateway_url = gateway_url.rstrip("/")
        self._gateway_token = gateway_token

    def send_message(self, recipient: str, message: str) -> bool:
        """Send a WhatsApp message to a phone number or group. Returns True on success."""
        to = format_recipient_for_openclaw(recipient)
        endpoint = f"{self._gateway_url}/tools/invoke"
        try:
            resp = requests.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {self._gateway_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "tool": "message",
                    "action": "send",
                    "args": {
                        "target": to,
                        "message": message,
                    },
                },
                timeout=30,
            )
            if resp.status_code == 200 and resp.json().get("ok"):
                logger.info("Message sent to %s via OpenClaw", to)
                return True
            else:
                logger.error(
                    "OpenClaw returned %d for %s: %s",
                    resp.status_code,
                    to,
                    resp.text[:200],
                )
                return False
        except Exception as exc:
            logger.error("Failed to send message to %s: %s", to, exc)
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


class TelegramNotifier:
    """Sends Telegram messages via the Telegram Bot API."""

    def __init__(self, bot_token: str):
        self._bot_token = bot_token
        self._api_base = f"{TELEGRAM_API_BASE}{bot_token}"

    def send_message(self, chat_id: str, message: str, parse_mode: Optional[str] = None) -> bool:
        """Send a Telegram message to a chat. Returns True on success."""
        endpoint = f"{self._api_base}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            resp = requests.post(endpoint, json=payload, timeout=30)
            data = resp.json()
            if resp.status_code == 200 and data.get("ok"):
                logger.info("Telegram message sent to chat %s", chat_id)
                return True
            else:
                logger.error(
                    "Telegram API returned %d for chat %s: %s",
                    resp.status_code,
                    chat_id,
                    data.get("description", resp.text[:200]),
                )
                return False
        except Exception as exc:
            logger.error("Failed to send Telegram message to %s: %s", chat_id, exc)
            return False

    def send_alert(
        self,
        chat_ids: List[str],
        service: str,
        report_count: int,
        threshold: int,
    ) -> List[str]:
        """Send alert to all chat IDs. Returns list of successfully notified chats."""
        message = format_alert_message(service, report_count, threshold)
        logger.info(
            "Sending Telegram alert for %s (%d reports) to %d chats",
            service,
            report_count,
            len(chat_ids),
        )

        sent_to = []
        for chat_id in chat_ids:
            if self.send_message(chat_id, message):
                sent_to.append(chat_id)

        logger.info(
            "Telegram alert delivered to %d/%d chats",
            len(sent_to),
            len(chat_ids),
        )
        return sent_to

    def send_test_message(self, chat_id: str) -> bool:
        """Send a test message to verify Telegram bot setup."""
        return self.send_message(
            chat_id,
            "\u2705 DDBot test message - Telegram integration is working!",
        )

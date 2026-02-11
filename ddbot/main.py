"""DDBot entry point - async polling loop with CLI interface."""

import argparse
import asyncio
import logging
import random
import signal
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from ddbot.config import Config, DATA_DIR, setup_logging
from ddbot.history import AlertHistory
from ddbot.notifier import WhatsAppNotifier, TelegramNotifier
from ddbot.scraper import DownDetectorScraper

HEARTBEAT_FILE = DATA_DIR / "heartbeat"

logger: logging.Logger | None = None

# Flag for graceful shutdown
_shutdown = asyncio.Event()


def _handle_signal(sig: signal.Signals) -> None:
    logger_to_use = logger or logging.getLogger("ddbot")
    logger_to_use.info("Received %s, shutting down...", sig.name)
    _shutdown.set()


def is_within_active_hours(config: Config) -> bool:
    """Check if current time is within configured active hours."""
    tz = ZoneInfo(config.timezone)
    current_hour = datetime.now(tz).hour
    return config.active_hours_start <= current_hour < config.active_hours_end


async def poll_once(
    scraper: DownDetectorScraper,
    whatsapp_notifier: WhatsAppNotifier | None,
    telegram_notifier: TelegramNotifier | None,
    history: AlertHistory,
    config: Config,
    services: list[str] | None = None,
) -> bool:
    """Run a single polling cycle across all (or specified) services.

    Returns True if at least one service was scraped successfully.
    """
    targets = services or config.services
    any_success = False

    for i, service in enumerate(targets):
        result = await scraper.scrape_service(service)

        if result.error:
            logger.warning("Scrape error for %s: %s", service, result.error)
        else:
            any_success = True
            logger.info(
                "%s: %d reports (status=%s)",
                service.upper(),
                result.report_count,
                result.status,
            )

            if result.report_count >= config.threshold:
                if history.is_in_cooldown(service, config.alert_cooldown):
                    logger.info(
                        "%s: threshold exceeded (%d >= %d) but in cooldown, skipping alert",
                        service.upper(),
                        result.report_count,
                        config.threshold,
                    )
                else:
                    all_sent_to = []

                    # Send WhatsApp alerts
                    if whatsapp_notifier and config.whatsapp_recipients:
                        sent_to = whatsapp_notifier.send_alert(
                            recipients=config.whatsapp_recipients,
                            service=service,
                            report_count=result.report_count,
                            threshold=config.threshold,
                        )
                        all_sent_to.extend(sent_to)

                    # Send Telegram alerts
                    if telegram_notifier and config.telegram_chat_ids:
                        sent_to = telegram_notifier.send_alert(
                            chat_ids=config.telegram_chat_ids,
                            service=service,
                            report_count=result.report_count,
                            threshold=config.threshold,
                        )
                        all_sent_to.extend([f"tg:{c}" for c in sent_to])

                    if all_sent_to:
                        history.record_alert(
                            service=service,
                            report_count=result.report_count,
                            recipients=all_sent_to,
                        )
            else:
                logger.debug(
                    "%s: below threshold (%d < %d)",
                    service.upper(),
                    result.report_count,
                    config.threshold,
                )

        # Random delay between services (skip after the last one)
        if i < len(targets) - 1:
            delay = random.uniform(config.scrape_delay_min, config.scrape_delay_max)
            logger.debug("Waiting %.1fs before next service", delay)
            await asyncio.sleep(delay)

    return any_success


def create_notifiers(config: Config) -> tuple[WhatsAppNotifier | None, TelegramNotifier | None]:
    """Create notifier instances based on config."""
    whatsapp = None
    telegram = None

    if config.openclaw_gateway_token and config.whatsapp_recipients:
        whatsapp = WhatsAppNotifier(config.openclaw_gateway_url, config.openclaw_gateway_token)
        logger.info("WhatsApp notifier enabled (%d recipients)", len(config.whatsapp_recipients))

    if config.telegram_bot_token and config.telegram_chat_ids:
        telegram = TelegramNotifier(config.telegram_bot_token)
        logger.info("Telegram notifier enabled (%d chats)", len(config.telegram_chat_ids))

    return whatsapp, telegram


async def run_loop(config: Config, debug_dump: bool = False) -> None:
    """Main polling loop."""
    scraper = DownDetectorScraper(debug_dump=debug_dump, chrome_path=config.chrome_path)
    whatsapp_notifier, telegram_notifier = create_notifiers(config)
    history = AlertHistory()
    consecutive_all_fail = 0
    max_backoff = 3600  # 1 hour cap

    await scraper.start()
    try:
        logger.info(
            "DDBot started - monitoring %s every %ds (threshold=%d, cooldown=%ds)",
            ", ".join(s.upper() for s in config.services),
            config.poll_interval,
            config.threshold,
            config.alert_cooldown,
        )

        while not _shutdown.is_set():
            wait_time = config.poll_interval

            if not is_within_active_hours(config):
                logger.debug(
                    "Outside active hours (%02d:00-%02d:00 %s), skipping poll",
                    config.active_hours_start,
                    config.active_hours_end,
                    config.timezone,
                )
            else:
                try:
                    any_success = await poll_once(scraper, whatsapp_notifier, telegram_notifier, history, config)
                    if any_success:
                        if consecutive_all_fail > 0:
                            logger.info(
                                "Poll succeeded after %d consecutive all-fail cycle(s)",
                                consecutive_all_fail,
                            )
                        consecutive_all_fail = 0
                        # Touch heartbeat for Docker HEALTHCHECK
                        try:
                            HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
                            HEARTBEAT_FILE.touch()
                        except OSError:
                            pass
                    else:
                        consecutive_all_fail += 1
                        wait_time = min(
                            config.poll_interval * (2 ** consecutive_all_fail),
                            max_backoff,
                        )
                        logger.warning(
                            "All services failed (streak: %d), backing off to %ds",
                            consecutive_all_fail,
                            wait_time,
                        )
                except Exception as exc:
                    consecutive_all_fail += 1
                    wait_time = min(
                        config.poll_interval * (2 ** consecutive_all_fail),
                        max_backoff,
                    )
                    logger.error(
                        "Poll crashed (all-fail streak: %d, backoff: %ds): %s",
                        consecutive_all_fail,
                        wait_time,
                        exc,
                        exc_info=True,
                    )

            # Wait for the computed interval or until shutdown signal
            try:
                await asyncio.wait_for(
                    _shutdown.wait(), timeout=wait_time
                )
            except asyncio.TimeoutError:
                pass  # Normal timeout, continue polling
    finally:
        await scraper.stop()


async def run_once(config: Config, services: list[str] | None = None, debug_dump: bool = False) -> None:
    """Single check mode (--once)."""
    scraper = DownDetectorScraper(debug_dump=debug_dump, chrome_path=config.chrome_path)
    whatsapp_notifier, telegram_notifier = create_notifiers(config)
    history = AlertHistory()

    await scraper.start()
    try:
        await poll_once(scraper, whatsapp_notifier, telegram_notifier, history, config, services=services)
    finally:
        await scraper.stop()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DDBot - DownDetector WhatsApp Alert Bot"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single check and exit",
    )
    parser.add_argument(
        "--service",
        type=str,
        help="Check a specific service (e.g. mtn)",
    )
    parser.add_argument(
        "--env",
        type=str,
        default=None,
        help="Path to .env file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape only, skip sending WhatsApp messages",
    )
    parser.add_argument(
        "--debug-dump",
        action="store_true",
        help="Save page HTML, screenshot, text, and JS data to data/debug_*.* for diagnosis",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    global logger

    try:
        args = parse_args(argv)
        config = Config.from_env(env_path=args.env)
        logger = setup_logging(config.log_level)
    except Exception as exc:
        # Fallback logging if config parsing fails
        logging.basicConfig(level=logging.ERROR)
        logging.error("Failed to initialize: %s", exc)
        sys.exit(1)

    try:
        # Validate config (skip WhatsApp validation in dry-run mode)
        errors = config.validate()
        if args.dry_run:
            errors = [e for e in errors if "OPENCLAW" not in e and "WHATSAPP_RECIPIENTS" not in e]
        if errors:
            for err in errors:
                logger.error("Config error: %s", err)
            sys.exit(1)

        # Register signal handlers (best-effort on Windows)
        loop = asyncio.new_event_loop()
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _handle_signal, sig)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler for all signals
            pass

        services = [args.service] if args.service else None

        if args.once:
            logger.info("Running single check mode")
            loop.run_until_complete(run_once(config, services=services, debug_dump=args.debug_dump))
        else:
            loop.run_until_complete(run_loop(config, debug_dump=args.debug_dump))

        loop.close()
    except SystemExit:
        raise
    except Exception as exc:
        logger.error("Fatal error: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

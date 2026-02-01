"""DDBot entry point - async polling loop with CLI interface."""

import argparse
import asyncio
import logging
import signal
import sys

from ddbot.config import Config, DATA_DIR, setup_logging
from ddbot.history import AlertHistory
from ddbot.notifier import WhatsAppNotifier
from ddbot.scraper import DownDetectorScraper

HEARTBEAT_FILE = DATA_DIR / "heartbeat"

logger: logging.Logger | None = None

# Flag for graceful shutdown
_shutdown = asyncio.Event()


def _handle_signal(sig: signal.Signals) -> None:
    logger_to_use = logger or logging.getLogger("ddbot")
    logger_to_use.info("Received %s, shutting down...", sig.name)
    _shutdown.set()


async def poll_once(
    scraper: DownDetectorScraper,
    notifier: WhatsAppNotifier,
    history: AlertHistory,
    config: Config,
    services: list[str] | None = None,
) -> None:
    """Run a single polling cycle across all (or specified) services."""
    targets = services or config.services

    for service in targets:
        result = await scraper.scrape_service(service)

        if result.error:
            logger.warning("Scrape error for %s: %s", service, result.error)
            continue

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
                sent_to = notifier.send_alert(
                    recipients=config.whatsapp_recipients,
                    service=service,
                    report_count=result.report_count,
                    threshold=config.threshold,
                )
                if sent_to:
                    history.record_alert(
                        service=service,
                        report_count=result.report_count,
                        recipients=sent_to,
                    )
        else:
            logger.debug(
                "%s: below threshold (%d < %d)",
                service.upper(),
                result.report_count,
                config.threshold,
            )


async def run_loop(config: Config) -> None:
    """Main polling loop."""
    scraper = DownDetectorScraper()
    notifier = WhatsAppNotifier(config.openclaw_gateway_url, config.openclaw_gateway_token)
    history = AlertHistory()
    consecutive_failures = 0

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
            try:
                await poll_once(scraper, notifier, history, config)
                if consecutive_failures > 0:
                    logger.info(
                        "Poll succeeded after %d consecutive failure(s)",
                        consecutive_failures,
                    )
                consecutive_failures = 0
                # Touch heartbeat for Docker HEALTHCHECK
                try:
                    HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
                    HEARTBEAT_FILE.touch()
                except OSError:
                    pass
            except Exception as exc:
                consecutive_failures += 1
                logger.error(
                    "Poll failed (consecutive failures: %d): %s",
                    consecutive_failures,
                    exc,
                    exc_info=True,
                )

            # Wait for poll_interval or until shutdown signal
            try:
                await asyncio.wait_for(
                    _shutdown.wait(), timeout=config.poll_interval
                )
            except asyncio.TimeoutError:
                pass  # Normal timeout, continue polling
    finally:
        await scraper.stop()


async def run_once(config: Config, services: list[str] | None = None) -> None:
    """Single check mode (--once)."""
    scraper = DownDetectorScraper()
    notifier = WhatsAppNotifier(config.openclaw_gateway_url, config.openclaw_gateway_token)
    history = AlertHistory()

    await scraper.start()
    try:
        await poll_once(scraper, notifier, history, config, services=services)
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
            loop.run_until_complete(run_once(config, services=services))
        else:
            loop.run_until_complete(run_loop(config))

        loop.close()
    except SystemExit:
        raise
    except Exception as exc:
        logger.error("Fatal error: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

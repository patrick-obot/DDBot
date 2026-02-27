#!/usr/bin/env python3
"""
DDBot health check — called by OpenClaw cron every 30 min.
Checks:
  1. Is the DDBot process running?
  2. Are there recent scrape errors in the logs?
  3. What is the current report count for monitored services?

Exits with:
  0 = healthy (no action needed)
  1 = DDBot failing or threshold exceeded → OpenClaw agent should run fallback
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

DDBOT_LOG = Path("/opt/ddbot/logs/ddbot.log")
SERVICES_ENV = Path("/opt/ddbot/.env")
STATE_FILE = Path("/home/mypi/.openclaw/workspace/logs/ddbot_health_state.json")
THRESHOLD = 10
ERROR_WINDOW_MINUTES = 35  # Look back slightly more than the cron interval


def is_ddbot_running() -> bool:
    result = subprocess.run(
        ["pgrep", "-f", "ddbot.main"],
        capture_output=True,
    )
    return result.returncode == 0


def get_monitored_services() -> list[str]:
    if not SERVICES_ENV.exists():
        return ["mtn"]
    for line in SERVICES_ENV.read_text().splitlines():
        if line.startswith("DD_SERVICES="):
            return [s.strip() for s in line.split("=", 1)[1].split(",") if s.strip()]
    return ["mtn"]


def count_recent_errors(window_minutes: int = ERROR_WINDOW_MINUTES) -> int:
    """Count scrape errors in DDBot log within the last N minutes."""
    if not DDBOT_LOG.exists():
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    error_count = 0

    try:
        lines = DDBOT_LOG.read_text(errors="replace").splitlines()
        for line in lines[-500:]:  # Only scan recent tail
            # Log format: 2026-02-26 20:02:28 | INFO | ...
            match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            if not match:
                continue
            try:
                ts = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue
            if ts < cutoff:
                continue
            if any(
                marker in line
                for marker in [
                    "Scrape error",
                    "Scrape attempt",
                    "Playwright fallback failed",
                    "blocked",
                    "ERROR",
                ]
            ):
                error_count += 1

    except Exception:
        pass

    return error_count


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_ddbot_fail_alert": 0, "last_threshold_alert": {}}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def main():
    state = load_state()
    now_ts = datetime.now(timezone.utc).timestamp()
    cooldown = 1800  # 30 min alert cooldown

    issues = []

    # 1. Process check
    if not is_ddbot_running():
        if now_ts - state.get("last_ddbot_fail_alert", 0) > cooldown:
            issues.append("DDBot process is NOT running")
            state["last_ddbot_fail_alert"] = now_ts

    # 2. Scrape error check
    error_count = count_recent_errors()
    if error_count >= 3:
        if now_ts - state.get("last_ddbot_fail_alert", 0) > cooldown:
            issues.append(f"DDBot has {error_count} scrape errors in the last {ERROR_WINDOW_MINUTES} min")
            state["last_ddbot_fail_alert"] = now_ts

    # 3. Output result for OpenClaw agent
    services = get_monitored_services()
    result = {
        "ddbot_running": is_ddbot_running(),
        "recent_scrape_errors": error_count,
        "monitored_services": services,
        "issues": issues,
        "needs_fallback": len(issues) > 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    save_state(state)
    print(json.dumps(result, indent=2))

    # Exit 1 if there are issues (signals OpenClaw agent to act)
    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()

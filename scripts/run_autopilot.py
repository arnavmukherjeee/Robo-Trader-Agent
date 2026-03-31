"""Launch the Autopilot — fully autonomous trading engine."""

import os
import signal
import sys

# Fix macOS SSL certificate issues before any network imports
import certifi

os.environ["SSL_CERT_FILE"] = certifi.where()

from loguru import logger

from config.settings import settings
from src.trading.autopilot import Autopilot


def main():
    # ── Logging ────────────────────────────────────────────────────────────
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format=(
            "<green>{time:HH:mm:ss.SSS}</green> | "
            "<level>{level:<8}</level> | "
            "{message}"
        ),
    )
    logger.add(
        "logs/autopilot_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="14 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {message}",
    )

    # ── Pre-flight checks ─────────────────────────────────────────────────
    if not settings.alpaca_api_key:
        logger.error("ALPACA_API_KEY not set in .env — aborting")
        sys.exit(1)

    # ── Autopilot instance ─────────────────────────────────────────────────
    pilot = Autopilot()

    # ── Graceful shutdown on Ctrl+C / SIGTERM ──────────────────────────────
    def shutdown(sig, frame):
        logger.info(f"Shutdown signal received ({signal.Signals(sig).name})...")
        pilot.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # ── Start (blocking) ───────────────────────────────────────────────────
    logger.info("Starting Autopilot...")
    pilot.run()


if __name__ == "__main__":
    main()

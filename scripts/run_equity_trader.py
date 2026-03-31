"""Launch the equity day trader.

Scans top S&P 500 stocks every 15 minutes during market hours,
uses Sonnet for analysis, and executes high-conviction long trades.
"""

import os
import signal
import sys

import certifi

os.environ["SSL_CERT_FILE"] = certifi.where()

from loguru import logger

from config.settings import settings
from src.trading.equity_trader import EquityTrader


def main():
    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG",
        format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level:<8}</level> | {message}",
    )
    logger.add(
        "logs/equity_trader_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="30 days",
        level="DEBUG",
    )

    if not settings.alpaca_api_key:
        logger.error("Set ALPACA_API_KEY in .env first")
        sys.exit(1)

    if not settings.anthropic_api_key:
        logger.error("Set ANTHROPIC_API_KEY in .env first (needed for Sonnet analysis)")
        sys.exit(1)

    trader = EquityTrader()

    # Graceful shutdown on Ctrl+C or SIGTERM
    def shutdown(sig, frame):
        logger.info("Shutdown signal received...")
        trader.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start (blocking)
    trader.run()


if __name__ == "__main__":
    main()

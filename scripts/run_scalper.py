"""Launch the crypto scalper."""

import os
import signal
import sys

import certifi
os.environ["SSL_CERT_FILE"] = certifi.where()

from loguru import logger

from config.settings import settings
from src.trading.scalper import CryptoScalper


def main():
    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG",
        format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level:<8}</level> | {message}",
    )
    logger.add("logs/scalper_{time:YYYY-MM-DD}.log", rotation="1 day", level="DEBUG")

    if not settings.alpaca_api_key:
        logger.error("Set ALPACA_API_KEY in .env first")
        sys.exit(1)

    scalper = CryptoScalper()

    # Graceful shutdown on Ctrl+C
    def shutdown(sig, frame):
        logger.info("Shutdown signal received...")
        scalper.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start (blocking)
    scalper.run()


if __name__ == "__main__":
    main()

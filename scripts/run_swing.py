#!/usr/bin/env python3
"""Entry point for the crypto swing trader.

Sets up SSL, logging, signal handling, and runs the SwingTrader loop.
Usage: python -m scripts.run_swing
"""

import asyncio
import os
import signal
import sys

import certifi

# Fix SSL certificate issues on macOS
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger
from config.settings import settings
from src.trading.swing_trader import SwingTrader


def setup_logging() -> None:
    """Configure loguru for swing trader output."""
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>swing</cyan> | "
            "<level>{message}</level>"
        ),
    )
    logger.add(
        "logs/swing_trader.log",
        rotation="50 MB",
        retention="7 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
    )


def main() -> None:
    setup_logging()

    logger.info("=== Crypto Swing Trader Starting ===")
    logger.info("SSL cert: {}", os.environ.get("SSL_CERT_FILE", "not set"))
    logger.info("Trading mode: {}", settings.trading_mode)
    logger.info("Anthropic key: {}...{}", settings.anthropic_api_key[:8], settings.anthropic_api_key[-4:])

    trader = SwingTrader()

    # Graceful shutdown on SIGINT/SIGTERM
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def shutdown_handler(sig: int, frame) -> None:
        sig_name = signal.Signals(sig).name
        logger.info("Received {} — shutting down gracefully", sig_name)
        trader.stop()
        # Close all positions on shutdown
        trader.close_all()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        loop.run_until_complete(trader.run())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt — shutting down")
        trader.stop()
        trader.close_all()
    finally:
        loop.close()
        logger.info("=== Crypto Swing Trader Stopped ===")
        logger.info("Final: {}", trader.stats.summary())


if __name__ == "__main__":
    main()

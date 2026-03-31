"""Entry point for Robo-Trader Agent."""

import sys

import uvicorn
from loguru import logger

from config.settings import settings


def setup_logging():
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | <cyan>{name}</cyan> - {message}",
    )
    logger.add(
        "logs/trader_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="30 days",
        level="DEBUG",
    )


def main():
    setup_logging()
    logger.info("=" * 60)
    logger.info("  ROBO-TRADER AGENT  ")
    logger.info("  LLM-Powered Automated Trading System")
    logger.info("=" * 60)

    if not settings.alpaca_api_key:
        logger.error("ALPACA_API_KEY not set. Copy .env.example to .env and fill in your keys.")
        sys.exit(1)

    if not settings.anthropic_api_key:
        logger.warning(
            "ANTHROPIC_API_KEY not set — LLM analysis will be unavailable. "
            "Strategy signals will still fire but won't get LLM-ranked."
        )

    logger.info(f"Trading mode: {settings.trading_mode}")
    logger.info(f"Equities: {', '.join(settings.equity_symbols)}")
    logger.info(f"Crypto: {', '.join(settings.crypto_symbols)}")

    uvicorn.run(
        "src.api.dashboard:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()

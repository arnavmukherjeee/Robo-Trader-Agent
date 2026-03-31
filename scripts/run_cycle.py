"""Run a single trading cycle manually (useful for testing)."""

import sys

from loguru import logger

from config.settings import settings
from src.orchestrator import TradingOrchestrator


def main():
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")

    if not settings.alpaca_api_key:
        logger.error("Set ALPACA_API_KEY in .env first")
        sys.exit(1)

    logger.info("Running single trading cycle...")
    orchestrator = TradingOrchestrator()

    # Show strategy count
    count = orchestrator.engine.count_strategies()
    logger.info(f"Total strategy combinations: {count:,}")

    # Run cycle
    results = orchestrator.run_cycle()

    logger.info(f"\n{'='*60}")
    logger.info(f"Cycle complete: {len(results)} trades executed")
    for trade in results:
        logger.info(
            f"  {trade['action']} ${trade['notional']:,.2f} of {trade['symbol']} "
            f"@ ${trade['price']:,.2f} (confidence: {trade['confidence']:.2f})"
        )

    # Show status
    status = orchestrator.get_status()
    logger.info(f"\nAccount equity: ${status['account']['equity']:,.2f}")
    logger.info(f"Open positions: {len(status['positions'])}")


if __name__ == "__main__":
    main()

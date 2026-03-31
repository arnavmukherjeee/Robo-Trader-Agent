"""Run backtests on historical data to evaluate strategies."""

import sys

import numpy as np
from loguru import logger

from config.settings import settings
from src.strategies.engine import StrategyEngine
from src.backtest.backtester import Backtester
from src.trading.alpaca_client import AlpacaClient, AssetType, classify_asset

from alpaca.data.timeframe import TimeFrame


def main():
    logger.remove()
    logger.add(sys.stderr, level="INFO")

    if not settings.alpaca_api_key:
        logger.error("Set ALPACA_API_KEY in .env first")
        sys.exit(1)

    alpaca = AlpacaClient()
    engine = StrategyEngine(combo_sizes=(2, 3))
    backtester = Backtester(initial_capital=100_000)

    # Generate strategies and sample
    all_strategies = engine.generate_strategies()
    logger.info(f"Generated {len(all_strategies):,} strategies")

    rng = np.random.default_rng(42)
    sample_size = min(500, len(all_strategies))
    indices = rng.choice(len(all_strategies), sample_size, replace=False)
    sample_strategies = [all_strategies[i] for i in indices]
    logger.info(f"Sampling {sample_size} strategies for backtest")

    # Test symbols
    test_symbols = ["AAPL", "MSFT", "BTC/USD", "ETH/USD"]

    all_results = []
    for symbol in test_symbols:
        asset_type = classify_asset(symbol)
        logger.info(f"\nBacktesting {symbol}...")

        try:
            df = alpaca.get_bars(symbol, asset_type, TimeFrame.Hour, days_back=90)
            logger.info(f"  Fetched {len(df)} bars")
        except Exception as e:
            logger.error(f"  Failed to fetch data: {e}")
            continue

        if len(df) < 250:
            logger.warning(f"  Insufficient data ({len(df)} bars), skipping")
            continue

        best_result = None
        for strat in sample_strategies:
            result = backtester.run(strat, df, symbol)
            if result.total_trades > 3:  # minimum trades for valid backtest
                if best_result is None or result.sharpe_ratio > best_result.sharpe_ratio:
                    best_result = result

        if best_result:
            logger.info(f"\n  Best strategy for {symbol}:")
            logger.info(f"  {best_result.summary()}")
            all_results.append(best_result)
        else:
            logger.info(f"  No profitable strategies found for {symbol}")

    logger.info(f"\n{'='*60}")
    logger.info(f"Backtest complete: {len(all_results)} symbols with results")
    for r in all_results:
        logger.info(f"  {r.symbol}: {r.total_return_pct:+.2f}% | Sharpe: {r.sharpe_ratio:.2f}")


if __name__ == "__main__":
    main()

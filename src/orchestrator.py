"""Main orchestrator — the brain that runs the full trading loop.

Flow:
1. Fetch market data for all symbols (equities + crypto)
2. Compute indicators
3. Run strategy engine to get top signals
4. Send to LLM analyst for final decision
5. Risk-check the recommendation
6. Execute approved trades via Alpaca
7. Monitor positions and manage exits
"""

import asyncio
from datetime import datetime

import numpy as np
from loguru import logger

from config.settings import settings
from src.strategies.engine import StrategyEngine
from src.strategies.indicators import compute_all_indicators
from src.trading.alpaca_client import AlpacaClient, AssetType, classify_asset
from src.llm.analyst import LLMAnalyst
from src.risk.manager import RiskManager
from src.strategies.signals import Direction

from alpaca.data.timeframe import TimeFrame


class TradingOrchestrator:
    """Runs the full automated trading pipeline."""

    def __init__(self):
        self.alpaca = AlpacaClient()
        self.engine = StrategyEngine(combo_sizes=(2, 3))
        self.llm = LLMAnalyst()
        self.risk = RiskManager()

        self.symbols = settings.equity_symbols + settings.crypto_symbols
        self.trade_log: list[dict] = []

        # Pre-generate a subset of strategies for speed
        # Full generation creates hundreds of thousands — we sample for live trading
        self._strategies = None
        logger.info(
            f"Orchestrator initialized | "
            f"{len(settings.equity_symbols)} equities + "
            f"{len(settings.crypto_symbols)} crypto | "
            f"Strategy count: {self.engine.count_strategies():,}"
        )

    def get_strategies(self):
        if self._strategies is None:
            all_strats = self.engine.generate_strategies()
            # Sample 10,000 for live use (full set for backtesting)
            if len(all_strats) > 10_000:
                rng = np.random.default_rng(42)
                indices = rng.choice(len(all_strats), 10_000, replace=False)
                self._strategies = [all_strats[i] for i in indices]
                logger.info(f"Sampled 10,000 strategies from {len(all_strats):,} total")
            else:
                self._strategies = all_strats
        return self._strategies

    def run_cycle(self) -> list[dict]:
        """Run one full trading cycle across all symbols."""
        logger.info("=" * 60)
        logger.info(f"Trading cycle started at {datetime.now()}")

        account = self.alpaca.get_account()
        positions = self.alpaca.get_positions()
        strategies = self.get_strategies()

        # Check portfolio health
        health = self.risk.check_portfolio_health(account, positions)
        logger.info(f"Portfolio health: {health['status']} | Exposure: {health['exposure_pct']:.1f}%")

        if health["status"] == "CRITICAL":
            logger.warning("CRITICAL portfolio status — skipping new trades, checking exits")
            self._check_exits(positions)
            return []

        # Handle danger positions first
        for symbol in health.get("danger_positions", []):
            logger.warning(f"Stop-loss triggered for {symbol} — closing position")
            try:
                self.alpaca.close_position(symbol)
                self.trade_log.append({
                    "time": datetime.now().isoformat(),
                    "symbol": symbol,
                    "action": "STOP_LOSS_EXIT",
                })
            except Exception as e:
                logger.error(f"Failed to close {symbol}: {e}")

        cycle_results = []

        for symbol in self.symbols:
            try:
                result = self._analyze_symbol(symbol, account, positions, strategies)
                if result:
                    cycle_results.append(result)
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                continue

        logger.info(
            f"Cycle complete | {len(cycle_results)} trades executed | "
            f"Equity: ${account['equity']:,.2f}"
        )
        return cycle_results

    def _analyze_symbol(
        self, symbol: str, account: dict, positions: list[dict], strategies: list
    ) -> dict | None:
        """Analyze a single symbol through the full pipeline."""
        asset_type = classify_asset(symbol)
        logger.info(f"Analyzing {symbol} ({asset_type.value})...")

        # 1. Fetch data
        try:
            df = self.alpaca.get_bars(
                symbol, asset_type, timeframe=TimeFrame.Hour, days_back=60
            )
        except Exception as e:
            logger.error(f"Failed to fetch data for {symbol}: {e}")
            return None

        if len(df) < 200:
            logger.warning(f"Insufficient data for {symbol}: {len(df)} bars (need 200)")
            return None

        # 2. Compute indicators
        df = compute_all_indicators(df)

        # 3. Run strategy engine
        top_results = self.engine.evaluate_top_n(df, strategies, top_n=50)
        if not top_results:
            logger.info(f"No strategy signals for {symbol}")
            return None

        logger.info(
            f"{symbol}: {len(top_results)} strategies fired | "
            f"Best confidence: {top_results[0].confidence:.2f}"
        )

        # 4. Build market summary for LLM
        latest = df.iloc[-1]
        market_summary = {
            "current_price": float(latest["close"]),
            "price_change_pct": float(latest.get("close_pct_change", 0) * 100),
            "volume_ratio": float(latest.get("volume_ratio", 1)),
            "atr": float(latest.get("atr_14", 0)),
            "rsi": float(latest.get("rsi_14", 50)),
        }

        # Current position info
        current_pos = next(
            (p for p in positions if p["symbol"] == symbol.replace("/", "")), None
        )
        portfolio_state = {
            "equity": account["equity"],
            "cash": account["cash"],
            "num_positions": len(positions),
            "current_position": (
                f"{current_pos['qty']} shares @ ${current_pos['avg_entry_price']}"
                if current_pos
                else "None"
            ),
        }

        # 5. LLM analysis (with fallback to pure signal-based decisions)
        recommendation = None
        if settings.anthropic_api_key:
            try:
                recommendation = self.llm.analyze_symbol(
                    symbol, top_results, market_summary, portfolio_state
                )
            except Exception as e:
                logger.warning(f"LLM analysis failed for {symbol}, falling back to signals: {e}")

        if recommendation is None:
            recommendation = self._signal_based_recommendation(
                symbol, top_results, market_summary
            )

        if recommendation is None:
            logger.info(f"No trade signal for {symbol}")
            return None

        # Crypto can't be shorted on Alpaca paper trading
        if asset_type == AssetType.CRYPTO and recommendation.direction == Direction.SHORT:
            logger.info(f"Skipping short for {symbol} — crypto shorting not supported on paper")
            return None

        logger.info(
            f"Recommendation: {recommendation.direction.value} {symbol} "
            f"confidence={recommendation.confidence:.2f} "
            f"size={recommendation.position_size_pct:.2%}"
        )

        # 6. Risk check
        current_price = market_summary["current_price"]
        risk_check = self.risk.check_trade(recommendation, current_price, account, positions)

        if not risk_check.approved:
            logger.info(f"Trade rejected: {risk_check.rejection_reason}")
            return None

        # 7. Execute trade
        return self._execute_trade(recommendation, risk_check, account, current_price)

    def _signal_based_recommendation(
        self, symbol: str, top_results: list, market_summary: dict
    ):
        """Fallback: make trade decisions purely from strategy signal consensus."""
        from src.llm.analyst import LLMTradeRecommendation

        long_results = [r for r in top_results if r.direction == Direction.LONG]
        short_results = [r for r in top_results if r.direction == Direction.SHORT]

        long_score = sum(r.confidence for r in long_results)
        short_score = sum(r.confidence for r in short_results)

        # Need strong consensus — at least 5 strategies agreeing with avg confidence > 0.6
        if long_score > short_score and len(long_results) >= 5:
            avg_conf = long_score / len(long_results)
            if avg_conf < 0.6:
                return None
            direction = Direction.LONG
            confidence = avg_conf
            reasons = [r.reasons[0] for r in long_results[:5] if r.reasons]
        elif short_score > long_score and len(short_results) >= 5:
            avg_conf = short_score / len(short_results)
            if avg_conf < 0.6:
                return None
            direction = Direction.SHORT
            confidence = avg_conf
            reasons = [r.reasons[0] for r in short_results[:5] if r.reasons]
        else:
            return None

        logger.info(
            f"Signal-based decision for {symbol}: {direction.value} "
            f"confidence={confidence:.2f} ({len(long_results)}L/{len(short_results)}S)"
        )

        return LLMTradeRecommendation(
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            position_size_pct=min(0.03, confidence * 0.05),  # conservative sizing
            reasoning=f"Signal consensus: {'; '.join(reasons[:3])}",
            strategies_used=[r.strategy.name for r in top_results[:5]],
            stop_loss_pct=0.03,
            take_profit_pct=0.06,
        )

    def _execute_trade(
        self, recommendation, risk_check, account: dict, current_price: float
    ) -> dict | None:
        """Execute an approved trade."""
        notional = account["equity"] * risk_check.adjusted_size_pct
        side = "buy" if recommendation.direction == Direction.LONG else "sell"

        try:
            order = self.alpaca.place_market_order(
                symbol=recommendation.symbol,
                notional=round(notional, 2),
                side=side,
            )

            trade_record = {
                "time": datetime.now().isoformat(),
                "symbol": recommendation.symbol,
                "action": side.upper(),
                "notional": notional,
                "price": current_price,
                "confidence": recommendation.confidence,
                "reasoning": recommendation.reasoning,
                "stop_loss": risk_check.stop_loss_price,
                "take_profit": risk_check.take_profit_price,
                "order_id": order["order_id"],
            }
            self.trade_log.append(trade_record)

            logger.info(
                f"TRADE EXECUTED: {side.upper()} ${notional:,.2f} of {recommendation.symbol} "
                f"@ ~${current_price:,.2f}"
            )
            return trade_record

        except Exception as e:
            logger.error(f"Trade execution failed for {recommendation.symbol}: {e}")
            return None

    def _check_exits(self, positions: list[dict]):
        """Check if any positions need to be closed based on risk rules."""
        for pos in positions:
            unrealized_pct = pos.get("unrealized_plpc", 0)
            if unrealized_pct < -settings.stop_loss_pct:
                logger.warning(
                    f"Exit signal: {pos['symbol']} down {unrealized_pct:.2%}"
                )
                try:
                    self.alpaca.close_position(pos["symbol"])
                except Exception as e:
                    logger.error(f"Failed to exit {pos['symbol']}: {e}")

    def get_status(self) -> dict:
        """Get current system status."""
        account = self.alpaca.get_account()
        positions = self.alpaca.get_positions()
        health = self.risk.check_portfolio_health(account, positions)

        return {
            "account": account,
            "positions": positions,
            "health": health,
            "strategy_count": self.engine.count_strategies(),
            "active_strategies": len(self.get_strategies()),
            "trade_log_count": len(self.trade_log),
            "recent_trades": self.trade_log[-10:],
        }
